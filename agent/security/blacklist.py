"""Blacklist di comandi distruttivi: blocco a monte, prima di subprocess."""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache

# (nome per il messaggio di errore, regex case-insensitive sull'intera riga)
_DEFAULT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("rm con -r/-f", r"\brm\s+(?:-{1,2}\w+\s+)*-{1,2}[rf]\w*"),
    ("rm --recursive/--force", r"\brm\b[^|;&]*--(?:recursive|force)"),
    ("rmdir/rd /s", r"\b(?:rmdir|rd)\s+/[sq]"),
    ("del /f /q /s", r"\bdel\s+/[fqs]"),
    ("format", r"\bformat\s+(?:[a-z]:|/q)"),
    ("mkfs", r"\bmkfs"),
    ("dd if=", r"\bdd\s+if="),
    ("shutdown/poweroff/halt", r"\b(?:shutdown|poweroff|halt)\b"),
    ("Remove-Item -Recurse", r"\bremove-item\b[^|;]*-recurse"),
    ("pipe verso shell", r"\|\s*(?:ba|z|k)?sh\b"),
    ("Invoke-Expression", r"\b(?:invoke-expression|iex)\b"),
)


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
