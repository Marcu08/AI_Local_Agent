"""Test 1.6.1: edit_file — sostituzione univoca con diff, conferma e audit."""

from __future__ import annotations

import json

from agent.llm.mock_client import MockClient, final_response, tool_call_response
from agent.loop import SYSTEM_PROMPT, run_turn
from agent.security.audit import AuditLog
from agent.security.confirm import ScriptedConfirm
from agent.tools import ToolContext, ToolResult, create_default_registry


def _history() -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def _dispatch(config, args: dict, *, approve: bool) -> tuple[ToolResult, ScriptedConfirm]:
    confirm = ScriptedConfirm(default=approve)
    result = create_default_registry().dispatch(
        "edit_file", args, ToolContext(config=config, confirm=confirm)
    )
    return result, confirm


def test_edit_file_sostituzione_unica(workspace, config) -> None:
    """Happy path: occorrenza unica → diff mostrato, conferma, file aggiornato."""
    target = workspace / "app.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")

    result, confirm = _dispatch(
        config,
        {"path": "app.py", "old_str": "return 1", "new_str": "return 2"},
        approve=True,
    )

    assert result.ok, result.error
    assert target.read_text(encoding="utf-8") == "def f():\n    return 2\n"
    assert result.decision == "confermato"
    assert len(confirm.calls) == 1
    _action, detail = confirm.calls[0]
    assert "-    return 1" in detail, "il diff deve mostrare la riga tolta"
    assert "+    return 2" in detail, "il diff deve mostrare la riga aggiunta"
    assert "app.py" in detail


def test_edit_file_zero_occorrenze_errore(workspace, config) -> None:
    """0 occorrenze: errore chiaro, nessuna conferma, file intatto."""
    target = workspace / "nota.txt"
    target.write_text("alpha beta\n", encoding="utf-8")

    result, confirm = _dispatch(
        config,
        {"path": "nota.txt", "old_str": "gamma", "new_str": "delta"},
        approve=True,
    )

    assert not result.ok
    assert "0 occorrenze" in (result.error or "")
    assert confirm.calls == [], "niente conferma se non c'è nulla da fare"
    assert target.read_text(encoding="utf-8") == "alpha beta\n"
    assert result.decision != "rifiutato", "è un errore di matching, non un rifiuto"


def test_edit_file_occorrenze_multiple_errore(workspace, config) -> None:
    """old_str ambigua: errore con il conteggio, nessuna sostituzione parziale."""
    target = workspace / "due.txt"
    target.write_text("x = 1\ny = 2\nx = 1\n", encoding="utf-8")

    result, confirm = _dispatch(
        config,
        {"path": "due.txt", "old_str": "x = 1", "new_str": "x = 99"},
        approve=True,
    )

    assert not result.ok
    assert "2 occorrenze" in (result.error or "")
    assert confirm.calls == []
    assert target.read_text(encoding="utf-8") == "x = 1\ny = 2\nx = 1\n"


def test_edit_file_rifiutato_file_invariato(workspace, config) -> None:
    """Conferma NO: decisione rifiutato, contenuto invariato."""
    target = workspace / "pr.txt"
    target.write_text("prima\n", encoding="utf-8")

    result, confirm = _dispatch(
        config,
        {"path": "pr.txt", "old_str": "prima", "new_str": "dopo"},
        approve=False,
    )

    assert not result.ok
    assert "rifiutata" in (result.error or "")
    assert result.decision == "rifiutato"
    assert len(confirm.calls) == 1
    assert target.read_text(encoding="utf-8") == "prima\n"


def test_edit_file_fuori_root_bloccato(config) -> None:
    """Path fuori workspace_root: bloccato prima di ogni lettura."""
    result, _confirm = _dispatch(
        config,
        {"path": "../../fuori.txt", "old_str": "a", "new_str": "b"},
        approve=True,
    )
    assert not result.ok
    assert result.decision == "bloccato"
    assert "PathNotAllowedError" in (result.error or "")


def test_edit_file_file_mancante_errore(workspace, config) -> None:
    """Nessuna creazione implicita: il file deve già esistere."""
    result, confirm = _dispatch(
        config,
        {"path": "assente.txt", "old_str": "a", "new_str": "b"},
        approve=True,
    )
    assert not result.ok
    assert "inesistente" in (result.error or "")
    assert confirm.calls == []
    assert not (workspace / "assente.txt").exists()


def test_edit_file_new_str_vuoto_cancella(workspace, config) -> None:
    """new_str vuota = rimozione della sola occorrenza."""
    target = workspace / "lungo.txt"
    target.write_text("inizio\nDA_CANCELLARE\nfine\n", encoding="utf-8")

    result, _confirm = _dispatch(
        config,
        {"path": "lungo.txt", "old_str": "DA_CANCELLARE\n", "new_str": ""},
        approve=True,
    )

    assert result.ok, result.error
    assert target.read_text(encoding="utf-8") == "inizio\nfine\n"


def test_edit_file_non_utf8_errore(workspace, config) -> None:
    """File non-UTF8: rifiuto esplicito invece di riscriverlo a pezzi."""
    target = workspace / "bin.dat"
    payload = bytes([0x80, 0x81, 0xFF, 0xFE])
    target.write_bytes(payload)

    result, confirm = _dispatch(
        config,
        {"path": "bin.dat", "old_str": "x", "new_str": "y"},
        approve=True,
    )

    assert not result.ok
    assert "UTF-8" in (result.error or "")
    assert confirm.calls == []
    assert target.read_bytes() == payload


def test_edit_file_riga_audit(workspace, config, tmp_path) -> None:
    """L'audit log registra edit_file come ogni altro tool (wiring generico)."""
    audit = AuditLog(tmp_path / "audit.jsonl")
    (workspace / "nota.txt").write_text("ciao mondo\n", encoding="utf-8")
    llm = MockClient(
        [
            tool_call_response("edit_file", path="nota.txt", old_str="mondo", new_str="terra"),
            final_response("Fatto."),
        ]
    )

    answer = run_turn(
        "via",
        history=_history(),
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(default=True),
        audit=audit,
    )

    assert answer == "Fatto."
    lines = [json.loads(row) for row in audit.path.read_text(encoding="utf-8").splitlines() if row]
    assert lines[0]["tool"] == "edit_file"
    assert lines[0]["decisione"] == "confermato"
    assert lines[0]["esito"] == "ok"
    assert (workspace / "nota.txt").read_text(encoding="utf-8") == "ciao terra\n"
