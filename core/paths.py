"""
DocFiller — Resolução Centralizada de Caminhos
==============================================
# [Opus - v1.0 Prep]: Centraliza todos os caminhos de dados, runtime e executáveis
# com suporte a execução standalone (Python normal) e empacotada (PyInstaller sys.frozen).
"""

import os
import sys
import shutil
from pathlib import Path

# Detecta se estamos rodando como executável congelado (PyInstaller) ou script Python
if getattr(sys, "frozen", False):
    # Executável gerado: sys.executable é dist/DocFiller/DocFiller.exe
    APP_DIR = Path(sys.executable).resolve().parent
    # Diretório de dados temporários extraídos pelo PyInstaller se houver (_MEIPASS)
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    # Código-fonte Python: raiz do projeto (pai de core/)
    APP_DIR = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = APP_DIR

# Diretório base de dados (persistência local)
# Se APP_DIR / "data" for gravável (ou for execução local/portátil), usa ele.
DATA_DIR = APP_DIR / "data"
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Testa se temos permissão de escrita
    test_file = DATA_DIR / ".write_test"
    test_file.touch()
    test_file.unlink()
except (PermissionError, OSError):
    # Se não puder escrever no APP_DIR (ex: C:\Program Files com restrição estrita),
    # usa %LOCALAPPDATA%\DocFiller\data
    local_app = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DocFiller" / "data"
    local_app.mkdir(parents=True, exist_ok=True)
    DATA_DIR = local_app

DOCUMENTS_DIR = DATA_DIR / "documents"
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_FILE = DATA_DIR / "docfiller.db"
SETTINGS_FILE = DATA_DIR / "settings.json"
CONFIG_DIR = APP_DIR / "config"

def get_bundled_tesseract_dir() -> Path:
    """Retorna o diretório onde o Tesseract portátil está localizado."""
    # 1. Pasta 'tesseract' ao lado do executável ou em _internal (PyInstaller 6.x)
    tess_internal = APP_DIR / "_internal" / "tesseract"
    if tess_internal.exists():
        return tess_internal
    tess_app = APP_DIR / "tesseract"
    if tess_app.exists():
        return tess_app
    # 2. Pasta temporária do PyInstaller se houver (_MEIPASS)
    tess_bundle = BUNDLE_DIR / "tesseract"
    if tess_bundle.exists():
        return tess_bundle
    # 3. Pasta 'bin/tesseract' no ambiente de desenvolvimento
    tess_bin = APP_DIR / "bin" / "tesseract"
    if tess_bin.exists():
        return tess_bin
    return tess_app

def get_default_tesseract_path() -> str:
    """
    Detecta automaticamente o executável do Tesseract seguindo a ordem:
    1. Tesseract embutido na pasta do aplicativo (distribuição portátil)
    2. C:\\Program Files\\Tesseract-OCR\\tesseract.exe (instalador padrão UB-Mannheim)
    3. C:\\Program Files\\tesseract.exe
    4. Comando no PATH do sistema operacional
    """
    bundled_exe = get_bundled_tesseract_dir() / "tesseract.exe"
    if bundled_exe.exists():
        return str(bundled_exe)

    std_ub = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if std_ub.exists():
        return str(std_ub)

    std_root = Path(r"C:\Program Files\tesseract.exe")
    if std_root.exists():
        return str(std_root)

    path_cmd = shutil.which("tesseract")
    if path_cmd:
        return path_cmd

    return str(std_ub)

def get_tessdata_prefix(tesseract_exe_path: str = "") -> str:
    """Retorna o caminho para a pasta tessdata correspondente ao tesseract."""
    if not tesseract_exe_path:
        tesseract_exe_path = get_default_tesseract_path()
    p = Path(tesseract_exe_path)
    tessdata = p.parent / "tessdata"
    if tessdata.exists():
        return str(tessdata)
    return ""
