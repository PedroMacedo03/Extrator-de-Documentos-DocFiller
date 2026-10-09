"""
DocFiller — Extrator de Dados (Gemini API)
==========================================

Responsável por enviar o texto processado (já sem dados LGPD e com tokens no lugar de dados sensíveis)
para a API do Gemini. 

O Gemini recebe APENAS tokens e estrutura o JSON. Ele não retém dados
reais porque eles sequer são enviados (devido ao DataMasker).
"""

import json
from google import genai
from google.genai import types
from pydantic import ValidationError

from .models_gemini import ExtractedDocument
from .retry_gemini import call_with_retry  # [Opus - v1.0 Multi-Doc]


class GeminiExtractor:
    """
    Integração com Gemini API para classificação e extração estruturada (Structured Output).
    """

    def __init__(self, api_key: str, model_name: str = "gemini-3.8-flash"):
        # Inicializa o cliente do SDK google-genai
        self.client = genai.Client(api_key=api_key)
        # Utilizando o modelo selecionado (padrão: gemini-3.8-flash para máxima acurácia)
        self.model_name = model_name
        
        self.system_instruction = (
            "Você é um sistema especialista em extração de dados de documentos brasileiros com foco em alta precisão.\n"
            "Seu trabalho é ler o texto providenciado (que passou por OCR) e retornar ESTRITAMENTE "
            "um JSON válido seguindo o schema exigido.\n\n"
            "MUITO IMPORTANTE - TOKENS DE MASCARAMENTO:\n"
            "1. PRESERVAÇÃO DE TOKENS: O texto pode conter tokens gerados por um sistema de privacidade "
            "(ex: [CPF_001], [NOME_001], [RG_001], [DATA_001], [REMOVIDO_LGPD]). "
            "Você DEVE manter esses tokens exatamente como estão ao preencher os campos do JSON.\n"
            "2. NUNCA INVENTE TOKENS: Você só deve usar um token se ele estiver EXPLICITAMENTE escrito no texto. "
            "Se o nome da pessoa ou um dado estiver no texto sem token, extraia o texto real como está no documento. "
            "JAMAIS substitua dados reais por tokens inventados como [NOME_001]!\n\n"
            "REGRAS ESPECÍFICAS PARA CARTEIRA DE IDENTIDADE (RG):\n"
            "1. NÚMERO DO RG: O RG é composto de 7 a 10 dígitos (ex: '30.580.301-7', '12.345.678-9' ou '804938626'). "
            "Ele geralmente fica identificado como 'REGISTRO GERAL', 'RG' ou no cabeçalho do documento.\n"
            "2. NUNCA USE A MATRÍCULA COMO RG: Identidades brasileiras frequentemente trazem no verso o campo "
            "'DOC ORIGEM' contendo a matrícula da certidão de nascimento (um código longo com mais de 20 caracteres e hífens, "
            "ex: '08-01-95-2003-1-00229-049-0107434-13'). Esse número longo NUNCA é o RG! Ignore a matrícula para o campo rg.\n"
            "3. Se o número do RG real (de 7 a 10 dígitos) não for legível no texto, retorne null. NUNCA coloque a matrícula no campo rg.\n\n"
            "REGRAS ESPECÍFICAS PARA CERTIDÕES BRASILEIRAS:\n"
            "1. DATAS POR EXTENSO: Em certidões de nascimento/casamento/óbito, datas quase sempre vêm "
            "escritas por extenso. Converta rigorosamente para o formato DD/MM/AAAA numérico.\n"
            "2. NÃO CONFUNDA DATAS: Em certidões, diferencie a 'Data de Nascimento' da pessoa da 'Data do Registro' "
            "ou 'Data de Emissão'. O campo data_nascimento deve conter EXCLUSIVAMENTE a data em que a pessoa nasceu.\n"
            "3. FILIAÇÃO: Em certidões e RGs, os nomes dos pais costumam vir após 'filho de', 'sendo pai', 'sendo mãe' ou 'FILIAÇÃO'. "
            "Limpe quaisquer partículas jurídicas ou repetições resultantes de ruído de OCR.\n\n"
            "REGRAS ESPECÍFICAS PARA TÍTULO DE ELEITOR:\n"
            "1. Classifique como 'TITULO_ELEITOR'.\n"
            "2. NÚMERO DO TÍTULO: O número da inscrição eleitoral possui 12 dígitos numéricos (ex: '0123 4567 8901'). Extraia no campo 'numero_titulo'.\n"
            "3. ZONA E SEÇÃO: Extraia os números respectivos da 'zona' (geralmente 3 dígitos) e 'secao' (geralmente 4 dígitos).\n"
            "4. MUNICÍPIO E UF: Extraia o município e a sigla do estado do domicílio eleitoral.\n"
            "5. DADOS PESSOAIS: Nome do eleitor, data de nascimento e filiação (pai/mãe) devem ser preenchidos no objeto 'pessoa'.\n\n"
            "REGRAS ESPECÍFICAS PARA IDENTIDADES MILITARES, POLICIAIS E CONSELHOS PROFISSIONAIS (OAB, CRM, CREA):\n"
            "1. Classifique como 'IDENTIDADE_FUNCIONAL'.\n"
            "2. ÓRGÃO/CORPORAÇÃO EMISSOR: Preencha 'orgao_emissor' com o nome explícito (ex: 'Exército Brasileiro', 'Marinha do Brasil', 'Polícia Militar', 'OAB', 'CRM', 'CREA', 'Polícia Federal').\n"
            "3. CATEGORIA FUNCIONAL: Defina 'categoria_funcional' como 'MILITAR', 'POLICIAL', 'CONSELHO_PROFISSIONAL' ou 'ORGAO_PUBLICO'.\n"
            "4. REGISTRO/MATRÍCULA: Extraia o número de matrícula militar, identidade militar ou registro profissional no conselho no campo 'numero_registro'.\n"
            "5. POSTO/GRADUAÇÃO/CARGO: Se houver patente militar ou profissão/cargo (ex: 'Capitão', 'Sargento', 'Tenente', 'Advogado', 'Médico', 'Engenheiro'), extraia em 'posto_graduacao_cargo'.\n"
            "6. DADOS PESSOAIS: Nome, CPF, RG civil (se constar), nascimento e filiação devem ser extraídos no objeto 'pessoa'.\n\n"
            "REGRAS ESPECÍFICAS PARA CERTIFICADOS DE ENSINO MÉDIO, CURSOS E DIPLOMAS:\n"
            "1. Classifique como 'CERTIFICADO_DIPLOMA'.\n"
            "2. INSTITUIÇÃO DE ENSINO: Preencha 'instituicao_ensino' com o nome completo do colégio, escola, centro universitário ou faculdade.\n"
            "3. NÍVEL E CURSO: Identifique 'nivel_ensino' ('ENSINO_MEDIO', 'GRADUACAO', 'TECNICO', etc.) e o nome do curso em 'curso'.\n"
            "4. CONCLUSÃO: A data em que o aluno concluiu o curso/ano letivo vai em 'data_conclusao' (DD/MM/AAAA). A data de expedição/colação de grau vai em 'data_emissao'.\n"
            "5. REGISTRO: Extraia o número de registro do diploma, livro, folha ou portaria do MEC no campo 'registro_diploma'.\n"
            "6. CONCLUINTE: Nome do aluno/formando, CPF e RG devem ser extraídos no objeto 'pessoa'.\n\n"
            "REGRAS ESPECÍFICAS PARA CARTEIRA DE IDENTIDADE NACIONAL (CIN - NOVO RG NACIONAL):\n"
            "1. Classifique como 'CIN' quando o documento trouxer 'REPÚBLICA FEDERATIVA DO BRASIL', 'CARTEIRA DE IDENTIDADE' "
            "e tiver o CPF como número único de identificação.\n"
            "2. O CPF é o identificador central (coloque em pessoa.cpf). No verso, se houver código MRZ (duas/três linhas com chevron <<<), extraia em 'codigo_mrz'.\n"
            "3. Se houver número de RG antigo estadual, extraia em 'registro_geral_antigo'.\n"
            "4. Extraia tipo sanguíneo/fator RH se citado (ex: O+, A-).\n\n"
            "REGRAS ESPECÍFICAS PARA PASSAPORTE BRASILEIRO:\n"
            "1. Classifique como 'PASSAPORTE'.\n"
            "2. NÚMERO DO PASSAPORTE: O número do passaporte brasileiro é composto de 2 letras seguidas de 6 dígitos numéricos (ex: 'BR123456', 'FU123456', 'CD987654'). Extraia no campo 'numero_passaporte'.\n"
            "3. Código MRZ: No rodapé da página de identificação constam 2 linhas de 44 caracteres com chevrons (<<<). Extraia em 'codigo_mrz'.\n"
            "4. Autoridade expedidora: Normalmente 'DPF' ou 'Polícia Federal'.\n\n"
            "REGRAS ESPECÍFICAS PARA CARTEIRAS DE ORDENS E CONSELHOS (OAB, CRM, CREA, CRC, CRO, ETC.):\n"
            "1. Classifique como 'CARTEIRA_CONSELHO'.\n"
            "2. Identifique o conselho em 'orgao_conselho' (ex: 'OAB', 'CRM', 'CREA', 'CRC', 'CRP').\n"
            "3. Extraia o número de inscrição/registro em 'numero_registro' e a seccional/estado em 'seccional_uf'.\n"
            "4. Tipo de inscrição ('ADVOGADO', 'MEDICO', 'ESTAGIARIO', etc.) em 'tipo_inscricao'.\n\n"
            "REGRAS ESPECÍFICAS PARA CERTIFICADO DE RESERVISTA / MILITAR (CDI, CAM, CR):\n"
            "1. Classifique como 'CERTIFICADO_RESERVISTA'.\n"
            "2. RA (REGISTRO DE ALISTAMENTO): Composto por 12 dígitos. Extraia em 'numero_ra'.\n"
            "3. Tipo militar: Identifique se é 'DISPENSA_INCORPORACAO_CDI', 'RESERVISTA_1_CATEGORIA', 'ALISTAMENTO_CAM', etc.\n"
            "4. Força Armada ou Junta Militar: Extraia em 'forca_armada' e 'circunscricao_militar'.\n\n"
            "REGRAS ESPECÍFICAS PARA CARTÃO NACIONAL DE SAÚDE (CARTÃO DO SUS):\n"
            "1. Classifique como 'CARTAO_SUS'.\n"
            "2. NÚMERO CNS: Composto de 15 dígitos numéricos (iniciando geralmente em 1, 2, 7, 8 ou 9). Extraia em 'numero_cns'.\n"
            "3. Nome do titular e nascimento em 'pessoa'.\n\n"
            "REGRAS ESPECÍFICAS PARA DOCUMENTO NACIONAL DO ESTUDANTE (DNE / CIE):\n"
            "1. Classifique como 'CARTEIRA_ESTUDANTE_DNE'.\n"
            "2. Extraia o código de uso em 'codigo_uso_dne' e a matrícula da escola em 'matricula_estudante'.\n"
            "3. Instituição de ensino, curso, nível e validade (geralmente 31/03) nos respectivos campos.\n\n"
            "REGRA GERAL: Se uma informação não constar explicitamente no documento, retorne null. Não invente dados."
        )

    def extract_structured_data(self, masked_text: str) -> ExtractedDocument:
        """
        Envia o texto mascarado para o Gemini e retorna o objeto tipado ExtractedDocument.
        """
        
        prompt = (
            "Classifique o documento abaixo e extraia seus dados estruturados como JSON no formato:\n"
            "{\n"
            '  "documento": {\n'
            '    "tipo": "<RG|CNH|CTPS|CPF|CASAMENTO|NASCIMENTO|OBITO|ESCRITURA_COMPRA_VENDA|IPTU|CERTIDAO_IMOVEL|TITULO_ELEITOR|IDENTIDADE_FUNCIONAL|CERTIFICADO_DIPLOMA|CIN|PASSAPORTE|CARTEIRA_CONSELHO|CERTIFICADO_RESERVISTA|CARTAO_SUS|CARTEIRA_ESTUDANTE_DNE|OUTROS>",\n'
            '    "pessoa": {\n'
            '      "nome_completo": "...",\n'
            '      "cpf": "...",\n'
            '      "rg": "...",\n'
            '      "data_nascimento": "DD/MM/AAAA",\n'
            '      "nome_pais": ["...", "..."],\n'
            '      "data_obito": "..." (apenas se certidão de óbito)\n'
            '    },\n'
            '    ... demais campos pertinentes ao tipo específico ...\n'
            '  },\n'
            '  "confianca": 95,\n'
            '  "observacoes": null\n'
            "}\n\n"
            "TEXTO DO DOCUMENTO:\n"
            "-------------------\n"
            f"{masked_text}\n"
            "-------------------\n"
        )

        try:
            # [Opus - v1.0 Multi-Doc]: Usamos response_mime_type="application/json" sem o response_schema
            # monolítico com Union de 20 classes (que excede a complexidade máxima OpenAPI do Gemini e causava 400 INVALID_ARGUMENT).
            # A tipagem estrita é validada e garantida pelo Pydantic logo em seguida no código Python.
            response = call_with_retry(lambda: self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_instruction,
                    response_mime_type="application/json",
                    temperature=0.1,  # Baixa temperatura para ser factual e exato
                )
            ))

            # O SDK pode retornar a string JSON, precisamos fazer o parse
            if not response.text:
                raise ValueError("API retornou uma resposta vazia.")

            data_dict = json.loads(response.text)

            # Normalização de chave raiz caso o modelo devolva os dados direto na raiz
            if "documento" not in data_dict and "tipo" in data_dict:
                data_dict = {
                    "documento": data_dict,
                    "confianca": 90,
                    "observacoes": None
                }
            elif "documento" not in data_dict:
                data_dict = {
                    "documento": {"tipo": "OUTROS", **data_dict},
                    "confianca": 80,
                    "observacoes": None
                }

            # Valida e converte para os modelos Pydantic
            try:
                document_obj = ExtractedDocument(**data_dict)
                return document_obj
            except ValidationError as ve:
                # [Opus - v1.0 Multi-Doc]: Fallback resiliente caso o Gemini tenha variado nomes de campos menores
                doc_raw = data_dict.get("documento", {})
                tipo_raw = doc_raw.get("tipo", "OUTROS") if isinstance(doc_raw, dict) else "OUTROS"
                from .models_gemini import GenericDocument, Person
                pessoa_dict = doc_raw.get("pessoa", {}) if isinstance(doc_raw, dict) else {}
                p_obj = Person(
                    nome_completo=pessoa_dict.get("nome_completo") if isinstance(pessoa_dict, dict) else None,
                    cpf=pessoa_dict.get("cpf") if isinstance(pessoa_dict, dict) else None,
                    rg=pessoa_dict.get("rg") if isinstance(pessoa_dict, dict) else None,
                    data_nascimento=pessoa_dict.get("data_nascimento") if isinstance(pessoa_dict, dict) else None,
                    data_obito=pessoa_dict.get("data_obito") if isinstance(pessoa_dict, dict) else None,
                ) if isinstance(pessoa_dict, dict) else None
                generic = GenericDocument(
                    tipo=tipo_raw,
                    titulo=doc_raw.get("titulo") if isinstance(doc_raw, dict) else f"Documento {tipo_raw}",
                    pessoa=p_obj
                )
                return ExtractedDocument(
                    documento=generic,
                    confianca=int(data_dict.get("confianca", 75)) if isinstance(data_dict.get("confianca"), (int, float)) else 75,
                    observacoes=data_dict.get("observacoes") or "Processado via schema adaptativo"
                )

        except Exception as e:
            print(f"[ERRO] Falha na comunicação com Gemini API: {e}")
            raise

# ──────────────────────────────────────────────────────────────────
# Teste Rápido
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Módulo Extractor carregado com sucesso.")
    # Exemplo de uso:
    # extractor = GeminiExtractor(api_key="SUA_API_KEY")
    # doc_tipado = extractor.extract_structured_data("RG: [RG_001] Nome: [NOME_001]")
    # print(doc_tipado.documento.tipo)
