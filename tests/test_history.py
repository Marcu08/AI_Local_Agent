"""Test 1.5.6: limiti di cronologia — system primo, coppie mai orfane, coda riparata."""

from __future__ import annotations

from agent.config import AgentConfig
from agent.llm.mock_client import MockClient, final_response, tool_call_response
from agent.loop import SYSTEM_PROMPT, UNTRUSTED_OPEN, run_turn, trim_history
from agent.security.confirm import ScriptedConfirm
from agent.tools import create_default_registry


def _system() -> dict:
    return {"role": "system", "content": SYSTEM_PROMPT}


def _turn(index: int) -> list[dict]:
    """Un turno completo: user, assistant con 1 tool call, observation, finale."""
    return [
        {"role": "user", "content": f"domanda {index}"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "list_dir", "arguments": {"path": "."}}}
            ],
        },
        {"role": "tool", "content": f"osservazione {index}", "tool_name": "list_dir"},
        {"role": "assistant", "content": f"risposta {index}"},
    ]


def _assert_invariants(history: list[dict]) -> None:
    """system primo; ogni assistant con tool_calls ha tutte le sue observation."""
    assert history, "history vuota"
    assert history[0]["role"] == "system", "system deve restare primo"
    index = 1
    while index < len(history):
        message = history[index]
        if message["role"] == "assistant" and message.get("tool_calls"):
            expected = len(message["tool_calls"])
            seen = 0
            following = index + 1
            while following < len(history) and history[following]["role"] == "tool":
                seen += 1
                following += 1
            assert seen == expected, f"coppia orfana: {seen}/{expected} observation"
            index = following
        else:
            assert message["role"] != "tool", "observation senza il suo tool_call"
            index += 1


def _all_history(n_turns: int) -> list[dict]:
    history = [_system()]
    for i in range(n_turns):
        history.extend(_turn(i))
    return history


def test_trim_numero_messaggi() -> None:
    """Sotto il limite di messaggi: tolti i gruppi più vecchi, system intatto."""
    history = _all_history(10)  # 1 + 10*4 = 41 messaggi
    trim_history(history, max_messages=17, max_chars=10**9)
    assert len(history) == 17
    _assert_invariants(history)
    assert history[1]["content"] == "domanda 6", "i turni 0-5 sono i più vecchi"
    assert history[-1]["content"] == "risposta 9", "i turni recenti restano"


def test_trim_caratteri_totali() -> None:
    """Sotto il limite di caratteri (system incluso): tolti prima i più vecchi."""
    budget = len(SYSTEM_PROMPT) + 250
    history = [_system()]
    for i in range(10):
        history.append({"role": "user", "content": f"{i:02d}" + "a" * 98})

    trim_history(history, max_messages=10**9, max_chars=budget)

    _assert_invariants(history)
    assert sum(len(m["content"]) for m in history) <= budget
    assert [m["content"][:2] for m in history[1:]] == ["08", "09"], "solo i più recenti"


def test_coppie_mai_orfane_sotto_pressione() -> None:
    """Il taglio avviene per turno intero: la coppia con 2 observation esce tutta insieme."""
    turn_old = [
        {"role": "user", "content": "vecchio"},
        {"role": "assistant", "content": "risposta vecchia"},
    ]
    turn0 = [
        {"role": "user", "content": "primo"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": {"path": "a"}}},
                {"function": {"name": "list_dir", "arguments": {"path": "."}}},
            ],
        },
        {"role": "tool", "content": "obs 1", "tool_name": "read_file"},
        {"role": "tool", "content": "obs 2", "tool_name": "list_dir"},
        {"role": "assistant", "content": "fine primo"},
    ]
    turn1 = [
        {"role": "user", "content": "secondo"},
        {"role": "assistant", "content": "fine secondo"},
    ]
    history = [_system(), *turn_old, *turn0, *turn1]  # 10 messaggi

    # sotto il limite: cade il turno più vecchio, la coppia resta intera
    trim_history(history, max_messages=8, max_chars=10**9)
    _assert_invariants(history)
    assert len(history) == 8
    assert history[1]["content"] == "primo"
    assert [m["content"] for m in history if m["role"] == "tool"] == ["obs 1", "obs 2"]

    # pressione estrema: cade l'intero turno con la coppia, mai metà
    trim_history(history, max_messages=6, max_chars=10**9)
    _assert_invariants(history)
    assert len(history) == 3
    assert not any(m["role"] == "tool" for m in history)

    trim_history(history, max_messages=2, max_chars=10**9)
    _assert_invariants(history)
    assert history == [_system()]


def test_coda_riparata_osservazioni_mancanti() -> None:
    """Turno interrotto a metà: la coda incompleta viene completata, non lasciata orfana."""
    history = [
        _system(),
        {"role": "user", "content": "via"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": {"path": "a"}}},
                {"function": {"name": "list_dir", "arguments": {"path": "."}}},
            ],
        },
        {"role": "tool", "content": "obs 1", "tool_name": "read_file"},
    ]
    trim_history(history, max_messages=100, max_chars=10**9)
    _assert_invariants(history)
    assert len(history) == 5
    synthetic = history[-1]
    assert synthetic["role"] == "tool"
    assert synthetic["tool_name"] == "list_dir"
    assert synthetic["content"].startswith(UNTRUSTED_OPEN)
    assert "ERRORE" in synthetic["content"] and "turno interrotto" in synthetic["content"]


def test_coda_riparata_senza_osservazioni() -> None:
    """Interruzione subito dopo la tool call: nessuna observation in coda."""
    history = [
        _system(),
        {"role": "user", "content": "via"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "run_command", "arguments": {"command": "dir"}}}
            ],
        },
    ]
    trim_history(history, max_messages=100, max_chars=10**9)
    _assert_invariants(history)
    assert len(history) == 4
    assert history[-1]["tool_name"] == "run_command"
    assert "ERRORE" in history[-1]["content"]


def test_system_prompt_non_sostituibile(workspace) -> None:
    """Un input utente non può mai scavalcare il system neppure da solo."""
    history = [_system()]
    trim_history(history, max_messages=1, max_chars=1)
    assert history == [_system()]


def test_run_turn_trima_prima_dell_input(workspace) -> None:
    """Integrazione: run_turn accorcia la cronologia vecchia e mantiene gli invarianti."""
    config = AgentConfig(
        workspace_roots=(workspace,),
        history_max_messages=10,
        history_max_chars=10**9,
    )
    history = _all_history(8)  # 33 messaggi > 10
    llm = MockClient(
        [tool_call_response("list_dir", path="."), final_response("Risposta finale.")]
    )

    answer = run_turn(
        "ultima domanda",
        history=history,
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(default=True),
    )

    assert answer == "Risposta finale."
    _assert_invariants(history)
    assert not any(m.get("content") == "domanda 0" for m in history), "i vecchi vanno via"
    assert any(m.get("content") == "ultima domanda" for m in history), "l'input resta"
    # trim pre-append (≤10) + 4 messaggi prodotti dal turno corrente
    assert len(history) <= 14
