"""
Testes automatizados para DatabaseManager e EntityResolver (v1.1 Sessions Redesign).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database_gemini import DatabaseManager
from core.entity_resolver_gemini import EntityResolver


def test_session_fixed_order_and_entity_resolution():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db = DatabaseManager(base_dir=tmpdir)
        resolver = EntityResolver(db)

        # 1. Criação de sessões com numeração fixa (seq_number)
        s1 = db.create_session("Sessão 1")
        s2 = db.create_session("Sessão 2")
        s3 = db.create_session("Sessão 3")

        # Mesmo excluindo a Sessão 2, a Sessão 3 mantém seq_number=3 e a próxima será 4
        db.delete_session(s2)
        s4 = db.create_session()
        sessions = db.get_all_sessions()
        assert [s["seq_number"] for s in sessions] == [1, 3, 4], f"Ordem inesperada: {sessions}"
        assert sessions[2]["name"] == "Sessão 4"

        # 2. Alterar a Sessão 4 ou a Sessão 3 NÃO deve mudar a ordem (Sessão 1 continua na frente)
        dummy_pdf = Path(tmpdir) / "doc_teste.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

        # Adiciona RG e CNH do mesmo titular (Pedro) na Sessão 1
        db.log_extraction(
            saved_file_path=dummy_pdf,
            original_name="RG_PEDRO.pdf",
            doc_type="RG",
            extracted_data={
                "dados": {
                    "tipo": "RG",
                    "pessoa": {
                        "nome_completo": "[NOME_001]",
                        "cpf": "[CPF_001]",
                        "rg": "[RG_001]",
                        "data_nascimento": "10/05/1990",
                        "nome_pais": ["JOAO SILVA", "MARIA SILVA"],
                    },
                },
                "token_map": {
                    "[NOME_001]": "PEDRO ALVES SILVA",
                    "[CPF_001]": "123.456.789-09",
                    "[RG_001]": "12.345.678-9",
                },
            },
            session_id=s1,
        )

        db.log_extraction(
            saved_file_path=dummy_pdf,
            original_name="CNH_PEDRO.pdf",
            doc_type="CNH",
            extracted_data={
                "dados": {
                    "tipo": "CNH",
                    "pessoa": {
                        "nome_completo": "PEDRO ALVES SILVA",
                        "cpf": "12345678909",
                        "data_nascimento": "11/05/1990",  # Data divergente para testar conflito ⚠️
                    },
                },
                "token_map": {},
            },
            session_id=s1,
        )

        # Verifica que RG e CNH foram agrupados na MESMA pessoa (pais NÃO viraram Pessoa)
        persons = db.get_session_persons(s1)
        assert len(persons) == 1, f"Esperava 1 pessoa, obteve: {persons}"
        pedro_id = persons[0]["id"]
        assert persons[0]["display_name"] == "PEDRO ALVES SILVA"
        assert persons[0]["doc_count"] == 2

        # Verifica consolidação e detecção de conflito na data de nascimento
        fields = {f.key: f for f in resolver.consolidate_person_data(pedro_id)}
        assert fields["cpf"].display_value == "123.456.789-09"
        assert fields["rg"].display_value == "12.345.678-9"
        assert fields["nome_pais"].display_value == "JOAO SILVA / MARIA SILVA"
        assert fields["data_nascimento"].display_value == "10/05/1990"  # RG vence CNH na prioridade
        assert fields["data_nascimento"].has_conflict is True
        assert len(fields["data_nascimento"].alternatives) == 2

        # 3. Testa override manual (não altera JSON original e permite restaurar)
        db.set_entity_override("PERSON", pedro_id, "rg", "99.999.999-0")
        fields_after = {f.key: f for f in resolver.consolidate_person_data(pedro_id)}
        assert fields_after["rg"].display_value == "99.999.999-0"
        assert fields_after["rg"].is_overridden is True
        assert fields_after["rg"].extracted_value == "12.345.678-9"

        # Restaurar valor extraído
        db.set_entity_override("PERSON", pedro_id, "rg", None)
        fields_restored = {f.key: f for f in resolver.consolidate_person_data(pedro_id)}
        assert fields_restored["rg"].display_value == "12.345.678-9"
        assert fields_restored["rg"].is_overridden is False

        # 4. Testa Certidão de Casamento (2 cônjuges: Pedro já existente + Cristina nova)
        db.log_extraction(
            saved_file_path=dummy_pdf,
            original_name="CASAMENTO.pdf",
            doc_type="CASAMENTO",
            extracted_data={
                "dados": {
                    "tipo": "CASAMENTO",
                    "conjuges": [
                        {"nome_completo": "PEDRO ALVES SILVA", "cpf": "123.456.789-09"},
                        {"nome_completo": "CRISTINA SOUZA", "cpf": "987.654.321-00"},
                    ],
                },
                "token_map": {},
            },
            session_id=s1,
        )
        persons = db.get_session_persons(s1)
        assert len(persons) == 2, f"Esperava 2 pessoas após casamento, obteve: {persons}"

        # 5. Testa homônimos com CPFs diferentes (NÃO devem ser mesclados)
        db.log_extraction(
            saved_file_path=dummy_pdf,
            original_name="RG_HOMONIMO.pdf",
            doc_type="RG",
            extracted_data={
                "dados": {
                    "tipo": "RG",
                    "pessoa": {
                        "nome_completo": "PEDRO ALVES SILVA",
                        "cpf": "111.222.333-44",
                    },
                },
                "token_map": {},
            },
            session_id=s1,
        )
        persons = db.get_session_persons(s1)
        assert len(persons) == 3, "Homônimo com CPF diferente deveria criar 3ª pessoa!"

        # 6. Testa IPTU + Escritura do mesmo imóvel:
        # - IPTU tem 'contribuinte', que NÃO deve virar Pessoa (regra estrita do usuário)
        # - Escritura tem 'compradores' e 'vendedores', que DEVEM virar Pessoa
        # - Ambos apontam para o mesmo Imóvel (pela inscrição/matrícula/endereço)
        db.log_extraction(
            saved_file_path=dummy_pdf,
            original_name="IPTU_2026.pdf",
            doc_type="IPTU",
            extracted_data={
                "dados": {
                    "tipo": "IPTU",
                    "contribuinte": {"nome_completo": "CONTRIBUINTE NAO PESSOA", "cpf": "555.666.777-88"},
                    "imovel": {
                        "endereco_completo": "RUA DAS FLORES, 100 - APTO 201",
                        "inscricao_municipal": "0123456-7",
                        "cep": "20000-000",
                    },
                },
                "token_map": {},
            },
            session_id=s1,
        )
        persons_after_iptu = db.get_session_persons(s1)
        assert len(persons_after_iptu) == 3, "Contribuinte de IPTU NÃO deve criar Pessoa!"

        props = db.get_session_properties(s1)
        assert len(props) == 1
        prop_id = props[0]["id"]

        db.log_extraction(
            saved_file_path=dummy_pdf,
            original_name="ESCRITURA.pdf",
            doc_type="ESCRITURA",
            extracted_data={
                "dados": {
                    "tipo": "ESCRITURA",
                    "compradores": [{"nome_completo": "PEDRO ALVES SILVA", "cpf": "123.456.789-09"}],
                    "vendedores": [{"nome_completo": "LUCAS MENDES", "cpf": "444.555.666-77"}],
                    "imovel": {
                        "endereco_completo": "RUA DAS FLORES, 100 - APTO 201",
                        "inscricao_municipal": "0123456-7",
                        "matricula_imovel": "88990",
                        "cep": "20000-000",
                    },
                },
                "token_map": {},
            },
            session_id=s1,
        )
        persons_after_esc = db.get_session_persons(s1)
        assert len(persons_after_esc) == 4, "Vendedor Lucas Mendes deve criar 4ª pessoa e comprador Pedro reaproveita 1ª!"
        props_after_esc = db.get_session_properties(s1)
        assert len(props_after_esc) == 1, "Escritura e IPTU do mesmo imóvel devem consolidar em 1 único imóvel!"

        prop_fields = {f.key: f for f in resolver.consolidate_property_data(prop_id)}
        assert prop_fields["endereco_completo"].display_value == "RUA DAS FLORES, 100 - APTO 201"
        assert prop_fields["inscricao_municipal"].display_value == "0123456-7"
        assert prop_fields["matricula_imovel"].display_value == "88990"
        assert prop_fields["cep"].display_value == "20000-000"

        print("[OK] Todos os testes de DatabaseManager e EntityResolver passaram com sucesso!")


if __name__ == "__main__":
    test_session_fixed_order_and_entity_resolution()
