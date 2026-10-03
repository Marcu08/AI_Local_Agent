"""Test 1.6.2: search_files — grep read-only con limiti, ignore e safe_resolve."""

from __future__ import annotations

import pytest

from agent.security.confirm import ScriptedConfirm
from agent.tools import ToolContext, ToolResult, create_default_registry
from agent.tools.fs_search import _MAX_FILE_BYTES, _MAX_RESULTS


def _dispatch(config, args: dict, *, approve: bool = True) -> tuple[ToolResult, ScriptedConfirm]:
    confirm = ScriptedConfirm(default=approve)
    result = create_default_registry().dispatch(
        "search_files", args, ToolContext(config=config, confirm=confirm)
    )
    return result, confirm


def test_search_files_trova_occorrenze_case_insensitive(workspace, config) -> None:
    """Formato file:riga:contenuto e matching senza distinzione maiuscole."""
    (workspace / "notes.md").write_text("# Note\nciao mondo\n", encoding="utf-8")
    (workspace / "sub" / "a.txt").write_text("MONDO nuovo\n", encoding="utf-8")

    result, confirm = _dispatch(config, {"query": "mondo"})

    assert result.ok, result.error
    out = result.output or ""
    assert "notes.md:2: ciao mondo" in out
    assert "a.txt:1: MONDO nuovo" in out
    assert confirm.calls == [], "tool di sola lettura: nessuna conferma"


def test_search_files_nessun_risultato(workspace, config) -> None:
    (workspace / "notes.md").write_text("alfa\n", encoding="utf-8")
    result, _ = _dispatch(config, {"query": "inesistente_xyz"})
    assert result.ok
    assert "Nessuna occorrenza" in (result.output or "")


def test_search_files_fuori_root_bloccato(config) -> None:
    result, _ = _dispatch(config, {"query": "x", "path": "../../"})
    assert not result.ok
    assert result.decision == "bloccato"
    assert "PathNotAllowedError" in (result.error or "")


def test_search_files_ignora_git_e_venv(workspace, config) -> None:
    """.git e .venv non vengono percorsi: la needle c'è solo lì."""
    (workspace / ".git").mkdir()
    (workspace / ".venv").mkdir()
    (workspace / ".git" / "hook.txt").write_text("needle\n", encoding="utf-8")
    (workspace / ".venv" / "lib.py").write_text("needle\n", encoding="utf-8")

    result, _ = _dispatch(config, {"query": "needle"})

    assert result.ok
    assert "Nessuna occorrenza" in (result.output or "")


def test_search_files_salta_file_binari(workspace, config) -> None:
    """File con NUL (dati) e con estensione binaria non vengono aperti."""
    (workspace / "dati.bin.dat").write_bytes(b"needle\x00" + b"x" * 100)
    (workspace / "foto.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"needle" + b"\x00" * 64)

    result, _ = _dispatch(config, {"query": "needle"})

    assert result.ok
    assert "Nessuna occorrenza" in (result.output or "")


def test_search_files_salta_file_grandi(workspace, config) -> None:
    """Oltre _MAX_FILE_BYTES il file viene ignorato (nessuna lettura completa)."""
    (workspace / "gigante.txt").write_bytes(b"x" * (_MAX_FILE_BYTES + 1) + b"needle")

    result, _ = _dispatch(config, {"query": "needle"})

    assert result.ok
    assert "Nessuna occorrenza" in (result.output or "")


def test_search_files_limite_risultati(workspace, config) -> None:
    """Massimo _MAX_RESULTS occorrenze + marker di troncamento esplicito."""
    righe = "\n".join(f"riga {i} dafteniente" for i in range(_MAX_RESULTS + 25))
    (workspace / "molti.txt").write_text(righe + "\n", encoding="utf-8")

    result, _ = _dispatch(config, {"query": "dafteniente"})

    assert result.ok
    out = result.output or ""
    assert out.count("dafteniente") == _MAX_RESULTS
    assert f"massimo {_MAX_RESULTS} occorrenze" in out


def test_search_files_path_file_singolo(workspace, config) -> None:
    """path può essere un file: si cerca solo quello."""
    (workspace / "notes.md").write_text("trovami qui\n", encoding="utf-8")
    (workspace / "sub" / "a.txt").write_text("trovami anche\n", encoding="utf-8")

    result, _ = _dispatch(config, {"query": "trovami", "path": "notes.md"})

    assert result.ok
    out = result.output or ""
    assert "notes.md" in out
    assert "a.txt" not in out


def test_search_files_path_mancante_errore(workspace, config) -> None:
    result, _ = _dispatch(config, {"query": ""})
    assert not result.ok
    assert "query" in (result.error or "")


def test_search_files_non_tocca_il_filesystem(workspace, config) -> None:
    """Read-only per contratto: il contenuto del file resta identico."""
    target = workspace / "intatto.md"
    target.write_text("contenuto originale\n", encoding="utf-8")

    _dispatch(config, {"query": "originale"})

    assert target.read_text(encoding="utf-8") == "contenuto originale\n"


# --- 1.6.6: containment per candidato (symlink verso l'esterno) -------------

def test_symlink_a_file_esterno_non_aperto(workspace, config, tmp_path) -> None:
    """Un symlink del workspace che punta a un file fuori non viene letto."""
    outside = tmp_path / "outside" / "secret.txt"  # "segreto\n", fuori dalle root
    link = workspace / "link_esterno.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink non supportati su questo sistema")

    result, _ = _dispatch(config, {"query": "segreto"})

    assert result.ok
    out = result.output or ""
    assert "Nessuna occorrenza" in out, out  # zero hit = il file fuori non è stato letto
    assert "secret.txt:" not in out, "il contenuto fuori root non deve comparire"


def test_symlink_a_cartella_esterna_non_percorsa(workspace, config, tmp_path) -> None:
    """Una symlink di cartella verso l'esterno non apre alcun contenuto fuori root."""
    outside = tmp_path / "outside"  # contiene secret.txt con "segreto"
    link = workspace / "collega_esterna"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink non supportati su questo sistema")

    result, _ = _dispatch(config, {"query": "segreto"})

    assert result.ok
    out = result.output or ""
    assert "Nessuna occorrenza" in out, out
    assert "secret.txt:" not in out, "nessuna hit dal contenuto esterno"


def test_file_normale_trovato_nonostante_symlink(workspace, config, tmp_path) -> None:
    """I symlink esterni saltati, il file regolare dentro le root viene trovato."""
    (workspace / "pubblico.txt").write_text("marcatore trova_me_xyz\n", encoding="utf-8")
    try:
        (workspace / "link_file.txt").symlink_to(tmp_path / "outside" / "secret.txt")
        (workspace / "link_dir").symlink_to(tmp_path / "outside", target_is_directory=True)
    except OSError:
        pytest.skip("symlink non supportati su questo sistema")

    result, _ = _dispatch(config, {"query": "trova_me_xyz"})

    assert result.ok
    out = result.output or ""
    assert "pubblico.txt:1: marcatore trova_me_xyz" in out
    assert "segreto" not in out, "niente contenuto dai link esterni"
