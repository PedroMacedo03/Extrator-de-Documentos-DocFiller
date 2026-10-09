# DocFiller — Extrator Inteligente de Documentos (v1.0)

O **DocFiller** é um aplicativo desktop Windows de alta performance construído com **PySide6** e **Fluent Design**, projetado para automatizar a leitura, extração estruturada e organização de dados de documentos civis e administrativos brasileiros, com estrita conformidade à **LGPD (Lei Geral de Proteção de Dados)**.

---

## 🌟 Funcionalidades Principais

- 📄 **20 Tipos de Documentos Brasileiros Suportados**:
  - *Identificação e Civis:* RG, CNH, Certidões (Nascimento, Casamento, Óbito), CIN (Carteira de Identidade Nacional), Passaporte Brasileiro.
  - *Eleitorais, Militares e Estudantis:* Título de Eleitor, Identidade Militar/Funcional, Certificado de Reservista/Alistamento, Documento Nacional do Estudante (DNE).
  - *Saúde e Classes Profissionais:* Cartão Nacional de Saúde (SUS), Carteiras de Ordens e Conselhos (OAB, CRM, CREA, etc.).
  - *Educação e Cartórios:* Diplomas e Certificados Escolares/Universitários, Escrituras de Imóveis, Matrículas de Imóveis, Espelho de IPTU.
- 🛡️ **Segurança e Conformidade LGPD**:
  - Os documentos são anonimizados localmente através do [`core/masker_gemini.py`](file:///f:/PEDRO/Projetos%20Antigravity/docfiller/core/masker_gemini.py). Nomes, CPFs, RGs e tokens pessoais são mascarados antes de qualquer consulta à IA. O modelo de inteligência artificial (Google Gemini) nunca recebe informações pessoais reais.
  - A desmascaração ocorre unicamente na memória RAM do computador local do usuário.
- 📑 **Arquitetura de Sessões (Processos / Lotes)**:
  - Agrupamento inteligente de múltiplos documentos sob uma mesma sessão/processo.
  - Pesquisa rápida por nome, edição direta in-place nas células, cópia individual e persistência em SQLite local.
- 🔍 **Visualizador e Prévia Integrada (Document Preview)**:
  - Renderização ultrarrápida (< 90ms) com **PyMuPDF**, controles de zoom (`+`, `-`, 100%, ajuste de largura, `Ctrl+Scroll`), paginação (`◀` / `▶`) e abertura no visualizador padrão do Windows.
- ⚙️ **OCR Híbrido e Portátil**:
  - Leitura nativa de texto em PDFs digitais e fallback automático para o Tesseract OCR portátil em imagens e documentos escaneados.

---

## 🚀 Como Executar

### Pré-requisitos
- Python 3.10 ou superior
- Windows 10 / 11

### Instalação de Dependências
```bash
pip install -r requirements.txt
```

### Execução Direta
```bash
python main.py
```
*(Ou execute `python app_gemini.py`)*

---

## 📦 Estrutura do Projeto

```
docfiller/
├── main.py                  # Ponto de entrada padrão
├── app_gemini.py            # Janela FluentWindow e navegação
├── CHANGELOG.md             # Marco histórico v0.9 e novidades da v1.0
├── requirements.txt         # Dependências do projeto
├── pyproject.toml           # Metadados de empacotamento
├── bin/tesseract/           # Binários portáteis do Tesseract OCR (Windows x64)
├── core/                    # Motores de OCR, IA, LGPD, Schemas e SQLite
│   ├── paths.py             # Resolução dinâmica de caminhos (sys.frozen)
│   ├── database_gemini.py   # Gerenciador SQLite e armazenamento
│   ├── extractor_gemini.py  # Extração estruturada via Gemini API
│   ├── masker_gemini.py     # Motor de tokenização e conformidade LGPD
│   ├── models_gemini.py     # Schemas Pydantic para 20 documentos
│   ├── ocr_local_gemini.py  # OCR Híbrido (PyMuPDF + Tesseract)
│   └── organizer_gemini.py  # Consolidação e validação cruzada
├── ui/                      # Telas da Interface Gráfica PySide6
│   ├── upload_page_gemini.py     # Upload, drag-and-drop e fila de processamento
│   ├── sessions_page_gemini.py   # Gestão de sessões, tabela e visualizador de documentos
│   ├── settings_page_gemini.py   # Configurações, chave de API e aviso LGPD
│   └── state_gemini.py           # Estado global da aplicação
├── automation/              # Motor Selenium (preparado para retorno na v1.1)
├── legacy/                  # Histórico de versões anteriores arquivadas
└── data/                    # Banco SQLite local e documentos arquivados
```
