# DocFiller — Arquivo Legacy (Histórico de Versões)

Este diretório preserva versões anteriores de módulos que foram substituídos por implementações superiores ao longo do desenvolvimento do projeto. Eles representam o "caminho das pedras" — a evolução técnica que nos trouxe até a versão atual.

> Nenhum desses arquivos é utilizado pelo aplicativo. São mantidos exclusivamente como documentação histórica.

## Arquivos Arquivados

| Arquivo | Substituído Por | Motivo da Substituição |
|:---|:---|:---|
| `legacy_masker.py` | `core/masker_gemini.py` | Motor LGPD reescrito com regex contextual para nomes em CAIXA ALTA, TitleCase, acentos e termos cartorários |
| `legacy_ocr_poppler.py` | `core/ocr_local_gemini.py` | Migração de Poppler/pdf2image para PyMuPDF nativo, eliminando dependência de binários C++ externos |
| `data_page_gemini.py` | `ui/sessions_page_gemini.py` | Aba "Dados Extraídos" (tabela plana) substituída pela arquitetura de Sessões com QSplitter, chips naturais e Document Preview integrado |
| `legacy_sessions_page_v1_0.py` | `ui/sessions_page_gemini.py` + `ui/sessions/*` | Versão v1.0.2 da aba "Sessões e Documentos" (com tabela por documento e modais `DocumentDetailDialog` / `EditDocumentDataDialog`), substituída na v1.1 pelo layout de 4 colunas orientado a Pessoas e Imóveis |

---

*Arquivados durante as transições v0.9 → v1.0 → v1.1 (Setembro–Outubro/2026)*
