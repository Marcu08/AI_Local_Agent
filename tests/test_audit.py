"""Test 1.5.5: audit JSONL — una riga per tool call, ogni ramo, nessun contenuto completo."""

from __future__ import annotations

import json
from pathlib import Path

from agent.llm.mock_client import MockClient, final_response, tool_call_response
from agent.loop import SYSTEM_PROMPT, run_turn
from agent.security.audit import AuditLog, default_audit_path
from agent.security.confirm import ScriptedConfirm
from agent.tools import create_default_registry

_FIELDS = {"ts", "tool", "args", "decisione", "esito", "durata_ms"}


def _history() -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def _lines(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    return [json.loads(row) for row in raw.splitlines() if row]


def test_rami_auto_bloccato_rifiutato(workspace, config, tmp_path) -> None:
    """Un solo turno produce le righe attese: auto/ok, bloccato, rifiutato."""
    audit = AuditLog(tmp_path / "audit.jsonl")
    llm = MockClient(
        [
            tool_call_response("list_dir", path="."),
            tool_call_response("run_command", command="del *.*"),
            tool_call_response("write_file", path="nuovo.txt", content="x"),
            final_response("Finito."),
        ]
    )

    answer = run_turn(
        "via",
        history=_history(),
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(default=False),
        audit=audit,
    )

    assert answer == "Finito."
    lines = _lines(audit.path)
    assert [row["tool"] for row in lines] == ["list_dir", "run_command", "write_file"]
    assert [(row["decisione"], row["esito"]) for row in lines] == [
        ("auto", "ok"),  # eseguito senza gate (lettura)
        ("bloccato", "errore"),  # blacklist prima della conferma
        ("rifiutato", "errore"),  # utente dice NO
    ]
    assert lines[0]["args"] == {"path": "."}
    for row in lines:
        assert set(row) == _FIELDS
        assert row["ts"].endswith("Z"), "timestamp UTC"
        assert isinstance(row["durata_ms"], int) and row["durata_ms"] >= 0
    assert not (workspace / "nuovo.txt").exists(), "rifiutato = nessuna scrittura"


def test_rami_confermato_e_errore(workspace, config, tmp_path) -> None:
    """Confermato (scrittura approvata) ed errore (tool inesistente)."""
    audit = AuditLog(tmp_path / "audit.jsonl")
    llm = MockClient(
        [
            tool_call_response("write_file", path="ok.txt", content="si"),
            tool_call_response("rettangolo", lato=3),
            final_response("Fine."),
        ]
    )

    run_turn(
        "via",
        history=_history(),
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(default=True),
        audit=audit,
    )

    lines = _lines(audit.path)
    assert [(row["tool"], row["decisione"], row["esito"]) for row in lines] == [
        ("write_file", "confermato", "ok"),
        ("rettangolo", "auto", "errore"),  # nessun gate: fallito a valle
    ]
    assert (workspace / "ok.txt").read_text(encoding="utf-8") == "si"


def test_audit_mai_contenuto_completo(config, tmp_path) -> None:
    """Gli argomenti sono troncati: il contenuto completo non finisce nell'audit."""
    audit = AuditLog(tmp_path / "audit.jsonl")
    segreto = "SEGRETOMAXIMO" * 40
    llm = MockClient(
        [
            tool_call_response("write_file", path="denso.txt", content=segreto),
            final_response("Fatto."),
        ]
    )

    run_turn(
        "via",
        history=_history(),
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(default=True),
        audit=audit,
    )

    raw = audit.path.read_text(encoding="utf-8")
    assert segreto not in raw, "mai loggare il contenuto completo"
    entry = json.loads(raw.splitlines()[0])
    assert entry["args"]["path"] == "denso.txt"
    content_arg = entry["args"]["content"]
    assert content_arg.endswith("...[troncato]")
    assert len(content_arg) <= 140


def test_audit_opzionale_e_path_di_default(config, tmp_path) -> None:
    """audit=None non scrive nulla; il path di default è logs/audit.jsonl; I/O rotto non alza."""
    llm = MockClient([final_response("ok")])
    answer = run_turn(
        "ciao",
        history=_history(),
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(default=True),
    )
    assert answer == "ok"

    default = default_audit_path()
    assert default.name == "audit.jsonl"
    assert default.parent.name == "logs"
    assert default.parent.parent == Path(__file__).resolve().parent.parent

    # path non scrivibile: record() non deve mai far esplodere il turno
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    broken = AuditLog(blocker / "audit.jsonl")
    entry = {
        "tool": "list_dir",
        "arguments": {},
        "decision": "auto",
        "outcome": "ok",
        "duration_ms": 1,
    }
    broken.record(**entry)
    broken.record(**entry)  # seconda chiamata: nessuna eccezione, nessun retry
