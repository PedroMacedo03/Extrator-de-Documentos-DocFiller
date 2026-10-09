# DocFiller — Histórico de Versões (Changelog)

---

## v1.0.1 — "Multi-Documento" (Outubro/2026)

> [Opus - v1.0 Multi-Doc]

### ✨ Novo

- **PDFs/TIFFs com vários documentos em um único arquivo** (ex.: RG + CNH + Certidão num mesmo scan) agora são **separados automaticamente**. Cada documento vira um registro próprio na sessão, com seu próprio sub-PDF, preview e dados extraídos. O arquivo original é preservado.
- Frente e verso do mesmo documento (RG, CNH, CIN) e documentos de várias páginas (certidões, escrituras) permanecem juntos.
- **TIFF multipágina** aceito (convertido internamente para PDF).
- A fila de upload informa quantos documentos foram encontrados em cada arquivo.
- **Retentativa automática** quando a API Gemini responde 503 "alta demanda" (comum no plano gratuito): até 3 novas tentativas com espera crescente.

### 🔒 Privacidade (LGPD)
- O arquivo inteiro é mascarado **antes** de qualquer chamada à nuvem; a segmentação e a extração recebem apenas texto com tokens. O `token_map` é isolado por documento (um documento nunca recebe tokens de outro).

### 🧩 Detalhes técnicos
- Novos módulos: `core/segmenter_gemini.py`, `core/retry_gemini.py`. `HybridOCR.extract_pages()` decide, página a página, entre texto nativo e OCR (PDFs mistos).
- Arquivo de 1 página/1 documento segue o fluxo anterior, sem chamada extra à IA.
- Se um documento do arquivo falhar, os demais são salvos e o usuário é avisado.

---

## v1.0 — "Extração & Sessões" (Em desenvolvimento — Setembro/2026)

> Primeira versão distribuível como aplicativo Windows (.exe).
> Foco em **extração inteligente de documentos** e **gerenciamento de sessões**.

### ✨ O que há de novo na v1.0

- **20 tipos de documentos brasileiros** suportados com extração estruturada via IA (Gemini)
- **Arquitetura de Sessões** completa com busca, renomeação, retomada e exclusão
- **Visualizador integrado de documentos** (PyMuPDF) com zoom, paginação e abertura externa
- **Segurança LGPD** com mascaramento de dados pessoais antes do envio à nuvem
- **OCR Híbrido** (PyMuPDF + Tesseract) com pré-processamento adaptativo
- **API Key segura** — gravada localmente via `settings.json`, nunca no código-fonte
- **Interface Fluent Design** com tema claro/escuro automático

### 🔒 Funcionalidade Suspensa Temporariamente

- **Automação Web (Selenium)**: O preenchimento automático de formulários em sites foi desativado na v1.0. Todo o código permanece intacto em `automation/` e `ui/automation_page_gemini.py` para reativação em versão futura. O motor YAML, os handlers de campos e o gerenciador de CAPTCHA continuam funcionais e prontos para integração.

---

## v0.9 — "Fundação Completa" (Setembro/2026)

> Versão de desenvolvimento interno com todas as funcionalidades construídas mas não empacotada para distribuição.

### Marcos Alcançados

- **Fase 1:** Diagnóstico, limpeza de dependências (Poppler → PyMuPDF), padronização de tags `[LEGACY]`/`[GEMINI]`
- **Fase 2:** OCR Híbrido com multi-pass e pré-processamento adaptativo (OpenCV)
- **Fase 3:** Motor LGPD completo — mascaramento contextual de nomes, CPFs, RGs e tokens cartorários
- **Fase 4:** Banco de dados SQLite com arquitetura de Sessões e migração transparente
- **Fase 5:** Redesign da página de Upload — seleção manual, fila visual, vinculação a sessões
- **Fase 6:** Redesign da página de Sessões — chips naturais, tabela responsiva, edição in-place, QSplitter
- **Fase 7:** Visualizador de documentos integrado (PyMuPDF < 90ms, zoom, paginação, Ctrl+Scroll)
- **Fase 8 & 9:** Expansão para 20 tipos de documentos (CIN, Passaporte, Título de Eleitor, Reservista, SUS, DNE, Conselhos OAB/CRM/CREA, Diplomas, Identidade Militar/Funcional)
- **Automação Web (Selenium):** Motor de preenchimento YAML, handlers de campos (text, date, select, checkbox, radio, file upload), gerenciador de browser com anti-detecção, pausa por CAPTCHA (reCAPTCHA, hCaptcha, Turnstile) e modal de intervenção humana — **funcional mas suspenso para a v1.0**

### Arquivos Legados Arquivados

Os seguintes módulos foram substituídos e movidos para `legacy/`:
- `legacy_masker.py` → substituído por `core/masker_gemini.py`
- `legacy_ocr_poppler.py` → substituído por `core/ocr_local_gemini.py`
- `data_page_gemini.py` → substituído por `ui/sessions_page_gemini.py`
