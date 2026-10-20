"""
DocFiller — Página de Upload e Extração
=======================================
Permite que o usuário arraste PDFs ou imagens. 
Roda o OCR e a API do Gemini em uma Thread de fundo (QThread)
para não congelar a janela, emitindo progresso em tempo real.
"""

import sys
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QListWidget, QProgressBar, QFileDialog, QInputDialog,
                               QListWidgetItem)

try:
    from qfluentwidgets import (TitleLabel, SubtitleLabel, BodyLabel, 
                                PrimaryPushButton, PushButton, InfoBar, InfoBarPosition,
                                ComboBox, CardWidget, ListWidget)
    from .state_gemini import AppState
    
    # Imports do backend
    sys.path.append(str(Path(__file__).parent.parent))
    from core.ocr_local_gemini import HybridOCR
    from core.masker_gemini import DataMasker
    from core.extractor_gemini import GeminiExtractor
    from core.database_gemini import DatabaseManager
    # [Opus - v1.0 Multi-Doc]: Segmentação de arquivos com vários documentos
    from core.segmenter_gemini import (DocumentSegmenter, join_pages_with_markers,
                                       split_masked_text, split_pdf, convert_image_to_pdf)
except ImportError:
    pass

# =====================================================================
# WORKER: Roda pesado em segundo plano (evita travamento da UI)
# =====================================================================
class ExtractWorker(QThread):
    progress = Signal(int, str)  # (porcentagem, mensagem_de_status)
    finished = Signal(int)       # (id_da_extracao_no_banco)
    error = Signal(str)          # (mensagem_de_erro)

    # [LEGACY]: def __init__(self, file_path: str):
    # [GEMINI - FASE 6]: Suporte a session_id para atrelar a extração à sessão correta
    def __init__(self, file_path: str, session_id: int = None):
        super().__init__()
        self.file_path = file_path
        self.session_id = session_id
        # [Opus - v1.0 Multi-Doc]: Um arquivo pode gerar vários registros (PDF com vários documentos)
        self.row_ids: list[int] = []
        self.failed_segments: list[str] = []

    def run(self):
        try:
            # 1. Validação de API Key
            if not AppState.GEMINI_API_KEY:
                self.error.emit("Chave da API do Gemini ausente! Vá em 'Configurações' e cole sua chave.")
                return

            # 2. Inicialização dos motores
            self.progress.emit(10, "Iniciando motor de OCR...")
            ocr = HybridOCR(tesseract_cmd=AppState.TESSERACT_PATH)
            masker = DataMasker()
            extractor = GeminiExtractor(api_key=AppState.GEMINI_API_KEY, model_name=AppState.GEMINI_MODEL)
            db = DatabaseManager()

            # 3. Salva uma cópia local segura
            self.progress.emit(15, "Salvando cópia do documento no sistema...")
            saved_path = db.save_file_locally(self.file_path)

            # [Opus - v1.0 Multi-Doc]: TIFF multipágina vira PDF para entrar no mesmo fluxo
            if saved_path.suffix.lower() in (".tif", ".tiff"):
                saved_path = convert_image_to_pdf(saved_path, saved_path.parent)

            # [LEGACY]: raw_text = ocr.extract_text(saved_path)  (texto único, 1 documento por arquivo)
            # [Opus - v1.0 Multi-Doc]: OCR página a página
            self.progress.emit(25, "Extraindo texto bruto (OCR) página a página...")
            pages = ocr.extract_pages(saved_path)
            if not any(p.strip() for p in pages):
                raise ValueError("Nenhum texto encontrado na imagem/PDF.")
            num_pages = len(pages)

            # 5. Mascaramento LGPD (Scrub) — arquivo inteiro de uma vez, com marcadores de página,
            # para que os tokens sejam consistentes entre as páginas.
            self.progress.emit(45, "Aplicando filtros de privacidade LGPD (Mascaramento)...")
            masking_result = masker.mask(join_pages_with_markers(pages))
            masked_pages = split_masked_text(masking_result.masked_text, num_pages)
            full_token_map = masking_result.token_map

            # [Opus - v1.0 Multi-Doc]: Segmentação (somente texto mascarado vai à nuvem)
            if num_pages > 1:
                self.progress.emit(55, f"Identificando documentos dentro do arquivo ({num_pages} páginas)...")
                segmenter = DocumentSegmenter(api_key=AppState.GEMINI_API_KEY, model_name=AppState.GEMINI_MODEL)
                segments = segmenter.segment(masked_pages)
            else:
                segments = [(1, 1, "")]

            multi = len(segments) > 1
            if multi:
                sub_paths = split_pdf(saved_path, segments, saved_path.parent, saved_path.stem)
            else:
                sub_paths = [saved_path]

            # 6/7. Extração estruturada + gravação, um registro por documento
            original_stem = Path(self.file_path).stem
            for idx, ((a, b, _tipo), sub_path) in enumerate(zip(segments, sub_paths), start=1):
                pct = 60 + int(35 * (idx - 1) / len(segments))
                self.progress.emit(pct, f"Enviando documento {idx}/{len(segments)} para a IA (Gemini)...")
                seg_text = "\n\n".join(masked_pages[a - 1:b])
                # [Opus - Security Audit (Item 8)]: Filtro case-insensitive para tokens presentes neste segmento
                seg_text_upper = seg_text.upper()
                seg_token_map = {t: v for t, v in full_token_map.items() if t.upper() in seg_text_upper}
                pages_label = f"p.{a}" if a == b else f"p.{a}-{b}"
                try:
                    extracted_doc = extractor.extract_structured_data(seg_text)
                    doc_dict = extracted_doc.documento.model_dump(exclude_none=True)
                    doc_type = extracted_doc.documento.tipo
                    # [LEGACY]: log_extraction sem session_id
                    # [GEMINI - FASE 6]: Passa session_id explicitamente
                    row_id = db.log_extraction(
                        saved_file_path=sub_path,
                        original_name=(f"{original_stem} ({pages_label}).pdf" if multi else Path(self.file_path).name),
                        doc_type=doc_type,
                        extracted_data={"dados": doc_dict, "token_map": seg_token_map},
                        session_id=self.session_id
                    )
                    self.row_ids.append(row_id)
                except Exception as seg_err:
                    # Um documento com falha não derruba os demais do mesmo arquivo
                    if not multi:
                        raise
                    self.failed_segments.append(f"{pages_label}: {seg_err}")

            if not self.row_ids:
                raise ValueError("Nenhum documento pôde ser extraído: " + "; ".join(self.failed_segments))

            self.progress.emit(100, "Extração concluída com sucesso!")
            self.finished.emit(self.row_ids[-1])

        except Exception as e:
            self.error.emit(str(e))


# =====================================================================
# INTERFACE GRÁFICA: Upload Page
# =====================================================================
class UploadPage(QWidget):
    # [GEMINI - CORREÇÃO H3]: Sinal emitido ao concluir a extração de um documento
    document_processed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("UploadPage")
        
        self.db = DatabaseManager()
        
        # Habilita o "Arrastar e Soltar" nesta página
        self.setAcceptDrops(True)
        
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(40, 30, 40, 30)
        self.vBoxLayout.setSpacing(15)
        
        self.titleLabel = TitleLabel("Upload de Documentos", self)
        self.vBoxLayout.addWidget(self.titleLabel)
        
        # [GEMINI - FASE 6]: Painel de Seleção e Criação de Sessão Ativa
        sessionCard = CardWidget(self)
        sessionLayout = QHBoxLayout(sessionCard)
        sessionLayout.setContentsMargins(15, 12, 15, 12)
        sessionLayout.setSpacing(15)
        
        sessionLayout.addWidget(BodyLabel("📁 <b>Sessão / Processo Ativo:</b>", sessionCard))
        
        self.sessionCombo = ComboBox(sessionCard)
        self.sessionCombo.setMinimumWidth(320)
        sessionLayout.addWidget(self.sessionCombo)
        
        self.btnNewSession = PushButton("➕ Nova Sessão", sessionCard)
        self.btnNewSession.clicked.connect(self.create_new_session_dialog)
        sessionLayout.addWidget(self.btnNewSession)
        
        sessionLayout.addStretch(1)
        self.vBoxLayout.addWidget(sessionCard)
        
        # Área de Drop
        self.dropLabel = TitleLabel("Arraste seus PDFs ou Imagens Aqui", self)
        self.dropLabel.setAlignment(Qt.AlignCenter)
        self.dropLabel.setStyleSheet("""
            QLabel {
                border: 2px dashed #666;
                border-radius: 10px;
                background-color: rgba(255, 255, 255, 0.03);
                padding: 30px;
                color: #aaa;
            }
        """)
        self.vBoxLayout.addWidget(self.dropLabel)
        
        # [GEMINI - FASE 6]: Botão manual para selecionar arquivos além do arrastar-e-soltar
        actionRow = QHBoxLayout()
        self.btnSelectFiles = PrimaryPushButton("📁 Selecionar Arquivos do Computador", self)
        self.btnSelectFiles.clicked.connect(self.select_files_manually)
        actionRow.addWidget(self.btnSelectFiles)
        
        # [Opus - v1.0 Multi-Doc]: texto atualizado (TIFF + PDFs com vários documentos)
        self.descLabel = BodyLabel("Formatos suportados: PDF, PNG, JPG, JPEG, TIFF. PDFs com vários documentos são separados automaticamente.", self)
        actionRow.addWidget(self.descLabel)
        actionRow.addStretch(1)
        self.vBoxLayout.addLayout(actionRow)
        
        # Barra de Progresso
        self.progressBar = QProgressBar(self)
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        self.progressBar.setTextVisible(False)
        self.progressBar.hide()
        self.vBoxLayout.addWidget(self.progressBar)
        
        # Status Label
        self.statusLabel = BodyLabel("Aguardando arquivo...", self)
        self.statusLabel.hide()
        self.vBoxLayout.addWidget(self.statusLabel)
        
        # [GEMINI - FASE 6]: Cabeçalho da fila com botão de limpar
        queueHeaderLayout = QHBoxLayout()
        self.historyLabel = SubtitleLabel("Fila de Processamento e Documentos Desta Sessão:", self)
        queueHeaderLayout.addWidget(self.historyLabel)
        queueHeaderLayout.addStretch(1)
        
        self.btnClearQueue = PushButton("🗑️ Limpar Fila", self)
        self.btnClearQueue.clicked.connect(self.clear_queue)
        queueHeaderLayout.addWidget(self.btnClearQueue)
        self.vBoxLayout.addLayout(queueHeaderLayout)
        
        # [GEMINI - CORREÇÃO TEMA ESCURO]: Uso de CardWidget + ListWidget do QFluentWidgets
        # Elimina o fundo branco forçado que deixava o texto invisível no modo escuro
        queueCard = CardWidget(self)
        queueLayout = QVBoxLayout(queueCard)
        queueLayout.setContentsMargins(6, 6, 6, 6)
        
        self.fileList = ListWidget(queueCard)
        self.fileList.setMinimumHeight(160)
        queueLayout.addWidget(self.fileList)
        self.vBoxLayout.addWidget(queueCard)
        
        # Referência ao Worker para não ser limpo pelo Garbage Collector
        self.worker = None
        # [GEMINI - CORREÇÃO M6]: Fila para múltiplos arquivos
        self.file_queue: list[str] = []
        
        # Inicializa a lista de sessões
        self.reload_sessions()

    # --- Gerenciamento de Sessão ---
    def reload_sessions(self, select_id: int = None):
        """Recarrega o combobox de sessões e preserva a seleção."""
        self.sessionCombo.clear()
        sessions = self.db.get_all_sessions()
        
        if not sessions:
            default_id = self.db.get_or_create_default_session()
            sessions = self.db.get_all_sessions()
            
        target_index = 0
        for idx, s in enumerate(sessions):
            display_text = f"{s['name']} ({s['doc_count']} docs)"
            self.sessionCombo.addItem(display_text, userData=s['id'])
            if select_id is not None and s['id'] == select_id:
                target_index = idx
                
        self.sessionCombo.setCurrentIndex(target_index)

    def get_active_session_id(self) -> int:
        """Retorna o ID da sessão atualmente selecionada."""
        idx = self.sessionCombo.currentIndex()
        if idx >= 0:
            sid = self.sessionCombo.itemData(idx)
            if sid is not None:
                return int(sid)
        return self.db.get_or_create_default_session()

    def set_active_session(self, session_id: int):
        """Define a sessão ativa vinda de outra página (ex: Retomar Sessão)."""
        self.reload_sessions(select_id=session_id)
        InfoBar.info("Sessão Ativada", f"Novos uploads serão salvos nesta sessão.", duration=2500, parent=self)

    def create_new_session_dialog(self):
        """Abre diálogo para criar nova sessão com nome padrão data/hora."""
        # [GEMINI]: Formato solicitado: HH/MM - DD/MM/AA
        default_name = datetime.now().strftime("Sessão %H/%M - %d/%m/%y")
        name, ok = QInputDialog.getText(
            self, 
            "Nova Sessão", 
            "Nome do Processo / Sessão:", 
            text=default_name
        )
        if ok and name.strip():
            new_id = self.db.create_session(name=name.strip())
            self.reload_sessions(select_id=new_id)
            InfoBar.success("Sessão Criada", f"'{name.strip()}' definida como ativa!", duration=3000, parent=self)

    # --- Seleção Manual de Arquivos ---
    def select_files_manually(self):
        """Abre diálogo para seleção de múltiplos arquivos do computador."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Selecionar Documentos para Extração",
            "",
            "Documentos Suportados (*.pdf *.png *.jpg *.jpeg *.tif *.tiff);;PDFs (*.pdf);;Imagens (*.png *.jpg *.jpeg *.tif *.tiff);;Todos os Arquivos (*.*)"
        )
        if files:
            self._enqueue_files(files)

    def clear_queue(self):
        """Limpa a fila pendente e os itens visuais."""
        self.file_queue.clear()
        self.fileList.clear()
        self.statusLabel.setText("Fila limpa.")
        self.progressBar.hide()
        InfoBar.info("Fila Limpa", "A lista de processamento foi reiniciada.", duration=2000, parent=self)

    # --- Eventos de Arrastar e Soltar Nativo do PySide6 ---
    def dragEnterEvent(self, event):
        """Disparado quando o arquivo entra na área da página."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.dropLabel.setStyleSheet("""
                QLabel {
                    border: 2px dashed #009faa;
                    border-radius: 10px;
                    background-color: rgba(0, 159, 170, 0.1);
                    padding: 30px;
                }
            """)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """Disparado se o usuário desistir de soltar."""
        self.dropLabel.setStyleSheet("""
            QLabel {
                border: 2px dashed #666;
                border-radius: 10px;
                background-color: transparent;
                padding: 30px;
                color: #aaa;
            }
        """)

    def dropEvent(self, event):
        """Disparado quando o arquivo é solto na página."""
        self.dragLeaveEvent(event)
        
        if event.mimeData().hasUrls():
            raw_paths = [url.toLocalFile() for url in event.mimeData().urls()]
            self._enqueue_files(raw_paths)

    def _format_file_size(self, size_bytes: int) -> str:
        """Formata bytes em KB ou MB."""
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes / (1024 * 1024):.2f} MB"

    def _enqueue_files(self, paths: list[str]):
        """Valida e adiciona arquivos na fila com visualização informativa."""
        valid_files = []
        for fp in paths:
            p = Path(fp)
            if p.suffix.lower() in ['.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff']:  # [Opus - v1.0 Multi-Doc]: +TIFF
                valid_files.append(fp)
                
        if not valid_files:
            InfoBar.error("Formato Inválido", "Selecione apenas arquivos PDF ou Imagens (PNG/JPG).", parent=self)
            return

        for fp in valid_files:
            p = Path(fp)
            icon = "📄 PDF" if p.suffix.lower() == '.pdf' else "🖼️ Imagem"
            try:
                size_str = self._format_file_size(p.stat().st_size)
            except Exception:
                size_str = "Tamanho desc."
            self.fileList.addItem(f"{icon} | {p.name} ({size_str}) — ⏳ Na fila")

        self.file_queue.extend(valid_files)
        if self.worker is None or not self.worker.isRunning():
            self._process_next_in_queue()

    def _process_next_in_queue(self):
        """Executa a extração do próximo documento da fila."""
        if not self.file_queue:
            return
            
        next_file = self.file_queue.pop(0)
        self.start_extraction(next_file)

    # --- Controle da Extração ---
    def start_extraction(self, file_path: str):
        """Inicia a QThread de extração para não congelar a tela."""
        if self.worker is not None and self.worker.isRunning():
            return

        active_session_id = self.get_active_session_id()
        self.progressBar.show()
        self.statusLabel.show()
        self.progressBar.setValue(0)
        remaining = len(self.file_queue)
        suffix = f" (+{remaining} na fila)" if remaining > 0 else ""
        filename = Path(file_path).name
        self.statusLabel.setText(f"Iniciando: {filename}{suffix}")

        # [Opus - v1.0 Multi-Doc]: Atualiza o status visual do item na lista para 'Processando...'
        for i in range(self.fileList.count()):
            item = self.fileList.item(i)
            if filename in item.text() and "Na fila" in item.text():
                item.setText(f"⚙️ {item.text().split('—')[0].strip()} — Processando...")
                break

        # [GEMINI - FASE 6]: Passa session_id para o Worker
        self.worker = ExtractWorker(file_path, session_id=active_session_id)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.extraction_finished)
        self.worker.error.connect(self.extraction_error)
        
        self.worker.start()

    def update_progress(self, percent: int, msg: str):
        self.progressBar.setValue(percent)
        remaining = len(self.file_queue)
        suffix = f" (+{remaining} na fila)" if remaining > 0 else ""
        self.statusLabel.setText(f"{msg}{suffix}")

    def extraction_finished(self, row_id: int):
        self.progressBar.setValue(100)
        filename = Path(self.worker.file_path).name
        # [Opus - v1.0 Multi-Doc]: Um arquivo pode ter gerado vários documentos
        row_ids = list(getattr(self.worker, "row_ids", None) or [row_id])
        n_docs = len(row_ids)
        docs_suffix = f" — {n_docs} documentos encontrados" if n_docs > 1 else ""
        
        # Atualiza o item na lista se existir
        for i in range(self.fileList.count()):
            item = self.fileList.item(i)
            if filename in item.text() and ("Na fila" in item.text() or "Processando" in item.text()):
                item.setText(f"✅ {item.text().split('—')[0].strip()} — Concluído e Salvo{docs_suffix}")
                break
        else:
            self.fileList.addItem(f"✅ {filename} (Salvo no Banco){docs_suffix}")
        
        # Atualiza contagem na combo de sessões
        self.reload_sessions(select_id=self.worker.session_id)
        
        # [GEMINI - CORREÇÃO H3]: Notifica ouvintes externos
        # [LEGACY]: self.document_processed.emit(row_id)
        # [Opus - v1.0 Multi-Doc]: um sinal por documento extraído
        for rid in row_ids:
            self.document_processed.emit(rid)
        
        if n_docs > 1:
            InfoBar.success("Concluído", f"{filename}: {n_docs} documentos separados e processados!", duration=4000, parent=self)
        else:
            InfoBar.success("Concluído", f"{filename} processado com sucesso!", duration=3000, parent=self)
        failed = getattr(self.worker, "failed_segments", None)
        if failed:
            InfoBar.warning("Atenção", f"{len(failed)} trecho(s) do arquivo não puderam ser extraídos: " + "; ".join(failed), duration=10000, parent=self)
        
        # [GEMINI - CORREÇÃO M6]: Continua processando próximo item da fila se houver
        if self.file_queue:
            self._process_next_in_queue()
        else:
            self.statusLabel.setText("Todos os documentos da fila foram processados!")

    def extraction_error(self, error_msg: str):
        self.progressBar.hide()
        filename = Path(self.worker.file_path).name if self.worker else "Arquivo"
        self.statusLabel.setText(f"Erro ao processar {filename}.")

        # [Opus - v1.0 Multi-Doc]: Atualiza o item na lista para erro em vez de mantê-lo 'Na fila'
        for i in range(self.fileList.count()):
            item = self.fileList.item(i)
            if filename in item.text() and ("Na fila" in item.text() or "Processando" in item.text()):
                item.setText(f"❌ {item.text().split('—')[0].strip()} — Falha no processamento")
                break

        InfoBar.error("Erro na Extração", f"{filename}: {error_msg}", duration=10000, parent=self)
        
        # Continua para os próximos arquivos mesmo se um falhar
        if self.file_queue:
            self._process_next_in_queue()
