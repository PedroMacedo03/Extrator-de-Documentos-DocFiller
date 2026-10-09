"""
DocFiller — Módulo Automation
=============================
[GEMINI - CORREÇÃO C4]: Pacote Python explícito para importações seguras do motor Selenium.
"""

from .browser_gemini import BrowserManager
from .field_handlers_gemini import FieldHandlers
from .form_filler_gemini import FormFiller
from .session_manager_gemini import SessionManager

__all__ = [
    "BrowserManager",
    "FieldHandlers",
    "FormFiller",
    "SessionManager",
]
