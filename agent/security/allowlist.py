"""Allowlist di comandi read-only: auto-approvazione solo per comandi puliti.

Ogni voce (`AllowlistEntry`) dichiara l'intestazione del comando E i flag
ammessi: qualsiasi flag non elencato forza la conferma umana. Così `git diff
--output=fuori.diff` (scrive un file) non passa più per "git diff".

Un comando è auto-approvabile SOLO se:
- non contiene metacaratteri shell;
- si tokenizza senza errori (shlex non-posix, compatibile Windows);
- il primo token è un nome di comando (mai un path) e l'intestazione corrisponde
  a una voce di ``security.command_allowlist`` (case-insensitive, senza .exe);
- ogni flag è tra quelli ammessi dalla voce corrispondente;
- nessun argomento è un path assoluto e ogni argomento-path, risolto con
  ``resolve()`` (symlink/junction compresi), resta dentro le workspace_root.

Tutto il resto richiede la conferma umana (default NO). Questa funzione riduce
la superficie: NON è un confine di sicurezza (vedi README "Limiti noti").
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from agent.security.paths import resolves_outside_roots

# separazione/piping/escaping/expansion: mai in un comando auto-approvato
_SHELL_METACHARS = frozenset("&|;<>()`$^%!\n\r")
_EXE_SUFFIXES = (".exe", ".cmd", ".bat", ".com")
_DRIVE_COLON = re.compile(r"^[A-Za-z]:")
# switch Windows brevi tipo /b /s /on: ammessi solo su Windows
_WINDOWS_SWITCH = re.compile(r"^/[A-Za-z]{1,3}$")


@dataclass(frozen=True)
class AllowlistEntry:
    """Voce di allowlist: intestazione comando + flag ammessi senza conferma."""

    command: str
    flags: tuple[str, ...] = ()


def _flag_name(token: str) -> str | None:
    """Token-opzione normalizzato (`--output=/x` → `--output`); None se non è un flag."""
    if token.startswith("-") and len(token) > 1:
        return token.split("=", 1)[0]
    if os.name == "nt" and _WINDOWS_SWITCH.match(token):
        return token.lower()
    return None


def _normalize_flag(flag: str) -> str:
    """Gli switch Windows sono case-insensitive, le opzioni git no."""
    return flag.lower() if flag.startswith("/") else flag


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
    allowlist: Sequence[AllowlistEntry],
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

    # la voce più lunga vince (es. "python -m pytest" su "python" generico)
    matched: AllowlistEntry | None = None
    matched_len = 0
    for entry in sorted(allowlist, key=lambda e: -len(e.command.split())):
        entry_tokens = [
            t for t in (_normalize_exe(p) for p in entry.command.split()) if t is not None
        ]
        if not entry_tokens or len(entry_tokens) != len(entry.command.split()):
            continue  # voce malformata o con path: non matcha mai
        if len(tokens) < len(entry_tokens):
            continue
        head = [_normalize_exe(t) for t in tokens[: len(entry_tokens)]]
        if head == entry_tokens:
            matched = entry
            matched_len = len(entry_tokens)
            break
    if matched is None:
        return "comando non presente in allowlist"

    allowed_flags = {_normalize_flag(f) for f in matched.flags}
    for arg in tokens[matched_len:]:
        flag = _flag_name(arg)
        if flag is not None:
            if _normalize_flag(flag) not in allowed_flags:
                return f"flag non ammesso ({flag})"
            continue
        if _is_absoluteish(arg):
            return f"argomento con path assoluto ({arg})"
        # Ogni argomento viene risolto (symlink/junction compresi) rispetto
        # alla root di lavoro: un link dentro la root che punta fuori non
        # passa senza conferma (1.5.7). Copre anche `..`.
        try:
            outside = resolves_outside_roots(arg, roots)
        except (OSError, RuntimeError, ValueError):
            return f"argomento non risolvibile ({arg})"
        if outside:
            return f"argomento che esce dalle workspace_root ({arg})"
    return None
