"""Whitelist dei path accessibili all'agente (anti path-traversal)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


class PathNotAllowedError(PermissionError):
    """Il path richiesto è fuori dalle workspace_root configurate."""


def safe_resolve(path: str | Path, roots: Sequence[Path]) -> Path:
    """Risolve `path` e verifica che cada sotto una workspace_root.

    Regole:
    - i path relativi sono risolti rispetto alla prima root;
    - il path viene canonicalizzato (``..``, separatori misti, symlink);
    - se il risultato non è sotto una root, viene alzato PathNotAllowedError.
    """
    if not roots:
        raise PathNotAllowedError("nessuna workspace_root configurata")
    raw = Path(str(path)).expanduser()
    if not raw.is_absolute():
        raw = Path(roots[0]) / raw
    resolved = raw.resolve()
    for root in roots:
        root_resolved = Path(root).resolve()
        if resolved == root_resolved or resolved.is_relative_to(root_resolved):
            return resolved
    raise PathNotAllowedError(f"path non permesso (fuori dalle workspace_root): {resolved}")


def is_allowed(path: str | Path, roots: Sequence[Path]) -> bool:
    """True se `path` è dentro una workspace_root (nessuna eccezione)."""
    try:
        safe_resolve(path, roots)
    except PathNotAllowedError:
        return False
    return True
