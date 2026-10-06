"""Test 1.8.1: tool ask_user — risposta, limiti, non-interattività, Ctrl+C.

Nessun input() reale: le risposte arrivano da ScriptedConfirm/monkeypatch,
come da convenzione dei test del progetto.
"""

from __future__ import annotations

import io
import json

from rich.console import Console

from agent.llm.mock_client import MockClient, final_response, tool_call_response
from agent.loop import SYSTEM_PROMPT, UNTRUSTED_OPEN, run_turn
from agent.security.audit import AuditLog
from agent.security.confirm import (
    ASK_INTERRUPTED,
    ASK_UNAVAILABLE,
    NonInteractiveConfirm,
    RichConfirmation,
    ScriptedConfirm,
)
from agent.tools import create_default_registry
from agent.tools.base import ToolContext

_Q = "Quale file vuoi che legga?"


def _ctx(config, confirm: ScriptedConfirm | None = None) -> tuple[ToolContext, ScriptedConfirm]:
    confirm = confirm or ScriptedConfirm()
    return ToolContext(config=config, confirm=confirm), confirm


def _dispatch(ctx: ToolContext, question: object = _Q):
    return create_default_registry().dispatch("ask_user", {"question": question}, ctx)


def test_risposta_normale(config) -> None:
    """Domanda valida → risposta dell'utente come output, decisione auto."""
    ctx, confirm = _ctx(config, ScriptedConfirm(ask_answers=["quello nuovo"]))

    result = _dispatch(ctx, _Q)

    assert result.ok, result.error
    assert result.output == "quello nuovo"
    assert result.decision is None  # audit → "auto"
    assert confirm.ask_calls == [_Q]


def test_domanda_mancante_o_non_stringa(config) -> None:
    """Senza 'question' (o con un non-stringa) errore d'uso con esempio e invito."""
    ctx, confirm = _ctx(config)

    for bad in (None, "", "   ", 42):
        result = create_default_registry().dispatch("ask_user", {"question": bad}, ctx)
        assert not result.ok
        assert "question" in (result.error or "")
        assert "Esempio d'uso" in (result.error or "")
        assert "Riprova" in (result.error or "")
    assert confirm.ask_calls == [], "nessuna domanda fatta con argomenti invalidi"


def test_domanda_troppo_lunga(config) -> None:
    """Oltre 300 caratteri → errore, e la risposta NON viene chiesta."""
    ctx, confirm = _ctx(config)

    result = _dispatch(ctx, "x" * 301)

    assert not result.ok
    assert "troppo lunga" in (result.error or "")
    assert "300" in (result.error or "")
    assert confirm.ask_calls == []


def test_limite_di_tre_domande_per_turno(config) -> None:
    """Le prime 3 chiamate passano, la quarta è un errore che invita a proseguire."""
    ctx, confirm = _ctx(config, ScriptedConfirm(ask_answers=["1", "2", "3"]))

    for _ in range(3):
        assert _dispatch(ctx).ok
    quarta = _dispatch(ctx)

    assert not quarta.ok
    assert "limite" in (quarta.error or "")
    assert "3 domande" in (quarta.error or "")
    assert "procedi" in (quarta.error or "")
    assert len(confirm.ask_calls) == 3, "la quarta chiamata non deve arrivare all'utente"


def test_limite_azzerrat_o_a_nuovo_turno(config) -> None:
    """Il contatore vive sul ToolContext: un nuovo turno (nuovo ctx) riparte."""
    ctx, confirm = _ctx(config, ScriptedConfirm(ask_answers=["a", "b", "c", "d"]))
    for _ in range(3):
        assert _dispatch(ctx).ok
    assert not _dispatch(ctx).ok

    nuovo_turno = ToolContext(config=config, confirm=confirm)
    assert _dispatch(nuovo_turno).ok, "un nuovo turno deve poter di nuovo chiedere"


def test_modalita_non_interattiva_non_blocca(config) -> None:
    """Demo/pipe: ask ritorna il segnale testuale, mai un blocco."""
    non_interattivo = NonInteractiveConfirm(default=True)

    assert non_interattivo.ask("Quale file?") == ASK_UNAVAILABLE
    assert non_interattivo.confirm("azione", "dettaglio") is True

    ctx = ToolContext(config=config, confirm=non_interattivo)
    result = _dispatch(ctx)
    assert result.ok
    assert result.output == ASK_UNAVAILABLE


def test_scripted_senza_risposte_non_blocca(config) -> None:
    """ScriptedConfirm senza ask_answers esaurite → ASK_UNAVAILABLE (mai input)."""
    ctx = ToolContext(config=config, confirm=ScriptedConfirm())

    result = _dispatch(ctx)

    assert result.ok
    assert result.output == ASK_UNAVAILABLE


def test_rich_ask_risposta_normale(monkeypatch) -> None:
    """La risposta digitata viene pulita (spazi) e ritornata."""
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "  note.md  ")
    rich = RichConfirmation(Console(file=io.StringIO()))

    assert rich.ask("Quale file?") == "note.md"


def test_ctrl_c_durante_lattesa_gestito_pulito(monkeypatch) -> None:
    """Ctrl+C durante l'attesa: nessuna eccezione, solo un segnale testuale."""

    def _interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", _interrupt)
    rich = RichConfirmation(Console(file=io.StringIO()))

    assert rich.ask("Quale file?") == ASK_INTERRUPTED


def test_rich_ask_eof_e_risposta_vuota(monkeypatch) -> None:
    """stdin chiuso o risposta vuota → nessuna risposta disponibile."""
    def _eof(*_args, **_kwargs):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    rich = RichConfirmation(Console(file=io.StringIO()))
    assert rich.ask("Quale file?") == ASK_UNAVAILABLE

    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "   ")
    assert rich.ask("Quale file?") == ASK_UNAVAILABLE


def _history() -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def test_osservazione_ask_user_non_avvolta(workspace, config) -> None:
    """La risposta dell'utente resta FUORI dal delimitatore untrusted."""
    llm = MockClient(
        [tool_call_response("ask_user", question=_Q), final_response("Ok, apro quello.")]
    )
    history = _history()

    answer = run_turn(
        "quale file leggo?",
        history=history,
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(ask_answers=["quello nuovo"]),
    )

    assert answer == "Ok, apro quello."
    tool_msg = next(msg for msg in history if msg["role"] == "tool")
    assert tool_msg["content"] == "quello nuovo"
    assert UNTRUSTED_OPEN not in tool_msg["content"], "input fidato: nessun wrapper"
    # nessun contenuto esterno visto → l'avviso nelle conferme non deve apparire
    assert tool_msg["tool_name"] == "ask_user"


def test_risposta_non_imposta_seen_untrusted(workspace, config) -> None:
    """Dopo ask_user la conferma di una scrittura NON mostra l'avviso esterno."""
    deny = ScriptedConfirm(answers=[False], ask_answers=["bozza.txt"], default=False)
    llm = MockClient(
        [
            tool_call_response("ask_user", question=_Q),
            tool_call_response("write_file", path="bozza.txt", content="ciao"),
            final_response("Annullato."),
        ]
    )

    run_turn(
        "scrivi il file",
        history=_history(),
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=deny,
    )

    assert len(deny.calls) == 1
    _action, detail = deny.calls[0]
    assert "contenuto esterno" not in detail, "ask_user non è contenuto esterno"


def test_turni_multipli_contano_le_domande_per_turno(workspace, config) -> None:
    """3 domande nel primo turno, la quarta del PRIMO turno è un errore, poi si riparte."""
    llm = MockClient(
        [
            tool_call_response("ask_user", question=_Q),
            tool_call_response("ask_user", question=_Q),
            tool_call_response("ask_user", question=_Q),
            tool_call_response("ask_user", question=_Q),  # 4ª: errore di limite
            final_response("Chiesto troppe volte, procedo."),
            tool_call_response("ask_user", question=_Q),
            final_response("Secondo turno ok."),
        ]
    )
    confirm = ScriptedConfirm(ask_answers=["a", "b", "c", "d"])
    history = _history()

    run_turn(
        "primo giro",
        history=history,
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=confirm,
    )
    tool_msgs = [msg for msg in history if msg["role"] == "tool"]
    assert tool_msgs[0]["content"] == "a"
    assert tool_msgs[3]["content"].startswith("ERRORE: limite"), tool_msgs[3]["content"]

    run_turn(
        "secondo giro",
        history=history,
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=confirm,
    )
    ultimo = [msg for msg in history if msg["role"] == "tool"][-1]
    assert ultimo["content"] == "d", "il contatore riparte a ogni turno"


def test_audit_registra_domanda_non_risposta(workspace, config, tmp_path) -> None:
    """Audit: decisione "auto", argomento = domanda, la risposta NON compare."""
    path = tmp_path / "audit.jsonl"
    llm = MockClient(
        [tool_call_response("ask_user", question=_Q), final_response("Ok.")]
    )

    run_turn(
        "chiedi",
        history=_history(),
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(ask_answers=["quello nuovo"]),
        audit=AuditLog(path=path),
    )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["tool"] == "ask_user"
    assert row["decisione"] == "auto"
    assert row["esito"] == "ok"
    assert row["args"]["question"] == _Q
    assert "quello nuovo" not in json.dumps(row["args"]), "la risposta non va nell'audit"


def test_audit_errore_di_limite_senza_eccezione(workspace, config, tmp_path) -> None:
    """La 4ª chiamata produce riga di audit con esito errore, decisione auto."""
    path = tmp_path / "audit.jsonl"
    llm = MockClient(
        [
            tool_call_response("ask_user", question=_Q),
            tool_call_response("ask_user", question=_Q),
            tool_call_response("ask_user", question=_Q),
            tool_call_response("ask_user", question=_Q),
            final_response("Basta così."),
        ]
    )

    run_turn(
        "troppe domande",
        history=_history(),
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(ask_answers=["1", "2", "3"]),
        audit=AuditLog(path=path),
    )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["esito"] for row in rows] == ["ok", "ok", "ok", "errore"]
    assert all(row["decisione"] == "auto" for row in rows)


def test_registro_contiene_ask_user_con_schema_stretto() -> None:
    """Registrato in create_default_registry con schema JSON valido e stringa maxLength."""
    registry = create_default_registry()
    tool = registry.get("ask_user")

    assert tool is not None
    assert "ask_user" in registry.names()
    schema = tool.parameters
    assert schema["type"] == "object"
    assert schema["required"] == ["question"]
    question = schema["properties"]["question"]
    assert question["type"] == "string"
    assert question["maxLength"] == 300
    assert "Esempio" in tool.description or "Esempio:" in tool.description
