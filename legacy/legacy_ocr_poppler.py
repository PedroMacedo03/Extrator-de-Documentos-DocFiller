"""
DocFiller — OCR Híbrido Local (VERSÃO LEGACY)
=============================================

NOTA DE ARQUIVAMENTO:
Esta versão foi substituída pois dependia da biblioteca externa `pdf2image`,
que por sua vez exigia a instalação dos binários C++ do `poppler` no Windows.
Isso causava o erro "Unable to get page count. Is poppler installed and in PATH?".

A versão atualizada (`ocr_local_gemini.py`) faz a mesma renderização utilizando 
os recursos nativos da biblioteca `pymupdf` (fitz), que já estava sendo utilizada,
eliminando a necessidade do Poppler.

Este arquivo é mantido apenas para fins de histórico e análise de dependências antigas.
"""

import os
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter

# Imports opcionais
try:
    import pymupdf as fitz  # PyMuPDF (Atualizado para evitar depreciação)
except ImportError:
    fitz = None

try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None

try:
    import pytesseract
except ImportError:
    pytesseract = None


class HybridOCR:
    """
    Motor de extração de texto híbrido (Texto Nativo + OCR Offline).
    """

    def __init__(
        self, 
        tesseract_cmd: str | None = None,
        poppler_path: str | None = None,
        lang: str = "por"
    ):
        self.lang = lang
        self.poppler_path = poppler_path

        if tesseract_cmd and pytesseract is not None:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def extract_text(self, file_path: str | Path) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {path}")

        ext = path.suffix.lower()

        if ext == ".pdf":
            return self._process_pdf(path)
        elif ext in [".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
            return self._process_image(path)
        else:
            raise ValueError(f"Formato de arquivo não suportado: {ext}")

    def _process_pdf(self, path: Path) -> str:
        """Processa um arquivo PDF (tenta nativo, fallback para OCR)."""
        if fitz is None:
            raise ImportError("PyMuPDF (fitz) não está instalado. Execute: pip install PyMuPDF")

        doc = fitz.open(path)
        full_text = []
        num_pages = len(doc)
        
        for page in doc:
            text = page.get_text("text")
            full_text.append(text)
            
        doc.close()
        
        combined_text = "\n".join(full_text).strip()
        
        if len(combined_text) < (num_pages * 50):
            print(f"[OCR] PDF escaneado detectado ({path.name}). Iniciando OCR via Tesseract...")
            return self._ocr_pdf(path)
            
        print(f"[OCR] PDF com texto nativo detectado ({path.name}). Extração limpa realizada.")
        return combined_text

    def _ocr_pdf(self, path: Path) -> str:
        """Converte PDF para imagens usando pdf2image/poppler e aplica Tesseract."""
        if convert_from_path is None:
            raise ImportError("pdf2image não instalado. Execute: pip install pdf2image")
        if pytesseract is None:
            raise ImportError("pytesseract não instalado. Execute: pip install pytesseract")

        kwargs = {}
        if self.poppler_path:
            kwargs["poppler_path"] = self.poppler_path

        # Converte páginas em imagens (300 DPI para boa qualidade de OCR) - REQUER POPPLER NO WINDOWS
        pages = convert_from_path(path, dpi=300, **kwargs)
        
        full_text = []
        for i, page_img in enumerate(pages):
            processed_img = self._preprocess_image(page_img)
            text = pytesseract.image_to_string(processed_img, lang=self.lang)
            full_text.append(f"--- PÁGINA {i+1} ---\n{text}")

        return "\n".join(full_text)

    def _process_image(self, path: Path) -> str:
        """Processa uma imagem direta com Tesseract."""
        if pytesseract is None:
            raise ImportError("pytesseract não instalado. Execute: pip install pytesseract")

        img = Image.open(path)
        processed_img = self._preprocess_image(img)
        text = pytesseract.image_to_string(processed_img, lang=self.lang)
        
        print(f"[OCR] Imagem processada com sucesso ({path.name}).")
        return text

    def _preprocess_image(self, img: Image.Image) -> Image.Image:
        """Filtros básicos (Grayscale, Contraste, Sharpen) para o Tesseract."""
        img = img.convert("L")
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        img = img.filter(ImageFilter.SHARPEN)
        return img
