"""Whitelist dei path accessibili all'agente (anti path-traversal)."""

from __future__ import annotations

import os
import re
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


def resolves_outside_roots(target: str, roots: Sequence[Path]) -> bool:
    """True se `target` cade fuori dalle workspace_root.

    I path relativi sono risolti rispetto alla prima root (il cwd forzato dei
    comandi). Un path con drive (`C:file`, imprevedibile) è sempre fuori.
    """
    if not roots:
        return True
    if re.match(r"^[A-Za-z]:", target):
        return True
    try:
        p = Path(target).expanduser()
    except (RuntimeError, OSError):
        return True  # `~utente` indeterminabile: consideralo fuori
    if not p.is_absolute():
        p = roots[0] / p
    resolved = p.resolve()
    return not any(
        resolved == root.resolve() or resolved.is_relative_to(root.resolve())
        for root in roots
    )


def sensitive_root_warnings(roots: Sequence[Path]) -> list[str]:
    """Avvisi se una workspace_root contiene o coincide con cartelle sensibili.

    Segnala: root che contiene/coincide con la home, o root che contiene
    cartelle come ~/.ssh, ~/.aws, ~/AppData o le cartelle di sistema Windows.
    Una root normale (es. una sottocartella della home) non produce avvisi.
    """
    home = Path.home().resolve()
    sensitive: list[tuple[Path, str]] = [
        (home / ".ssh", "~/.ssh (chiavi SSH)"),
        (home / ".aws", "~/.aws (credenziali cloud)"),
        (home / ".gnupg", "~/.gnupg (chiavi GPG)"),
        (home / "AppData", "~/AppData (dati applicazioni)"),
        (home / "Documents", "~/Documenti"),
    ]
    for env_name, label in (
        ("SystemRoot", "cartella di Windows"),
        ("ProgramFiles", "Program Files"),
    ):
        value = os.environ.get(env_name)
        if value:
            sensitive.append((Path(value).resolve(), label))

    warnings: list[str] = []
    for raw_root in roots:
        root = Path(raw_root).resolve()
        if root == home or home.is_relative_to(root):
            warnings.append(f"workspace_root {root} contiene o coincide con la home dell'utente")
        else:
            for target, label in sensitive:
                if target.is_relative_to(root):
                    warnings.append(f"workspace_root {root} contiene {label}")
    return warnings
