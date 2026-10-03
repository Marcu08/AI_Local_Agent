"""Recupero dalla memoria: oggi stub, la Fase 2 collega VectorStore + embeddings."""

from __future__ import annotations

from typing import Any


def search(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Ritorna i chunk più rilevanti per `query`.

    Scaffold: restituisce sempre [] finché non ci sono ingestion e indicizzazione.
    """
    if not query or not query.strip():
        return []
    return []
