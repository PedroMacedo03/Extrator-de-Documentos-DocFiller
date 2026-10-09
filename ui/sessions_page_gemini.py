"""
DocFiller — Aba de Sessões e Documentos (Sessions Page)
======================================================
Substitui a antiga página de dados soltos, organizando o sistema em Sessões/Processos.

Recursos:
- Otimizado para modo Janela e Tela Cheia (layout responsivo com QSplitter horizontal)
- Formato de data e hora rigoroso: HH/MM - DD/MM/AA (ex: 14/35 - 23/09/26)
- Suporte total a Temas Escuro e Claro (sem cores duras ou fundos brancos travados)
- Apresentação Natural de Sessões:
    - Painel Esquerdo: Lista de Sessões com busca em tempo real, badges de documentos e atalhos de ação
    - Painel Direito:
        1. Cartão da Sessão com Fichas/Chips visuais dos Documentos Anexados (scroll horizontal leve)
        2. Tabela Espaçosa de Dados Consolidados com:
           - Edição dupla: duplo clique na célula OU botão explícito "✏️ Editar Dados"
           - Cópia individual de células (Ctrl+C e menu de contexto com botão direito)
           - Persistência das alterações manuais no SQLite (LGPD segura)
- Botão "📥 Retomar Sessão" que define a sessão como ativa e redireciona para a aba de Upload
"""

import os
import sys
from pathlib import Path
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import pymupdf
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QImage, QPixmap, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QHeaderView,
    QTableWidgetItem, QDialog, QTextEdit, QScrollArea, QFrame,
    QListWidgetItem, QInputDialog, QMessageBox,
    QApplication, QMenu, QFormLayout, QLineEdit, QLabel, QSizePolicy
)

try:
    from qfluentwidgets import (
        TitleLabel, SubtitleLabel, BodyLabel, TableWidget, 
        PrimaryPushButton, PushButton, InfoBar, CardWidget,
        SearchLineEdit, LineEdit, ListWidget
    )
    
    sys.path.append(str(Path(__file__).parent.parent))
    from core.database_gemini import DatabaseManager
    from core.masker_gemini import DataMasker
except ImportError:
    pass


# =====================================================================
# FORMATADOR DE DATA E HORA: HH/MM - DD/MM/AA
# =====================================================================
def format_datetime_br(val: Any) -> str:
    """
    [GEMINI]: Formata estritamente no padrão solicitado pelo usuário:
    HH/MM - DD/MM/AA (ex: 14/35 - 23/09/26)
    """
    if not val:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%H/%M - %d/%m/%y")
    val_str = str(val).strip()
    try:
        clean = val_str.split(".")[0].replace("T", " ")
        if len(clean) >= 19:
            dt = datetime.strptime(clean[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%H/%M - %d/%m/%y")
        elif len(clean) == 10:
            dt = datetime.strptime(clean, "%Y-%m-%d")
            return dt.strftime("%d/%m/%y")
    except Exception:
        pass
    return val_str


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
# MODAL: Ficha Completa do Documento (Detalhes e JSON)
# =====================================================================
class DocumentDetailDialog(QDialog):
    """Janela Modal que exibe a FICHA COMPLETA de todos os campos extraídos."""
    def __init__(self, file_name: str, doc_type: str, dados: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Ficha do Documento — {file_name}")
        self.resize(780, 620)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(15)
        
        title = TitleLabel(f"{doc_type}: {file_name}", self)
        layout.addWidget(title)
        
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        content = QWidget()
        c_layout = QVBoxLayout(content)
        c_layout.setSpacing(15)
        
        # 1. Dados Pessoais
        pessoa = dados.get("pessoa") or {}
        if not pessoa and doc_type == "CASAMENTO" and "conjuges" in dados:
            conjuges = dados.get("conjuges") or []
            pessoa = conjuges[0] if (conjuges and isinstance(conjuges[0], dict)) else {}
        if not pessoa and doc_type == "ESCRITURA" and "compradores" in dados:
            compradores = dados.get("compradores") or []
            pessoa = compradores[0] if (compradores and isinstance(compradores[0], dict)) else {}
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
            
        pais = pessoa.get("nome_pais", []) or []
        pais_str = ", ".join(pais) if pais else "Não informado"
        p_layout.addWidget(BodyLabel(f"<b>Filiação (Pais):</b> {pais_str}", p_card))
        
        c_layout.addWidget(p_card)
        
        # 2. Dados do Cartório / Registro Civil
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
            
        # 3. Dados Imobiliários
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

        # 4. Dados do Título de Eleitor
        if any(dados.get(k) for k in ["numero_titulo", "zona", "secao", "municipio"]):
            t_card = CardWidget(content)
            t_box = QVBoxLayout(t_card)
            t_box.addWidget(SubtitleLabel("🗳️ Dados do Título Eleitoral", t_card))
            if dados.get("numero_titulo"):
                t_box.addWidget(BodyLabel(f"<b>Número do Título:</b> {dados.get('numero_titulo')}", t_card))
            t_box.addWidget(BodyLabel(f"<b>Zona Eleitoral:</b> {dados.get('zona', '-')} | <b>Seção:</b> {dados.get('secao', '-')}", t_card))
            if dados.get("municipio") or dados.get("uf"):
                t_box.addWidget(BodyLabel(f"<b>Município / UF:</b> {dados.get('municipio', '-')} / {dados.get('uf', '-')}", t_card))
            if dados.get("data_emissao"):
                t_box.addWidget(BodyLabel(f"<b>Data de Emissão:</b> {dados.get('data_emissao')}", t_card))
            c_layout.addWidget(t_card)

        # 5. Dados Militares / Funcionais / Órgãos Públicos / Conselhos
        if any(dados.get(k) for k in ["orgao_emissor", "numero_registro", "posto_graduacao_cargo", "categoria_funcional"]):
            f_card = CardWidget(content)
            f_box = QVBoxLayout(f_card)
            f_box.addWidget(SubtitleLabel("🎖️ Dados Funcionais / Militares / Conselho", f_card))
            if dados.get("orgao_emissor"):
                f_box.addWidget(BodyLabel(f"<b>Órgão / Corporação Emissora:</b> {dados.get('orgao_emissor')}", f_card))
            if dados.get("categoria_funcional"):
                f_box.addWidget(BodyLabel(f"<b>Categoria Funcional:</b> {dados.get('categoria_funcional')}", f_card))
            if dados.get("numero_registro"):
                f_box.addWidget(BodyLabel(f"<b>Registro / Matrícula Militar:</b> {dados.get('numero_registro')}", f_card))
            if dados.get("posto_graduacao_cargo"):
                f_box.addWidget(BodyLabel(f"<b>Posto / Patente / Cargo:</b> {dados.get('posto_graduacao_cargo')}", f_card))
            if dados.get("uf_emissor"):
                f_box.addWidget(BodyLabel(f"<b>UF Emissor:</b> {dados.get('uf_emissor')}", f_card))
            if dados.get("data_expedicao") or dados.get("data_validade"):
                f_box.addWidget(BodyLabel(f"<b>Data Expedição:</b> {dados.get('data_expedicao', '-')} | <b>Validade:</b> {dados.get('data_validade', 'Indeterminada')}", f_card))
            c_layout.addWidget(f_card)

        # 6. Dados Acadêmicos / Conclusão de Curso / Diploma
        if any(dados.get(k) for k in ["instituicao_ensino", "curso", "nivel_ensino", "registro_diploma"]):
            d_card = CardWidget(content)
            d_box = QVBoxLayout(d_card)
            d_box.addWidget(SubtitleLabel("🎓 Dados Acadêmicos e Escolares", d_card))
            if dados.get("instituicao_ensino"):
                d_box.addWidget(BodyLabel(f"<b>Instituição de Ensino:</b> {dados.get('instituicao_ensino')}", d_card))
            if dados.get("nivel_ensino"):
                d_box.addWidget(BodyLabel(f"<b>Nível de Ensino:</b> {dados.get('nivel_ensino')}", d_card))
            if dados.get("curso"):
                d_box.addWidget(BodyLabel(f"<b>Curso / Habilitação:</b> {dados.get('curso')}", d_card))
            if dados.get("data_conclusao"):
                d_box.addWidget(BodyLabel(f"<b>Data de Conclusão:</b> {dados.get('data_conclusao')}", d_card))
            if dados.get("data_emissao"):
                d_box.addWidget(BodyLabel(f"<b>Data de Emissão / Colação:</b> {dados.get('data_emissao')}", d_card))
            if dados.get("registro_diploma"):
                d_box.addWidget(BodyLabel(f"<b>Registro MEC / Livro / Folha:</b> {dados.get('registro_diploma')}", d_card))
            if dados.get("cidade_instituicao"):
                d_box.addWidget(BodyLabel(f"<b>Cidade / UF da Instituição:</b> {dados.get('cidade_instituicao')}", d_card))
            c_layout.addWidget(d_card)

        # 7. Carteira de Identidade Nacional (CIN)
        if doc_type == "CIN" or any(dados.get(k) for k in ["registro_geral_antigo", "codigo_mrz", "tipo_sanguineo_fator_rh"]):
            cin_card = CardWidget(content)
            cin_box = QVBoxLayout(cin_card)
            cin_box.addWidget(SubtitleLabel("🪪 Carteira de Identidade Nacional (CIN)", cin_card))
            if dados.get("nome_social"):
                cin_box.addWidget(BodyLabel(f"<b>Nome Social:</b> {dados.get('nome_social')}", cin_card))
            if dados.get("orgao_emissor") or dados.get("uf_emissor"):
                cin_box.addWidget(BodyLabel(f"<b>Órgão / UF Emissor:</b> {dados.get('orgao_emissor', '-')} / {dados.get('uf_emissor', '-')}", cin_card))
            if dados.get("data_emissao") or dados.get("data_validade"):
                cin_box.addWidget(BodyLabel(f"<b>Data Emissão:</b> {dados.get('data_emissao', '-')} | <b>Validade:</b> {dados.get('data_validade', 'Indeterminada')}", cin_card))
            if dados.get("registro_geral_antigo"):
                cin_box.addWidget(BodyLabel(f"<b>RG Estadual Antigo:</b> {dados.get('registro_geral_antigo')}", cin_card))
            if dados.get("tipo_sanguineo_fator_rh"):
                cin_box.addWidget(BodyLabel(f"<b>Tipo Sanguíneo:</b> {dados.get('tipo_sanguineo_fator_rh')}", cin_card))
            if dados.get("codigo_mrz"):
                cin_box.addWidget(BodyLabel(f"<b>Código MRZ:</b> <code>{dados.get('codigo_mrz')}</code>", cin_card))
            c_layout.addWidget(cin_card)

        # 8. Passaporte
        if doc_type == "PASSAPORTE" or dados.get("numero_passaporte"):
            pass_card = CardWidget(content)
            pass_box = QVBoxLayout(pass_card)
            pass_box.addWidget(SubtitleLabel("🛂 Passaporte Brasileiro", pass_card))
            if dados.get("numero_passaporte"):
                pass_box.addWidget(BodyLabel(f"<b>Número do Passaporte:</b> {dados.get('numero_passaporte')}", pass_card))
            if dados.get("pais_emissor") or dados.get("tipo_passaporte"):
                pass_box.addWidget(BodyLabel(f"<b>País / Tipo:</b> {dados.get('pais_emissor', 'BRA')} ({dados.get('tipo_passaporte', 'Comum')})", pass_card))
            if dados.get("autoridade_emissora"):
                pass_box.addWidget(BodyLabel(f"<b>Autoridade Emissora:</b> {dados.get('autoridade_emissora')}", pass_card))
            if dados.get("data_emissao") or dados.get("data_validade"):
                pass_box.addWidget(BodyLabel(f"<b>Emissão:</b> {dados.get('data_emissao', '-')} | <b>Validade:</b> {dados.get('data_validade', '-')}", pass_card))
            if dados.get("codigo_mrz"):
                pass_box.addWidget(BodyLabel(f"<b>Linhas MRZ:</b> <code>{dados.get('codigo_mrz')}</code>", pass_card))
            c_layout.addWidget(pass_card)

        # 9. Carteira de Ordem / Conselho Profissional
        if doc_type == "CARTEIRA_CONSELHO" or dados.get("orgao_conselho"):
            ord_card = CardWidget(content)
            ord_box = QVBoxLayout(ord_card)
            ord_box.addWidget(SubtitleLabel("⚖️ Carteira de Ordem / Conselho Profissional", ord_card))
            if dados.get("orgao_conselho"):
                ord_box.addWidget(BodyLabel(f"<b>Conselho / Ordem:</b> {dados.get('orgao_conselho')}", ord_card))
            if dados.get("numero_registro"):
                ord_box.addWidget(BodyLabel(f"<b>Número de Inscrição:</b> {dados.get('numero_registro')}", ord_card))
            if dados.get("seccional_uf"):
                ord_box.addWidget(BodyLabel(f"<b>Seccional / UF:</b> {dados.get('seccional_uf')}", ord_card))
            if dados.get("tipo_inscricao") or dados.get("profissao_cargo"):
                ord_box.addWidget(BodyLabel(f"<b>Tipo Inscrição / Cargo:</b> {dados.get('tipo_inscricao', '-')} ({dados.get('profissao_cargo', '-')})", ord_card))
            if dados.get("data_expedicao") or dados.get("data_validade"):
                ord_box.addWidget(BodyLabel(f"<b>Expedição:</b> {dados.get('data_expedicao', '-')} | <b>Validade:</b> {dados.get('data_validade', 'Indeterminada')}", ord_card))
            c_layout.addWidget(ord_card)

        # 10. Certificado Militar / Reservista
        if doc_type == "CERTIFICADO_RESERVISTA" or any(dados.get(k) for k in ["numero_ra", "tipo_documento_militar", "forca_armada"]):
            mil_card = CardWidget(content)
            mil_box = QVBoxLayout(mil_card)
            mil_box.addWidget(SubtitleLabel("🪖 Certificado Militar / Reservista", mil_card))
            if dados.get("numero_ra"):
                mil_box.addWidget(BodyLabel(f"<b>Registro de Alistamento (RA):</b> {dados.get('numero_ra')}", mil_card))
            if dados.get("tipo_documento_militar"):
                mil_box.addWidget(BodyLabel(f"<b>Tipo de Certificado:</b> {dados.get('tipo_documento_militar')}", mil_card))
            if dados.get("forca_armada") or dados.get("circunscricao_militar"):
                mil_box.addWidget(BodyLabel(f"<b>Força / Circunscrição:</b> {dados.get('forca_armada', '-')} / {dados.get('circunscricao_militar', '-')}", mil_card))
            if dados.get("situacao_militar"):
                mil_box.addWidget(BodyLabel(f"<b>Situação Militar:</b> {dados.get('situacao_militar')}", mil_card))
            if dados.get("data_expedicao"):
                mil_box.addWidget(BodyLabel(f"<b>Data de Expedição:</b> {dados.get('data_expedicao')}", mil_card))
            c_layout.addWidget(mil_card)

        # 11. Cartão Nacional de Saúde (SUS)
        if doc_type == "CARTAO_SUS" or dados.get("numero_cns"):
            sus_card = CardWidget(content)
            sus_box = QVBoxLayout(sus_card)
            sus_box.addWidget(SubtitleLabel("🏥 Cartão Nacional de Saúde (SUS)", sus_card))
            if dados.get("numero_cns"):
                sus_box.addWidget(BodyLabel(f"<b>Número CNS:</b> {dados.get('numero_cns')}", sus_card))
            if dados.get("municipio_cadastro"):
                sus_box.addWidget(BodyLabel(f"<b>Município de Cadastro:</b> {dados.get('municipio_cadastro')}", sus_card))
            if dados.get("data_cadastro"):
                sus_box.addWidget(BodyLabel(f"<b>Data de Cadastro:</b> {dados.get('data_cadastro')}", sus_card))
            c_layout.addWidget(sus_card)

        # 12. Documento Nacional do Estudante (DNE)
        if doc_type == "CARTEIRA_ESTUDANTE_DNE" or any(dados.get(k) for k in ["codigo_uso_dne", "matricula_estudante"]):
            dne_card = CardWidget(content)
            dne_box = QVBoxLayout(dne_card)
            dne_box.addWidget(SubtitleLabel("🎓 Documento Nacional do Estudante (DNE)", dne_card))
            if dados.get("instituicao_ensino"):
                dne_box.addWidget(BodyLabel(f"<b>Instituição de Ensino:</b> {dados.get('instituicao_ensino')}", dne_card))
            if dados.get("curso") or dados.get("nivel_escolaridade"):
                dne_box.addWidget(BodyLabel(f"<b>Curso / Nível:</b> {dados.get('curso', '-')} ({dados.get('nivel_escolaridade', '-')})", dne_card))
            if dados.get("matricula_estudante"):
                dne_box.addWidget(BodyLabel(f"<b>Matrícula do Aluno:</b> {dados.get('matricula_estudante')}", dne_card))
            if dados.get("codigo_uso_dne"):
                dne_box.addWidget(BodyLabel(f"<b>Código de Uso:</b> <code>{dados.get('codigo_uso_dne')}</code>", dne_card))
            if dados.get("entidade_emissora"):
                dne_box.addWidget(BodyLabel(f"<b>Entidade Emissora:</b> {dados.get('entidade_emissora')}", dne_card))
            if dados.get("data_validade"):
                dne_box.addWidget(BodyLabel(f"<b>Validade:</b> {dados.get('data_validade')}", dne_card))
            c_layout.addWidget(dne_card)
            
        # JSON Completo Bruto
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
        
        btn_close = PushButton("Fechar", self)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)


# =====================================================================
# MODAL: Edição Explícita de Dados
# =====================================================================
class EditDocumentDataDialog(QDialog):
    """Permite editar os principais campos extraídos de um documento."""
    def __init__(self, doc_id: int, file_name: str, dados: dict, parent=None):
        super().__init__(parent)
        self.doc_id = doc_id
        self.dados = dados
        self.setWindowTitle(f"✏️ Editar Dados — {file_name}")
        self.resize(600, 480)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(15)
        
        layout.addWidget(TitleLabel(f"Editar Dados do Documento #{doc_id}", self))
        layout.addWidget(BodyLabel(f"Arquivo: <b>{file_name}</b>", self))
        
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        # Extrai referências existentes
        pessoa = self.dados.get("pessoa") or {}
        if not isinstance(pessoa, dict):
            pessoa = {}
            
        self.edit_nome = LineEdit(self)
        self.edit_nome.setText(pessoa.get("nome_completo", ""))
        form_layout.addRow("Nome Completo:", self.edit_nome)
        
        self.edit_cpf = LineEdit(self)
        self.edit_cpf.setText(pessoa.get("cpf", ""))
        form_layout.addRow("CPF:", self.edit_cpf)
        
        self.edit_rg = LineEdit(self)
        self.edit_rg.setText(pessoa.get("rg", ""))
        form_layout.addRow("RG:", self.edit_rg)
        
        self.edit_nasc = LineEdit(self)
        self.edit_nasc.setText(pessoa.get("data_nascimento", ""))
        form_layout.addRow("Data Nascimento:", self.edit_nasc)
        
        pais = pessoa.get("nome_pais", []) or []
        mae = pais[1] if len(pais) > 1 else (pais[0] if len(pais) == 1 else "")
        pai = pais[0] if len(pais) > 1 else ""
        
        self.edit_mae = LineEdit(self)
        self.edit_mae.setText(mae)
        form_layout.addRow("Nome da Mãe:", self.edit_mae)
        
        self.edit_pai = LineEdit(self)
        self.edit_pai.setText(pai)
        form_layout.addRow("Nome do Pai:", self.edit_pai)
        
        self.edit_cartorio = LineEdit(self)
        self.edit_cartorio.setText(self.dados.get("cartorio") or self.dados.get("matricula") or "")
        form_layout.addRow("Cartório / Matrícula:", self.edit_cartorio)
        
        layout.addLayout(form_layout)
        
        # Botões
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        
        self.btn_cancel = PushButton("Cancelar", self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        self.btn_save = PrimaryPushButton("💾 Salvar Alterações", self)
        self.btn_save.clicked.connect(self.save_and_accept)
        btn_layout.addWidget(self.btn_save)
        
        layout.addLayout(btn_layout)

    def save_and_accept(self):
        """Atualiza o dicionário de dados em memória."""
        if "pessoa" not in self.dados or not isinstance(self.dados["pessoa"], dict):
            self.dados["pessoa"] = {}
            
        self.dados["pessoa"]["nome_completo"] = self.edit_nome.text().strip()
        self.dados["pessoa"]["cpf"] = self.edit_cpf.text().strip()
        self.dados["pessoa"]["rg"] = self.edit_rg.text().strip()
        self.dados["pessoa"]["data_nascimento"] = self.edit_nasc.text().strip()
        
        # Filiação
        pais = []
        if self.edit_pai.text().strip():
            pais.append(self.edit_pai.text().strip())
        if self.edit_mae.text().strip():
            pais.append(self.edit_mae.text().strip())
        self.dados["pessoa"]["nome_pais"] = pais
        
        if self.edit_cartorio.text().strip():
            self.dados["cartorio"] = self.edit_cartorio.text().strip()
            
        self.accept()


# =====================================================================
# VISUALIZADOR DE DOCUMENTOS INTEGRADO: DocumentPreviewWidget
# =====================================================================
class DocumentPreviewWidget(CardWidget):
    """
    [GEMINI]: Visualizador e Prévia Integrada de Documentos (PDFs e Imagens).
    Renderiza páginas com PyMuPDF em alta fidelidade com controles de:
    - Navegação de páginas (Anterior / Próxima)
    - Zoom dinâmico (Zoom in, Zoom out, Ajustar à largura, Ctrl + Roda do Mouse)
    - Abertura no leitor padrão do Windows (os.startfile)
    - Botão de ocultar/fechar prévia
    """
    close_requested = Signal()

    def __init__(self, parent=None):
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
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # --- BARRA DE FERRAMENTAS DO VISUALIZADOR ---
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.lbl_doc_info = BodyLabel("📄 <i>Nenhum documento selecionado</i>", self)
        toolbar.addWidget(self.lbl_doc_info)

        toolbar.addStretch(1)

        # Navegação de Páginas
        self.btn_prev_page = PushButton("◀", self)
        self.btn_prev_page.setFixedSize(30, 28)
        self.btn_prev_page.setToolTip("Página Anterior")
        self.btn_prev_page.clicked.connect(self.prev_page)
        self.btn_prev_page.setEnabled(False)
        toolbar.addWidget(self.btn_prev_page)

        self.lbl_page_counter = BodyLabel("Pág. 0 / 0", self)
        self.lbl_page_counter.setStyleSheet("font-weight: 500;")
        toolbar.addWidget(self.lbl_page_counter)

        self.btn_next_page = PushButton("▶", self)
        self.btn_next_page.setFixedSize(30, 28)
        self.btn_next_page.setToolTip("Próxima Página")
        self.btn_next_page.clicked.connect(self.next_page)
        self.btn_next_page.setEnabled(False)
        toolbar.addWidget(self.btn_next_page)

        # Divisor visual
        sep1 = QFrame(self)
        sep1.setFrameShape(QFrame.VLine)
        sep1.setFrameShadow(QFrame.Sunken)
        toolbar.addWidget(sep1)

        # Controles de Zoom
        self.btn_zoom_out = PushButton("🔍 -", self)
        self.btn_zoom_out.setFixedSize(46, 28)
        self.btn_zoom_out.setToolTip("Reduzir Zoom (Ctrl + Roda)")
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.btn_zoom_out.setEnabled(False)
        toolbar.addWidget(self.btn_zoom_out)

        self.lbl_zoom = BodyLabel("100%", self)
        self.lbl_zoom.setFixedWidth(44)
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        toolbar.addWidget(self.lbl_zoom)

        self.btn_zoom_in = PushButton("🔍 +", self)
        self.btn_zoom_in.setFixedSize(46, 28)
        self.btn_zoom_in.setToolTip("Aumentar Zoom (Ctrl + Roda)")
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        self.btn_zoom_in.setEnabled(False)
        toolbar.addWidget(self.btn_zoom_in)

        self.btn_fit_width = PushButton("↔️ Ajustar", self)
        self.btn_fit_width.setFixedSize(80, 28)
        self.btn_fit_width.setToolTip("Ajustar visualização à largura do painel")
        self.btn_fit_width.clicked.connect(self.fit_width)
        self.btn_fit_width.setEnabled(False)
        toolbar.addWidget(self.btn_fit_width)

        # Divisor visual
        sep2 = QFrame(self)
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFrameShadow(QFrame.Sunken)
        toolbar.addWidget(sep2)

        # Abrir no aplicativo nativo do Windows
        self.btn_open_external = PushButton("📂 Abrir no Windows", self)
        self.btn_open_external.setToolTip("Abrir documento no aplicativo padrão do Windows")
        self.btn_open_external.clicked.connect(self.open_in_windows)
        self.btn_open_external.setEnabled(False)
        toolbar.addWidget(self.btn_open_external)

        # Botão Fechar/Ocultar Prévia
        self.btn_close = PushButton("✕", self)
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setToolTip("Ocultar Painel de Prévia")
        self.btn_close.clicked.connect(self.close_requested.emit)
        toolbar.addWidget(self.btn_close)

        layout.addLayout(toolbar)

        # --- ÁREA DE SCROLL COM VISUALIZAÇÃO DO DOCUMENTO ---
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: rgba(128, 128, 128, 0.08);
                border: 1px solid rgba(128, 128, 128, 0.15);
                border-radius: 8px;
            }
        """)

        # Container interno para centralização da imagem
        self.image_container = QWidget()
        img_box = QVBoxLayout(self.image_container)
        img_box.setContentsMargins(15, 15, 15, 15)
        img_box.setAlignment(Qt.AlignCenter)

        self.lbl_image = QLabel(self.image_container)
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setText("📄 Clique em um documento para visualizar a prévia aqui.")
        self.lbl_image.setStyleSheet("color: #888; font-size: 13px; font-style: italic;")
        img_box.addWidget(self.lbl_image)

        self.scroll_area.setWidget(self.image_container)
        layout.addWidget(self.scroll_area, 1)

    def load_document(self, file_path: str, original_name: str = "", doc_type: str = ""):
        """Carrega e renderiza o documento informado."""
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

            # Atualiza textos e botões
            badge = f"<span style='color: #009faa; font-weight: bold;'>[{self.doc_type}]</span>" if self.doc_type else ""
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
        """Renderiza a página atual com o fator de zoom selecionado."""
        if not self.doc or self.current_page < 0 or self.current_page >= self.total_pages:
            return

        try:
            page = self.doc[self.current_page]
            # DPI dinâmico baseado no zoom: nítido e veloz (base 140 DPI)
            target_dpi = int(max(60, min(300, 140 * self.zoom_factor)))
            pix = page.get_pixmap(dpi=target_dpi)

            fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
            qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
            pixmap = QPixmap.fromImage(qimg)

            self.lbl_image.setText("")
            self.lbl_image.setPixmap(pixmap)
            self.lbl_image.setStyleSheet("border: 1px solid rgba(0, 0, 0, 0.15); border-radius: 4px;")

            # Atualiza indicadores
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
        """Calcula o zoom ideal para preencher a largura visível da janela."""
        if not self.doc:
            return
        vw = self.scroll_area.viewport().width() - 50
        if vw <= 100:
            return
        page = self.doc[self.current_page]
        base_width_at_140dpi = page.rect.width * (140.0 / 72.0)
        if base_width_at_140dpi > 0:
            factor = vw / base_width_at_140dpi
            self.zoom_factor = max(self.min_zoom, min(self.max_zoom, round(factor, 2)))
            self.render_current_page()

    def open_in_windows(self):
        """Abre o arquivo com o visualizador padrão configurado no Windows."""
        if self.resolved_path and self.resolved_path.is_file():
            try:
                os.startfile(str(self.resolved_path.resolve()))
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Não foi possível abrir o arquivo externamente:\n{e}")

    def wheelEvent(self, event):
        """Permite zoom suave via Ctrl + Scroll da roda do mouse."""
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
        """Limpa visualização e reseta estado."""
        self.close_document()
        self.lbl_image.setPixmap(QPixmap())
        self.lbl_image.setText("📄 Clique em um documento para visualizar a prévia aqui.")
        self.lbl_image.setStyleSheet("color: #888; font-size: 13px; font-style: italic;")
        self.lbl_doc_info.setText("📄 <i>Nenhum documento selecionado</i>")
        self._disable_controls()

    def close_document(self):
        if self.doc:
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None


# =====================================================================
# INTERFACE GRÁFICA PRINCIPAL: SessionsPage
# =====================================================================
class SessionsPage(QWidget):
    """
    Página de Gerenciamento e Visualização por Sessões/Processos.
    Otimizada para visualização natural em janelas e modo tela cheia.
    """
    # Sinal emitido para retomar uma sessão na aba de upload
    resume_session_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SessionsPage")
        
        self.db = DatabaseManager()
        self.masker = DataMasker()
        self.current_session_id: Optional[int] = None
        self._current_extractions: List[Dict[str, Any]] = []
        self._active_doc_id: Optional[int] = None
        self._doc_chip_widgets: Dict[int, CardWidget] = {}
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(25, 20, 25, 20)
        self.main_layout.setSpacing(12)
        
        # 1. Barra Superior com Título, Busca Rápida e Ações
        self._init_top_bar()
        
        # 2. Corpo com QSplitter Horizontal (Redimensionável pelo usuário)
        self._init_splitter_body()
        
        # 3. Configura Atalho Global de Cópia (Ctrl+C)
        self.shortcut_copy = QShortcut(QKeySequence.Copy, self.table_data)
        self.shortcut_copy.activated.connect(self.copy_selected_cell)
        
        # Carrega dados iniciais
        self.load_sessions()

    # --- Inicialização da Barra Superior ---
    def _init_top_bar(self):
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)
        
        self.titleLabel = TitleLabel("Sessões e Documentos", self)
        top_bar.addWidget(self.titleLabel)
        
        top_bar.addStretch(1)
        
        # Barra de Pesquisa de Sessões em tempo real
        self.search_box = SearchLineEdit(self)
        self.search_box.setPlaceholderText("🔍 Buscar sessão por nome...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(260)
        self.search_box.textChanged.connect(self.on_search_changed)
        top_bar.addWidget(self.search_box)
        
        # Botão Nova Sessão
        self.btn_new_session = PrimaryPushButton("➕ Nova Sessão", self)
        self.btn_new_session.clicked.connect(self.create_session_prompt)
        top_bar.addWidget(self.btn_new_session)
        
        # Botão Recarregar
        self.btn_refresh = PushButton("🔄 Atualizar", self)
        self.btn_refresh.clicked.connect(self.reload_all)
        top_bar.addWidget(self.btn_refresh)
        
        self.main_layout.addLayout(top_bar)

    # --- Inicialização do QSplitter Responsivo ---
    def _init_splitter_body(self):
        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        
        # -------------------------------------------------------------
        # PAINEL ESQUERDO: Lista de Sessões / Processos
        # -------------------------------------------------------------
        left_panel = QWidget(self.splitter)
        left_panel.setMinimumWidth(210)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)
        
        left_layout.addWidget(SubtitleLabel("Processos / Sessões:", left_panel))
        
        # Container com CardWidget para harmonizar tema escuro/claro nativamente
        list_card = CardWidget(left_panel)
        list_card_layout = QVBoxLayout(list_card)
        list_card_layout.setContentsMargins(4, 4, 4, 4)
        
        self.session_list = ListWidget(list_card)
        self.session_list.itemClicked.connect(self.on_session_selected)
        list_card_layout.addWidget(self.session_list)
        left_layout.addWidget(list_card)
        
        # Botões de Ação da Sessão Selecionada
        sess_actions = QVBoxLayout()
        sess_actions.setSpacing(6)
        
        self.btn_resume = PrimaryPushButton("📥 Retomar Sessão (Add Docs)", left_panel)
        self.btn_resume.clicked.connect(self.resume_selected_session)
        sess_actions.addWidget(self.btn_resume)
        
        h_sess_btn = QHBoxLayout()
        h_sess_btn.setSpacing(6)
        self.btn_rename = PushButton("✏️ Renomear", left_panel)
        self.btn_rename.clicked.connect(self.rename_selected_session)
        h_sess_btn.addWidget(self.btn_rename)
        
        self.btn_delete_session = PushButton("🗑️ Excluir", left_panel)
        self.btn_delete_session.clicked.connect(self.delete_selected_session)
        h_sess_btn.addWidget(self.btn_delete_session)
        sess_actions.addLayout(h_sess_btn)
        
        left_layout.addLayout(sess_actions)
        
        # -------------------------------------------------------------
        # PAINEL DIREITO: Visão Natural da Sessão (Anexos + Visualizador + Tabela)
        # -------------------------------------------------------------
        right_panel = QWidget(self.splitter)
        right_panel.setMinimumWidth(380)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)
        
        # 1. CARTÃO SUPERIOR: Cabeçalho da Sessão e Fichas/Chips de Documentos Anexados
        # Fixado no topo, compacto e responsivo
        self.session_header_card = CardWidget(right_panel)
        self.session_header_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        header_card_layout = QVBoxLayout(self.session_header_card)
        header_card_layout.setContentsMargins(14, 10, 14, 10)
        header_card_layout.setSpacing(8)
        
        # Linha 1: Título da Sessão, Metadados e Ações Rápidas
        meta_row = QHBoxLayout()
        self.lbl_session_title = SubtitleLabel("Selecione uma Sessão", self.session_header_card)
        meta_row.addWidget(self.lbl_session_title)
        meta_row.addStretch(1)
        
        self.lbl_session_meta = BodyLabel("", self.session_header_card)
        self.lbl_session_meta.setStyleSheet("color: #888;")
        meta_row.addWidget(self.lbl_session_meta)

        self.btn_toggle_preview = PushButton("👁️ Ocultar Prévia", self.session_header_card)
        self.btn_toggle_preview.setToolTip("Alternar exibição do visualizador de documentos")
        self.btn_toggle_preview.clicked.connect(self.toggle_preview_visibility)
        meta_row.addWidget(self.btn_toggle_preview)

        header_card_layout.addLayout(meta_row)
        
        # Linha 2: Área de Fichas/Chips dos Documentos Anexados (com Scroll Horizontal leve)
        self.docs_scroll = QScrollArea(self.session_header_card)
        self.docs_scroll.setWidgetResizable(True)
        self.docs_scroll.setFrameShape(QFrame.NoFrame)
        self.docs_scroll.setFixedHeight(90)
        self.docs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.docs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.docs_container = QWidget()
        self.docs_layout = QHBoxLayout(self.docs_container)
        self.docs_layout.setContentsMargins(0, 0, 0, 0)
        self.docs_layout.setSpacing(10)
        self.docs_scroll.setWidget(self.docs_container)
        header_card_layout.addWidget(self.docs_scroll)
        
        right_layout.addWidget(self.session_header_card)
        
        # 2. QSplitter VERTICAL: Visualizador de Documentos (Topo) + Tabela de Dados (Base)
        # Permite ao usuário arrastar para aumentar a prévia ou a tabela!
        self.right_splitter = QSplitter(Qt.Vertical, right_panel)
        self.right_splitter.setHandleWidth(6)
        self.right_splitter.setChildrenCollapsible(False)

        # 2a. Visualizador de Prévia do Documento
        self.preview_widget = DocumentPreviewWidget(self.right_splitter)
        self.preview_widget.close_requested.connect(self.toggle_preview_visibility)
        self.right_splitter.addWidget(self.preview_widget)

        # 2b. SEÇÃO PRINCIPAL: Tabela Espaçosa de Dados Extraídos e Consolidados
        table_container = QWidget(self.right_splitter)
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 2, 0, 0)
        table_layout.setSpacing(8)

        data_header = QHBoxLayout()
        data_header.addWidget(SubtitleLabel("📊 Dados Extraídos e Consolidados:", table_container))
        data_header.addStretch(1)
        
        self.btn_edit_data = PushButton("✏️ Editar Linha", table_container)
        self.btn_edit_data.clicked.connect(self.edit_selected_data)
        data_header.addWidget(self.btn_edit_data)
        
        self.btn_save_data = PushButton("💾 Salvar Alterações", table_container)
        self.btn_save_data.clicked.connect(self.save_table_changes)
        data_header.addWidget(self.btn_save_data)
        
        self.btn_copy_cell = PushButton("📋 Copiar Célula (Ctrl+C)", table_container)
        self.btn_copy_cell.clicked.connect(self.copy_selected_cell)
        data_header.addWidget(self.btn_copy_cell)
        
        table_layout.addLayout(data_header)
        
        # Tabela de Dados
        self.table_data = TableWidget(table_container)
        self.table_data.setWordWrap(False)
        self.table_data.setEditTriggers(TableWidget.DoubleClicked)
        self.table_data.setSelectionBehavior(TableWidget.SelectItems)
        self.table_data.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_data.customContextMenuRequested.connect(self.show_context_menu)
        self.table_data.itemSelectionChanged.connect(self._on_table_selection_changed)
        
        self.data_columns = [
            "ID Doc", "Arquivo Origem", "Tipo", "Nome Completo", 
            "CPF", "RG", "Data Nasc.", "Nome da Mãe", "Nome do Pai", "Cartório / Registro"
        ]
        self.table_data.setColumnCount(len(self.data_columns))
        self.table_data.setHorizontalHeaderLabels(self.data_columns)
        
        header = self.table_data.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        
        table_layout.addWidget(self.table_data)
        self.right_splitter.addWidget(table_container)

        # Proporções verticais: Prévia (380px) / Tabela (260px)
        self.right_splitter.setSizes([380, 260])
        right_layout.addWidget(self.right_splitter, 1)
        
        # Configuração do Splitter Horizontal Principal
        self.splitter.addWidget(left_panel)
        self.splitter.addWidget(right_panel)
        self.splitter.setSizes([260, 740])
        
        self.main_layout.addWidget(self.splitter)

    # --- Carregamento de Dados ---
    def reload_all(self):
        """Recarrega sessões mantendo a seleção atual se possível."""
        self.load_sessions(target_session_id=self.current_session_id)

    def load_sessions(self, target_session_id: Optional[int] = None):
        """Busca todas as sessões no SQLite e popula a lista lateral."""
        search_query = self.search_box.text().strip()
        sessions = self.db.get_all_sessions(search=search_query)
        
        self.session_list.clear()
        
        if not sessions and not search_query:
            # Garante ao menos uma sessão padrão
            def_id = self.db.get_or_create_default_session()
            sessions = self.db.get_all_sessions()
            
        select_row = 0
        for idx, s in enumerate(sessions):
            sid = s["id"]
            name = s["name"]
            docs = s["doc_count"]
            updated = s.get("updated_at") or s.get("created_at") or ""
            
            # Formatação estrita solicitada: HH/MM - DD/MM/AA
            date_display = format_datetime_br(updated)
            item_text = f"📁 {name}\n🕒 {date_display}  •  📄 {docs} doc(s)"
            
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, sid)
            item.setToolTip(f"{name}\nÚltima Modificação: {date_display}\nDocumentos: {docs}")
            self.session_list.addItem(item)
            
            if target_session_id is not None and sid == target_session_id:
                select_row = idx
                
        if self.session_list.count() > 0:
            self.session_list.setCurrentRow(select_row)
            first_item = self.session_list.item(select_row)
            self.on_session_selected(first_item)
        else:
            self.current_session_id = None
            self.table_data.setRowCount(0)
            self.lbl_session_title.setText("Nenhuma sessão encontrada.")
            self.lbl_session_meta.setText("")
            self._render_document_cards([])

    def on_search_changed(self, text: str):
        """Filtra as sessões conforme o usuário digita."""
        self.load_sessions(target_session_id=self.current_session_id)

    def on_session_selected(self, item: QListWidgetItem):
        """Ao clicar em uma sessão, carrega seus documentos e dados extraídos."""
        if not item:
            return
        session_id = item.data(Qt.UserRole)
        self.current_session_id = session_id
        
        session = self.db.get_session(session_id)
        session_name = session["name"] if session else f"Sessão #{session_id}"
        updated = session.get("updated_at") or session.get("created_at") if session else ""
        date_str = format_datetime_br(updated)
        
        self.lbl_session_title.setText(f"📁 {session_name}")
        self.lbl_session_meta.setText(f"🕒 Atualizado: {date_str}")
        
        self._load_session_content(session_id)

    def _load_session_content(self, session_id: int):
        """Carrega documentos e dados da sessão ativa."""
        self.table_data.blockSignals(True)
        self.table_data.setRowCount(0)
        self._current_extractions.clear()
        
        extractions = self.db.get_session_extractions(session_id)
        self._current_extractions = extractions
        
        # 1. Renderiza os cartões de documentos anexados de forma natural
        self._render_document_cards(extractions)
        
        # 2. Popula a tabela de dados extraídos
        for idx, row in enumerate(extractions):
            raw_json = row.get("extracted_data_json", "{}")
            try:
                payload = json.loads(raw_json)
                dados = payload.get("dados", {})
                token_map = payload.get("token_map", {})
                if token_map:
                    dados = self.masker.demask_dict(dados, token_map)
            except Exception:
                dados = {}
                
            # Extrai pessoa principal
            pessoa = dados.get("pessoa") or {}
            if not pessoa and row["document_type"] == "CASAMENTO" and "conjuges" in dados:
                conjuges = dados.get("conjuges") or []
                pessoa = conjuges[0] if (conjuges and isinstance(conjuges[0], dict)) else {}
            if not pessoa and row["document_type"] == "ESCRITURA" and "compradores" in dados:
                compradores = dados.get("compradores") or []
                pessoa = compradores[0] if (compradores and isinstance(compradores[0], dict)) else {}
            if not pessoa and row["document_type"] == "IPTU" and "contribuinte" in dados:
                pessoa = dados.get("contribuinte") or {}
            if not isinstance(pessoa, dict):
                pessoa = {}
                
            nome = pessoa.get("nome_completo", "-") or "-"
            cpf = pessoa.get("cpf", "-") or "-"
            rg = pessoa.get("rg", "-") or "-"
            nasc = pessoa.get("data_nascimento", "-") or "-"
            
            pais = pessoa.get("nome_pais", []) or []
            mae = pais[1] if len(pais) > 1 else (pais[0] if len(pais) == 1 else "-")
            pai = pais[0] if len(pais) > 1 else "-"
            cartorio = dados.get("cartorio") or dados.get("matricula")
            if not cartorio:
                doc_type_upper = str(row.get("document_type", "")).upper()
                if "TITULO" in doc_type_upper or "ELEITOR" in doc_type_upper:
                    z = dados.get("zona")
                    s = dados.get("secao")
                    u = dados.get("uf")
                    num = dados.get("numero_titulo")
                    if z and s:
                        cartorio = f"Zona {z} / Seção {s} ({u or '-'})"
                    elif num:
                        cartorio = f"Título: {num}"
                elif "CIN" in doc_type_upper:
                    org = dados.get("orgao_emissor") or "Polícia Civil"
                    uf = dados.get("uf_emissor") or ""
                    cartorio = f"CIN ({org}/{uf})" if uf else f"CIN ({org})"
                elif "PASSAPORTE" in doc_type_upper:
                    num = dados.get("numero_passaporte") or "-"
                    pais = dados.get("pais_emissor") or "BRA"
                    cartorio = f"Passaporte {num} ({pais})"
                elif "CONSELHO" in doc_type_upper or "ORDEM" in doc_type_upper:
                    org = dados.get("orgao_conselho") or "Conselho"
                    num = dados.get("numero_registro") or ""
                    uf = dados.get("seccional_uf") or ""
                    cartorio = f"{org}/{uf} {num}" if uf else f"{org} {num}"
                elif "RESERVISTA" in doc_type_upper:
                    ra = dados.get("numero_ra") or dados.get("numero_certificado") or "-"
                    forca = dados.get("forca_armada") or "Defesa"
                    cartorio = f"Reservista {forca} (RA: {ra})"
                elif "SUS" in doc_type_upper:
                    cns = dados.get("numero_cns") or "-"
                    cartorio = f"SUS CNS: {cns}"
                elif "ESTUDANTE" in doc_type_upper or "DNE" in doc_type_upper:
                    inst = dados.get("instituicao_ensino") or "Inst."
                    cur = dados.get("curso") or ""
                    cartorio = f"DNE {inst} ({cur})" if cur else f"DNE {inst}"
                elif "FUNCIONAL" in doc_type_upper or "MILITAR" in doc_type_upper:
                    org = dados.get("orgao_emissor") or "Órgão"
                    reg = dados.get("numero_registro") or dados.get("posto_graduacao_cargo")
                    cartorio = f"{org} ({reg})" if reg else org
                elif "CERTIFICADO" in doc_type_upper or "DIPLOMA" in doc_type_upper:
                    inst = dados.get("instituicao_ensino") or "Inst."
                    cur = dados.get("curso")
                    cartorio = f"{inst} - {cur}" if cur else inst
            cartorio = cartorio or "-"
            
            data_items = [
                str(row["id"]), row["original_name"], row["document_type"],
                nome, cpf, rg, nasc, mae, pai, cartorio
            ]
            
            self.table_data.insertRow(idx)
            for col_idx, val in enumerate(data_items):
                cell = QTableWidgetItem(str(val))
                # ID, Arquivo e Tipo ficam bloqueados contra edição in-place
                if col_idx in [0, 1, 2]:
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.table_data.setItem(idx, col_idx, cell)
                
        # Ajusta larguras de colunas de forma balanceada
        self._apply_smart_column_widths()
        self.table_data.blockSignals(False)

    def _render_document_cards(self, extractions: List[Dict[str, Any]]):
        """Renderiza visualmente os documentos anexados como chips/cartões elegantes."""
        self._doc_chip_widgets.clear()

        # Limpa widgets e espaçadores com segurança máxima
        while self.docs_layout.count() > 0:
            item = self.docs_layout.takeAt(0)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
                
        if not extractions:
            self._active_doc_id = None
            empty_lbl = BodyLabel("Nenhum documento anexado ainda. Clique em '📥 Retomar Sessão' para adicionar arquivos.", self.docs_container)
            empty_lbl.setStyleSheet("color: #888; font-style: italic;")
            self.docs_layout.addWidget(empty_lbl)
            self.docs_layout.addStretch(1)
            self.preview_widget.clear_document()
            return

        for row in extractions:
            doc_id = row["id"]
            card = CardWidget(self.docs_container)
            card.setCursor(Qt.PointingHandCursor)
            card.setToolTip("Clique para visualizar este documento na prévia")

            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(10, 6, 10, 6)
            c_layout.setSpacing(3)
            
            # Linha superior: Tipo e Ações
            top_line = QHBoxLayout()
            doc_type = row.get("document_type", "DOC")
            type_lbl = BodyLabel(f"📄 <b>{doc_type}</b>", card)
            top_line.addWidget(type_lbl)
            top_line.addStretch(1)
            
            btn_ficha = PushButton("👁️", card)
            btn_ficha.setFixedSize(24, 24)
            btn_ficha.setToolTip("Ver Ficha Completa e JSON")
            btn_ficha.clicked.connect(lambda checked=False, r=row: self._open_document_details(r))
            top_line.addWidget(btn_ficha)
            
            btn_del = PushButton("🗑️", card)
            btn_del.setFixedSize(24, 24)
            btn_del.setToolTip("Excluir este documento da sessão")
            btn_del.clicked.connect(lambda checked=False, r=row: self._confirm_delete_document(r))
            top_line.addWidget(btn_del)
            c_layout.addLayout(top_line)
            
            # Linha intermediária: Nome do arquivo encurtado
            orig_name = row.get("original_name", "")
            short_name = orig_name if len(orig_name) <= 24 else orig_name[:21] + "..."
            name_lbl = BodyLabel(short_name, card)
            name_lbl.setToolTip(orig_name)
            c_layout.addWidget(name_lbl)
            
            # Linha inferior: Data/Hora no formato estrito HH/MM - DD/MM/AA
            created_str = format_datetime_br(row.get("created_at"))
            date_lbl = BodyLabel(f"🕒 {created_str}", card)
            date_lbl.setStyleSheet("color: #888; font-size: 11px;")
            c_layout.addWidget(date_lbl)
            
            # Clique no chip seleciona e abre na prévia
            card.mousePressEvent = lambda event, r=row: self.select_document(r)

            self._doc_chip_widgets[doc_id] = card
            self.docs_layout.addWidget(card)
            
        self.docs_layout.addStretch(1)

        # Seleciona automaticamente o primeiro documento da lista ou mantém o ativo
        target_doc = None
        if self._active_doc_id:
            for r in extractions:
                if r["id"] == self._active_doc_id:
                    target_doc = r
                    break
        if not target_doc and extractions:
            target_doc = extractions[0]

        if target_doc:
            self.select_document(target_doc, update_table_selection=True)
        else:
            self.preview_widget.clear_document()

    def select_document(self, row: Dict[str, Any], update_table_selection: bool = True):
        """Seleciona o documento ativo, destaca visualmente o chip e renderiza na prévia."""
        doc_id = row.get("id")
        self._active_doc_id = doc_id

        # Atualiza o estilo visual dos chips destacando o selecionado
        for chip_id, chip_widget in self._doc_chip_widgets.items():
            if chip_id == doc_id:
                chip_widget.setStyleSheet(
                    "CardWidget { border: 2px solid #009faa; background-color: rgba(0, 159, 170, 0.12); border-radius: 8px; }"
                )
            else:
                chip_widget.setStyleSheet("")

        # Carrega o arquivo no visualizador
        self.preview_widget.load_document(
            file_path=row.get("file_path", ""),
            original_name=row.get("original_name", ""),
            doc_type=row.get("document_type", "")
        )

        # Se solicitado, seleciona a linha correspondente na tabela
        if update_table_selection:
            for r_idx in range(self.table_data.rowCount()):
                item = self.table_data.item(r_idx, 0)
                if item and item.text() == str(doc_id):
                    self.table_data.blockSignals(True)
                    self.table_data.selectRow(r_idx)
                    self.table_data.blockSignals(False)
                    break

    def _on_table_selection_changed(self):
        """Sincroniza a seleção da tabela com o visualizador e os chips."""
        current_row = self.table_data.currentRow()
        if current_row < 0:
            return
        item = self.table_data.item(current_row, 0)
        if not item:
            return
        try:
            doc_id = int(item.text())
            if doc_id == self._active_doc_id:
                return
            for r in self._current_extractions:
                if r.get("id") == doc_id:
                    self.select_document(r, update_table_selection=False)
                    break
        except ValueError:
            pass

    def toggle_preview_visibility(self):
        """Oculta ou exibe o visualizador de prévia do documento."""
        is_vis = self.preview_widget.isVisible()
        self.preview_widget.setVisible(not is_vis)
        if is_vis:
            self.btn_toggle_preview.setText("👁️ Mostrar Prévia")
        else:
            self.btn_toggle_preview.setText("👁️ Ocultar Prévia")
            self.right_splitter.setSizes([380, 260])

    def _apply_smart_column_widths(self):
        """Ajusta as larguras para visualização confortável em janela sem estourar limites."""
        self.table_data.resizeColumnsToContents()
        # Garante larguras mínimas confortáveis
        min_widths = [60, 160, 100, 180, 120, 110, 95, 160, 160, 140]
        for col, min_w in enumerate(min_widths):
            if col < self.table_data.columnCount():
                current_w = self.table_data.columnWidth(col)
                self.table_data.setColumnWidth(col, max(current_w, min_w))

    # --- Ações de Sessão ---
    def create_session_prompt(self):
        """Abre diálogo para criar nova sessão com nome padrão no formato HH/MM - DD/MM/AA."""
        default_name = datetime.now().strftime("Sessão %H/%M - %d/%m/%y")
        name, ok = QInputDialog.getText(
            self, "Nova Sessão", "Nome da Sessão / Processo:", text=default_name
        )
        if ok and name.strip():
            new_id = self.db.create_session(name=name.strip())
            self.load_sessions(target_session_id=new_id)
            InfoBar.success("Sessão Criada", f"'{name.strip()}' criada com sucesso!", duration=2500, parent=self)

    def rename_selected_session(self):
        """Renomeia a sessão selecionada."""
        if not self.current_session_id:
            InfoBar.warning("Atenção", "Selecione uma sessão primeiro.", parent=self)
            return
            
        session = self.db.get_session(self.current_session_id)
        current_name = session["name"] if session else ""
        
        new_name, ok = QInputDialog.getText(
            self, "Renomear Sessão", "Novo nome da Sessão:", text=current_name
        )
        if ok and new_name.strip() and new_name.strip() != current_name:
            self.db.rename_session(self.current_session_id, new_name.strip())
            self.load_sessions(target_session_id=self.current_session_id)
            InfoBar.success("Renomeado", "Sessão atualizada com sucesso!", duration=2000, parent=self)

    def delete_selected_session(self):
        """Exclui a sessão inteira e seus documentos."""
        if not self.current_session_id:
            return
            
        session = self.db.get_session(self.current_session_id)
        name = session["name"] if session else f"#{self.current_session_id}"
        
        reply = QMessageBox.question(
            self,
            "Confirmar Exclusão",
            f"Tem certeza que deseja excluir a sessão '{name}' e todos os seus documentos?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._active_doc_id = None
            self.preview_widget.clear_document()
            self.db.delete_session(self.current_session_id)
            self.load_sessions()
            InfoBar.info("Excluído", f"Sessão '{name}' foi removida.", duration=2500, parent=self)

    def resume_selected_session(self):
        """Ativa a sessão e solicita ao App que redirecione para a página de Upload."""
        if not self.current_session_id:
            InfoBar.warning("Atenção", "Selecione uma sessão na lista.", parent=self)
            return
            
        self.resume_session_requested.emit(self.current_session_id)

    # --- Ações de Documento e Dados ---
    def _open_document_details(self, row: Dict[str, Any]):
        """Abre a modal de Ficha Completa a partir do registro do documento."""
        self.select_document(row)
        raw_json = row.get("extracted_data_json", "{}")
        try:
            payload = json.loads(raw_json)
            dados = payload.get("dados", {})
            token_map = payload.get("token_map", {})
            if token_map:
                dados = self.masker.demask_dict(dados, token_map)
        except Exception:
            dados = {}
            
        dialog = DocumentDetailDialog(
            file_name=row["original_name"],
            doc_type=row["document_type"],
            dados=dados,
            parent=self
        )
        dialog.exec()

    def _confirm_delete_document(self, row: Dict[str, Any]):
        """Exclui o documento selecionado do banco e da sessão."""
        doc_id = row["id"]
        doc_name = row["original_name"]
        
        reply = QMessageBox.question(
            self,
            "Confirmar Exclusão de Documento",
            f"Deseja excluir o documento '{doc_name}' da sessão?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if self._active_doc_id == doc_id:
                self._active_doc_id = None
                self.preview_widget.clear_document()
            self.db.delete_extraction(doc_id)
            self._load_session_content(self.current_session_id)
            self.load_sessions(target_session_id=self.current_session_id)
            InfoBar.info("Documento Excluído", f"'{doc_name}' foi removido.", duration=2000, parent=self)

    def edit_selected_data(self):
        """Abre o diálogo explícito para editar todos os campos da linha selecionada."""
        row_idx = self.table_data.currentRow()
        if row_idx < 0 or row_idx >= len(self._current_extractions):
            InfoBar.warning("Atenção", "Clique em uma linha da tabela de dados para editar.", parent=self)
            return
            
        row = self._current_extractions[row_idx]
        doc_id = row["id"]
        raw_json = row.get("extracted_data_json", "{}")
        try:
            payload = json.loads(raw_json)
            dados = payload.get("dados", {})
            token_map = payload.get("token_map", {})
            if token_map:
                dados = self.masker.demask_dict(dados, token_map)
        except Exception:
            dados = {}
            
        dialog = EditDocumentDataDialog(
            doc_id=doc_id,
            file_name=row["original_name"],
            dados=dados,
            parent=self
        )
        if dialog.exec():
            # Salva os dados atualizados no SQLite
            self.db.update_extraction_data(doc_id, dialog.dados)
            self._load_session_content(self.current_session_id)
            InfoBar.success("Dados Salvos", f"Informações do documento #{doc_id} atualizadas!", duration=2500, parent=self)

    def save_table_changes(self):
        """Persiste as edições feitas diretamente nas células da tabela no SQLite."""
        if not self._current_extractions:
            return
            
        changes_count = 0
        for row_idx in range(self.table_data.rowCount()):
            if row_idx >= len(self._current_extractions):
                break
                
            rec = self._current_extractions[row_idx]
            doc_id = rec["id"]
            
            # Lê valores editados na tabela
            nome = self.table_data.item(row_idx, 3).text().strip()
            cpf = self.table_data.item(row_idx, 4).text().strip()
            rg = self.table_data.item(row_idx, 5).text().strip()
            nasc = self.table_data.item(row_idx, 6).text().strip()
            mae = self.table_data.item(row_idx, 7).text().strip()
            pai = self.table_data.item(row_idx, 8).text().strip()
            cartorio = self.table_data.item(row_idx, 9).text().strip()
            
            # Carrega dados existentes
            raw_json = rec.get("extracted_data_json", "{}")
            try:
                payload = json.loads(raw_json)
                dados = payload.get("dados", {})
            except Exception:
                dados = {}
                
            if "pessoa" not in dados or not isinstance(dados["pessoa"], dict):
                dados["pessoa"] = {}
                
            dados["pessoa"]["nome_completo"] = nome
            dados["pessoa"]["cpf"] = cpf
            dados["pessoa"]["rg"] = rg
            dados["pessoa"]["data_nascimento"] = nasc
            
            pais = []
            if pai and pai != "-":
                pais.append(pai)
            if mae and mae != "-":
                pais.append(mae)
            dados["pessoa"]["nome_pais"] = pais
            
            if cartorio and cartorio != "-":
                dados["cartorio"] = cartorio
                
            self.db.update_extraction_data(doc_id, dados)
            changes_count += 1
            
        self._load_session_content(self.current_session_id)
        InfoBar.success("Salvo com Sucesso", f"{changes_count} registro(s) persistido(s) no banco local.", duration=2500, parent=self)

    def copy_selected_cell(self):
        """Copia o conteúdo exato da célula selecionada para a área de transferência."""
        selected_items = self.table_data.selectedItems()
        if selected_items:
            text = selected_items[0].text()
            QApplication.clipboard().setText(text)
            InfoBar.info("Copiado", f"'{text}' copiado para a Área de Transferência.", duration=1800, parent=self)

    def show_context_menu(self, pos):
        """Menu de contexto com o botão direito do mouse na tabela de dados."""
        menu = QMenu(self)
        
        copy_action = menu.addAction("📋 Copiar Valor (Ctrl+C)")
        copy_action.triggered.connect(self.copy_selected_cell)
        
        edit_action = menu.addAction("✏️ Editar Linha Completa")
        edit_action.triggered.connect(self.edit_selected_data)
        
        row_idx = self.table_data.currentRow()
        if 0 <= row_idx < len(self._current_extractions):
            row = self._current_extractions[row_idx]
            details_action = menu.addAction("👁️ Ver Ficha do Documento")
            details_action.triggered.connect(lambda: self._open_document_details(row))
            
            menu.addSeparator()
            delete_action = menu.addAction("🗑️ Excluir Documento")
            delete_action.triggered.connect(lambda: self._confirm_delete_document(row))
        
        menu.exec(self.table_data.viewport().mapToGlobal(pos))
