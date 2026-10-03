"""Test della whitelist path: anti path-traversal e canonicalizzazione."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.security.paths import (
    PathNotAllowedError,
    is_allowed,
    safe_resolve,
    sensitive_root_warnings,
)


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


# --- casi richiesti dalla 1.5.2 ------------------------------------------------


def test_traversal_relativo_con_punti(workspace: Path) -> None:
    """Anche un path relativo con .. rifiutato: non esce dalla root."""
    with pytest.raises(PathNotAllowedError, match="non permesso"):
        safe_resolve("../../etc/passwd", [workspace])


def test_symlink_che_esce_dalla_root(workspace: Path, tmp_path: Path) -> None:
    """Symlink/junction dentro la root ma che punta fuori: rifiutato."""
    link = workspace / "escape"
    try:
        link.symlink_to(tmp_path / "outside", target_is_directory=True)
    except OSError:
        pytest.skip("symlink non permessi su questo sistema (admin/Developer Mode)")
    with pytest.raises(PathNotAllowedError):
        safe_resolve(link, [workspace])
    with pytest.raises(PathNotAllowedError):
        safe_resolve(link / "secret.txt", [workspace])


@pytest.mark.skipif(os.name != "nt", reason="lettera di drive solo su Windows")
def test_path_altro_drive_rifiutato(workspace: Path) -> None:
    with pytest.raises(PathNotAllowedError):
        safe_resolve("Z:/qualcosa/file.txt", [workspace])


@pytest.mark.skipif(os.name != "nt", reason="path UNC solo su Windows")
def test_path_unc_rifiutato(workspace: Path) -> None:
    # IP letterale: nessuna risoluzione DNS, connessione SMB rifiutata subito
    with pytest.raises(PathNotAllowedError):
        safe_resolve(r"\\127.0.0.1\nonexistent-share\file.txt", [workspace])


# --- avvisi root sensibili (1.5.2) ---------------------------------------------


def test_warning_root_coincide_con_home() -> None:
    warnings = sensitive_root_warnings([Path.home()])
    assert any("home" in w for w in warnings)


def test_warning_root_contiene_home() -> None:
    warnings = sensitive_root_warnings([Path.home().parent])
    assert any("home" in w for w in warnings)


def test_warning_root_contiene_chiavi_ssh() -> None:
    warnings = sensitive_root_warnings([Path.home() / ".ssh"])
    assert any(".ssh" in w for w in warnings)


def test_nessun_warning_root_normale(tmp_path: Path) -> None:
    assert sensitive_root_warnings([tmp_path]) == []


@pytest.mark.skipif(os.name != "nt", reason="SystemRoot esiste solo su Windows")
def test_warning_root_cartella_windows() -> None:
    warnings = sensitive_root_warnings([Path(os.environ["SystemRoot"])])
    assert any("Windows" in w for w in warnings)
