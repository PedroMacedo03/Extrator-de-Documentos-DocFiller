"""
DocFiller — Submódulo de Componentes da Aba 'Sessões e Documentos' (v1.1)
=========================================================================
[Opus - v1.1 Sessions Redesign]: Componentes modulares para o layout de 4 colunas
focado em verificação manual por Pessoas e Imóveis.
"""

from .field_row import AttributeFieldRow
from .session_list_panel import SessionListPanel
from .entity_panel import SessionEntityPanel
from .attached_docs_panel import AttachedDocsPanel

__all__ = [
    "AttributeFieldRow",
    "SessionListPanel",
    "SessionEntityPanel",
    "AttachedDocsPanel",
]
