"""Tool di lettura filesystem: libera dentro le workspace_root."""

from __future__ import annotations

from typing import Any

from agent.security.paths import PathNotAllowedError, safe_resolve
from agent.tools.base import ToolContext, ToolResult, clip

_MAX_ENTRIES = 500


def list_dir(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Elenca una cartella: [D] cartelle, [F] file con dimensione in byte."""
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return ToolResult.failure("argomento 'path' mancante (stringa)")
    try:
        path = safe_resolve(raw_path, ctx.config.workspace_roots)
    except PathNotAllowedError as e:
        return ToolResult.failure(f"{type(e).__name__}: {e}", decision="bloccato")
    if not path.exists():
        return ToolResult.failure(f"cartella inesistente: {path}")
    if not path.is_dir():
        return ToolResult.failure(f"non è una cartella: {path}")
    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    lines: list[str] = []
    for entry in entries[:_MAX_ENTRIES]:
        if entry.is_dir():
            lines.append(f"[D] {entry.name}/")
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                size = -1
            lines.append(f"[F] {entry.name}  ({size} byte)")
    if len(entries) > _MAX_ENTRIES:
        lines.append(f"... e altri {len(entries) - _MAX_ENTRIES} elementi")
    header = f"{path} — {len(entries)} elementi"
    body = "\n".join(lines) if lines else "(cartella vuota)"
    return ToolResult(output=header + "\n" + body)


def read_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Legge un file di testo con numerazione righe; offset/limit opzionali (1-based)."""
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return ToolResult.failure("argomento 'path' mancante (stringa)")
    try:
        path = safe_resolve(raw_path, ctx.config.workspace_roots)
    except PathNotAllowedError as e:
        return ToolResult.failure(f"{type(e).__name__}: {e}", decision="bloccato")
    if not path.exists():
        return ToolResult.failure(f"file inesistente: {path}")
    if path.is_dir():
        return ToolResult.failure(f"è una cartella, non un file: {path}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ToolResult.failure(f"lettura fallita: {e}")
    lines = text.splitlines()
    try:
        offset = int(args.get("offset", 1) or 1)
        limit_raw = args.get("limit")
        limit = int(limit_raw) if limit_raw is not None else None
    except (TypeError, ValueError):
        return ToolResult.failure("offset/limit devono essere numeri interi")
    if offset < 1:
        return ToolResult.failure("offset deve essere >= 1 (righe numerate da 1)")
    if limit is not None and limit < 1:
        return ToolResult.failure("limit deve essere >= 1")
    if offset > len(lines) and lines:
        return ToolResult.failure(f"offset {offset} oltre la fine ({len(lines)} righe)")
    selected = lines[offset - 1 :]
    if limit is not None:
        selected = selected[:limit]
    numbered = [f"{i:5d} | {line}" for i, line in enumerate(selected, start=offset)]
    last_line = offset + len(selected) - 1 if selected else offset
    header = f"{path} — righe {offset}-{last_line} di {len(lines)}"
    body = "\n".join(numbered) if numbered else "(nessuna riga)"
    return ToolResult(output=clip(header + "\n" + body, ctx.config.max_tool_output_chars))
