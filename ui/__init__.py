"""
DocFiller — Módulo UI
=====================
[GEMINI - CORREÇÃO C4]: Pacote Python explícito para telas e estado da aplicação.
[Opus - v1.0 Prep]: Removido DataPage (movido para legacy/) e AutomationPage (desativada na v1.0).
                    Adicionado SessionsPage como substituta de DataPage.
"""

from .state_gemini import AppState
from .upload_page_gemini import UploadPage
from .sessions_page_gemini import SessionsPage
from .settings_page_gemini import SettingsPage

__all__ = [
    "AppState",
    "UploadPage",
    "SessionsPage",
    "SettingsPage",
]
