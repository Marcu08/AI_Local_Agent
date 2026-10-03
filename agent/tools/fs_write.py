"""Tool di scrittura filesystem: diff always-on, conferma Y/N Human-in-the-Loop."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from agent.security.paths import safe_resolve
from agent.tools.base import ToolContext, ToolResult, clip


def _build_diff(existing: str | None, proposed: str, path: Path) -> str:
    """Diff unificato confronto contenuto corrente vs proposto."""
    before = (existing or "").splitlines(keepends=True)
    after = proposed.splitlines(keepends=True)
    diff = difflib.unified_diff(
        before,
        after,
        fromfile=f"{path} (attuale)",
        tofile=f"{path} (proposto)",
    )
    text = "".join(diff)
    if not text:
        return "(nessuna differenza a livello di righe)"
    return text


def write_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Crea/sovrascrive un file: mostra il diff, chiede y/N, poi scrive."""
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return ToolResult.failure("argomento 'path' mancante (stringa)")
    content = args.get("content")
    if not isinstance(content, str):
        return ToolResult.failure("argomento 'content' mancante (stringa)")
    path = safe_resolve(raw_path, ctx.config.workspace_roots)
    if path.exists() and path.is_dir():
        return ToolResult.failure(f"è una cartella, non un file: {path}")

    existing: str | None = None
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult.failure(f"lettura del file esistente fallita: {e}")
    if existing == content:
        return ToolResult(output=f"Nessuna modifica: {path} è già aggiornato")

    diff = clip(_build_diff(existing, content, path), ctx.config.security.max_output_chars)
    if ctx.config.security.require_write_confirmation:
        approved = ctx.confirm.confirm(f"Scrittura file: {path}", diff)
        if not approved:
            return ToolResult.failure(
                f"Scrittura rifiutata dall'utente: il file {path} non è stato modificato."
            )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        return ToolResult.failure(f"scrittura fallita: {e}")
    verb = "Creato" if existing is None else "Aggiornato"
    return ToolResult(output=f"{verb}: {path} ({len(content)} caratteri)")
