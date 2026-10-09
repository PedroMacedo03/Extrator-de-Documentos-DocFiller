"""
DocFiller — Página de Dados (Data Page)
=======================================
Apresenta as informações extraídas em um formato de planilha (Excel-like) com:
- Desmascaramento automático (restauração dos dados reais pós-LGPD)
- Colunas completas e redimensionáveis
- Ficha detalhada do documento ao clicar duas vezes
"""

import sys
from pathlib import Path
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                               QHeaderView, QTableWidgetItem, QDialog,
                               QTextEdit, QScrollArea, QFrame)

try:
    from qfluentwidgets import (TitleLabel, SubtitleLabel, BodyLabel, TableWidget, 
                                PrimaryPushButton, PushButton, InfoBar, CardWidget)
    
    sys.path.append(str(Path(__file__).parent.parent))
    from core.database_gemini import DatabaseManager
    from core.masker_gemini import DataMasker
except ImportError:
    pass


class DocumentDetailDialog(QDialog):
    """Janela Modal que exibe a FICHA COMPLETA de todos os campos extraídos."""
    def __init__(self, file_name: str, doc_type: str, dados: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Ficha do Documento — {file_name}")
        self.resize(750, 600)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)
        
        # Cabeçalho
        title = TitleLabel(f"{doc_type}: {file_name}", self)
        layout.addWidget(title)
        
        # Área rolável com as informações
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        content = QWidget()
        c_layout = QVBoxLayout(content)
        c_layout.setSpacing(15)
        
        # 1. Dados Pessoais
        # [LEGACY]: pessoa = dados.get("pessoa", {})
        # [GEMINI - CORREÇÃO H5]: Proteção contra valores null vindos do JSON do Gemini
        pessoa = dados.get("pessoa") or {}
        if not pessoa and doc_type == "CASAMENTO" and "conjuges" in dados:
            conjuges = dados.get("conjuges") or []
            pessoa = conjuges[0] if (conjuges and isinstance(conjuges[0], dict)) else {}
        if not isinstance(pessoa, dict):
            pessoa = {}
            
        p_card = CardWidget(content)
        p_layout = QVBoxLayout(p_card)
        p_layout.addWidget(SubtitleLabel("👤 Dados Pessoais", p_card))
        
        nome = pessoa.get("nome_completo") or "Não informado"
        cpf = pessoa.get("cpf") or "Não informado"
        rg = pessoa.get("rg") or "Não informado"
        nasc = pessoa.get("data_nascimento") or "Não informado"
        obito = pessoa.get("data_obito") or "Nenhum registro"
        
        p_layout.addWidget(BodyLabel(f"<b>Nome Completo:</b> {nome}", p_card))
        p_layout.addWidget(BodyLabel(f"<b>CPF:</b> {cpf}", p_card))
        p_layout.addWidget(BodyLabel(f"<b>RG:</b> {rg}", p_card))
        p_layout.addWidget(BodyLabel(f"<b>Data de Nascimento:</b> {nasc}", p_card))
        if pessoa.get("data_obito"):
            p_layout.addWidget(BodyLabel(f"<b>Data de Óbito:</b> {obito}", p_card))
            
        # Filiação
        pais = pessoa.get("nome_pais", []) or []
        pais_str = ", ".join(pais) if pais else "Não informado"
        p_layout.addWidget(BodyLabel(f"<b>Filiação (Pais):</b> {pais_str}", p_card))
        
        c_layout.addWidget(p_card)
        
        # 2. Dados do Cartório / Registro Civil (se houver)
        cartorio = dados.get("cartorio")
        matricula = dados.get("matricula") or dados.get("matricula_certidao")
        livro = dados.get("livro")
        folha = dados.get("folha")
        termo = dados.get("termo")
        naturalidade = dados.get("naturalidade")
        
        if any([cartorio, matricula, livro, folha, termo, naturalidade]):
            c_card = CardWidget(content)
            c_box = QVBoxLayout(c_card)
            c_box.addWidget(SubtitleLabel("🏛️ Dados Registrais e Cartorários", c_card))
            if cartorio:
                c_box.addWidget(BodyLabel(f"<b>Cartório:</b> {cartorio}", c_card))
            if matricula:
                c_box.addWidget(BodyLabel(f"<b>Matrícula:</b> {matricula}", c_card))
            if naturalidade:
                c_box.addWidget(BodyLabel(f"<b>Naturalidade:</b> {naturalidade}", c_card))
            if livro:
                c_box.addWidget(BodyLabel(f"<b>Livro:</b> {livro} | <b>Folha:</b> {folha or '-'} | <b>Termo:</b> {termo or '-'}", c_card))
            c_layout.addWidget(c_card)
            
        # 3. Dados Imobiliários (se houver)
        imovel = dados.get("imovel")
        if imovel:
            i_card = CardWidget(content)
            i_box = QVBoxLayout(i_card)
            i_box.addWidget(SubtitleLabel("🏠 Dados do Imóvel", i_card))
            i_box.addWidget(BodyLabel(f"<b>Inscrição Municipal:</b> {imovel.get('inscricao_municipal', '-')}", i_card))
            i_box.addWidget(BodyLabel(f"<b>Matrícula:</b> {imovel.get('matricula_imovel', '-')}", i_card))
            i_box.addWidget(BodyLabel(f"<b>Endereço:</b> {imovel.get('endereco_completo', '-')}", i_card))
            i_box.addWidget(BodyLabel(f"<b>CEP:</b> {imovel.get('cep', '-')}", i_card))
            c_layout.addWidget(i_card)
            
        # 4. JSON Completo Bruto (Inspecionar tudo)
        j_card = CardWidget(content)
        j_box = QVBoxLayout(j_card)
        j_box.addWidget(SubtitleLabel("📋 JSON Estruturado Completo", j_card))
        json_view = QTextEdit(j_card)
        json_view.setReadOnly(True)
        json_view.setPlainText(json.dumps(dados, indent=2, ensure_ascii=False))
        json_view.setMaximumHeight(180)
        j_box.addWidget(json_view)
        c_layout.addWidget(j_card)
        
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        # Botão Fechar
        btn_close = PushButton("Fechar", self)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)


class DataPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("DataPage")
        
        self.db = DatabaseManager()
        self.masker = DataMasker()
        self._raw_records = []  # Guarda os registros completos em memória
        
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(40, 40, 40, 40)
        self.vBoxLayout.setSpacing(20)
        
        # Cabeçalho com ações
        hLayout = QHBoxLayout()
        self.titleLabel = TitleLabel("Dados Extraídos e Validados", self)
        hLayout.addWidget(self.titleLabel)
        
        hLayout.addStretch(1)
        
        self.btnDetails = PushButton("👁️ Ver Ficha Completa", self)
        self.btnDetails.clicked.connect(self.show_selected_details)
        hLayout.addWidget(self.btnDetails)
        
        self.btnRefresh = PushButton("🔄 Atualizar Planilha", self)
        self.btnRefresh.clicked.connect(self.load_data)
        hLayout.addWidget(self.btnRefresh)
        
        self.vBoxLayout.addLayout(hLayout)
        
        # Instrução de uso
        self.helpLabel = BodyLabel("💡 Dica: Dê duplo-clique em qualquer linha para abrir a Ficha Completa com todos os dados e o JSON.", self)
        self.vBoxLayout.addWidget(self.helpLabel)
        
        # Criação da Tabela (Estilo Planilha)
        self.table = TableWidget(self)
        self.table.setWordWrap(False)
        # [LEGACY]: self.table.setEditTriggers(TableWidget.DoubleClicked)
        # [GEMINI - CORREÇÃO M5]: Desabilita edição in-place ao dar duplo clique para que abra apenas o modal da Ficha
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(TableWidget.SelectRows)
        self.table.itemDoubleClicked.connect(self.on_double_click)
        
        # Colunas completas
        self.columns = [
            "ID", "Arquivo Origem", "Tipo Doc", "Pessoa Principal", 
            "CPF", "RG", "Data Nasc.", "Nome da Mãe", "Nome do Pai", "Cartório / Registro"
        ]
        
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        
        self.vBoxLayout.addWidget(self.table)
        
        # Carrega os dados na inicialização
        self.load_data()

    def load_data(self):
        """Busca no banco SQLite, desmascara os dados com token_map e popula a planilha visual."""
        self.table.setRowCount(0)
        self._raw_records.clear()
        
        try:
            extractions = self.db.get_recent_extractions(limit=50)
            
            for row_idx, row in enumerate(extractions):
                self.table.insertRow(row_idx)
                
                db_id = str(row["id"])
                file_name = row["original_name"]
                doc_type = row["document_type"]
                
                # Parse do JSON estruturado que o Gemini devolveu
                raw_json = row["extracted_data_json"]
                try:
                    payload = json.loads(raw_json)
                    dados = payload.get("dados", {})
                    token_map = payload.get("token_map", {})
                    
                    # DESMASCARAMENTO: Restaura os dados reais locais (RG, CPF, Nomes)
                    if token_map:
                        dados = self.masker.demask_dict(dados, token_map)
                except Exception as ex:
                    print(f"[ERRO DESMASCARAMENTO] {ex}")
                    dados = {}
                
                # Guarda na memória para o visualizador de detalhes
                self._raw_records.append({
                    "id": db_id,
                    "file_name": file_name,
                    "doc_type": doc_type,
                    "dados": dados
                })
                
                # Extraindo dados da Pessoa Principal
                # [LEGACY]: pessoa = dados.get("pessoa", {})
                # [GEMINI - CORREÇÃO H5]: Proteção contra null vindo do JSON do Gemini
                pessoa = dados.get("pessoa") or {}
                if not pessoa and doc_type == "CASAMENTO" and "conjuges" in dados:
                    conjuges = dados.get("conjuges") or []
                    pessoa = conjuges[0] if (conjuges and isinstance(conjuges[0], dict)) else {}
                if not pessoa and doc_type == "ESCRITURA" and "compradores" in dados:
                    compradores = dados.get("compradores") or []
                    pessoa = compradores[0] if (compradores and isinstance(compradores[0], dict)) else {}
                if not pessoa and doc_type == "IPTU" and "contribuinte" in dados:
                    pessoa = dados.get("contribuinte") or {}
                if not isinstance(pessoa, dict):
                    pessoa = {}
                    
                nome = pessoa.get("nome_completo", "-") or "-"
                cpf = pessoa.get("cpf", "-") or "-"
                rg = pessoa.get("rg", "-") or "-"
                nasc = pessoa.get("data_nascimento", "-") or "-"
                
                # Filiação: Mãe e Pai
                pais = pessoa.get("nome_pais", []) or []
                mae = pais[1] if len(pais) > 1 else (pais[0] if len(pais) == 1 else "-")
                pai = pais[0] if len(pais) > 1 else "-"
                
                # Cartório / Registro
                cartorio = dados.get("cartorio") or dados.get("matricula") or "-"
                
                items = [db_id, file_name, doc_type, nome, cpf, rg, nasc, mae, pai, cartorio]
                
                for col_idx, text in enumerate(items):
                    cell = QTableWidgetItem(str(text))
                    if col_idx in [0, 1]:
                        cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row_idx, col_idx, cell)
                    
            # Auto-redimensiona as colunas para o texto caber sem cortar
            self.table.resizeColumnsToContents()
            
            InfoBar.success("Atualizado", f"{len(extractions)} documento(s) carregado(s) e desmascarados.", duration=2500, parent=self)
            
        except Exception as e:
            InfoBar.error("Erro ao carregar", f"Falha na leitura do banco: {str(e)}", parent=self)

    def on_double_click(self, item):
        """Abre a ficha completa ao dar duplo clique em uma célula."""
        row = item.row()
        self._open_details(row)

    def show_selected_details(self):
        """Abre a ficha pelo botão da barra de ferramentas."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            current_row = self.table.currentRow()
            if current_row >= 0:
                self._open_details(current_row)
                return
            InfoBar.warning("Nenhuma seleção", "Clique em uma linha da tabela primeiro.", parent=self)
            return
        row = selected_rows[0].row()
        self._open_details(row)

    def _open_details(self, row_idx: int):
        if 0 <= row_idx < len(self._raw_records):
            rec = self._raw_records[row_idx]
            dialog = DocumentDetailDialog(
                file_name=rec["file_name"],
                doc_type=rec["doc_type"],
                dados=rec["dados"],
                parent=self
            )
            dialog.exec()
