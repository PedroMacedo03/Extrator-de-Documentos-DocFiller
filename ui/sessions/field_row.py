"""
DocFiller — Linha de Atributo (Dados de Pessoa / Dados de Imóvel)
=================================================================

[Opus - v1.1 Sessions Redesign]:
Implementa o comportamento aprovado pelo usuário para cada atributo:
- Clique simples: seleciona a linha e revela o botão ✏️ no extremo direito
  (permite selecionar texto com o mouse sem entrar em modo de edição sem querer).
- Duplo clique: copia o valor do atributo para a área de transferência (emite sinal para toast).
- Botão ✏️ (no extremo direito): abre edição inline apenas para aquele atributo (Salvar / Cancelar).
- Indicador ⚠️: exibido quando documentos da mesma pessoa/imóvel divergem naquele campo,
  mostrando as alternativas e o documento de origem de cada uma.
- Indicador de override manual + opção de "Restaurar valor extraído".
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy, QWidget
)

from core.entity_resolver_gemini import ConsolidatedField


class AttributeFieldRow(QFrame):
    """
    Linha individual de um atributo no painel 'DADOS' (Pessoa) ou 'DADOS IMÓVEL' (Imóvel).
    """

    row_selected = Signal(object)               # Emite self quando clicado com clique simples
    value_copied = Signal(str, str)             # (label, valor_copiado)
    override_saved = Signal(str, object)        # (field_key, novo_valor_str_ou_None_para_restaurar)

    def __init__(self, field_key: str, label_text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.field_key = field_key
        self.label_text = label_text
        self.current_field: Optional[ConsolidatedField] = None
        self._is_selected: bool = False
        self._is_editing: bool = False

        self.setObjectName("AttributeFieldRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._init_ui()
        self._apply_row_style()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 6, 4)
        layout.setSpacing(6)

        # Rótulo do campo (ex: "nome completo:")
        self.lbl_name = QLabel(f"{self.label_text}:", self)
        self.lbl_name.setMinimumWidth(128)
        self.lbl_name.setMaximumWidth(150)
        self.lbl_name.setStyleSheet("font-weight: 600; font-size: 12px; color: #8a94a6;")
        self.lbl_name.installEventFilter(self)
        layout.addWidget(self.lbl_name)

        # Valor em modo visualização (permite seleção com o mouse sem entrar em edição)
        self.lbl_value = QLabel("NÃO ENCONTRADO", self)
        self.lbl_value.setWordWrap(True)
        self.lbl_value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.lbl_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_value.setCursor(Qt.IBeamCursor)
        self.lbl_value.installEventFilter(self)
        layout.addWidget(self.lbl_value, 1)

        # Editor inline (oculto por padrão; só abre ao clicar no botão ✏️)
        self.edit_input = QLineEdit(self)
        self.edit_input.setPlaceholderText(f"DIGITE {self.label_text.upper()}")
        self.edit_input.setStyleSheet(
            "QLineEdit { padding: 2px 6px; font-size: 12px; border: 1px solid #009faa; border-radius: 4px; }"
        )
        self.edit_input.returnPressed.connect(self._save_inline_edit)
        self.edit_input.installEventFilter(self)
        self.edit_input.hide()
        layout.addWidget(self.edit_input, 1)

        # Botão ⚠️ de divergência entre documentos (oculto se não houver conflito)
        self.btn_conflict = QPushButton("⚠️", self)
        self.btn_conflict.setFixedSize(24, 22)
        self.btn_conflict.setCursor(Qt.PointingHandCursor)
        self.btn_conflict.setStyleSheet(
            "QPushButton { border: none; background: rgba(255, 185, 0, 0.18); border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background: rgba(255, 185, 0, 0.35); }"
        )
        self.btn_conflict.clicked.connect(self._show_conflict_menu)
        self.btn_conflict.hide()
        layout.addWidget(self.btn_conflict)

        # Indicador discreto de edição manual (override)
        self.lbl_override_badge = QLabel("✎", self)
        self.lbl_override_badge.setToolTip("Editado manualmente (clique com botão direito para restaurar valor extraído)")
        self.lbl_override_badge.setStyleSheet("color: #009faa; font-size: 11px; font-weight: bold;")
        self.lbl_override_badge.hide()
        layout.addWidget(self.lbl_override_badge)

        # Botões do modo de edição inline (Salvar ✔ / Cancelar ✕ / Restaurar ↺)
        self.btn_save = QPushButton("✔", self)
        self.btn_save.setFixedSize(24, 22)
        self.btn_save.setToolTip("Salvar alteração manual (Enter)")
        self.btn_save.setStyleSheet(
            "QPushButton { border: none; background: rgba(16, 124, 16, 0.22); color: #2ecc71; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: rgba(16, 124, 16, 0.4); }"
        )
        self.btn_save.clicked.connect(self._save_inline_edit)
        self.btn_save.hide()
        layout.addWidget(self.btn_save)

        self.btn_cancel = QPushButton("✕", self)
        self.btn_cancel.setFixedSize(24, 22)
        self.btn_cancel.setToolTip("Cancelar edição (Esc)")
        self.btn_cancel.setStyleSheet(
            "QPushButton { border: none; background: rgba(209, 52, 56, 0.20); color: #e74c3c; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: rgba(209, 52, 56, 0.38); }"
        )
        self.btn_cancel.clicked.connect(self.cancel_inline_edit)
        self.btn_cancel.hide()
        layout.addWidget(self.btn_cancel)

        self.btn_restore = QPushButton("↺", self)
        self.btn_restore.setFixedSize(24, 22)
        self.btn_restore.setToolTip("Restaurar valor original extraído do documento")
        self.btn_restore.setStyleSheet(
            "QPushButton { border: none; background: rgba(128, 128, 128, 0.18); border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background: rgba(128, 128, 128, 0.35); }"
        )
        self.btn_restore.clicked.connect(self._restore_extracted_value)
        self.btn_restore.hide()
        layout.addWidget(self.btn_restore)

        # Botão ✏️ no extremo direito (visível quando a linha está selecionada)
        self.btn_edit = QPushButton("✏️", self)
        self.btn_edit.setFixedSize(26, 22)
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.setToolTip(f"Editar {self.label_text}")
        self.btn_edit.setStyleSheet(
            "QPushButton { border: 1px solid rgba(0, 159, 170, 0.45); background: rgba(0, 159, 170, 0.12); border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: rgba(0, 159, 170, 0.28); }"
        )
        self.btn_edit.clicked.connect(self.start_inline_edit)
        self.btn_edit.hide()
        layout.addWidget(self.btn_edit)

    # ──────────────────────────────────────────────────────────────
    # Atualização de dados e estado visual
    # ──────────────────────────────────────────────────────────────

    def set_field_data(self, field: Optional[ConsolidatedField]):
        """Atualiza o conteúdo da linha com o atributo consolidado."""
        self.current_field = field
        if self._is_editing:
            self.cancel_inline_edit()

        if not field or not field.display_value:
            self.lbl_value.setText("não encontrado")
            self.lbl_value.setStyleSheet("font-size: 12px; color: #777; font-style: italic;")
            self.lbl_value.setToolTip("Clique simples seleciona • Duplo clique copia • ✏️ edita")
            self.btn_conflict.hide()
            self.lbl_override_badge.hide()
            return

        self.lbl_value.setText(field.display_value)
        self.lbl_value.setStyleSheet("font-size: 12px; font-weight: 600;")

        # Tooltip informativo com origem do dado
        tip_lines = [f"<b>{self.label_text}:</b> {field.display_value}"]
        if field.is_overridden:
            tip_lines.append("✏️ <i>Editado manualmente pelo usuário</i>")
            if field.extracted_value:
                tip_lines.append(f"Valor original extraído: {field.extracted_value} ({field.source_doc_name})")
        elif field.source_doc_name:
            tip_lines.append(f"📄 Fonte: {field.source_doc_name} [{field.source_doc_type}]")
        tip_lines.append("💡 <i>Clique simples: seleciona | Duplo clique: copia</i>")
        self.lbl_value.setToolTip("<br>".join(tip_lines))

        self.lbl_override_badge.setVisible(field.is_overridden)

        if field.has_conflict and len(field.alternatives) > 1:
            alt_summary = "<br>".join(
                f"• <b>{a.value}</b> — <i>{a.doc_name} [{a.doc_type}]</i>"
                for a in field.alternatives
            )
            self.btn_conflict.setToolTip(
                f"<b>⚠️ Divergência detectada entre documentos:</b><br>{alt_summary}<br><br>"
                "<i>Clique no ícone ⚠️ para escolher qual valor usar.</i>"
            )
            self.btn_conflict.show()
        else:
            self.btn_conflict.hide()

    def set_selected(self, selected: bool):
        """Define se esta linha está selecionada (revelando o botão ✏️ no extremo direito)."""
        self._is_selected = selected
        if not self._is_editing:
            self.btn_edit.setVisible(selected)
        self._apply_row_style()

    def _apply_row_style(self):
        if self._is_selected or self._is_editing:
            self.setStyleSheet(
                "#AttributeFieldRow { background-color: rgba(0, 159, 170, 0.13); "
                "border: 1px solid rgba(0, 159, 170, 0.45); border-radius: 5px; }"
            )
        else:
            self.setStyleSheet(
                "#AttributeFieldRow { background-color: transparent; "
                "border: 1px solid transparent; border-radius: 5px; }"
                "#AttributeFieldRow:hover { background-color: rgba(128, 128, 128, 0.08); }"
            )

    # ──────────────────────────────────────────────────────────────
    # Edição Inline (apenas via botão ✏️)
    # ──────────────────────────────────────────────────────────────

    def start_inline_edit(self):
        """Entra no modo de edição inline para este atributo específico."""
        self.row_selected.emit(self)
        self._is_editing = True
        current_val = self.current_field.display_value if (self.current_field and self.current_field.display_value) else ""
        self.edit_input.setText(current_val)
        self.lbl_value.hide()
        self.btn_edit.hide()
        self.edit_input.show()
        self.btn_save.show()
        self.btn_cancel.show()
        self.btn_restore.setVisible(bool(self.current_field and self.current_field.is_overridden))
        self.edit_input.setFocus()
        self.edit_input.selectAll()
        self._apply_row_style()

    def cancel_inline_edit(self):
        """Sai do modo de edição sem salvar."""
        self._is_editing = False
        self.edit_input.hide()
        self.btn_save.hide()
        self.btn_cancel.hide()
        self.btn_restore.hide()
        self.lbl_value.show()
        self.btn_edit.setVisible(self._is_selected)
        self._apply_row_style()

    def _save_inline_edit(self):
        if not self._is_editing:
            return
        new_text = self.edit_input.text().strip().upper()
        self.cancel_inline_edit()
        if new_text:
            self.override_saved.emit(self.field_key, new_text)
        else:
            # Se apagou tudo e salvou, restaura o extraído
            self.override_saved.emit(self.field_key, None)

    def _restore_extracted_value(self):
        """Remove o override manual e restaura o valor extraído originalmente."""
        self.cancel_inline_edit()
        self.override_saved.emit(self.field_key, None)

    # ──────────────────────────────────────────────────────────────
    # Cópia por Duplo Clique e Menus
    # ──────────────────────────────────────────────────────────────

    def copy_value_to_clipboard(self):
        """Copia o valor atual para a área de transferência."""
        val = self.current_field.display_value if self.current_field else ""
        if not val:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(val)
        self.value_copied.emit(self.label_text, val)

    def _show_conflict_menu(self):
        if not self.current_field or not self.current_field.alternatives:
            return
        menu = QMenu(self)
        header = QAction("⚠️ Escolher valor entre documentos divergentes:", self)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()

        for alt in self.current_field.alternatives:
            act = QAction(f"{alt.value}  —  ({alt.doc_name} [{alt.doc_type}])", self)
            act.triggered.connect(lambda checked=False, v=alt.value: self.override_saved.emit(self.field_key, v))
            menu.addAction(act)

        if self.current_field.is_overridden:
            menu.addSeparator()
            act_rest = QAction("↺ Restaurar seleção automática por prioridade", self)
            act_rest.triggered.connect(self._restore_extracted_value)
            menu.addAction(act_rest)

        menu.exec(QCursor.pos())

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        val = self.current_field.display_value if self.current_field else ""
        if val:
            act_copy = QAction(f"📋 Copiar '{val}'", self)
            act_copy.triggered.connect(self.copy_value_to_clipboard)
            menu.addAction(act_copy)

        act_edit = QAction(f"✏️ Editar {self.label_text}", self)
        act_edit.triggered.connect(self.start_inline_edit)
        menu.addAction(act_edit)

        if self.current_field and self.current_field.is_overridden:
            ext_v = self.current_field.extracted_value or "não encontrado"
            act_restore = QAction(f"↺ Restaurar valor extraído ({ext_v})", self)
            act_restore.triggered.connect(self._restore_extracted_value)
            menu.addAction(act_restore)

        menu.exec(self.mapToGlobal(pos))

    # ──────────────────────────────────────────────────────────────
    # Eventos de Mouse e Teclado (Clique simples vs Duplo clique)
    # ──────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self._is_editing:
            self.row_selected.emit(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and not self._is_editing:
            self.row_selected.emit(self)
            self.copy_value_to_clipboard()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.edit_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.cancel_inline_edit()
                return True
        elif watched in (self.lbl_name, self.lbl_value) and not self._is_editing:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self.row_selected.emit(self)
            elif event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.row_selected.emit(self)
                self.copy_value_to_clipboard()
                return True
        return super().eventFilter(watched, event)
