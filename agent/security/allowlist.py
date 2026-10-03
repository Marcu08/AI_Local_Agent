"""Allowlist di comandi read-only: auto-approvazione solo per comandi puliti.

Un comando è auto-approvabile SOLO se:
- non contiene metacaratteri shell;
- si tokenizza senza errori (shlex non-posix, compatibile Windows);
- il primo token è un nome di comando (mai un path) e l'intestazione corrisponde
  a una voce di ``security.command_allowlist`` (case-insensitive, senza .exe);
- nessun argomento è un path assoluto e nessun ``..`` esce dalle workspace_root.

Tutto il resto richiede la conferma umana (default NO). Questa funzione riduce
la superficie: NON è un confine di sicurezza (vedi README "Limiti noti").
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Sequence
from pathlib import Path

from agent.security.paths import resolves_outside_roots

# separazione/piping/escaping/expansion: mai in un comando auto-approvato
_SHELL_METACHARS = frozenset("&|;<>()`$^%!\n\r")
_EXE_SUFFIXES = (".exe", ".cmd", ".bat", ".com")
_DRIVE_COLON = re.compile(r"^[A-Za-z]:")
# switch Windows brevi tipo /b /s /on: ammessi solo su Windows
_WINDOWS_SWITCH = re.compile(r"^/[A-Za-z]{1,3}$")


def _strip_quotes(token: str) -> str:
    return token.strip('"').strip("'")


def _normalize_exe(token: str) -> str | None:
    """Nome comando normalizzato; None se il token è un path (mai auto-approvabile)."""
    text = _strip_quotes(token)
    if not text or "/" in text or "\\" in text or _DRIVE_COLON.match(text):
        return None
    lowered = text.lower()
    for suffix in _EXE_SUFFIXES:
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def _is_absoluteish(text: str) -> bool:
    """Path assoluto su ogni piattaforma, più UNC, drive (`C:file`) e switch Windows.

    Su Windows uno switch corto (`/b`, `/on`) non è un path; su POSIX ogni `/x`
    lo è.
    """
    if _DRIVE_COLON.match(text):
        return True
    if text.startswith("\\"):
        return True
    if text.startswith("/"):
        if os.name == "nt" and _WINDOWS_SWITCH.match(text):
            return False
        return True
    if text.startswith("~"):
        try:
            return Path(text).expanduser().is_absolute()
        except (RuntimeError, OSError):
            return True  # home indeterminabile: non auto-approvare
    return Path(text).is_absolute()


def autoapprove_reason(
    command: str,
    allowlist: Sequence[str],
    roots: Sequence[Path],
) -> str | None:
    """None se il comando è auto-approvabile, altrimenti il motivo della conferma."""
    if any(ch in command for ch in _SHELL_METACHARS):
        return "contiene metacaratteri shell"
    try:
        raw_tokens = shlex.split(command, posix=False)
    except ValueError:
        return "tokenizzazione impossibile (virgolette non bilanciate)"
    tokens = [t for t in (_strip_quotes(tok) for tok in raw_tokens) if t]
    if not tokens:
        return "comando vuoto"
    exe = _normalize_exe(tokens[0])
    if exe is None:
        return "il primo token è un path, non un nome di comando"

    # l'entry più lunga vince (es. "python -m pytest" su "python" generico)
    matched_len = 0
    for entry in sorted(allowlist, key=lambda e: -len(e.split())):
        entry_tokens = [t for t in (_normalize_exe(p) for p in entry.split()) if t is not None]
        if not entry_tokens or len(entry_tokens) != len(entry.split()):
            continue  # voce malformata o con path: non matcha mai
        if len(tokens) < len(entry_tokens):
            continue
        head = [_normalize_exe(t) for t in tokens[: len(entry_tokens)]]
        if head == entry_tokens:
            matched_len = len(entry_tokens)
            break
    if matched_len == 0:
        return "comando non presente in allowlist"

    for arg in tokens[1:]:
        if _is_absoluteish(arg):
            return f"argomento con path assoluto ({arg})"
        if ".." in Path(arg).parts and resolves_outside_roots(arg, roots):
            return f"argomento che esce dalle workspace_root ({arg})"
    return None
