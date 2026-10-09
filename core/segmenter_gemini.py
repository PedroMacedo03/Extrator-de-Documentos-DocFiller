"""
DocFiller — Segmentador de PDFs Multi-Documento
===============================================
# [Opus - v1.0 Multi-Doc]: Novo módulo. Permite que um único PDF/TIFF contendo vários
# documentos (RG + CNH + Certidão...) seja dividido em documentos individuais.

Fluxo:
  1. As páginas chegam JÁ MASCARADAS (LGPD) — nenhum dado real vai à nuvem.
  2. O Gemini devolve apenas intervalos de páginas + tipo provável (chamada leve).
  3. Os intervalos são validados/reparados localmente.
  4. O PyMuPDF corta o PDF em sub-arquivos, um por documento.
"""

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from .retry_gemini import call_with_retry

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    fitz = None

# Marcador de página inserido no texto antes do mascaramento (não casa com nenhum padrão LGPD).
PAGE_MARKER_FMT = "<<<PAGINA_{n}>>>"
_PAGE_MARKER_RE = re.compile(r"<<<PAGINA_(\d+)>>>")

# Máximo de caracteres de cada página enviados para a segmentação (controla custo).
_MAX_CHARS_PER_PAGE = 1200


class PageSegment(BaseModel):
    pagina_inicio: int = Field(description="Primeira página do documento (começando em 1)")
    pagina_fim: int = Field(description="Última página do documento (inclusive)")
    tipo_provavel: str = Field(description="Tipo provável do documento (ex: RG, CNH, CERTIDAO_NASCIMENTO)")


class SegmentationResult(BaseModel):
    documentos: list[PageSegment]


def join_pages_with_markers(pages: list[str]) -> str:
    """Junta as páginas num texto único com marcadores, para mascarar o arquivo todo de uma vez."""
    return "\n".join(f"{PAGE_MARKER_FMT.format(n=i + 1)}\n{text}" for i, text in enumerate(pages))


def split_masked_text(masked_text: str, num_pages: int) -> list[str]:
    """Reverte join_pages_with_markers sobre o texto JÁ mascarado."""
    parts = _PAGE_MARKER_RE.split(masked_text)
    # split() devolve [antes, '1', texto1, '2', texto2, ...]
    pages = [""] * num_pages
    for i in range(1, len(parts) - 1, 2):
        idx = int(parts[i]) - 1
        if 0 <= idx < num_pages:
            pages[idx] = parts[i + 1].strip()
    return pages


def normalize_segments(segments: list[PageSegment], num_pages: int) -> list[tuple[int, int, str]]:
    """
    Garante intervalos contíguos, sem sobreposição, cobrindo 1..num_pages.
    Repara lacunas estendendo o documento anterior; se algo sair do esperado, o chamador
    trata como documento único.
    """
    out: list[list] = []
    for seg in sorted(segments, key=lambda s: (s.pagina_inicio, s.pagina_fim)):
        start = max(1, min(num_pages, seg.pagina_inicio))
        end = max(start, min(num_pages, seg.pagina_fim))
        if out and start <= out[-1][1]:
            start = out[-1][1] + 1
        if start > end:
            continue
        if out and start > out[-1][1] + 1:
            out[-1][1] = start - 1  # fecha a lacuna estendendo o anterior
        if not out and start > 1:
            start = 1
        out.append([start, end, (seg.tipo_provavel or "").strip()])
    if not out:
        return [(1, num_pages, "")]
    out[-1][1] = num_pages
    return [(a, b, t) for a, b, t in out]


class DocumentSegmenter:
    """Identifica quais páginas de um arquivo pertencem a cada documento."""

    SYSTEM_INSTRUCTION = (
        "Você analisa o texto (já anonimizado, com tokens como [NOME_001]) de cada página de um "
        "arquivo digitalizado que pode conter VÁRIOS documentos brasileiros em sequência "
        "(RG, CNH, CPF, certidões, título de eleitor, comprovantes, etc.).\n"
        "Sua tarefa é dividir o arquivo em documentos, devolvendo intervalos de páginas.\n"
        "REGRAS:\n"
        "1. Cada página pertence a EXATAMENTE um documento; os intervalos são contíguos e cobrem todas as páginas.\n"
        "2. Frente e verso do mesmo documento (ex: RG, CNH, CIN) ficam no MESMO intervalo.\n"
        "3. Documentos com várias páginas (certidões, escrituras, matrículas, diplomas) ficam num único intervalo.\n"
        "4. Páginas em branco, capas ou folhas de rosto são anexadas ao documento adjacente.\n"
        "5. Na dúvida entre separar ou juntar páginas de conteúdo evidentemente diferente, SEPARE; "
        "se a continuidade for evidente (mesma pessoa e mesmo tipo, texto que continua), JUNTE.\n"
        "6. Páginas numeradas a partir de 1, na ordem recebida."
    )

    def __init__(self, api_key: str, model_name: str = "gemini-3.8-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def segment(self, masked_pages: list[str]) -> list[tuple[int, int, str]]:
        """Retorna [(pagina_inicio, pagina_fim, tipo_provavel), ...]. Nunca lança: em caso de falha, 1 documento."""
        n = len(masked_pages)
        if n <= 1:
            return [(1, max(n, 1), "")]

        blocks = []
        for i, text in enumerate(masked_pages):
            snippet = re.sub(r"\n{3,}", "\n\n", text).strip()[:_MAX_CHARS_PER_PAGE] or "(página sem texto legível)"
            blocks.append(f"=== PÁGINA {i + 1} ===\n{snippet}")
        prompt = (
            f"O arquivo tem {n} páginas. Devolva a divisão em documentos.\n\n" + "\n\n".join(blocks)
        )

        try:
            response = call_with_retry(lambda: self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=SegmentationResult,
                    temperature=0.0,
                ),
            ))
            if not response.text:
                raise ValueError("Resposta vazia da segmentação.")
            result = SegmentationResult(**json.loads(response.text))
            return normalize_segments(result.documentos, n)
        except Exception as e:
            print(f"[SEGMENTADOR] Falha na segmentação ({e}). Tratando arquivo como documento único.")
            return [(1, n, "")]


def split_pdf(src: Path, ranges: list[tuple[int, int, str]], dest_dir: Path, stem: str) -> list[Path]:
    """Corta o PDF em um sub-arquivo por intervalo. Retorna os caminhos, na mesma ordem dos intervalos."""
    if fitz is None:
        raise ImportError("PyMuPDF (fitz) não está instalado. Execute: pip install PyMuPDF")
    dest_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    src_doc = fitz.open(src)
    try:
        for a, b, tipo in ranges:
            label = re.sub(r"[^A-Za-z0-9_-]+", "", tipo.replace(" ", "_"))[:30]
            pages_label = f"p{a}" if a == b else f"p{a}-{b}"
            name = f"{stem}_{pages_label}" + (f"_{label}" if label else "") + ".pdf"
            out_path = dest_dir / name
            part = fitz.open()
            try:
                part.insert_pdf(src_doc, from_page=a - 1, to_page=b - 1)
                part.save(out_path)
            finally:
                part.close()
            outputs.append(out_path)
    finally:
        src_doc.close()
    return outputs


def convert_image_to_pdf(src: Path, dest_dir: Path) -> Path:
    """Converte imagem/TIFF multipágina em PDF (para entrar no mesmo fluxo de segmentação)."""
    if fitz is None:
        raise ImportError("PyMuPDF (fitz) não está instalado. Execute: pip install PyMuPDF")
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"{src.stem}.pdf"
    img_doc = fitz.open(src)
    try:
        pdf_bytes = img_doc.convert_to_pdf()
    finally:
        img_doc.close()
    pdf = fitz.open("pdf", pdf_bytes)
    try:
        pdf.save(out_path)
    finally:
        pdf.close()
    return out_path
