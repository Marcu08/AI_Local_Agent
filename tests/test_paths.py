"""Test della whitelist path: anti path-traversal e canonicalizzazione."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.security.paths import PathNotAllowedError, is_allowed, safe_resolve


def test_path_dentro_la_root(workspace: Path) -> None:
    resolved = safe_resolve(workspace / "notes.md", [workspace])
    assert resolved == (workspace / "notes.md").resolve()
    assert resolved.is_file()


def test_root_stessa(workspace: Path) -> None:
    assert safe_resolve(workspace, [workspace]) == workspace.resolve()


def test_path_relativo_risolve_sulla_root(workspace: Path) -> None:
    resolved = safe_resolve("sub/a.txt", [workspace])
    assert resolved == (workspace / "sub" / "a.txt").resolve()


def test_path_relativo_con_punto(workspace: Path) -> None:
    resolved = safe_resolve("./notes.md", [workspace])
    assert resolved == (workspace / "notes.md").resolve()


def test_traversal_con_parentesco_rifiutato(workspace: Path, tmp_path: Path) -> None:
    """workspace/../outside/secret.txt deve essere rifiutato."""
    with pytest.raises(PathNotAllowedError, match="non permesso"):
        safe_resolve(workspace / ".." / "outside" / "secret.txt", [workspace])


def test_traversal_assoluto_rifiutato(workspace: Path, tmp_path: Path) -> None:
    with pytest.raises(PathNotAllowedError):
        safe_resolve(tmp_path / "outside" / "secret.txt", [workspace])


def test_path_windows_traversal_rifiutato(workspace: Path) -> None:
    with pytest.raises(PathNotAllowedError):
        safe_resolve(str(workspace) + r"\..\..\Windows\System32", [workspace])


def test_path_inesistente_ma_dentro(workspace: Path) -> None:
    """Anche un path non ancora creato è permesso se sta dentro la root."""
    resolved = safe_resolve("nuova_cartella/file.txt", [workspace])
    assert resolved.is_relative_to(workspace.resolve())


def test_nessuna_root(workspace: Path) -> None:
    with pytest.raises(PathNotAllowedError, match="nessuna workspace_root"):
        safe_resolve(workspace / "notes.md", [])


def test_is_allowed_booleani(workspace: Path, tmp_path: Path) -> None:
    assert is_allowed(workspace / "notes.md", [workspace]) is True
    assert is_allowed(tmp_path / "outside" / "secret.txt", [workspace]) is False
