"""
DocFiller — Interface Gráfica Principal
=======================================
Ponto de entrada da UI usando PySide6 e QFluentWidgets.
"""

import sys
from pathlib import Path

# [LEGACY]: sys.path.append(str(Path(__file__).parent.parent)) (apontava para diretório avô)
# [GEMINI - CORREÇÃO M9]: sys.path aponta diretamente para a raiz do projeto docfiller
sys.path.append(str(Path(__file__).parent))

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel

try:
    from qfluentwidgets import (FluentWindow, NavigationItemPosition, SubtitleLabel, 
                                setTheme, Theme, FluentIcon as FIF)
except ImportError:
    print("Por favor, instale as dependências: pip install PySide6 PySide6-Fluent-Widgets")
    sys.exit(1)

from ui.upload_page_gemini import UploadPage
from ui.settings_page_gemini import SettingsPage
# [LEGACY]: from ui.data_page_gemini import DataPage
# [GEMINI - FASE 6]: Nova SessionsPage que substitui a antiga DataPage
from ui.sessions_page_gemini import SessionsPage
# [Opus - v1.0 Prep]: Aba 'Automação Web' (Selenium) desativada para a v1.0. Retornará em versão futura.
# from ui.automation_page_gemini import AutomationPage

class DocFillerApp(FluentWindow):
    def __init__(self):
        super().__init__()
        
        # Configuração da Janela
        self.setWindowTitle("DocFiller — Automação LGPD")
        self.resize(1180, 780)
        self.setMinimumSize(850, 600)
        
        # Força tema claro ou escuro
        setTheme(Theme.AUTO) 
        
        # Inicializa as Páginas
        self.upload_page = UploadPage(self)
        # [LEGACY]: self.data_page = DataPage(self)
        # [GEMINI - FASE 6]: Substituição pela SessionsPage
        self.sessions_page = SessionsPage(self)
        # [Opus - v1.0 Prep]: self.automation_page = AutomationPage(self)
        self.settings_page = SettingsPage(self)
        
        # [GEMINI - CORREÇÃO H3 & FASE 6]: Conexão reativa:
        # Quando um documento termina de ser extraído, recarrega a tela de sessões automaticamente.
        self.upload_page.document_processed.connect(lambda row_id: self.sessions_page.reload_all())
        
        # [GEMINI - FASE 6]: Conexão do Retomar Sessão:
        # Ao clicar em "Retomar Sessão" na lista, define a sessão ativa no Upload e navega até lá
        self.sessions_page.resume_session_requested.connect(self.resume_session)
        
        self.init_navigation()
        self.init_shortcuts()
        
    def init_navigation(self):
        # Adiciona itens na barra lateral
        self.addSubInterface(self.upload_page, FIF.FOLDER_ADD, 'Upload de Documentos')
        self.addSubInterface(self.sessions_page, FIF.DOCUMENT, 'Sessões e Documentos')
        # [Opus - v1.0 Prep]: self.addSubInterface(self.automation_page, FIF.PLAY, 'Automação Web')
        
        # Separador para configurações no rodapé
        self.addSubInterface(
            self.settings_page, 
            FIF.SETTING, 
            'Configurações', 
            NavigationItemPosition.BOTTOM
        )

    def init_shortcuts(self):
        """[GEMINI - FASE 6]: Atalhos de teclado globais."""
        # Ctrl + O: Abre seletor de arquivos no Upload
        self.shortcut_upload = QShortcut(QKeySequence("Ctrl+O"), self)
        self.shortcut_upload.activated.connect(self.action_open_upload)
        
        # Ctrl + F: Foca na busca da aba de sessões
        self.shortcut_find = QShortcut(QKeySequence("Ctrl+F"), self)
        self.shortcut_find.activated.connect(self.action_find_session)
        
        # F5 ou Ctrl + R: Recarrega dados das sessões
        self.shortcut_f5 = QShortcut(QKeySequence("F5"), self)
        self.shortcut_f5.activated.connect(self.action_refresh)
        self.shortcut_ctrl_r = QShortcut(QKeySequence("Ctrl+R"), self)
        self.shortcut_ctrl_r.activated.connect(self.action_refresh)

    def action_open_upload(self):
        """Atalho Ctrl+O: Vai para Upload e abre a caixa de diálogo."""
        self.switchTo(self.upload_page)
        self.upload_page.select_files_manually()

    def action_find_session(self):
        """Atalho Ctrl+F: Vai para Sessões e foca na barra de pesquisa."""
        self.switchTo(self.sessions_page)
        self.sessions_page.search_box.setFocus()
        self.sessions_page.search_box.selectAll()

    def action_refresh(self):
        """Atalho F5/Ctrl+R: Recarrega as sessões e tabelas."""
        self.sessions_page.reload_all()
        self.upload_page.reload_sessions()

    def resume_session(self, session_id: int):
        """
        [GEMINI - FASE 6]: Retoma uma sessão selecionada:
        Define como ativa na página de upload e muda a visualização para a aba de Upload.
        """
        self.upload_page.set_active_session(session_id)
        self.switchTo(self.upload_page)


if __name__ == '__main__':
    try:
        # Habilita suporte a DPI alto no Windows
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        
        app = QApplication(sys.argv)
        
        w = DocFillerApp()
        w.show()
        
        # Força o Windows a trazer a tela para frente
        w.raise_()
        w.activateWindow()
        
        print("=> A Janela foi instruída a abrir. Verifique a barra de tarefas!")
        sys.exit(app.exec())
        
    except Exception as e:
        print("\n[ERRO CRÍTICO] A interface falhou ao carregar:")
        import traceback
        traceback.print_exc()
        input("\nPressione ENTER para fechar...")
