"""Audit log JSONL: una riga per tool call, senza contenuti completi né segreti.

Ogni tool call produce una riga con: timestamp UTC, tool, argomenti (valori
troncati a un'anteprima corta), decisione (auto / confermato / rifiutato /
bloccato), esito (ok / errore) e durata. La scrittura non alza mai eccezioni:
un problema di I/O non deve interrompere il turno.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_VALUE_CHARS = 120
_TRUNC_MARKER = "...[troncato]"
_MAX_DEPTH = 4


def default_audit_path() -> Path:
    """`logs/audit.jsonl` alla radice del progetto (gitignored)."""
    # __file__ = <root>/agent/security/audit.py → risali a <root>
    return Path(__file__).resolve().parent.parent.parent / "logs" / "audit.jsonl"


def _truncate(text: str) -> str:
    if len(text) <= MAX_VALUE_CHARS:
        return text
    return text[:MAX_VALUE_CHARS] + _TRUNC_MARKER


def _sanitize(value: Any, depth: int = 0) -> Any:
    """Solo metadati + anteprima corta: mai il contenuto completo di un file."""
    if isinstance(value, str):
        return _truncate(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if depth >= _MAX_DEPTH:
        return _truncate(str(value))
    if isinstance(value, dict):
        return {str(key): _sanitize(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth + 1) for item in value]
    return _truncate(str(value))


class AuditLog:
    """Accoda una riga JSON per tool call su un file JSONL."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else default_audit_path()
        self._broken = False

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        tool: str,
        arguments: dict[str, Any] | None,
        decision: str,
        outcome: str,
        duration_ms: int,
    ) -> None:
        """Scrive la riga di audit; in caso di errore I/O smette di scrivere."""
        if self._broken:
            return
        entry = {
            "ts": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "tool": tool,
            "args": _sanitize(arguments if isinstance(arguments, dict) else {}),
            "decisione": decision,
            "esito": outcome,
            "durata_ms": max(0, int(duration_ms)),
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            self._broken = True  # l'audit non deve mai rompere il turno
