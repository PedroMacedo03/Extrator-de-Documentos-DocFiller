"""
DocFiller — Coluna 2: Painel Central da Sessão (Pessoas / Dados / Documentos || Imóveis / Dados Imóvel)
========================================================================================================

[Opus - v1.1 Sessions Redesign]:
Implementa a coluna central com a organização e funcionalidades solicitadas pelo usuário:
1. Sem abreviações e sem reticências em nenhum rótulo, botão ou menu.
2. Ordem de cima para baixo:
   - Domínio de PESSOAS (identidade visual Azul-Petróleo):
     1º PESSOAS (seleção de pessoa)
     2º DADOS (atributos consolidados da pessoa selecionada)
     3º DOCUMENTOS (documentos pertencentes à pessoa selecionada)
   - Separação de alto destaque visual entre o grupo de PESSOAS e o grupo de IMÓVEIS.
   - Domínio de IMÓVEIS (identidade visual Âmbar/Dourado):
     4º IMÓVEIS (seleção de imóvel)
     5º DADOS IMÓVEL (atributos consolidados do imóvel selecionado)
   - Rodapé fixo com DATA DE CRIAÇÃO DA SESSÃO e DATA DA ÚLTIMA ALTERAÇÃO DA SESSÃO.
3. Redimensionamento vertical dinâmico (QSplitter vertical) em todas as seções, permitindo
   aumentar e diminuir livremente a altura de PESSOAS, DADOS, DOCUMENTOS, IMÓVEIS e DADOS IMÓVEL.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidgetItem, QMenu, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget
)

from qfluentwidgets import CardWidget, ListWidget

from core.entity_resolver_gemini import (
    ConsolidatedField, PERSON_DISPLAY_FIELDS, PROPERTY_DISPLAY_FIELDS
)
from .field_row import AttributeFieldRow
from .session_list_panel import format_datetime_br


# Mapa sem abreviações para tipos de documento
DOC_TYPE_FRIENDLY_LABELS: Dict[str, str] = {
    "RG": "CARTEIRA DE IDENTIDADE",
    "CIN": "CARTEIRA DE IDENTIDADE NACIONAL",
    "CNH": "CARTEIRA NACIONAL DE HABILITAÇÃO",
    "CPF": "COMPROVANTE DE CADASTRO DE PESSOA FÍSICA",
    "NASCIMENTO": "CERTIDÃO DE NASCIMENTO",
    "CASAMENTO": "CERTIDÃO DE CASAMENTO",
    "OBITO": "CERTIDÃO DE ÓBITO",
    "ESCRITURA": "ESCRITURA PÚBLICA",
    "ESCRITURA_COMPRA_VENDA": "ESCRITURA DE COMPRA E VENDA",
    "IPTU": "IMPOSTO PREDIAL E TERRITORIAL URBANO",
    "CERTIDAO_IMOVEL": "CERTIDÃO DE MATRÍCULA DE IMÓVEL",
    "TITULO_ELEITOR": "TÍTULO DE ELEITOR",
    "PASSAPORTE": "PASSAPORTE",
    "CERTIFICADO_RESERVISTA": "CERTIFICADO DE RESERVISTA",
    "CARTAO_SUS": "CARTÃO NACIONAL DE SAÚDE",
    "CARTEIRA_ESTUDANTE_DNE": "CARTEIRA DE IDENTIFICAÇÃO ESTUDANTIL",
    "CARTEIRA_CONSELHO": "CARTEIRA DE CONSELHO PROFISSIONAL",
    "IDENTIDADE_FUNCIONAL": "IDENTIDADE FUNCIONAL",
    "CERTIFICADO_DIPLOMA": "CERTIFICADO OU DIPLOMA",
    "CTPS": "CARTEIRA DE TRABALHO E PREVIDÊNCIA SOCIAL",
    "OUTROS": "DOCUMENTO",
}


def format_doc_type_label(doc_type: str) -> str:
    t = str(doc_type or "OUTROS").strip().upper()
    return DOC_TYPE_FRIENDLY_LABELS.get(t, t)


def _create_section_header(
    title: str,
    parent: QWidget,
    domain: str = "PERSON",
    right_button: Optional[QPushButton] = None,
) -> QFrame:
    """
    Cria faixa de cabeçalho com destaque visual distinto para cabeçalhos de PESSOAS
    (azul-petróleo) versus cabeçalhos de IMÓVEIS (âmbar/dourado).
    """
    frame = QFrame(parent)
    if domain == "PROPERTY":
        frame.setStyleSheet(
            "QFrame { background-color: rgba(212, 136, 6, 0.22); "
            "border-left: 4px solid #d48806; "
            "border-top: 1px solid rgba(212, 136, 6, 0.50); "
            "border-bottom: 1px solid rgba(212, 136, 6, 0.50); }"
        )
        text_color = "#f0a020"
    else:
        frame.setStyleSheet(
            "QFrame { background-color: rgba(0, 159, 170, 0.18); "
            "border-left: 4px solid #009faa; "
            "border-top: 1px solid rgba(0, 159, 170, 0.45); "
            "border-bottom: 1px solid rgba(0, 159, 170, 0.45); }"
        )
        text_color = "#00b7c3"

    lay = QHBoxLayout(frame)
    lay.setContentsMargins(8, 4, 8, 4)
    lay.setSpacing(6)

    lbl = QLabel(title.upper(), frame)
    lbl.setAlignment(Qt.AlignCenter if right_button is None else Qt.AlignVCenter | Qt.AlignLeft)
    lbl.setStyleSheet(
        f"font-weight: 800; font-size: 11px; letter-spacing: 0.7px; color: {text_color}; "
        "border: none; background: transparent;"
    )
    lay.addWidget(lbl, 1)

    if right_button is not None:
        lay.addWidget(right_button)

    return frame


class SessionEntityPanel(CardWidget):
    """
    Coluna 2: Painel verticalmente redimensionável com:
    [Domínio Pessoas]: PESSOAS -> DADOS -> DOCUMENTOS
    === Separador de Destaque ===
    [Domínio Imóveis]: IMÓVEIS -> DADOS IMÓVEL
    + Rodapé com Datas da Sessão.
    """

    person_selected = Signal(int)                           # person_id
    property_selected = Signal(int)                         # property_id
    document_selected = Signal(dict)                        # extraction dict
    person_override_saved = Signal(int, str, object)        # (person_id, field_key, new_val_or_None)
    property_override_saved = Signal(int, str, object)      # (property_id, field_key, new_val_or_None)
    field_copied = Signal(str, str)                         # (label, value)

    # Ações de gestão manual de Pessoas, Imóveis e Vínculos
    add_person_requested = Signal()
    rename_person_requested = Signal(int)                   # person_id
    merge_person_requested = Signal(int, int)               # (target_person_id, source_person_id)
    delete_person_requested = Signal(int)                   # person_id

    add_property_requested = Signal()
    rename_property_requested = Signal(int)                 # property_id
    delete_property_requested = Signal(int)                 # property_id

    reassign_doc_link_requested = Signal(int, int)          # (link_id, new_person_id)
    split_doc_to_new_person_requested = Signal(int, int)    # (link_id, extraction_id)
    delete_document_requested = Signal(dict)                # extraction dict
    open_document_external_requested = Signal(dict)         # extraction dict

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumWidth(320)

        self._current_person_id: Optional[int] = None
        self._current_property_id: Optional[int] = None
        self._persons_cache: List[Dict[str, Any]] = []
        self._properties_cache: List[Dict[str, Any]] = []
        self._person_docs_cache: List[Dict[str, Any]] = []
        self._all_field_rows: List[AttributeFieldRow] = []

        self._init_ui()

    def _init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(6, 6, 6, 6)
        outer_layout.setSpacing(4)

        # Splitter vertical principal que separa o DOMÍNIO DE PESSOAS (acima)
        # do DOMÍNIO DE IMÓVEIS (abaixo) com uma barra divisória de alto destaque
        self.domain_splitter = QSplitter(Qt.Vertical, self)
        self.domain_splitter.setChildrenCollapsible(False)
        self.domain_splitter.setHandleWidth(12)
        self.domain_splitter.setStyleSheet("""
            QSplitter::handle:vertical {
                background-color: rgba(212, 136, 6, 0.28);
                border-top: 2px solid #009faa;
                border-bottom: 2px solid #d48806;
                margin: 2px 0px;
            }
            QSplitter::handle:vertical:hover {
                background-color: rgba(212, 136, 6, 0.50);
            }
        """)

        # ══════════════════════════════════════════════════════════
        # BLOCO SUPERIOR: DOMÍNIO DE PESSOAS (PESSOAS -> DADOS -> DOCUMENTOS)
        # ══════════════════════════════════════════════════════════
        persons_domain_box = QFrame(self.domain_splitter)
        persons_domain_box.setStyleSheet(
            "QFrame#PersonsDomainBox { border: 1px solid rgba(0, 159, 170, 0.35); border-radius: 6px; }"
        )
        persons_domain_box.setObjectName("PersonsDomainBox")
        persons_domain_layout = QVBoxLayout(persons_domain_box)
        persons_domain_layout.setContentsMargins(4, 4, 4, 4)
        persons_domain_layout.setSpacing(0)

        # Splitter vertical interno para redimensionar livremente PESSOAS ↕ DADOS ↕ DOCUMENTOS
        self.persons_splitter = QSplitter(Qt.Vertical, persons_domain_box)
        self.persons_splitter.setChildrenCollapsible(False)
        self.persons_splitter.setHandleWidth(6)
        self.persons_splitter.setStyleSheet("""
            QSplitter::handle:vertical {
                background-color: rgba(0, 159, 170, 0.18);
                border-top: 1px solid rgba(0, 159, 170, 0.40);
                margin: 1px 4px;
            }
            QSplitter::handle:vertical:hover {
                background-color: rgba(0, 159, 170, 0.45);
            }
        """)

        # ── 1. Aba PESSOAS (no topo) ──
        pane_persons = QWidget(self.persons_splitter)
        pane_persons.setMinimumHeight(68)
        lay_persons = QVBoxLayout(pane_persons)
        lay_persons.setContentsMargins(0, 0, 0, 2)
        lay_persons.setSpacing(3)

        btn_add_person = QPushButton("➕ Adicionar", pane_persons)
        btn_add_person.setFixedHeight(20)
        btn_add_person.setCursor(Qt.PointingHandCursor)
        btn_add_person.setToolTip("Adicionar Pessoa manualmente nesta sessão")
        btn_add_person.setStyleSheet(
            "QPushButton { padding: 1px 6px; border: 1px solid rgba(0, 159, 170, 0.55); "
            "border-radius: 3px; font-size: 10px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(0, 159, 170, 0.25); }"
        )
        btn_add_person.clicked.connect(self.add_person_requested.emit)
        lay_persons.addWidget(
            _create_section_header("👤 PESSOAS", pane_persons, domain="PERSON", right_button=btn_add_person)
        )

        self.persons_list = ListWidget(pane_persons)
        self.persons_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.persons_list.customContextMenuRequested.connect(self._show_person_context_menu)
        self.persons_list.itemClicked.connect(self._on_person_item_clicked)
        lay_persons.addWidget(self.persons_list, 1)
        self.persons_splitter.addWidget(pane_persons)

        # ── 2. Aba DADOS (abaixo de PESSOAS) ──
        pane_person_data = QWidget(self.persons_splitter)
        pane_person_data.setMinimumHeight(90)
        lay_person_data = QVBoxLayout(pane_person_data)
        lay_person_data.setContentsMargins(0, 0, 0, 2)
        lay_person_data.setSpacing(3)

        self.header_person_data = _create_section_header("📋 DADOS", pane_person_data, domain="PERSON")
        lay_person_data.addWidget(self.header_person_data)

        person_data_scroll = QScrollArea(pane_person_data)
        person_data_scroll.setWidgetResizable(True)
        person_data_scroll.setFrameShape(QFrame.NoFrame)
        person_data_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        person_fields_widget = QWidget(person_data_scroll)
        person_fields_box = QVBoxLayout(person_fields_widget)
        person_fields_box.setContentsMargins(2, 2, 2, 2)
        person_fields_box.setSpacing(2)

        self.person_field_rows: Dict[str, AttributeFieldRow] = {}
        for key, label in PERSON_DISPLAY_FIELDS:
            row = AttributeFieldRow(key, label, person_fields_widget)
            row.row_selected.connect(self._on_any_field_row_selected)
            row.value_copied.connect(self.field_copied.emit)
            row.override_saved.connect(self._on_person_field_override)
            self.person_field_rows[key] = row
            self._all_field_rows.append(row)
            person_fields_box.addWidget(row)
        person_fields_box.addStretch(1)
        person_data_scroll.setWidget(person_fields_widget)
        lay_person_data.addWidget(person_data_scroll, 1)
        self.persons_splitter.addWidget(pane_person_data)

        # ── 3. Aba DOCUMENTOS (abaixo de DADOS) ──
        pane_person_docs = QWidget(self.persons_splitter)
        pane_person_docs.setMinimumHeight(68)
        lay_person_docs = QVBoxLayout(pane_person_docs)
        lay_person_docs.setContentsMargins(0, 0, 0, 2)
        lay_person_docs.setSpacing(3)

        lay_person_docs.addWidget(_create_section_header("📄 DOCUMENTOS", pane_person_docs, domain="PERSON"))

        self.person_docs_list = ListWidget(pane_person_docs)
        self.person_docs_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.person_docs_list.customContextMenuRequested.connect(self._show_person_doc_context_menu)
        self.person_docs_list.itemClicked.connect(self._on_person_doc_clicked)
        lay_person_docs.addWidget(self.person_docs_list, 1)
        self.persons_splitter.addWidget(pane_person_docs)

        self.persons_splitter.setStretchFactor(0, 2)
        self.persons_splitter.setStretchFactor(1, 4)
        self.persons_splitter.setStretchFactor(2, 2)
        self.persons_splitter.setSizes([95, 195, 95])

        persons_domain_layout.addWidget(self.persons_splitter, 1)
        self.domain_splitter.addWidget(persons_domain_box)

        # ══════════════════════════════════════════════════════════
        # BLOCO INFERIOR: DOMÍNIO DE IMÓVEIS (IMÓVEIS -> DADOS IMÓVEL)
        # ══════════════════════════════════════════════════════════
        properties_domain_box = QFrame(self.domain_splitter)
        properties_domain_box.setStyleSheet(
            "QFrame#PropertiesDomainBox { border: 1px solid rgba(212, 136, 6, 0.45); border-radius: 6px; }"
        )
        properties_domain_box.setObjectName("PropertiesDomainBox")
        properties_domain_layout = QVBoxLayout(properties_domain_box)
        properties_domain_layout.setContentsMargins(4, 4, 4, 4)
        properties_domain_layout.setSpacing(0)

        # Splitter vertical interno para redimensionar livremente IMÓVEIS ↕ DADOS IMÓVEL
        self.properties_splitter = QSplitter(Qt.Vertical, properties_domain_box)
        self.properties_splitter.setChildrenCollapsible(False)
        self.properties_splitter.setHandleWidth(6)
        self.properties_splitter.setStyleSheet("""
            QSplitter::handle:vertical {
                background-color: rgba(212, 136, 6, 0.22);
                border-top: 1px solid rgba(212, 136, 6, 0.45);
                margin: 1px 4px;
            }
            QSplitter::handle:vertical:hover {
                background-color: rgba(212, 136, 6, 0.50);
            }
        """)

        # ── 4. Aba IMÓVEIS ──
        pane_properties = QWidget(self.properties_splitter)
        pane_properties.setMinimumHeight(64)
        lay_properties = QVBoxLayout(pane_properties)
        lay_properties.setContentsMargins(0, 0, 0, 2)
        lay_properties.setSpacing(3)

        btn_add_prop = QPushButton("➕ Adicionar", pane_properties)
        btn_add_prop.setFixedHeight(20)
        btn_add_prop.setCursor(Qt.PointingHandCursor)
        btn_add_prop.setToolTip("Adicionar Imóvel manualmente nesta sessão")
        btn_add_prop.setStyleSheet(
            "QPushButton { padding: 1px 6px; border: 1px solid rgba(212, 136, 6, 0.60); "
            "border-radius: 3px; font-size: 10px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(212, 136, 6, 0.25); }"
        )
        btn_add_prop.clicked.connect(self.add_property_requested.emit)
        lay_properties.addWidget(
            _create_section_header("🏠 IMÓVEIS", pane_properties, domain="PROPERTY", right_button=btn_add_prop)
        )

        self.properties_list = ListWidget(pane_properties)
        self.properties_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.properties_list.customContextMenuRequested.connect(self._show_property_context_menu)
        self.properties_list.itemClicked.connect(self._on_property_item_clicked)
        lay_properties.addWidget(self.properties_list, 1)
        self.properties_splitter.addWidget(pane_properties)

        # ── 5. Aba DADOS IMÓVEL ──
        pane_prop_data = QWidget(self.properties_splitter)
        pane_prop_data.setMinimumHeight(80)
        lay_prop_data = QVBoxLayout(pane_prop_data)
        lay_prop_data.setContentsMargins(0, 0, 0, 2)
        lay_prop_data.setSpacing(3)

        lay_prop_data.addWidget(_create_section_header("📐 DADOS IMÓVEL", pane_prop_data, domain="PROPERTY"))

        prop_data_scroll = QScrollArea(pane_prop_data)
        prop_data_scroll.setWidgetResizable(True)
        prop_data_scroll.setFrameShape(QFrame.NoFrame)
        prop_data_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        prop_fields_widget = QWidget(prop_data_scroll)
        prop_fields_box = QVBoxLayout(prop_fields_widget)
        prop_fields_box.setContentsMargins(2, 2, 2, 2)
        prop_fields_box.setSpacing(2)

        self.property_field_rows: Dict[str, AttributeFieldRow] = {}
        for key, label in PROPERTY_DISPLAY_FIELDS:
            row = AttributeFieldRow(key, label, prop_fields_widget)
            row.row_selected.connect(self._on_any_field_row_selected)
            row.value_copied.connect(self.field_copied.emit)
            row.override_saved.connect(self._on_property_field_override)
            self.property_field_rows[key] = row
            self._all_field_rows.append(row)
            prop_fields_box.addWidget(row)
        prop_fields_box.addStretch(1)
        prop_data_scroll.setWidget(prop_fields_widget)
        lay_prop_data.addWidget(prop_data_scroll, 1)
        self.properties_splitter.addWidget(pane_prop_data)

        self.properties_splitter.setStretchFactor(0, 2)
        self.properties_splitter.setStretchFactor(1, 3)
        self.properties_splitter.setSizes([85, 135])

        properties_domain_layout.addWidget(self.properties_splitter, 1)
        self.domain_splitter.addWidget(properties_domain_box)

        self.domain_splitter.setStretchFactor(0, 6)
        self.domain_splitter.setStretchFactor(1, 4)
        self.domain_splitter.setSizes([390, 230])

        outer_layout.addWidget(self.domain_splitter, 1)

        # ──────────────────────────────────────────────────────────
        # 6. RODAPÉ FIXO: DATAS DE CRIAÇÃO E ÚLTIMA ALTERAÇÃO DA SESSÃO
        # ──────────────────────────────────────────────────────────
        footer_frame = QFrame(self)
        footer_frame.setStyleSheet(
            "QFrame { border-top: 2px solid rgba(128, 128, 128, 0.35); "
            "background-color: rgba(128, 128, 128, 0.06); border-radius: 4px; }"
        )
        footer_layout = QVBoxLayout(footer_frame)
        footer_layout.setContentsMargins(10, 6, 10, 6)
        footer_layout.setSpacing(2)

        self.lbl_created_at = QLabel("DATA DE CRIAÇÃO DA SESSÃO: Não informado", footer_frame)
        self.lbl_created_at.setStyleSheet("font-size: 11px; font-weight: 700; border: none;")
        footer_layout.addWidget(self.lbl_created_at)

        self.lbl_updated_at = QLabel("DATA DA ÚLTIMA ALTERAÇÃO DA SESSÃO: Não informado", footer_frame)
        self.lbl_updated_at.setStyleSheet("font-size: 11px; font-weight: 700; color: #009faa; border: none;")
        footer_layout.addWidget(self.lbl_updated_at)

        outer_layout.addWidget(footer_frame)

    # ──────────────────────────────────────────────────────────────
    # Métodos públicos de atualização de estado
    # ──────────────────────────────────────────────────────────────

    def set_session_dates(self, created_at: Any, updated_at: Any):
        c_str = format_datetime_br(created_at)
        u_str = format_datetime_br(updated_at)
        self.lbl_created_at.setText(f"DATA DE CRIAÇÃO DA SESSÃO: {c_str}")
        self.lbl_updated_at.setText(f"DATA DA ÚLTIMA ALTERAÇÃO DA SESSÃO: {u_str}")

    def populate_persons(
        self,
        persons: List[Dict[str, Any]],
        selected_person_id: Optional[int] = None,
    ) -> Optional[int]:
        """Preenche a lista 'PESSOAS' marcando a selecionada com '◄ (SELECIONADO)'."""
        self._persons_cache = persons
        self.persons_list.blockSignals(True)
        self.persons_list.clear()

        if not persons:
            self._current_person_id = None
            empty_item = QListWidgetItem("Nenhuma pessoa reconhecida nesta sessão")
            empty_item.setFlags(Qt.NoItemFlags)
            self.persons_list.addItem(empty_item)
            self.persons_list.blockSignals(False)
            self.set_person_fields([])
            self.populate_person_documents([])
            return None

        valid_ids = [p["id"] for p in persons]
        if selected_person_id in valid_ids:
            chosen_id = selected_person_id
        elif self._current_person_id in valid_ids:
            chosen_id = self._current_person_id
        else:
            chosen_id = persons[0]["id"]

        self._current_person_id = chosen_id
        target_row = 0

        for idx, p in enumerate(persons):
            pid = p["id"]
            name = p.get("display_name") or f"PESSOA {idx + 1}"
            is_sel = (pid == chosen_id)
            suffix = "  ◄ (SELECIONADO)" if is_sel else ""
            item = QListWidgetItem(f"👤 {name}{suffix}")
            item.setData(Qt.UserRole, pid)
            self.persons_list.addItem(item)
            if is_sel:
                target_row = idx

        self.persons_list.setCurrentRow(target_row)
        self.persons_list.blockSignals(False)
        return chosen_id

    def set_person_fields(self, fields: List[ConsolidatedField]):
        by_key = {f.key: f for f in fields}
        for key, row in self.person_field_rows.items():
            row.set_field_data(by_key.get(key))

    def populate_person_documents(self, docs: List[Dict[str, Any]]):
        """
        Preenche a lista 'DOCUMENTOS' apenas com os documentos vinculados à Pessoa selecionada
        (sem exibir dados pessoais na lista).
        """
        self._person_docs_cache = docs
        self.person_docs_list.blockSignals(True)
        self.person_docs_list.clear()

        if not docs:
            empty_item = QListWidgetItem("Nenhum documento vinculado a esta pessoa")
            empty_item.setFlags(Qt.NoItemFlags)
            self.person_docs_list.addItem(empty_item)
            self.person_docs_list.blockSignals(False)
            return

        for d in docs:
            dtype = format_doc_type_label(d.get("document_type") or "")
            fname = d.get("original_name") or ""
            role = d.get("link_role") or "TITULAR"
            role_tag = f" ({role})" if role not in ("TITULAR", "") else ""
            item = QListWidgetItem(f"📄 {dtype}{role_tag} — {fname}")
            item.setData(Qt.UserRole, d)
            item.setToolTip(f"<b>{dtype}</b><br>Arquivo: {fname}<br>Papel: {role}<br><i>Clique para abrir na prévia</i>")
            self.person_docs_list.addItem(item)

        self.person_docs_list.blockSignals(False)

    def populate_properties(
        self,
        properties: List[Dict[str, Any]],
        selected_property_id: Optional[int] = None,
    ) -> Optional[int]:
        """Preenche a lista 'IMÓVEIS' marcando o selecionado com '◄ (SELECIONADO)'."""
        self._properties_cache = properties
        self.properties_list.blockSignals(True)
        self.properties_list.clear()

        if not properties:
            self._current_property_id = None
            empty_item = QListWidgetItem("Nenhum imóvel reconhecido nesta sessão")
            empty_item.setFlags(Qt.NoItemFlags)
            self.properties_list.addItem(empty_item)
            self.properties_list.blockSignals(False)
            self.set_property_fields([])
            return None

        valid_ids = [pr["id"] for pr in properties]
        if selected_property_id in valid_ids:
            chosen_id = selected_property_id
        elif self._current_property_id in valid_ids:
            chosen_id = self._current_property_id
        else:
            chosen_id = properties[0]["id"]

        self._current_property_id = chosen_id
        target_row = 0

        for idx, pr in enumerate(properties):
            pr_id = pr["id"]
            label = pr.get("label") or f"ENDEREÇO {idx + 1}"
            is_sel = (pr_id == chosen_id)
            suffix = "  ◄ (SELECIONADO)" if is_sel else ""
            item = QListWidgetItem(f"🏠 {label}{suffix}")
            item.setData(Qt.UserRole, pr_id)
            self.properties_list.addItem(item)
            if is_sel:
                target_row = idx

        self.properties_list.setCurrentRow(target_row)
        self.properties_list.blockSignals(False)
        return chosen_id

    def set_property_fields(self, fields: List[ConsolidatedField]):
        by_key = {f.key: f for f in fields}
        for key, row in self.property_field_rows.items():
            row.set_field_data(by_key.get(key))

    @property
    def current_person_id(self) -> Optional[int]:
        return self._current_person_id

    @property
    def current_property_id(self) -> Optional[int]:
        return self._current_property_id

    # ──────────────────────────────────────────────────────────────
    # Callbacks internos e Menus de Contexto (sem reticências)
    # ──────────────────────────────────────────────────────────────

    def _on_any_field_row_selected(self, selected_row: AttributeFieldRow):
        """Garante que apenas 1 linha de atributo exiba o botão ✏️ por vez ao receber clique simples."""
        for row in self._all_field_rows:
            row.set_selected(row is selected_row)

    def _on_person_field_override(self, field_key: str, new_val_or_none: object):
        if self._current_person_id is not None:
            self.person_override_saved.emit(self._current_person_id, field_key, new_val_or_none)

    def _on_property_field_override(self, field_key: str, new_val_or_none: object):
        if self._current_property_id is not None:
            self.property_override_saved.emit(self._current_property_id, field_key, new_val_or_none)

    def _on_person_item_clicked(self, item: QListWidgetItem):
        pid = item.data(Qt.UserRole)
        if pid is not None:
            self._current_person_id = int(pid)
            self.populate_persons(self._persons_cache, selected_person_id=self._current_person_id)
            self.person_selected.emit(self._current_person_id)

    def _on_person_doc_clicked(self, item: QListWidgetItem):
        doc_dict = item.data(Qt.UserRole)
        if isinstance(doc_dict, dict):
            self.document_selected.emit(doc_dict)

    def _on_property_item_clicked(self, item: QListWidgetItem):
        pr_id = item.data(Qt.UserRole)
        if pr_id is not None:
            self._current_property_id = int(pr_id)
            self.populate_properties(self._properties_cache, selected_property_id=self._current_property_id)
            self.property_selected.emit(self._current_property_id)

    def _show_person_context_menu(self, pos):
        item = self.persons_list.itemAt(pos)
        if not item:
            return
        pid = item.data(Qt.UserRole)
        if pid is None:
            return

        menu = QMenu(self)
        act_rename = QAction("✏️ Renomear Pessoa", self)
        act_rename.triggered.connect(lambda: self.rename_person_requested.emit(int(pid)))
        menu.addAction(act_rename)

        other_persons = [p for p in self._persons_cache if p["id"] != pid]
        if other_persons:
            merge_menu = menu.addMenu("🔗 Mesclar esta pessoa com")
            for op in other_persons:
                act_m = QAction(f"👤 {op['display_name']}", self)
                act_m.triggered.connect(
                    lambda checked=False, target_id=op["id"], src_id=pid: self.merge_person_requested.emit(int(target_id), int(src_id))
                )
                merge_menu.addAction(act_m)

        menu.addSeparator()
        act_del = QAction("🗑️ Excluir Pessoa da Sessão", self)
        act_del.triggered.connect(lambda: self.delete_person_requested.emit(int(pid)))
        menu.addAction(act_del)

        menu.exec(self.persons_list.mapToGlobal(pos))

    def _show_person_doc_context_menu(self, pos):
        item = self.person_docs_list.itemAt(pos)
        if not item:
            return
        doc_dict = item.data(Qt.UserRole)
        if not isinstance(doc_dict, dict):
            return

        link_id = doc_dict.get("link_id")
        ext_id = doc_dict.get("id")

        menu = QMenu(self)
        act_prev = QAction("👁️ Visualizar na Prévia", self)
        act_prev.triggered.connect(lambda: self.document_selected.emit(doc_dict))
        menu.addAction(act_prev)

        act_open = QAction("📂 Abrir no Windows", self)
        act_open.triggered.connect(lambda: self.open_document_external_requested.emit(doc_dict))
        menu.addAction(act_open)

        if link_id is not None:
            other_persons = [p for p in self._persons_cache if p["id"] != self._current_person_id]
            if other_persons:
                move_menu = menu.addMenu("🔄 Reatribuir documento para outra pessoa")
                for op in other_persons:
                    act_mv = QAction(f"👤 {op['display_name']}", self)
                    act_mv.triggered.connect(
                        lambda checked=False, lid=link_id, npid=op["id"]: self.reassign_doc_link_requested.emit(int(lid), int(npid))
                    )
                    move_menu.addAction(act_mv)

            act_split = QAction("➕ Separar documento em Nova Pessoa", self)
            act_split.triggered.connect(lambda: self.split_doc_to_new_person_requested.emit(int(link_id), int(ext_id)))
            menu.addAction(act_split)

        menu.addSeparator()
        act_del = QAction("🗑️ Excluir Documento", self)
        act_del.triggered.connect(lambda: self.delete_document_requested.emit(doc_dict))
        menu.addAction(act_del)

        menu.exec(self.person_docs_list.mapToGlobal(pos))

    def _show_property_context_menu(self, pos):
        item = self.properties_list.itemAt(pos)
        if not item:
            return
        pr_id = item.data(Qt.UserRole)
        if pr_id is None:
            return

        menu = QMenu(self)
        act_rename = QAction("✏️ Renomear Imóvel", self)
        act_rename.triggered.connect(lambda: self.rename_property_requested.emit(int(pr_id)))
        menu.addAction(act_rename)

        menu.addSeparator()
        act_del = QAction("🗑️ Excluir Imóvel da Sessão", self)
        act_del.triggered.connect(lambda: self.delete_property_requested.emit(int(pr_id)))
        menu.addAction(act_del)

        menu.exec(self.properties_list.mapToGlobal(pos))
