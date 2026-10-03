"""Test del loop ReAct con LLM mock: nessuna rete, nessun Ollama vivo."""

from __future__ import annotations

from agent.config import AgentConfig
from agent.llm.mock_client import MockClient, final_response, tool_call_response
from agent.loop import SYSTEM_PROMPT, run_turn
from agent.security.confirm import ScriptedConfirm
from agent.tools import create_default_registry


def _history() -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def test_tool_call_osservazione_risposta_finale(workspace, config) -> None:
    llm = MockClient(
        [tool_call_response("list_dir", path="."), final_response("Ecco i file.")]
    )
    registry = create_default_registry()
    events: list[tuple[str, str]] = []
    history = _history()

    answer = run_turn(
        "elenca i file",
        history=history,
        llm=llm,
        registry=registry,
        config=config,
        confirm=ScriptedConfirm(default=True),
        on_event=lambda kind, payload: events.append((kind, payload)),
    )

    assert answer == "Ecco i file."
    kinds = [kind for kind, _ in events]
    assert "act" in kinds
    assert "observation" in kinds
    assert kinds[-1] == "final"

    roles = [msg["role"] for msg in history]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    tool_msg = history[3]
    assert tool_msg["tool_name"] == "list_dir"
    assert "notes.md" in tool_msg["content"]

    # i tool schemas devono essere passati al LLM nel primo turno
    first_call = llm.received[0]
    assert first_call["tools"], "nessun tool schema passato al LLM"
    names = {schema["function"]["name"] for schema in first_call["tools"]}
    assert {"list_dir", "read_file", "write_file", "run_command", "search_memory"} <= names


def test_scrittura_rifiutata_file_assente(workspace, config) -> None:
    llm = MockClient(
        [
            tool_call_response("write_file", path="nuovo.txt", content="ciao"),
            final_response("Ok, annullato."),
        ]
    )
    registry = create_default_registry()
    deny = ScriptedConfirm(default=False)
    history = _history()

    answer = run_turn(
        "scrivi un file",
        history=history,
        llm=llm,
        registry=registry,
        config=config,
        confirm=deny,
    )

    assert answer == "Ok, annullato."
    assert not (workspace / "nuovo.txt").exists()
    assert len(deny.calls) == 1
    tool_msg = next(msg for msg in history if msg["role"] == "tool")
    assert "rifiutata" in tool_msg["content"]


def test_scrittura_confermata_file_creato(workspace, config) -> None:
    llm = MockClient(
        [
            tool_call_response("write_file", path="ok.txt", content="si"),
            final_response("Fatto."),
        ]
    )
    registry = create_default_registry()
    history = _history()

    run_turn(
        "scrivi",
        history=history,
        llm=llm,
        registry=registry,
        config=config,
        confirm=ScriptedConfirm(default=True),
    )

    assert (workspace / "ok.txt").read_text(encoding="utf-8") == "si"


def test_max_iterations_rispettato(workspace) -> None:
    config = AgentConfig(workspace_roots=(workspace,), max_iterations=2)
    # il "modello" chiede sempre tool: deve fermarsi al limite
    llm = MockClient([tool_call_response("list_dir", path=".")])
    registry = create_default_registry()
    events: list[tuple[str, str]] = []
    history = _history()

    answer = run_turn(
        "loop infinito",
        history=history,
        llm=llm,
        registry=registry,
        config=config,
        confirm=ScriptedConfirm(default=True),
        on_event=lambda kind, payload: events.append((kind, payload)),
    )

    assert "Limite di iterazioni" in answer
    assert llm.calls == 2
    assert events[-1][0] == "limit"
    assert [msg["role"] for msg in history].count("tool") == 2


def test_tool_sconosciuto_non_interrompe(workspace, config) -> None:
    llm = MockClient(
        [
            tool_call_response("rettangolo", lato=3),
            final_response("Il tool non esiste, mi scuso."),
        ]
    )
    registry = create_default_registry()
    history = _history()

    answer = run_turn(
        "usa un tool inventato",
        history=history,
        llm=llm,
        registry=registry,
        config=config,
        confirm=ScriptedConfirm(default=True),
    )

    assert answer == "Il tool non esiste, mi scuso."
    tool_msg = next(msg for msg in history if msg["role"] == "tool")
    assert "sconosciuto" in tool_msg["content"]


def test_risposta_senza_tool(workspace, config) -> None:
    llm = MockClient([final_response("Risposta diretta.")])
    registry = create_default_registry()
    history = _history()

    answer = run_turn(
        "ciao",
        history=history,
        llm=llm,
        registry=registry,
        config=config,
        confirm=ScriptedConfirm(default=True),
    )

    assert answer == "Risposta diretta."
    assert len(history) == 3  # system + user + assistant
