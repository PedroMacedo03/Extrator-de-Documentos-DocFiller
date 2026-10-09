"""
DocFiller — Ponto de Entrada Principal (Main)
=============================================
# [Opus - v1.0 Prep]: Entry point padronizado para execução direta e empacotamento com PyInstaller.
"""

import sys
import os
from pathlib import Path

# Garante que o diretório da aplicação esteja no sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Configura caminhos e variáveis de ambiente
from core.paths import APP_DIR, DATA_DIR, get_default_tesseract_path, get_tessdata_prefix

# Configura Tesseract se disponível
tess_cmd = get_default_tesseract_path()
if os.path.exists(tess_cmd):
    tessdata = get_tessdata_prefix(tess_cmd)
    if tessdata:
        os.environ["TESSDATA_PREFIX"] = tessdata

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from app_gemini import DocFillerApp


def main():
    try:
        # Habilita suporte a DPI alto no Windows
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        app = QApplication(sys.argv)
        app.setApplicationName("DocFiller")
        app.setOrganizationName("DocFiller")

        window = DocFillerApp()
        window.show()

        # Força o Windows a trazer a janela para frente
        window.raise_()
        window.activateWindow()

        sys.exit(app.exec())

    except Exception as e:
        print("\n[ERRO CRÍTICO] A interface falhou ao carregar:")
        import traceback
        traceback.print_exc()
        if not getattr(sys, "frozen", False):
            input("\nPressione ENTER para fechar...")


if __name__ == "__main__":
    main()
