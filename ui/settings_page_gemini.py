"""
DocFiller — Página de Configurações
===================================
Página para o usuário preencher chaves de API (sempre que iniciar o app,
por segurança) e ajustar configurações locais (Caminho do Tesseract).
"""

from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSpacerItem, QSizePolicy

try:
    from qfluentwidgets import (TitleLabel, SubtitleLabel, BodyLabel, 
                                PasswordLineEdit, LineEdit,  # [Opus - v1.0 Prep]: Removed SwitchButton (Selenium disabled)
                                PrimaryPushButton, PushButton, InfoBar, InfoBarPosition)
    from .state_gemini import AppState
except ImportError:
    pass

class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsPage")
        
        # Layout Principal
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(40, 40, 40, 40)
        self.vBoxLayout.setSpacing(20)
        
        # Título
        self.titleLabel = TitleLabel("Configurações do DocFiller", self)
        self.vBoxLayout.addWidget(self.titleLabel)
        
        # --- SEÇÃO GEMINI API ---
        self.apiLabel = SubtitleLabel("Gemini API (Google)", self)
        self.vBoxLayout.addWidget(self.apiLabel)
        
        # [Opus - v1.0 Prep]: Updated label — key is now persisted to settings.json
        self.apiDescLabel = BodyLabel("Insira sua chave da API. A chave será gravada localmente de forma segura.", self)
        self.vBoxLayout.addWidget(self.apiDescLabel)
        
        # Campo de Senha para API Key
        self.apiInput = PasswordLineEdit(self)
        self.apiInput.setPlaceholderText("Cole sua Gemini API Key aqui...")
        self.apiInput.setClearButtonEnabled(True)
        # [LEGACY]: Campo iniciava vazio, forçando colar a cada teste
        # [GEMINI - CORREÇÃO H7]: Preenche com a chave salva em memória se houver
        if AppState.GEMINI_API_KEY:
            self.apiInput.setText(AppState.GEMINI_API_KEY)
        self.apiInput.textChanged.connect(self.update_api_key)
        self.vBoxLayout.addWidget(self.apiInput)
        
        # Botão para gerar a Chave
        self.btnGetApiKey = PushButton("Pegar minha API Key no Google AI Studio", self)
        self.btnGetApiKey.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://aistudio.google.com/app/apikey")))
        self.vBoxLayout.addWidget(self.btnGetApiKey)
        
        # [Opus - v1.0 Prep]: Cartão informativo de Privacidade & LGPD
        from qfluentwidgets import SimpleCardWidget
        self.lgpdCard = SimpleCardWidget(self)
        lgpdLayout = QVBoxLayout(self.lgpdCard)
        lgpdLayout.setContentsMargins(16, 12, 16, 12)
        lgpdLayout.setSpacing(6)
        lgpdTitle = SubtitleLabel("🛡️ Privacidade e Conformidade LGPD", self.lgpdCard)
        lgpdText = BodyLabel(
            "O DocFiller executa anonimização local estrita antes de qualquer envio à nuvem. "
            "Seus dados pessoais (nomes, CPFs, RGs, registros) são previamente mascarados por tokens "
            "sintéticos (ex: [NOME_001], [CPF_001]). O modelo Gemini recebe apenas dados anonimizados, "
            "e a restauração dos dados reais é realizada exclusivamente na memória local do seu computador.",
            self.lgpdCard
        )
        lgpdText.setWordWrap(True)
        lgpdLayout.addWidget(lgpdTitle)
        lgpdLayout.addWidget(lgpdText)
        self.vBoxLayout.addWidget(self.lgpdCard)
        
        # Seletor de Modelo
        self.vBoxLayout.addSpacing(10)
        self.modelLabel = BodyLabel("Modelo de IA (Gemini):", self)
        self.vBoxLayout.addWidget(self.modelLabel)
        
        from qfluentwidgets import ComboBox
        self.modelCombo = ComboBox(self)
        self.modelCombo.addItems([
            "gemini-3.8-flash (Recomendado — Alta Precisão & Inteligência)",
            "gemini-3.5-flash (Intermediário)",
            "gemini-3.5-flash-lite (Econômico — Ultra Rápido)",
            "gemini-2.5-flash (Estável)"
        ])
        # Define gemini-3.8-flash como o padrão selecionado
        self.modelCombo.setCurrentIndex(0)
        self.modelCombo.currentTextChanged.connect(self.update_model)
        self.vBoxLayout.addWidget(self.modelCombo)
        
        # --- SEÇÃO OCR ---
        self.vBoxLayout.addSpacing(20)
        self.ocrLabel = SubtitleLabel("Caminho do Tesseract OCR", self)
        self.vBoxLayout.addWidget(self.ocrLabel)
        
        self.ocrDescLabel = BodyLabel("Caminho onde o tesseract.exe está instalado no seu Windows. (Fica gravado permanentemente)", self)
        self.vBoxLayout.addWidget(self.ocrDescLabel)
        
        # [GEMINI - PERSISTÊNCIA]: Campo com botão de procurar arquivo
        ocrLayout = QHBoxLayout()
        self.ocrInput = LineEdit(self)
        self.ocrInput.setText(AppState.TESSERACT_PATH)
        self.ocrInput.textChanged.connect(self.update_ocr_path)
        ocrLayout.addWidget(self.ocrInput)
        
        self.btnBrowseOcr = PushButton("📁 Procurar .exe", self)
        self.btnBrowseOcr.clicked.connect(self.browse_tesseract)
        ocrLayout.addWidget(self.btnBrowseOcr)
        self.vBoxLayout.addLayout(ocrLayout)
        
        # [Opus - v1.0 Prep]: Selenium automation section removed for v1.0
        # --- SEÇÃO AUTOMAÇÃO WEB (DESABILITADA) ---
        self.vBoxLayout.addSpacing(20)
        self.webLabel = SubtitleLabel("Automação Web (Selenium)", self)
        self.vBoxLayout.addWidget(self.webLabel)
        
        self.webNoteLabel = BodyLabel(
            "⚠️ A automação via Selenium está temporariamente desabilitada. "
            "Este recurso retornará em uma versão futura.", self
        )
        self.webNoteLabel.setWordWrap(True)
        self.vBoxLayout.addWidget(self.webNoteLabel)
        
        # Espaçador final para empurrar tudo para cima
        try:
            policy_min = QSizePolicy.Policy.Minimum
            policy_exp = QSizePolicy.Policy.Expanding
        except AttributeError:
            policy_min = QSizePolicy.Minimum
            policy_exp = QSizePolicy.Expanding
        self.vBoxLayout.addSpacerItem(QSpacerItem(20, 40, policy_min, policy_exp))

    def update_api_key(self, text):
        # [Opus - v1.0 Prep]: Now persists key to settings.json via set_api_key
        AppState.set_api_key(text.strip())

    def update_model(self, text):
        # Pega o nome técnico antes do primeiro espaço
        model_name = text.split(" ")[0].strip()
        AppState.GEMINI_MODEL = model_name
        AppState.save_settings()
        
    def update_ocr_path(self, text):
        # [GEMINI - PERSISTÊNCIA]: Salva no disco imediatamente toda vez que o usuário alterar
        AppState.set_tesseract_path(text)

    def browse_tesseract(self):
        """[GEMINI]: Abre a janela nativa do Windows para escolher o executável do Tesseract."""
        from PySide6.QtWidgets import QFileDialog
        caminho_inicial = str(Path(AppState.TESSERACT_PATH).parent) if AppState.TESSERACT_PATH else r"C:\Program Files"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Localizar Executável do Tesseract (tesseract.exe)",
            caminho_inicial,
            "Executáveis (*.exe);;Todos os Arquivos (*.*)"
        )
        if file_path:
            # Converte barras para padrão Windows
            file_path_clean = str(Path(file_path))
            self.ocrInput.setText(file_path_clean)
            AppState.set_tesseract_path(file_path_clean)
            InfoBar.success(
                title="Caminho Salvo Permanentemente",
                content=f"O Tesseract foi configurado em: {file_path_clean}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500,
                parent=self
            )
