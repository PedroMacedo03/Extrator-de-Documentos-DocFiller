"""
DocFiller — Retentativas para a API Gemini
==========================================
# [Opus - v1.0 Multi-Doc]: No plano gratuito é comum a API responder 503 UNAVAILABLE
# ("high demand") de forma momentânea. Em vez de falhar na primeira, tentamos de novo
# com espera crescente. Erros definitivos (400, 404, chave inválida, cota) NÃO são repetidos.
"""

import time
from typing import Callable, TypeVar

T = TypeVar("T")

# Esperas (segundos) antes de cada nova tentativa → até 4 tentativas no total
_BACKOFF_SECONDS = (3, 8, 15)

_TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "high demand", "overloaded")


def is_transient_error(exc: Exception) -> bool:
    text = str(exc)
    return any(marker.lower() in text.lower() for marker in _TRANSIENT_MARKERS)


def call_with_retry(fn: Callable[[], T], on_wait: Callable[[int, int], None] | None = None) -> T:
    """Executa fn(); em erro transitório espera e tenta de novo. on_wait(tentativa, segundos) é opcional."""
    for attempt, wait in enumerate(_BACKOFF_SECONDS, start=1):
        try:
            return fn()
        except Exception as e:
            if not is_transient_error(e):
                raise
            print(f"[GEMINI] Servidor sobrecarregado (tentativa {attempt}). Nova tentativa em {wait}s...")
            if on_wait:
                on_wait(attempt, wait)
            time.sleep(wait)
    return fn()  # última tentativa: se falhar, o erro sobe normalmente
