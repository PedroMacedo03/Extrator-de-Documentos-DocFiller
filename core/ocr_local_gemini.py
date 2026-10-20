"""
DocFiller — OCR Híbrido Local
=============================

Implementa uma abordagem híbrida de extração de texto para alimentar o mascarador LGPD:

1. PDFs com camada de texto (nativos): Extração direta super rápida usando PyMuPDF.
2. Imagens (PNG, JPG) e PDFs escaneados: Extração via Tesseract OCR (100% offline).
"""

import os
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter

try:
    import pymupdf as fitz  # PyMuPDF
except ImportError:
    fitz = None

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
        """
        Inicializa o extrator híbrido.
        No Windows, tesseract_cmd geralmente precisa ser fornecido se não estiver no PATH.
        (A dependência do poppler foi removida para facilitar no Windows!)
        """
        self.lang = lang

        # [Opus - v1.0 Prep]: Resolução dinâmica do executável e diretório tessdata
        from core.paths import get_default_tesseract_path, get_tessdata_prefix
        chosen_cmd = tesseract_cmd or get_default_tesseract_path()

        if chosen_cmd and pytesseract is not None:
            if os.path.exists(chosen_cmd):
                pytesseract.pytesseract.tesseract_cmd = chosen_cmd
                tessdata_dir = get_tessdata_prefix(chosen_cmd)
                if tessdata_dir:
                    os.environ["TESSDATA_PREFIX"] = tessdata_dir

    def extract_text(self, file_path: str | Path) -> str:
        """
        Ponto de entrada principal. Determina o tipo de arquivo e aplica
        a melhor estratégia de extração.
        """
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

        # 1. Tenta extração de texto nativa primeiro
        doc = fitz.open(path)
        full_text = []
        num_pages = len(doc)  # <-- Pegamos o número de páginas antes de fechar!
        
        for page in doc:
            # Extrai blocos de texto mantendo um pouco da estrutura
            text = page.get_text("text")
            full_text.append(text)
            
        doc.close()
        
        combined_text = "\n".join(full_text).strip()
        
        # Heurística: Se a quantidade de texto for muito pequena em relação
        # ao número de páginas, provavelmente é um PDF escaneado (imagens dentro do PDF).
        # Em média, uma página com dados tem pelo menos 50-100 caracteres.
        if len(combined_text) < (num_pages * 50):
            print(f"[OCR] PDF escaneado detectado ({path.name}). Iniciando OCR via Tesseract...")
            return self._ocr_pdf(path)
            
        print(f"[OCR] PDF com texto nativo detectado ({path.name}). Extração limpa realizada.")
        return combined_text

    def _ocr_pdf(self, path: Path) -> str:
        """Converte PDF para imagens e aplica Tesseract (sem precisar de Poppler!)."""
        if pytesseract is None:
            raise ImportError("pytesseract não instalado. Execute: pip install pytesseract")

        doc = fitz.open(path)
        full_text = []
        
        for i, page in enumerate(doc):
            # Usamos o próprio PyMuPDF para renderizar a página como imagem (zoom para 300 DPI aprox)
            zoom = 300 / 72  # 72 é o DPI padrão do PDF
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            
            # Converte os pixels para uma imagem PIL legível pelo Tesseract
            mode = "RGBA" if pix.alpha else "RGB"
            img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
            
            # Pré-processamento básico
            processed_img = self._preprocess_image(img)
            
            # Extração de texto
            # [LEGACY]: text = pytesseract.image_to_string(processed_img, lang=self.lang)
            # [GEMINI - MULTI-PASS]: Executa PSM padrão e PSM 6 (bloco uniforme). Em documentos como RG,
            # os campos em caixas adjacentes (ex: RG e Data de Expedição) são ignorados pelo PSM 3 mas
            # lidos com máxima fidelidade pelo PSM 6.
            # [Opus - RG/CNH Multi-Layout OCR]: Inclui 3ª passada sem filtro agressivo (img original em PSM 6)
            # para evitar que fundos de segurança (guilloche de CNH e RGs coloridos) destruam dígitos de CPF.
            try:
                combined_page = self._run_multipass_ocr(img, processed_img)
                full_text.append(f"--- PÁGINA {i+1} ---\n{combined_page}")
            except pytesseract.TesseractNotFoundError:
                doc.close()
                raise FileNotFoundError("O executável do Tesseract OCR não foi encontrado no Windows! Verifique as configurações.")
            except Exception as e:
                doc.close()
                raise RuntimeError(f"Erro no Tesseract: {str(e)}")

        doc.close()
        return "\n".join(full_text)

    def _process_image(self, path: Path) -> str:
        """Processa uma imagem direta com Tesseract."""
        if pytesseract is None:
            raise ImportError("pytesseract não instalado. Execute: pip install pytesseract")

        img = Image.open(path)
        processed_img = self._preprocess_image(img)
        
        try:
            # [Opus - RG/CNH Multi-Layout OCR]: Usa pipeline multi-pass (com e sem filtro de nitidez)
            result = self._run_multipass_ocr(img, processed_img)

            print(f"[OCR] Imagem processada com sucesso ({path.name}).")
            return result
        except pytesseract.TesseractNotFoundError:
            raise FileNotFoundError("O executável do Tesseract OCR não foi encontrado no Windows! Verifique as configurações.")

    # [Opus - v1.0 Multi-Doc]: OCR por página. Retorna uma lista (1 texto por página) para permitir
    # que PDFs com vários documentos sejam segmentados. Decide página a página entre texto nativo
    # e OCR, o que cobre PDFs mistos (algumas páginas digitais, outras escaneadas).
    def extract_pages(self, file_path: str | Path) -> list[str]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {path}")
        if path.suffix.lower() != ".pdf":
            return [self.extract_text(path)]
        if fitz is None:
            raise ImportError("PyMuPDF (fitz) não está instalado. Execute: pip install PyMuPDF")

        pages: list[str] = []
        doc = fitz.open(path)
        try:
            for page in doc:
                native = page.get_text("text").strip()
                if len(native) >= 50:
                    pages.append(native)
                else:
                    pages.append(self._ocr_single_page(page))
        finally:
            doc.close()
        return pages

    def _ocr_single_page(self, page) -> str:
        """[Opus - v1.0 Multi-Doc]: OCR (PSM 3 + PSM 6 + Raw PSM 6) de uma única página de PDF."""
        if pytesseract is None:
            raise ImportError("pytesseract não instalado. Execute: pip install pytesseract")
        zoom = 300 / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        mode = "RGBA" if pix.alpha else "RGB"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        processed_img = self._preprocess_image(img)
        try:
            return self._run_multipass_ocr(img, processed_img)
        except pytesseract.TesseractNotFoundError:
            raise FileNotFoundError("O executável do Tesseract OCR não foi encontrado no Windows! Verifique as configurações.")

    def _run_multipass_ocr(self, raw_img: Image.Image, processed_img: Image.Image) -> str:
        """
        # [Opus - RG/CNH Multi-Layout OCR]: Combina 3 leituras complementares:
        # 1. Imagem alto-contraste em PSM 3 (layout geral)
        # 2. Imagem alto-contraste em PSM 6 (caixas adjacentes de RG antigo/novo)
        # 3. Imagem original sem filtro agressivo em PSM 6 (preserva CPF/Nome sobre fundo de segurança de CNH/RG)
        """
        parts = []
        text_std = pytesseract.image_to_string(processed_img, lang=self.lang)
        parts.append(text_std)

        try:
            text_block = pytesseract.image_to_string(processed_img, lang=self.lang, config="--psm 6")
            if text_block.strip():
                parts.append("=== SEGMENTAÇÃO EM BLOCO ===\n" + text_block)
        except Exception:
            pass

        try:
            text_raw_block = pytesseract.image_to_string(raw_img, lang=self.lang, config="--psm 6")
            if text_raw_block.strip():
                parts.append("=== LEITURA SUAVE (FUNDO DE SEGURANÇA) ===\n" + text_raw_block)
        except Exception:
            pass

        return "\n\n".join(parts)

    def _preprocess_image(self, img: Image.Image) -> Image.Image:
        """
        Aplica filtros básicos (Grayscale, Contraste, Sharpen)
        para melhorar a precisão do Tesseract.
        """
        # Converter para tons de cinza
        img = img.convert("L")
        
        # Aumentar contraste (ajuda a destacar o texto do fundo)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        
        # Filtro de nitidez básico
        img = img.filter(ImageFilter.SHARPEN)
        
        return img
