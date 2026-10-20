"""
DocFiller — Aba de Sessões e Documentos (v1.1 — Estação de Verificação Manual)
==============================================================================

[Opus - v1.1 Sessions Redesign]:
Implementa o novo layout de 4 colunas projetado pelo usuário para verificação manual:
- Coluna 1 (SessionListPanel): Lista de sessões com ordem de criação fixa (seq_number),
  data de criação e data da última alteração. O nome só muda manualmente.
- Coluna 2 (SessionEntityPanel):
    1. DADOS (atributos consolidados da Pessoa selecionada)
    2. PESSOAS (titular, cônjuges, comprador e vendedor reconhecidos na sessão)
    3. DOCUMENTOS (documentos pertencentes à Pessoa selecionada, sem exibir dados pessoais)
    4. IMÓVEIS (imóveis reconhecidos na sessão)
    5. DADOS IMÓVEL (atributos consolidados do Imóvel selecionado)
    6. Rodapé com DATA DE CRIAÇÃO DA SESSÃO e DATA DA ÚLTIMA ALTERAÇÃO DA SESSÃO
- Coluna 3 (AttachedDocsPanel): LISTA DOS DOCS. ANEXADOS na sessão (apenas tipo e arquivo,
  sem mostrar informações pessoais).
- Coluna 4 (DocumentPreviewWidget): PRÉVIA DO DOCUMENTO SELECIONADO (renderização PyMuPDF
  com zoom/páginas, livre de tabelas de dados pessoais ao lado).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pymupdf
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QScrollArea, QSplitter, QVBoxLayout, QWidget
)

from qfluentwidgets import BodyLabel, CardWidget, InfoBar, PushButton

sys.path.append(str(Path(__file__).parent.parent))
from core.database_gemini import DatabaseManager
from core.entity_resolver_gemini import EntityResolver
from ui.sessions import (
    AttachedDocsPanel,
    SessionEntityPanel,
    SessionListPanel,
)


def resolve_doc_path(file_path: str) -> Optional[Path]:
    """
    [GEMINI]: Resolve o caminho de um documento armazenado no banco local.
    Suporta caminhos absolutos e relativos à pasta raiz do DocFiller.
    """
    if not file_path:
        return None
    p = Path(file_path)
    if p.is_file():
        return p
    proj_root = Path(__file__).resolve().parent.parent
    candidate = proj_root / file_path
    if candidate.is_file():
        return candidate
    cwd_candidate = Path.cwd() / file_path
    if cwd_candidate.is_file():
        return cwd_candidate
    return None


# =====================================================================
# COLUNA 4: Visualizador e Prévia Integrada de Documentos (sem dados pessoais)
# =====================================================================
class DocumentPreviewWidget(CardWidget):
    """
    [GEMINI / Opus - v1.1 Sessions Redesign]:
    Coluna 4 ('PRÉVIA DO DOCUMENTO SELECIONADO' do mockup).
    Renderiza páginas com PyMuPDF em alta fidelidade com controles de página e zoom,
    sem exibir informações pessoais junto ao documento.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent=parent)
        self.doc = None
        self.current_page: int = 0
        self.total_pages: int = 0
        self.zoom_factor: float = 1.0
        self.min_zoom: float = 0.4
        self.max_zoom: float = 3.0
        self.zoom_step: float = 0.2
        self.file_path: Optional[str] = None
        self.resolved_path: Optional[Path] = None
        self.original_name: str = ""
        self.doc_type: str = ""

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Barra de ferramentas superior da prévia
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.lbl_doc_info = BodyLabel("📄 <b>PRÉVIA DO DOCUMENTO SELECIONADO</b>", self)
        toolbar.addWidget(self.lbl_doc_info)

        toolbar.addStretch(1)

        # Navegação de páginas
        self.btn_prev_page = PushButton("◀", self)
        self.btn_prev_page.setFixedSize(28, 26)
        self.btn_prev_page.setToolTip("Página Anterior")
        self.btn_prev_page.clicked.connect(self.prev_page)
        self.btn_prev_page.setEnabled(False)
        toolbar.addWidget(self.btn_prev_page)

        self.lbl_page_counter = BodyLabel("Pág. 0 / 0", self)
        self.lbl_page_counter.setStyleSheet("font-weight: 500; font-size: 12px;")
        toolbar.addWidget(self.lbl_page_counter)

        self.btn_next_page = PushButton("▶", self)
        self.btn_next_page.setFixedSize(28, 26)
        self.btn_next_page.setToolTip("Próxima Página")
        self.btn_next_page.clicked.connect(self.next_page)
        self.btn_next_page.setEnabled(False)
        toolbar.addWidget(self.btn_next_page)

        sep1 = QFrame(self)
        sep1.setFrameShape(QFrame.VLine)
        sep1.setFrameShadow(QFrame.Sunken)
        toolbar.addWidget(sep1)

        # Controles de Zoom
        self.btn_zoom_out = PushButton("🔍 -", self)
        self.btn_zoom_out.setFixedSize(44, 26)
        self.btn_zoom_out.setToolTip("Reduzir Zoom (Ctrl + Roda)")
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.btn_zoom_out.setEnabled(False)
        toolbar.addWidget(self.btn_zoom_out)

        self.lbl_zoom = BodyLabel("100%", self)
        self.lbl_zoom.setFixedWidth(42)
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        toolbar.addWidget(self.lbl_zoom)

        self.btn_zoom_in = PushButton("🔍 +", self)
        self.btn_zoom_in.setFixedSize(44, 26)
        self.btn_zoom_in.setToolTip("Aumentar Zoom (Ctrl + Roda)")
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        self.btn_zoom_in.setEnabled(False)
        toolbar.addWidget(self.btn_zoom_in)

        self.btn_fit_width = PushButton("↔️ Ajustar", self)
        self.btn_fit_width.setFixedSize(76, 26)
        self.btn_fit_width.setToolTip("Ajustar visualização à largura do painel")
        self.btn_fit_width.clicked.connect(self.fit_width)
        self.btn_fit_width.setEnabled(False)
        toolbar.addWidget(self.btn_fit_width)

        sep2 = QFrame(self)
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFrameShadow(QFrame.Sunken)
        toolbar.addWidget(sep2)

        self.btn_open_external = PushButton("📂 Abrir", self)
        self.btn_open_external.setFixedHeight(26)
        self.btn_open_external.setToolTip("Abrir documento no leitor padrão do Windows")
        self.btn_open_external.clicked.connect(self.open_in_windows)
        self.btn_open_external.setEnabled(False)
        toolbar.addWidget(self.btn_open_external)

        layout.addLayout(toolbar)

        # Área de scroll com a página renderizada
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: rgba(128, 128, 128, 0.08);
                border: 1px solid rgba(128, 128, 128, 0.18);
                border-radius: 8px;
            }
        """)

        self.image_container = QWidget()
        img_box = QVBoxLayout(self.image_container)
        img_box.setContentsMargins(12, 12, 12, 12)
        img_box.setAlignment(Qt.AlignCenter)

        self.lbl_image = QLabel(self.image_container)
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setText("PRÉVIA DO\nDOCUMENTO\nSELECIONADO")
        self.lbl_image.setStyleSheet(
            "color: #888; font-size: 16px; font-weight: 700; letter-spacing: 1px;"
        )
        img_box.addWidget(self.lbl_image)

        self.scroll_area.setWidget(self.image_container)
        layout.addWidget(self.scroll_area, 1)

    def load_document(self, file_path: str, original_name: str = "", doc_type: str = ""):
        """Carrega e renderiza o documento selecionado."""
        self.close_document()

        self.file_path = file_path
        self.original_name = original_name or (Path(file_path).name if file_path else "")
        self.doc_type = doc_type
        self.resolved_path = resolve_doc_path(file_path)

        if not self.resolved_path or not self.resolved_path.exists():
            self._show_not_found(file_path)
            return

        try:
            self.doc = pymupdf.open(str(self.resolved_path))
            self.total_pages = len(self.doc)
            self.current_page = 0
            self.zoom_factor = 1.0

            badge = (
                f"<span style='color: #009faa; font-weight: bold;'>[{self.doc_type}]</span>"
                if self.doc_type else ""
            )
            self.lbl_doc_info.setText(f"📄 <b>{self.original_name}</b> {badge}")
            self.btn_open_external.setEnabled(True)
            self.btn_zoom_out.setEnabled(True)
            self.btn_zoom_in.setEnabled(True)
            self.btn_fit_width.setEnabled(True)

            self.render_current_page()

        except Exception as e:
            self.lbl_image.setPixmap(QPixmap())
            self.lbl_image.setText(f"⚠️ Erro ao abrir documento:\n{e}")
            self.lbl_image.setStyleSheet("color: #d13438; font-size: 13px; padding: 20px;")
            self._disable_controls()

    def _show_not_found(self, file_path: str):
        self.lbl_image.setPixmap(QPixmap())
        self.lbl_image.setText(
            f"⚠️ Documento não encontrado no disco local:\n{file_path}\n\n"
            "Verifique se o arquivo ainda existe na pasta 'data/documents/'."
        )
        self.lbl_image.setStyleSheet("color: #d83b01; font-size: 13px; padding: 20px;")
        self.lbl_doc_info.setText("📄 <i>Arquivo não encontrado</i>")
        self._disable_controls()

    def _disable_controls(self):
        self.btn_prev_page.setEnabled(False)
        self.btn_next_page.setEnabled(False)
        self.btn_zoom_out.setEnabled(False)
        self.btn_zoom_in.setEnabled(False)
        self.btn_fit_width.setEnabled(False)
        self.btn_open_external.setEnabled(False)
        self.lbl_page_counter.setText("Pág. 0 / 0")

    def render_current_page(self):
        if not self.doc or self.current_page < 0 or self.current_page >= self.total_pages:
            return
        try:
            page = self.doc[self.current_page]
            target_dpi = int(max(60, min(300, 140 * self.zoom_factor)))
            pix = page.get_pixmap(dpi=target_dpi)

            fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
            qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
            pixmap = QPixmap.fromImage(qimg)

            self.lbl_image.setText("")
            self.lbl_image.setPixmap(pixmap)
            self.lbl_image.setStyleSheet("border: 1px solid rgba(0, 0, 0, 0.15); border-radius: 4px;")

            self.lbl_page_counter.setText(f"Pág. {self.current_page + 1} / {self.total_pages}")
            self.lbl_zoom.setText(f"{int(self.zoom_factor * 100)}%")
            self.btn_prev_page.setEnabled(self.current_page > 0)
            self.btn_next_page.setEnabled(self.current_page < self.total_pages - 1)
        except Exception as e:
            self.lbl_image.setText(f"⚠️ Erro ao renderizar página {self.current_page + 1}: {e}")

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.render_current_page()

    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.render_current_page()

    def zoom_in(self):
        if self.zoom_factor < self.max_zoom:
            self.zoom_factor = min(self.max_zoom, round(self.zoom_factor + self.zoom_step, 2))
            self.render_current_page()

    def zoom_out(self):
        if self.zoom_factor > self.min_zoom:
            self.zoom_factor = max(self.min_zoom, round(self.zoom_factor - self.zoom_step, 2))
            self.render_current_page()

    def fit_width(self):
        if not self.doc:
            return
        vw = self.scroll_area.viewport().width() - 40
        if vw <= 100:
            return
        page = self.doc[self.current_page]
        base_width_at_140dpi = page.rect.width * (140.0 / 72.0)
        if base_width_at_140dpi > 0:
            factor = vw / base_width_at_140dpi
            self.zoom_factor = max(self.min_zoom, min(self.max_zoom, round(factor, 2)))
            self.render_current_page()

    def open_in_windows(self):
        if self.resolved_path and self.resolved_path.is_file():
            try:
                os.startfile(str(self.resolved_path.resolve()))
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Não foi possível abrir o arquivo externamente:\n{e}")

    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def clear_document(self):
        self.close_document()
        self.lbl_image.setPixmap(QPixmap())
        self.lbl_image.setText("PRÉVIA DO\nDOCUMENTO\nSELECIONADO")
        self.lbl_image.setStyleSheet(
            "color: #888; font-size: 16px; font-weight: 700; letter-spacing: 1px;"
        )
        self.lbl_doc_info.setText("📄 <b>PRÉVIA DO DOCUMENTO SELECIONADO</b>")
        self._disable_controls()

    def close_document(self):
        if self.doc:
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None


# =====================================================================
# INTERFACE PRINCIPAL: SessionsPage (4 Colunas)
# =====================================================================
class SessionsPage(QWidget):
    """
    [Opus - v1.1 Sessions Redesign]:
    Estação de Verificação Manual em 4 Colunas:
    Coluna 1: Sessões (ordem fixa de criação + datas)
    Coluna 2: Dados (Pessoa) | Pessoas | Documentos (da Pessoa) | Imóveis | Dados Imóvel + Rodapé Datas
    Coluna 3: Lista dos Docs. Anexados (todos os documentos da sessão, sem dados pessoais)
    Coluna 4: Prévia do Documento Selecionado (sem dados pessoais)
    """

    resume_session_requested = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent=parent)
        self.setObjectName("SessionsPage")

        self.db = DatabaseManager()
        self.resolver = EntityResolver(self.db)
        self.current_session_id: Optional[int] = None

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(14, 14, 14, 14)
        self.main_layout.setSpacing(8)

        self._init_four_column_splitter()
        self.load_sessions()

    def _init_four_column_splitter(self):
        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)

        # Coluna 1: Sessões
        self.col1_sessions = SessionListPanel(self.splitter)
        self.search_box = self.col1_sessions.search_box  # Compatibilidade com atalho Ctrl+F em app_gemini.py

        # Coluna 2: Painel de Entidades (Dados / Pessoas / Documentos / Imóveis / Dados Imóvel / Datas)
        self.col2_entities = SessionEntityPanel(self.splitter)

        # Coluna 3: Lista dos Docs. Anexados
        self.col3_attached = AttachedDocsPanel(self.splitter)

        # Coluna 4: Prévia do Documento Selecionado
        self.col4_preview = DocumentPreviewWidget(self.splitter)
        self.col4_preview.setMinimumWidth(320)

        self.splitter.addWidget(self.col1_sessions)
        self.splitter.addWidget(self.col2_entities)
        self.splitter.addWidget(self.col3_attached)
        self.splitter.addWidget(self.col4_preview)

        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setStretchFactor(3, 5)
        self.splitter.setSizes([220, 350, 210, 500])

        self.main_layout.addWidget(self.splitter, 1)

        # ── Conexões da Coluna 1 (Sessões) ──
        self.col1_sessions.session_selected.connect(self._on_session_selected)
        self.col1_sessions.create_requested.connect(self.create_session_prompt)
        self.col1_sessions.rename_requested.connect(self.rename_session_by_id)
        self.col1_sessions.delete_requested.connect(self.delete_session_by_id)
        self.col1_sessions.resume_requested.connect(self.resume_session_by_id)
        self.col1_sessions.search_changed.connect(self._on_search_changed)

        # ── Conexões da Coluna 2 (Pessoas / Imóveis / Atributos) ──
        self.col2_entities.person_selected.connect(self._on_person_selected)
        self.col2_entities.property_selected.connect(self._on_property_selected)
        self.col2_entities.document_selected.connect(self._on_document_selected_from_person)
        self.col2_entities.person_override_saved.connect(self._on_person_override_saved)
        self.col2_entities.property_override_saved.connect(self._on_property_override_saved)
        self.col2_entities.field_copied.connect(self._on_field_copied)

        self.col2_entities.add_person_requested.connect(self._add_person_manually)
        self.col2_entities.rename_person_requested.connect(self._rename_person)
        self.col2_entities.merge_person_requested.connect(self._merge_persons)
        self.col2_entities.delete_person_requested.connect(self._delete_person)

        self.col2_entities.add_property_requested.connect(self._add_property_manually)
        self.col2_entities.rename_property_requested.connect(self._rename_property)
        self.col2_entities.delete_property_requested.connect(self._delete_property)

        self.col2_entities.reassign_doc_link_requested.connect(self._reassign_doc_link)
        self.col2_entities.split_doc_to_new_person_requested.connect(self._split_doc_to_new_person)
        self.col2_entities.delete_document_requested.connect(self._confirm_delete_document)
        self.col2_entities.open_document_external_requested.connect(self._open_document_external)

        # ── Conexões da Coluna 3 (Lista dos Docs Anexados) ──
        self.col3_attached.document_selected.connect(self._on_document_selected_from_attached)
        self.col3_attached.delete_document_requested.connect(self._confirm_delete_document)
        self.col3_attached.open_document_external_requested.connect(self._open_document_external)
        self.col3_attached.link_doc_to_person_requested.connect(self._link_doc_to_person)
        self.col3_attached.link_doc_to_property_requested.connect(self._link_doc_to_property)

    # ──────────────────────────────────────────────────────────────
    # Carregamento e Sincronização de Sessões e Entidades
    # ──────────────────────────────────────────────────────────────

    def reload_all(self):
        """Recarrega sessões, entidades e listas preservando a seleção atual."""
        self.load_sessions(target_session_id=self.current_session_id)

    def load_sessions(self, target_session_id: Optional[int] = None):
        search_term = self.col1_sessions.search_box.text().strip()
        sessions = self.db.get_all_sessions(search=search_term)

        if not sessions and not search_term:
            self.db.get_or_create_default_session()
            sessions = self.db.get_all_sessions()

        chosen_sid = self.col1_sessions.populate_sessions(
            sessions=sessions,
            selected_session_id=target_session_id or self.current_session_id,
        )
        if chosen_sid is not None:
            self._load_session_content(chosen_sid)
        else:
            self.current_session_id = None
            self.col2_entities.set_session_dates(None, None)
            self.col2_entities.populate_persons([])
            self.col2_entities.populate_properties([])
            self.col3_attached.populate_documents([])
            self.col4_preview.clear_document()

    def _on_search_changed(self, _text: str):
        self.load_sessions(target_session_id=self.current_session_id)

    def _on_session_selected(self, session_id: int):
        self._load_session_content(session_id)

    def _load_session_content(
        self,
        session_id: int,
        prefer_person_id: Optional[int] = None,
        prefer_property_id: Optional[int] = None,
        keep_preview_doc_id: Optional[int] = None,
    ):
        self.current_session_id = session_id

        # Garante que todas as extrações da sessão já tenham passado pelo EntityResolver
        self.resolver.ensure_session_resolved(session_id)

        session_info = self.db.get_session(session_id)
        if session_info:
            self.col2_entities.set_session_dates(
                session_info.get("created_at"),
                session_info.get("updated_at"),
            )

        # Carrega Pessoas e Imóveis da sessão
        persons = self.db.get_session_persons(session_id)
        properties = self.db.get_session_properties(session_id)
        self.col3_attached.set_entities_context(persons, properties)

        chosen_pid = self.col2_entities.populate_persons(persons, selected_person_id=prefer_person_id)
        if chosen_pid is not None:
            self._refresh_person_view(chosen_pid)

        chosen_prid = self.col2_entities.populate_properties(properties, selected_property_id=prefer_property_id)
        if chosen_prid is not None:
            self._refresh_property_view(chosen_prid)

        # Carrega Lista dos Docs. Anexados (Coluna 3)
        all_docs = self.db.get_session_extractions(session_id)
        selected_doc = self.col3_attached.populate_documents(all_docs, selected_doc_id=keep_preview_doc_id)

        if selected_doc is not None:
            self._preview_document(selected_doc)
        else:
            self.col4_preview.clear_document()

    def _refresh_person_view(self, person_id: int):
        """Atualiza o bloco 'DADOS' e o bloco 'DOCUMENTOS' para a Pessoa selecionada."""
        fields = self.resolver.consolidate_person_data(person_id)
        self.col2_entities.set_person_fields(fields)

        person_docs = self.db.get_entity_extractions("PERSON", person_id)
        self.col2_entities.populate_person_documents(person_docs)

    def _refresh_property_view(self, property_id: int):
        """Atualiza o bloco 'DADOS IMÓVEL' para o Imóvel selecionado."""
        fields = self.resolver.consolidate_property_data(property_id)
        self.col2_entities.set_property_fields(fields)

    def _on_person_selected(self, person_id: int):
        self._refresh_person_view(person_id)

    def _on_property_selected(self, property_id: int):
        self._refresh_property_view(property_id)
        # Se o imóvel possuir documento vinculado, exibe o primeiro na prévia
        prop_docs = self.db.get_entity_extractions("PROPERTY", property_id)
        if prop_docs:
            self._preview_document(prop_docs[0])
            self.col3_attached.select_document_by_id(prop_docs[0]["id"])

    def _on_document_selected_from_person(self, doc_dict: Dict[str, Any]):
        self._preview_document(doc_dict)
        if doc_dict.get("id") is not None:
            self.col3_attached.select_document_by_id(int(doc_dict["id"]))

    def _on_document_selected_from_attached(self, doc_dict: Dict[str, Any]):
        self._preview_document(doc_dict)

    def _preview_document(self, doc_dict: Dict[str, Any]):
        self.col4_preview.load_document(
            file_path=doc_dict.get("file_path", ""),
            original_name=doc_dict.get("original_name", ""),
            doc_type=doc_dict.get("document_type", ""),
        )

    # ──────────────────────────────────────────────────────────────
    # Callbacks de Cópia e Overrides de Atributos (Pessoa / Imóvel)
    # ──────────────────────────────────────────────────────────────

    def _on_field_copied(self, label: str, value: str):
        InfoBar.success(
            f"{label} copiado!",
            f"'{value}' copiado para a área de transferência.",
            duration=2000,
            parent=self,
        )

    def _on_person_override_saved(self, person_id: int, field_key: str, new_val_or_none: object):
        val_str = str(new_val_or_none) if new_val_or_none is not None else None
        if self.db.set_entity_override("PERSON", person_id, field_key, val_str):
            self._refresh_session_timestamps_and_entities(
                prefer_person_id=person_id,
                prefer_property_id=self.col2_entities.current_property_id,
            )
            msg = "Valor restaurado para o original extraído." if val_str is None else f"Alteração salva em '{field_key}'."
            InfoBar.success("Dados Atualizados", msg, duration=2200, parent=self)

    def _on_property_override_saved(self, property_id: int, field_key: str, new_val_or_none: object):
        val_str = str(new_val_or_none) if new_val_or_none is not None else None
        if self.db.set_entity_override("PROPERTY", property_id, field_key, val_str):
            self._refresh_session_timestamps_and_entities(
                prefer_person_id=self.col2_entities.current_person_id,
                prefer_property_id=property_id,
            )
            msg = "Valor restaurado para o original extraído." if val_str is None else f"Alteração salva em '{field_key}'."
            InfoBar.success("Dados do Imóvel Atualizados", msg, duration=2200, parent=self)

    def _refresh_session_timestamps_and_entities(
        self,
        prefer_person_id: Optional[int] = None,
        prefer_property_id: Optional[int] = None,
    ):
        """Atualiza lista de sessões (para refletir updated_at sem mudar ordem) e recarrega a sessão ativa."""
        if not self.current_session_id:
            return
        search_term = self.col1_sessions.search_box.text().strip()
        sessions = self.db.get_all_sessions(search=search_term)
        self.col1_sessions.populate_sessions(sessions, selected_session_id=self.current_session_id)
        self._load_session_content(
            self.current_session_id,
            prefer_person_id=prefer_person_id,
            prefer_property_id=prefer_property_id,
        )

    # ──────────────────────────────────────────────────────────────
    # Ações de Sessão (Criar, Renomear, Excluir, Retomar)
    # ──────────────────────────────────────────────────────────────

    def create_session_prompt(self):
        next_seq = self.db.get_next_session_seq_number()
        default_name = f"Sessão {next_seq}"
        name, ok = QInputDialog.getText(
            self,
            "Nova Sessão",
            "Nome da nova sessão (a ordem de criação será fixa):",
            text=default_name,
        )
        if ok and name.strip():
            new_id = self.db.create_session(name=name.strip())
            self.load_sessions(target_session_id=new_id)
            InfoBar.success("Sessão Criada", f"'{name.strip()}' criada com sucesso.", duration=2500, parent=self)

    def rename_session_by_id(self, session_id: int):
        s_info = self.db.get_session(session_id)
        if not s_info:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Renomear Sessão",
            "Novo nome da sessão:",
            text=s_info["name"],
        )
        if ok and new_name.strip():
            self.db.rename_session(session_id, new_name.strip())
            self.load_sessions(target_session_id=session_id)
            InfoBar.success("Renomeada", f"Sessão renomeada para '{new_name.strip()}'.", duration=2200, parent=self)

    def delete_session_by_id(self, session_id: int):
        s_info = self.db.get_session(session_id)
        if not s_info:
            return
        reply = QMessageBox.question(
            self,
            "Excluir Sessão",
            f"Tem certeza que deseja excluir a sessão '{s_info['name']}' e todos os seus vínculos?\n\n"
            "(A numeração das demais sessões permanecerá fixa.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.db.delete_session(session_id)
            self.current_session_id = None
            self.load_sessions()
            InfoBar.warning("Sessão Excluída", f"'{s_info['name']}' foi removida.", duration=2500, parent=self)

    def resume_session_by_id(self, session_id: int):
        self.resume_session_requested.emit(session_id)

    # ──────────────────────────────────────────────────────────────
    # Ações de Pessoas, Imóveis e Documentos
    # ──────────────────────────────────────────────────────────────

    def _add_person_manually(self):
        if not self.current_session_id:
            return
        name, ok = QInputDialog.getText(
            self,
            "Nova Pessoa",
            "Nome da pessoa:",
        )
        if ok and name.strip():
            pid = self.db.create_person(self.current_session_id, name.strip().upper())
            self._refresh_session_timestamps_and_entities(prefer_person_id=pid)

    def _rename_person(self, person_id: int):
        p = self.db.get_person(person_id)
        if not p:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Renomear Pessoa",
            "Nome de exibição da pessoa:",
            text=p["display_name"],
        )
        if ok and new_name.strip():
            self.db.rename_person(person_id, new_name.strip())
            self._refresh_session_timestamps_and_entities(prefer_person_id=person_id)

    def _merge_persons(self, target_person_id: int, source_person_id: int):
        t = self.db.get_person(target_person_id)
        s = self.db.get_person(source_person_id)
        if not t or not s:
            return
        reply = QMessageBox.question(
            self,
            "Mesclar Pessoas",
            f"Deseja unir todos os documentos e dados de '{s['display_name']}' dentro de '{t['display_name']}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.db.merge_persons(target_person_id, source_person_id)
            self._refresh_session_timestamps_and_entities(prefer_person_id=target_person_id)
            InfoBar.success("Pessoas Mescladas", f"Dados unificados em '{t['display_name']}'.", duration=2500, parent=self)

    def _delete_person(self, person_id: int):
        p = self.db.get_person(person_id)
        if not p:
            return
        reply = QMessageBox.question(
            self,
            "Excluir Pessoa",
            f"Deseja remover '{p['display_name']}' da lista de pessoas desta sessão?\n"
            "(Os documentos anexados continuarão na sessão.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.db.delete_person(person_id)
            self._refresh_session_timestamps_and_entities()

    def _add_property_manually(self):
        if not self.current_session_id:
            return
        label, ok = QInputDialog.getText(
            self,
            "Novo Imóvel",
            "Endereço ou identificação do imóvel:",
        )
        if ok and label.strip():
            pr_id = self.db.create_property(self.current_session_id, label.strip().upper())
            self._refresh_session_timestamps_and_entities(prefer_property_id=pr_id)

    def _rename_property(self, property_id: int):
        pr = self.db.get_property(property_id)
        if not pr:
            return
        new_label, ok = QInputDialog.getText(
            self,
            "Renomear Imóvel",
            "Endereço / identificação do imóvel:",
            text=pr["label"],
        )
        if ok and new_label.strip():
            self.db.rename_property(property_id, new_label.strip())
            self._refresh_session_timestamps_and_entities(prefer_property_id=property_id)

    def _delete_property(self, property_id: int):
        pr = self.db.get_property(property_id)
        if not pr:
            return
        reply = QMessageBox.question(
            self,
            "Excluir Imóvel",
            f"Deseja remover o imóvel '{pr['label']}' desta sessão?\n"
            "(Os documentos anexados continuarão na sessão.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.db.delete_property(property_id)
            self._refresh_session_timestamps_and_entities()

    def _reassign_doc_link(self, link_id: int, new_person_id: int):
        if self.db.reassign_extraction_link(link_id, new_person_id):
            self._refresh_session_timestamps_and_entities(prefer_person_id=new_person_id)
            InfoBar.success("Documento Reatribuído", "O documento foi movido para a pessoa selecionada.", duration=2200, parent=self)

    def _split_doc_to_new_person(self, link_id: int, _extraction_id: int):
        if not self.current_session_id:
            return
        name, ok = QInputDialog.getText(
            self,
            "Separar em Nova Pessoa",
            "Nome da nova pessoa para este documento:",
        )
        if ok and name.strip():
            new_pid = self.db.create_person(self.current_session_id, name.strip().upper())
            self.db.reassign_extraction_link(link_id, new_pid)
            self._refresh_session_timestamps_and_entities(prefer_person_id=new_pid)
            InfoBar.success("Documento Separado", f"Vinculado à nova pessoa '{name.strip().upper()}'.", duration=2500, parent=self)

    def _link_doc_to_person(self, extraction_id: int, person_id: int):
        self.db.add_extraction_link(
            extraction_id=extraction_id,
            entity_type="PERSON",
            entity_id=person_id,
            role="TITULAR",
            json_path="documento.pessoa",
        )
        if self.current_session_id:
            self.db.touch_session(self.current_session_id)
        self._refresh_session_timestamps_and_entities(prefer_person_id=person_id)
        InfoBar.success("Documento Vinculado", "Documento associado à pessoa selecionada.", duration=2000, parent=self)

    def _link_doc_to_property(self, extraction_id: int, property_id: int):
        self.db.add_extraction_link(
            extraction_id=extraction_id,
            entity_type="PROPERTY",
            entity_id=property_id,
            role="IMOVEL",
            json_path="documento.imovel",
        )
        if self.current_session_id:
            self.db.touch_session(self.current_session_id)
        self._refresh_session_timestamps_and_entities(prefer_property_id=property_id)
        InfoBar.success("Documento Vinculado", "Documento associado ao imóvel selecionado.", duration=2000, parent=self)

    def _confirm_delete_document(self, doc_dict: Dict[str, Any]):
        doc_id = doc_dict.get("id")
        if doc_id is None:
            return
        file_name = doc_dict.get("original_name") or f"ID {doc_id}"
        doc_type = doc_dict.get("document_type") or "OUTROS"

        reply = QMessageBox.question(
            self,
            "Excluir Documento",
            f"Tem certeza que deseja excluir o documento '{file_name}' ({doc_type}) desta sessão?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            if self.db.delete_extraction(int(doc_id)):
                self.col4_preview.clear_document()
                self._refresh_session_timestamps_and_entities(
                    prefer_person_id=self.col2_entities.current_person_id,
                    prefer_property_id=self.col2_entities.current_property_id,
                )
                InfoBar.warning("Documento Excluído", f"'{file_name}' foi removido da sessão.", duration=2500, parent=self)

    def _open_document_external(self, doc_dict: Dict[str, Any]):
        fp = doc_dict.get("file_path") or ""
        resolved = resolve_doc_path(fp)
        if resolved and resolved.is_file():
            try:
                os.startfile(str(resolved.resolve()))
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Não foi possível abrir o arquivo externamente:\n{e}")
        else:
            QMessageBox.warning(self, "Arquivo não encontrado", f"Caminho não localizado:\n{fp}")
