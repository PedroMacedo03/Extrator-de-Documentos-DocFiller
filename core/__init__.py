"""
DocFiller — Módulo Core
=======================
[GEMINI - CORREÇÃO C4]: Pacote Python explícito para importações seguras e empacotamento.
"""

from .database_gemini import DatabaseManager
from .entity_resolver_gemini import EntityResolver  # [Opus - v1.1 Sessions Redesign]
from .extractor_gemini import GeminiExtractor
from .masker_gemini import DataMasker
from .models_gemini import ExtractedDocument
from .ocr_local_gemini import HybridOCR
from .organizer_gemini import DocumentOrganizer

# [Opus - v1.0 Prep]: Exportação do módulo de resolução de caminhos paths
from . import paths

__all__ = [
    "DatabaseManager",
    "EntityResolver",
    "GeminiExtractor",
    "DataMasker",
    "ExtractedDocument",
    "HybridOCR",
    "DocumentOrganizer",
    "paths",
]
