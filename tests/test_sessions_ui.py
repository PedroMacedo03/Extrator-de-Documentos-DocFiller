"""
Teste de integração da nova interface de 4 colunas da aba 'Sessões e Documentos' (v1.1).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from core.database_gemini import DatabaseManager
from core.entity_resolver_gemini import EntityResolver
from ui.sessions_page_gemini import SessionsPage


def test_sessions_page_four_columns():
    app = QApplication.instance() or QApplication(sys.argv)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        page = SessionsPage()
        page.db = DatabaseManager(base_dir=tmpdir)
        page.resolver = EntityResolver(page.db)

        s1 = page.db.create_session("Sessão Teste 1")
        dummy_pdf = Path(tmpdir) / "doc.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

        page.db.log_extraction(
            saved_file_path=dummy_pdf,
            original_name="RG_TITULAR.pdf",
            doc_type="RG",
            extracted_data={
                "dados": {
                    "tipo": "RG",
                    "pessoa": {
                        "nome_completo": "CARLOS SILVA",
                        "cpf": "123.456.789-09",
                        "rg": "11.222.333-4",
                        "data_nascimento": "01/01/1980",
                        "nome_pais": ["JOSE SILVA", "ANA SILVA"],
                    },
                },
                "token_map": {},
            },
            session_id=s1,
        )

        page.db.log_extraction(
            saved_file_path=dummy_pdf,
            original_name="ESCRITURA_IMOVEL.pdf",
            doc_type="ESCRITURA",
            extracted_data={
                "dados": {
                    "tipo": "ESCRITURA",
                    "compradores": [{"nome_completo": "CARLOS SILVA", "cpf": "123.456.789-09"}],
                    "vendedores": [{"nome_completo": "MARCOS ROCHA", "cpf": "999.888.777-66"}],
                    "imovel": {
                        "endereco_completo": "AV BRASIL, 500",
                        "inscricao_municipal": "778899",
                        "matricula_imovel": "12345",
                        "cep": "20040-000",
                    },
                },
                "token_map": {},
            },
            session_id=s1,
        )

        page.load_sessions(target_session_id=s1)

        # Verifica as 4 colunas no QSplitter
        assert page.splitter.count() == 4
        # Verifica os splitters verticais de redimensionamento dinâmico na Coluna 2
        assert page.col2_entities.domain_splitter.count() == 2
        assert page.col2_entities.persons_splitter.count() == 3  # 1: PESSOAS -> 2: DADOS -> 3: DOCUMENTOS
        assert page.col2_entities.properties_splitter.count() == 2  # 4: IMÓVEIS -> 5: DADOS IMÓVEL
        assert page.col2_entities.persons_list.count() == 2  # Carlos (comprador/titular) + Marcos (vendedor)
        assert page.col2_entities.properties_list.count() == 1  # AV BRASIL, 500
        assert page.col3_attached.docs_list.count() == 2  # RG + ESCRITURA

        # Verifica que o CPF consolidado de Carlos está exibido no bloco DADOS
        cpf_row = page.col2_entities.person_field_rows["cpf"]
        assert cpf_row.lbl_value.text() == "123.456.789-09"

        # Clique simples na linha do CPF deve selecioná-la e habilitar o botão ✏️ sem entrar em modo de edição
        page.col2_entities._on_any_field_row_selected(cpf_row)
        assert cpf_row._is_selected is True
        assert cpf_row._is_editing is False
        assert cpf_row.btn_edit.isHidden() is False

        # Duplo clique copia para o clipboard
        cpf_row.copy_value_to_clipboard()
        assert QApplication.clipboard().text() == "123.456.789-09"

        # Edição inline via botão ✏️
        cpf_row.start_inline_edit()
        assert cpf_row._is_editing is True
        cpf_row.edit_input.setText("111.222.333-44")
        cpf_row._save_inline_edit()
        assert cpf_row.lbl_value.text() == "111.222.333-44"
        assert cpf_row.current_field.is_overridden is True

        # Restaurar valor extraído
        cpf_row._restore_extracted_value()
        assert cpf_row.lbl_value.text() == "123.456.789-09"
        assert cpf_row.current_field.is_overridden is False

        print("[OK] Teste de integração da GUI de 4 colunas passou com sucesso!")


if __name__ == "__main__":
    test_sessions_page_four_columns()
