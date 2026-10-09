"""
DocFiller — Estado da Aplicação (Com Persistência Local de Preferências)
========================================================================
Armazena variáveis globais de configuração e preferências.
[GEMINI - PERSISTÊNCIA]: Configurações do ambiente (como o caminho do Tesseract,
modelo padrão e modo headless) agora são persistidas em data/settings.json,
mantendo o que o usuário configurar entre reinicializações do app.
"""

import json
from pathlib import Path

# [Opus - v1.0 Prep]: Importa caminhos dinâmicos de core.paths
from core.paths import SETTINGS_FILE, get_default_tesseract_path


class AppState:
    # [Opus - v1.0 Prep]: Removed hardcoded API key; now persisted in settings.json
    GEMINI_API_KEY: str = ""
    
    # [Opus - v1.0 Prep]: Caminho padrão detectado dinamicamente (embutido ou UB-Mannheim)
    TESSERACT_PATH: str = get_default_tesseract_path()
    
    # Configuração do Modelo Gemini (gemini-3.8-flash definido como padrão para máxima precisão)
    GEMINI_MODEL: str = "gemini-3.8-flash"
    
    # Configuração de Automação
    HEADLESS_MODE: bool = False

    @classmethod
    def load_settings(cls):
        """[GEMINI]: Carrega preferências salvas no disco (ex: caminho do Tesseract)."""
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "tesseract_path" in data and data["tesseract_path"]:
                        cls.TESSERACT_PATH = str(data["tesseract_path"]).strip()
                    if "gemini_model" in data and data["gemini_model"]:
                        cls.GEMINI_MODEL = str(data["gemini_model"]).strip()
                    if "headless_mode" in data:
                        cls.HEADLESS_MODE = bool(data["headless_mode"])
                    # [Opus - v1.0 Prep]: Load persisted API key from settings.json
                    if "gemini_api_key" in data and data["gemini_api_key"]:
                        cls.GEMINI_API_KEY = str(data["gemini_api_key"]).strip()
        except Exception as e:
            print(f"[AVISO] Falha ao carregar settings.json: {e}")

    @classmethod
    def save_settings(cls):
        """[GEMINI]: Salva preferências persistentes no disco (data/settings.json)."""
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "gemini_api_key": cls.GEMINI_API_KEY,  # [Opus - v1.0 Prep]: Persist API key to disk
                "tesseract_path": cls.TESSERACT_PATH,
                "gemini_model": cls.GEMINI_MODEL,
                "headless_mode": cls.HEADLESS_MODE,
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ERRO] Falha ao salvar settings.json: {e}")

    @classmethod
    def set_tesseract_path(cls, path: str):
        """Atualiza o caminho e salva imediatamente no disco."""
        cls.TESSERACT_PATH = path.strip()
        cls.save_settings()

    # [Opus - v1.0 Prep]: New method to persist API key changes immediately
    @classmethod
    def set_api_key(cls, key: str):
        """Atualiza a chave da API e salva imediatamente no disco."""
        cls.GEMINI_API_KEY = key.strip()
        cls.save_settings()


# [GEMINI]: Carrega automaticamente as preferências salvas ao importar o módulo
AppState.load_settings()
