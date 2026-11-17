"""
Teste de verificação do empacotamento e resolução do Tesseract OCR integrado (v1.1.1).
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.paths import (
    get_bundled_tesseract_dir,
    get_default_tesseract_path,
    is_bundled_tesseract,
    get_tessdata_prefix,
)
from core.ocr_local_gemini import HybridOCR
from ui.state_gemini import AppState
import pytesseract


def test_bundled_tesseract_detection():
    # 1. Verifica se o executável do Tesseract integrado é encontrado no projeto
    default_path = get_default_tesseract_path()
    assert os.path.isfile(default_path), f"Tesseract executável não encontrado: {default_path}"
    assert is_bundled_tesseract(default_path) is True

    # 2. Verifica se a pasta tessdata do motor integrado existe e contém os idiomas necessários
    tessdata = get_tessdata_prefix(default_path)
    assert os.path.isdir(tessdata), f"Pasta tessdata não encontrada: {tessdata}"
    por_data = Path(tessdata) / "por.traineddata"
    assert por_data.is_file(), f"Modelo de português 'por.traineddata' não encontrado em {tessdata}"

    # 3. Verifica inicialização do HybridOCR com o motor integrado
    ocr = HybridOCR()
    assert pytesseract.pytesseract.tesseract_cmd == default_path
    version = pytesseract.get_tesseract_version()
    assert version is not None, "Falha ao obter versão do Tesseract integrado"
    langs = pytesseract.get_languages()
    assert "por" in langs, "Idioma 'por' não está disponível no Tesseract integrado"

    # 4. Verifica resiliência do HybridOCR a caminhos inexistentes (fallback automático para o integrado)
    ocr_invalid = HybridOCR(tesseract_cmd=r"C:\Caminho\Inexistente\tesseract.exe")
    assert pytesseract.pytesseract.tesseract_cmd == default_path, (
        "HybridOCR deveria ter feito fallback automático para o Tesseract integrado"
    )

    # 5. Verifica restauração no AppState
    AppState.set_tesseract_path(r"C:\Custom\Path\tesseract.exe")
    restored = AppState.restore_bundled_tesseract()
    assert restored == default_path
    assert AppState.TESSERACT_PATH == default_path

    print("[OK] Testes de empacotamento e resolução do Tesseract integrado passaram com sucesso!")


if __name__ == "__main__":
    test_bundled_tesseract_detection()
