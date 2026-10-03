"""Tool search_memory — wiring scaffold verso la Fase 2 (RAG)."""

from __future__ import annotations

from typing import Any

from agent.memory.retrieval import search
from agent.tools.base import ToolContext, ToolResult, clip

_NOT_IMPLEMENTED = (
    "Memoria RAG non ancora implementata (Fase 2): nessun documento indicizzato. "
    "La struttura e' pronta — ingestion con scripts/ingest.py e vector store con ChromaDB."
)


def search_memory(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Cerca nei documenti indicizzati. Oggi restituisce sempre 'non implementato'."""
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return ToolResult.failure("argomento 'query' mancante (stringa)")
    results = search(query, k=5)
    if not results:
        return ToolResult(output=f"{_NOT_IMPLEMENTED} (query ricevuta: {query.strip()!r})")
    lines = [f"[{r.get('score', '?'):.3f}] {r.get('text', '')}" for r in results]
    return ToolResult(output=clip("\n".join(lines), ctx.config.max_tool_output_chars))
