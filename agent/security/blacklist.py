"""Blacklist di comandi distruttivi: blocco a monte, prima di subprocess."""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from agent.security.paths import resolves_outside_roots

# (nome per il messaggio di errore, regex case-insensitive sull'intera riga)
_DEFAULT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("rm con -r/-f", r"\brm\s+(?:-{1,2}\w+\s+)*-{1,2}[rf]\w*"),
    ("rm --recursive/--force", r"\brm\b[^|;&]*--(?:recursive|force)"),
    ("rmdir/rd /s", r"\b(?:rmdir|rd)\s+/[sq]"),
    ("del /f /q /s", r"\bdel\s+/[fqs]"),
    ("del con wildcard", r"\bdel\b[^|;&]*[*?]"),
    ("format", r"\bformat\s+(?:[a-z]:|/q)"),
    ("mkfs", r"\bmkfs"),
    ("dd if=", r"\bdd\s+if="),
    ("shutdown/poweroff/halt", r"\b(?:shutdown|poweroff|halt)\b"),
    ("Remove-Item", r"\bremove-item\b"),
    ("pipe verso shell", r"\|\s*(?:ba|z|k)?sh\b"),
    ("Invoke-Expression", r"\b(?:invoke-expression|iex)\b"),
    ("download seguito da esecuzione", r"\b(?:curl|wget|iwr|invoke-webrequest)\b"
                                       r"[^|;&]*(?:\||&&|;)\s*\S"),
    ("git clean", r"\bgit\s+clean\b"),
    ("git reset --hard", r"\bgit\s+reset\b[^|;&]*--hard\b"),
    ("git checkout -- (ripristino file)", r"\bgit\s+checkout\b[^|;&]*\s--(?:\s|$)"),
    # il payload di -c è codice: può contenere `;` tra gli operatori
    ("python -c con rimozione file",
     r"\b(?:python\w*|py)\b.*\s-c\b.*(?:rmtree|os\.remove|os\.unlink|os\.rmdir)"),
)

_MOVE_COMMANDS = frozenset({"move", "ren", "copy", "xcopy", "mv", "cp"})
_REDIRECT_RE = re.compile(r"^(?P<fd>\d*)(?P<op><{1,2}|>{1,2})(?P<target>.*)$")
_WINDOWS_SWITCH_RE = re.compile(r"^/[A-Za-z]$")


def _strip_quotes(token: str) -> str:
    return token.strip('"').strip("'")


@lru_cache(maxsize=None)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def find_destructive_match(command: str, extra: Sequence[str] = ()) -> str | None:
    """Ritorna la descrizione del pattern che ha scattato, oppure None.

    `extra` sono voci aggiuntive lette da config.json (match per sottostringa,
    case-insensitive), applicate prima delle regex predefinite.
    """
    lowered = command.lower()
    for item in extra:
        if item.strip() and item.lower() in lowered:
            return f"blacklist config: {item!r}"
    for name, pattern in _DEFAULT_PATTERNS:
        if _compiled(pattern).search(command):
            return name
    return None


def is_destructive(command: str, extra: Sequence[str] = ()) -> bool:
    """True se il comando va bloccato dalla blacklist."""
    return find_destructive_match(command, extra) is not None


def find_path_based_block(command: str, roots: Sequence[Path]) -> str | None:
    """Blocchi che dipendono dalle workspace_root (secondo strato della blacklist).

    - move/ren/copy con argomento sorgente o destinazione fuori dalle root;
    - redirect (`>`, `>>`, `<`, `2>...`) con target fuori dalle root.

    Ritorna la descrizione del blocco, oppure None. Le path non determinabili
    (tokenizzazione fallita, target assente) non bloccano: ricade nella conferma.
    """
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        return None
    cleaned = [t for t in (_strip_quotes(tok) for tok in tokens) if t]
    if not cleaned:
        return None

    first = cleaned[0].lower()
    base = first.replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    if base in _MOVE_COMMANDS or stem in _MOVE_COMMANDS:
        for arg in cleaned[1:]:
            if not arg or arg.startswith("-") or _WINDOWS_SWITCH_RE.match(arg):
                continue
            if resolves_outside_roots(arg, roots):
                return (
                    "comando di spostamento/copia con path fuori "
                    f"dalle workspace_root: {arg}"
                )

    for i, token in enumerate(cleaned):
        match = _REDIRECT_RE.match(token)
        if match is None:
            continue
        target = match.group("target")
        if not target and i + 1 < len(cleaned):
            target = cleaned[i + 1]
        if not target or target.startswith("&"):  # es. 2>&1: merge, non un path
            continue
        if resolves_outside_roots(target, roots):
            kind = "di output" if match.group("op")[0] == ">" else "di input"
            return f"redirect {kind} verso fuori dalle workspace_root: {target}"
    return None
