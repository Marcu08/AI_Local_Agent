"""Tool di scrittura filesystem: diff always-on, conferma Y/N Human-in-the-Loop."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from agent.security.paths import PathNotAllowedError, safe_resolve
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
    try:
        path = safe_resolve(raw_path, ctx.config.workspace_roots)
    except PathNotAllowedError as e:
        return ToolResult.failure(f"{type(e).__name__}: {e}", decision="bloccato")
    if path.exists() and path.is_dir():
        return ToolResult.failure(f"è una cartella, non un file: {path}")

    decision = "auto"
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
        detail = diff
        if ctx.seen_untrusted:
            detail += (
                "\n\n[avviso] azione proposta dopo la lettura di contenuto "
                "esterno (tool_output non fidato)"
            )
        approved = ctx.confirm.confirm(f"Scrittura file: {path}", detail)
        if not approved:
            return ToolResult.failure(
                f"Scrittura rifiutata dall'utente: il file {path} non è stato modificato.",
                decision="rifiutato",
            )
        decision = "confermato"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        return ToolResult.failure(f"scrittura fallita: {e}", decision=decision)
    verb = "Creato" if existing is None else "Aggiornato"
    return ToolResult(
        output=f"{verb}: {path} ({len(content)} caratteri)", decision=decision
    )


def edit_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Sostituisce l'unica occorrenza di `old_str` con `new_str`: diff + conferma.

    Regole (1.6.1):
    - il file deve ESISTERE ed essere testo UTF-8: non è uno strumento di
      creazione (niente riscrittura di file interi per modifiche piccole);
    - `old_str` deve comparire ESATTAMENTE una volta: 0 o >1 occorrenze =
      errore chiaro e nessuna scrittura;
    - prima di scrivere mostra il diff e chiede y/N (stesso gate di write_file).
    """
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return ToolResult.failure("argomento 'path' mancante (stringa)")
    old_str = args.get("old_str")
    if not isinstance(old_str, str) or not old_str:
        return ToolResult.failure("argomento 'old_str' mancante (stringa non vuota)")
    new_str = args.get("new_str")
    if not isinstance(new_str, str):
        return ToolResult.failure(
            "argomento 'new_str' mancante (stringa, ammesso il vuoto)"
        )
    if old_str == new_str:
        return ToolResult.failure("old_str e new_str identiche: nessuna modifica da fare")
    try:
        path = safe_resolve(raw_path, ctx.config.workspace_roots)
    except PathNotAllowedError as e:
        return ToolResult.failure(f"{type(e).__name__}: {e}", decision="bloccato")
    if not path.exists():
        return ToolResult.failure(
            f"file inesistente: {path} (edit_file modifica solo file esistenti)"
        )
    if path.is_dir():
        return ToolResult.failure(f"è una cartella, non un file: {path}")
    try:
        # strict: un file non-UTF8 non va riscritto (lo farebbe a pezzi)
        existing = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult.failure(
            f"non è un file di testo UTF-8: {path} (nessuna modifica effettuata)"
        )
    except OSError as e:
        return ToolResult.failure(f"lettura del file fallita: {e}")

    count = existing.count(old_str)
    if count == 0:
        return ToolResult.failure(
            f"old_str non trovata (0 occorrenze) in {path}: nessuna modifica effettuata"
        )
    if count > 1:
        return ToolResult.failure(
            f"old_str ambigua: {count} occorrenze in {path}: fornisci una stringa "
            "più lunga che identifichi una sola posizione"
        )
    proposed = existing.replace(old_str, new_str, 1)

    decision = "auto"
    diff = clip(_build_diff(existing, proposed, path), ctx.config.security.max_output_chars)
    if ctx.config.security.require_write_confirmation:
        detail = diff
        if ctx.seen_untrusted:
            detail += (
                "\n\n[avviso] azione proposta dopo la lettura di contenuto "
                "esterno (tool_output non fidato)"
            )
        approved = ctx.confirm.confirm(f"Modifica file: {path}", detail)
        if not approved:
            return ToolResult.failure(
                f"Modifica rifiutata dall'utente: il file {path} non è stato modificato.",
                decision="rifiutato",
            )
        decision = "confermato"
    try:
        path.write_text(proposed, encoding="utf-8")
    except OSError as e:
        return ToolResult.failure(f"scrittura fallita: {e}", decision=decision)
    return ToolResult(
        output=f"Aggiornato: {path} (1 occorrenza sostituita)", decision=decision
    )
