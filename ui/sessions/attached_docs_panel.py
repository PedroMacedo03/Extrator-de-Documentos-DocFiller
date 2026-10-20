"""
DocFiller — Coluna 3: Lista dos Documentos Anexados na Sessão
=============================================================

[Opus - v1.1 Sessions Redesign]:
Implementa a Coluna 3 ('LISTA DOS DOCUMENTOS ANEXADOS'):
- Lista todos os documentos enviados na sessão ativa.
- NÃO exibe nenhuma informação pessoal (apenas o tipo do documento e o nome do arquivo).
- Clicar em qualquer documento carrega-o imediatamente na Prévia (Coluna 4).
- Sem abreviações e sem reticências.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidgetItem, QMenu, QPushButton,
    QVBoxLayout, QWidget
)

from qfluentwidgets import CardWidget, ListWidget

from .entity_panel import format_doc_type_label


class AttachedDocsPanel(CardWidget):
    """
    Coluna 3: Lista de todos os documentos anexados na sessão (sem dados pessoais).
    """

    document_selected = Signal(dict)                        # extraction dict
    delete_document_requested = Signal(dict)                # extraction dict
    open_document_external_requested = Signal(dict)         # extraction dict
    link_doc_to_person_requested = Signal(int, int)         # (extraction_id, person_id)
    link_doc_to_property_requested = Signal(int, int)       # (extraction_id, property_id)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumWidth(205)
        self._docs_cache: List[Dict[str, Any]] = []
        self._persons_cache: List[Dict[str, Any]] = []
        self._properties_cache: List[Dict[str, Any]] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Cabeçalho "LISTA DOS DOCUMENTOS ANEXADOS" (sem abreviação)
        header_frame = QFrame(self)
        header_frame.setStyleSheet(
            "QFrame { background-color: rgba(0, 159, 170, 0.14); "
            "border-top: 1px solid rgba(128, 128, 128, 0.35); "
            "border-bottom: 1px solid rgba(128, 128, 128, 0.35); }"
        )
        header_lay = QVBoxLayout(header_frame)
        header_lay.setContentsMargins(6, 5, 6, 5)
        header_lay.setSpacing(1)

        self.lbl_header = QLabel("LISTA DOS DOCUMENTOS\nANEXADOS", header_frame)
        self.lbl_header.setAlignment(Qt.AlignCenter)
        self.lbl_header.setStyleSheet(
            "font-weight: 700; font-size: 11px; letter-spacing: 0.5px; border: none; background: transparent;"
        )
        header_lay.addWidget(self.lbl_header)
        layout.addWidget(header_frame)

        # Lista de documentos anexados
        self.docs_list = ListWidget(self)
        self.docs_list.setSpacing(2)
        self.docs_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.docs_list.customContextMenuRequested.connect(self._show_context_menu)
        self.docs_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.docs_list, 1)

        # Barra inferior com botão excluir documento selecionado
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(2, 0, 2, 0)
        bottom_row.setSpacing(4)

        self.lbl_count = QLabel("0 documentos", self)
        self.lbl_count.setStyleSheet("font-size: 11px; color: #888;")
        bottom_row.addWidget(self.lbl_count, 1)

        self.btn_delete_doc = QPushButton("🗑️ Excluir", self)
        self.btn_delete_doc.setFixedHeight(26)
        self.btn_delete_doc.setCursor(Qt.PointingHandCursor)
        self.btn_delete_doc.setToolTip("Excluir documento selecionado da sessão")
        self.btn_delete_doc.setStyleSheet(
            "QPushButton { padding: 2px 8px; border: 1px solid rgba(209, 52, 56, 0.45); "
            "background: rgba(209, 52, 56, 0.12); border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: rgba(209, 52, 56, 0.28); }"
        )
        self.btn_delete_doc.clicked.connect(self._delete_selected_doc)
        bottom_row.addWidget(self.btn_delete_doc)

        layout.addLayout(bottom_row)

    def set_entities_context(
        self,
        persons: List[Dict[str, Any]],
        properties: List[Dict[str, Any]],
    ):
        """Atualiza cache de Pessoas e Imóveis da sessão para o menu de vinculação manual."""
        self._persons_cache = persons
        self._properties_cache = properties

    def populate_documents(
        self,
        docs: List[Dict[str, Any]],
        selected_doc_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Preenche a lista de documentos anexados exibindo apenas a ordem, o tipo
        e o nome do arquivo (sem nenhuma informação pessoal).
        """
        self._docs_cache = docs
        self.docs_list.blockSignals(True)
        self.docs_list.clear()
        doc_word = "documento" if len(docs) == 1 else "documentos"
        self.lbl_count.setText(f"{len(docs)} {doc_word}")

        if not docs:
            empty_item = QListWidgetItem("Nenhum documento anexado")
            empty_item.setFlags(Qt.NoItemFlags)
            self.docs_list.addItem(empty_item)
            self.docs_list.blockSignals(False)
            return None

        target_row = 0
        for idx, d in enumerate(docs):
            dtype_label = format_doc_type_label(d.get("document_type") or "")
            fname = d.get("original_name") or f"Documento {idx + 1}"
            item_text = f"{idx + 1}. {dtype_label}\n    {fname}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, d)
            item.setToolTip(
                f"<b>#{idx + 1} — {dtype_label}</b><br>"
                f"Arquivo: {fname}<br>"
                "<i>Clique para visualizar na prévia ao lado</i>"
            )
            self.docs_list.addItem(item)
            if selected_doc_id is not None and d.get("id") == selected_doc_id:
                target_row = idx

        self.docs_list.setCurrentRow(target_row)
        self.docs_list.blockSignals(False)
        return docs[target_row]

    def select_document_by_id(self, doc_id: int):
        self.docs_list.blockSignals(True)
        for i in range(self.docs_list.count()):
            item = self.docs_list.item(i)
            d = item.data(Qt.UserRole)
            if isinstance(d, dict) and d.get("id") == doc_id:
                self.docs_list.setCurrentRow(i)
                break
        self.docs_list.blockSignals(False)

    def _on_item_clicked(self, item: QListWidgetItem):
        doc_dict = item.data(Qt.UserRole)
        if isinstance(doc_dict, dict):
            self.document_selected.emit(doc_dict)

    def _delete_selected_doc(self):
        item = self.docs_list.currentItem()
        if not item:
            return
        doc_dict = item.data(Qt.UserRole)
        if isinstance(doc_dict, dict):
            self.delete_document_requested.emit(doc_dict)

    def _show_context_menu(self, pos):
        item = self.docs_list.itemAt(pos)
        if not item:
            return
        doc_dict = item.data(Qt.UserRole)
        if not isinstance(doc_dict, dict):
            return

        ext_id = doc_dict.get("id")
        menu = QMenu(self)

        act_prev = QAction("👁️ Visualizar na Prévia", self)
        act_prev.triggered.connect(lambda: self.document_selected.emit(doc_dict))
        menu.addAction(act_prev)

        act_open = QAction("📂 Abrir no Windows", self)
        act_open.triggered.connect(lambda: self.open_document_external_requested.emit(doc_dict))
        menu.addAction(act_open)

        if ext_id is not None and self._persons_cache:
            person_menu = menu.addMenu("👤 Vincular a Pessoa")
            for p in self._persons_cache:
                act_p = QAction(f"👤 {p['display_name']}", self)
                act_p.triggered.connect(
                    lambda checked=False, eid=ext_id, pid=p["id"]: self.link_doc_to_person_requested.emit(int(eid), int(pid))
                )
                person_menu.addAction(act_p)

        if ext_id is not None and self._properties_cache:
            prop_menu = menu.addMenu("🏠 Vincular a Imóvel")
            for pr in self._properties_cache:
                act_pr = QAction(f"🏠 {pr['label']}", self)
                act_pr.triggered.connect(
                    lambda checked=False, eid=ext_id, prid=pr["id"]: self.link_doc_to_property_requested.emit(int(eid), int(prid))
                )
                prop_menu.addAction(act_pr)

        menu.addSeparator()
        act_del = QAction("🗑️ Excluir Documento", self)
        act_del.triggered.connect(lambda: self.delete_document_requested.emit(doc_dict))
        menu.addAction(act_del)

        menu.exec(self.docs_list.mapToGlobal(pos))
