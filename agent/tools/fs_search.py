"""Tool di ricerca testuale read-only dentro le workspace_root (1.6.2).

Greppa una stringa (case-insensitive) nei file di testo, ignorando cartelle
di lavoro (.git, .venv, ...), file binari e file troppo grandi, con limiti
espliciti su numero di occorrenze e dimensione: il tool è sola lettura e non
chiede mai conferma (il gate è la whitelist dei path, come read_file).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.security.paths import PathNotAllowedError, is_allowed, safe_resolve
from agent.tools.base import ToolContext, ToolResult, clip

# limiti del tool: prevedibile anche su alberi enormi (costanti, non config)
_MAX_RESULTS = 50  # occorrenze restituite
_MAX_FILE_BYTES = 1_000_000  # file più grandi saltati
_MAX_FILES_SCANNED = 5_000  # plafond di file esaminati per chiamata
_MAX_LINE_CHARS = 200  # riga citata troncata a questa lunghezza

# cartelle mai percorse (repo git, ambienti virtuali, cache, dipendenze)
_SKIP_DIRS = frozenset(
    {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache"}
)
# estensioni binarie note: saltate prima anche dello sniff
_BINARY_EXTS = frozenset(
    {
        ".pyc", ".pyd", ".dll", ".exe", ".so", ".png", ".jpg", ".jpeg", ".gif",
        ".ico", ".bmp", ".pdf", ".zip", ".gz", ".tar", ".7z", ".rar", ".mp3",
        ".mp4", ".wav", ".woff", ".woff2", ".ttf", ".otf", ".db", ".sqlite",
        ".bin", ".pkl", ".pickle", ".parquet", ".onnx",
    }
)
_SNIFF_BYTES = 8192


def _collect_candidates(start: Path) -> tuple[list[Path], bool]:
    """File da esaminare, in ordine deterministico; True se il plafond è pieno."""
    if start.is_file():
        return [start], False
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(start):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            candidates.append(Path(dirpath) / name)
            if len(candidates) >= _MAX_FILES_SCANNED:
                return candidates, True
    return candidates, False


def search_files(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Cerca `query` nei file di testo sotto `path` (default: prima root)."""
    query = args.get("query")
    if not isinstance(query, str) or not query:
        return ToolResult.failure("argomento 'query' mancante (stringa non vuota)")
    raw_path = args.get("path")
    if raw_path is None:
        raw_path = "."
    if not isinstance(raw_path, str) or not raw_path.strip():
        return ToolResult.failure("argomento 'path' non valido (stringa non vuota)")
    try:
        start = safe_resolve(raw_path, ctx.config.workspace_roots)
    except PathNotAllowedError as e:
        return ToolResult.failure(f"{type(e).__name__}: {e}", decision="bloccato")
    if not start.exists():
        return ToolResult.failure(f"percorso inesistente: {start}")
    if not (start.is_dir() or start.is_file()):
        return ToolResult.failure(f"percorso non leggibile: {start}")

    needle = query.lower()
    candidates, scan_capped = _collect_candidates(start)

    hits: list[str] = []
    scanned = 0
    truncated = False
    for file in candidates:
        if len(hits) >= _MAX_RESULTS:
            truncated = True
            break
        try:
            # 1.6.6: ogni candidato viene risolto e deve restare dentro le root:
            # un symlink (file o cartella) che punta fuori non viene mai aperto
            resolved = file.resolve()
            if not is_allowed(resolved, ctx.config.workspace_roots):
                continue
        except (OSError, RuntimeError, ValueError):
            continue  # symlink spezzato o path irrisolvibile: salta
        scanned += 1
        try:
            if resolved.stat().st_size > _MAX_FILE_BYTES:
                continue
            if resolved.suffix.lower() in _BINARY_EXTS:
                continue
            with resolved.open("rb") as fh:
                if b"\x00" in fh.read(_SNIFF_BYTES):
                    continue  # binario rilevato dallo sniff
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # file illeggibile (permessi, link spezzati): salta
        display = file.relative_to(start) if start.is_dir() else Path(file.name)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                quoted = line[:_MAX_LINE_CHARS]
                if len(line) > _MAX_LINE_CHARS:
                    quoted += "... [riga troncata]"
                hits.append(f"{display}:{lineno}: {quoted}")
                if len(hits) >= _MAX_RESULTS:
                    truncated = True
                    break

    if not hits:
        return ToolResult(
            output=f"Nessuna occorrenza di {query!r} in {start} "
            f"(file esaminati: {scanned})"
        )
    parts = ["\n".join(hits)]
    if truncated:
        parts.append(f"... [troncato: massimo {_MAX_RESULTS} occorrenze]")
    if scan_capped:
        parts.append(f"... [limite di file esaminati raggiunto: {_MAX_FILES_SCANNED}]")
    return ToolResult(output=clip("\n".join(parts), ctx.config.security.max_output_chars))
