"""
DocFiller — Coluna 1: Painel de Lista de Sessões (Ordem Fixa + Datas)
=====================================================================

[Opus - v1.1 Sessions Redesign]:
- Exibe as sessões em ordem de criação fixa (seq_number ASC), que não muda mesmo
  quando a sessão sofre alterações posteriores.
- Mostra em cada item o número fixo, o nome (alterável apenas manualmente),
  a data de criação e a data da última alteração.
- Sem abreviações e sem reticências na interface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout, QListWidgetItem, QMenu, QVBoxLayout, QWidget
)

from qfluentwidgets import (
    CardWidget, ListWidget, PrimaryPushButton, PushButton, SearchLineEdit, SubtitleLabel
)


def format_datetime_br(val: Any) -> str:
    """Formata timestamps do banco no padrão brasileiro HH:MM - DD/MM/AAAA."""
    if not val:
        return "Não informado"
    if isinstance(val, datetime):
        return val.strftime("%H:%M - %d/%m/%Y")
    val_str = str(val).strip()
    try:
        clean = val_str.split(".")[0].replace("T", " ")
        if len(clean) >= 19:
            dt = datetime.strptime(clean[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%H:%M - %d/%m/%Y")
        elif len(clean) == 10:
            dt = datetime.strptime(clean, "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
    except Exception:
        pass
    return val_str


class SessionListPanel(CardWidget):
    """
    Coluna 1 ('SESSÕES'):
    Lista de sessões com ordem de criação fixa, datas de criação/alteração e botões de gestão.
    """

    session_selected = Signal(int)              # session_id
    create_requested = Signal()
    rename_requested = Signal(int)              # session_id
    delete_requested = Signal(int)              # session_id
    resume_requested = Signal(int)              # session_id
    search_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumWidth(215)
        self._sessions_cache: List[Dict[str, Any]] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Cabeçalho "SESSÕES"
        header_row = QHBoxLayout()
        header_lbl = SubtitleLabel("SESSÕES", self)
        header_lbl.setStyleSheet("font-weight: 700; font-size: 14px;")
        header_row.addWidget(header_lbl)
        header_row.addStretch(1)

        self.btn_new = PrimaryPushButton("➕ Nova Sessão", self)
        self.btn_new.setFixedHeight(28)
        self.btn_new.setToolTip("Criar Nova Sessão")
        self.btn_new.clicked.connect(self.create_requested.emit)
        header_row.addWidget(self.btn_new)
        layout.addLayout(header_row)

        # Busca (mantida como self.search_box para compatibilidade com Ctrl+F)
        self.search_box = SearchLineEdit(self)
        self.search_box.setPlaceholderText("Filtrar sessões")
        self.search_box.textChanged.connect(self.search_changed.emit)
        layout.addWidget(self.search_box)

        # Lista de sessões
        self.session_list = ListWidget(self)
        self.session_list.setSpacing(3)
        self.session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._show_context_menu)
        self.session_list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self.session_list, 1)

        # Barra inferior de ações da sessão selecionada
        actions_row = QHBoxLayout()
        actions_row.setSpacing(5)

        self.btn_resume = PushButton("📥 Enviar Documentos", self)
        self.btn_resume.setFixedHeight(28)
        self.btn_resume.setToolTip("Abrir esta sessão na aba de Upload de Documentos")
        self.btn_resume.clicked.connect(self._emit_resume_current)
        actions_row.addWidget(self.btn_resume)

        self.btn_rename = PushButton("✏️", self)
        self.btn_rename.setFixedSize(32, 28)
        self.btn_rename.setToolTip("Renomear sessão selecionada")
        self.btn_rename.clicked.connect(self._emit_rename_current)
        actions_row.addWidget(self.btn_rename)

        self.btn_delete = PushButton("🗑️", self)
        self.btn_delete.setFixedSize(32, 28)
        self.btn_delete.setToolTip("Excluir sessão selecionada")
        self.btn_delete.clicked.connect(self._emit_delete_current)
        actions_row.addWidget(self.btn_delete)

        layout.addLayout(actions_row)

    def populate_sessions(
        self,
        sessions: List[Dict[str, Any]],
        selected_session_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Preenche a lista mantendo a ordem de criação fixa vinda do banco
        e retorna o session_id que ficou selecionado.
        """
        self._sessions_cache = sessions
        self.session_list.blockSignals(True)
        self.session_list.clear()

        target_row = 0
        for idx, s in enumerate(sessions):
            sid = s["id"]
            seq = s.get("seq_number") or sid
            name = s.get("name") or f"Sessão {seq}"
            doc_count = int(s.get("doc_count", 0) or 0)
            doc_word = "documento" if doc_count == 1 else "documentos"
            created_str = format_datetime_br(s.get("created_at"))
            updated_str = format_datetime_br(s.get("updated_at"))

            title_prefix = f"#{seq} · {name}" if not name.lower().startswith(f"sessão {seq}") else name
            item_text = (
                f"📁 {title_prefix}  ({doc_count} {doc_word})\n"
                f"   Data de criação: {created_str}\n"
                f"   Última alteração: {updated_str}"
            )
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, sid)
            item.setToolTip(
                f"<b>Ordem Fixa #{seq} — {name}</b><br>"
                f"Quantidade: {doc_count} {doc_word}<br>"
                f"Data de criação: {created_str}<br>"
                f"Última alteração: {updated_str}"
            )
            self.session_list.addItem(item)

            if selected_session_id is not None and sid == selected_session_id:
                target_row = idx

        self.session_list.blockSignals(False)

        if sessions:
            self.session_list.setCurrentRow(target_row)
            chosen_id = sessions[target_row]["id"]
            return chosen_id
        return None

    def current_session_id(self) -> Optional[int]:
        item = self.session_list.currentItem()
        if item is not None:
            return item.data(Qt.UserRole)
        return None

    def _on_item_changed(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]):
        if current is not None:
            sid = current.data(Qt.UserRole)
            if sid is not None:
                self.session_selected.emit(int(sid))

    def _emit_resume_current(self):
        sid = self.current_session_id()
        if sid is not None:
            self.resume_requested.emit(sid)

    def _emit_rename_current(self):
        sid = self.current_session_id()
        if sid is not None:
            self.rename_requested.emit(sid)

    def _emit_delete_current(self):
        sid = self.current_session_id()
        if sid is not None:
            self.delete_requested.emit(sid)

    def _show_context_menu(self, pos):
        item = self.session_list.itemAt(pos)
        if not item:
            return
        sid = item.data(Qt.UserRole)
        if sid is None:
            return

        menu = QMenu(self)
        act_resume = QAction("📥 Retomar Sessão na Aba de Upload", self)
        act_resume.triggered.connect(lambda: self.resume_requested.emit(sid))
        menu.addAction(act_resume)

        act_rename = QAction("✏️ Renomear Sessão Manualmente", self)
        act_rename.triggered.connect(lambda: self.rename_requested.emit(sid))
        menu.addAction(act_rename)

        menu.addSeparator()
        act_del = QAction("🗑️ Excluir Sessão", self)
        act_del.triggered.connect(lambda: self.delete_requested.emit(sid))
        menu.addAction(act_del)

        menu.exec(self.session_list.mapToGlobal(pos))
