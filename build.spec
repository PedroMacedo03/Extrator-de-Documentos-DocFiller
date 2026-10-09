# -*- mode: python ; coding: utf-8 -*-
"""
DocFiller — PyInstaller Build Specification (v1.0.0)
===================================================
# [Opus - v1.0 Prep]: Especificação de empacotamento standalone Windows (.exe)
# no modo --onedir, incluindo recursos de QFluentWidgets, PyMuPDF, Certifi
# e o Tesseract OCR portátil embutido.
"""

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

block_cipher = None

# Diretório raiz do projeto
BASE_DIR = Path.cwd()

datas = []
binaries = []
hiddenimports = []

# 1. QFluentWidgets (estilos QSS, ícones SVG, fontes Fluent)
datas += collect_data_files('qfluentwidgets')
hiddenimports += collect_submodules('qfluentwidgets')

# 2. PyMuPDF (fitz)
datas += collect_data_files('pymupdf')
binaries += collect_dynamic_libs('pymupdf')
hiddenimports += ['fitz', 'pymupdf', 'fitz._fitz']

# 3. Certificados SSL (Certifi) para conexões seguras com Google Gemini API
try:
    import certifi
    datas += [(certifi.where(), 'certifi')]
except ImportError:
    pass

# 4. google-genai e Pydantic
hiddenimports += collect_submodules('google.genai')
hiddenimports += collect_submodules('pydantic')
hiddenimports += collect_submodules('pydantic_core')

# 5. Dependências adicionais
hiddenimports += ['PIL', 'PIL.Image', 'pytesseract', 'yaml', 'sqlite3']

# 6. Inclui arquivos de configuração (exemplo YAML)
config_dir = BASE_DIR / "config"
if config_dir.exists():
    datas += [('config', 'config')]

# 7. Inclui o Tesseract OCR portátil embutido (bin/tesseract -> tesseract)
tesseract_bin_dir = BASE_DIR / "bin" / "tesseract"
if tesseract_bin_dir.exists():
    datas += [('bin/tesseract', 'tesseract')]

a = Analysis(
    ['main.py'],
    pathex=[str(BASE_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 
        'matplotlib', 
        'scipy', 
        'PyQt5', 
        'PyQt6', 
        'PySide2',
        'pygame',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DocFiller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DocFiller',
)
