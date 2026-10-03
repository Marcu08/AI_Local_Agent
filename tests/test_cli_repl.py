"""Test 1.6.4/1.6.6: comandi REPL /reset, /save <nome> e /load <nome>.

Le conversazioni vivono in conversations_dir (default ~/.agent/conversations,
fuori dalle workspace_root) e /load valida lo schema per intero: un file
malformato dà errore chiaro senza toccare la cronologia.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.cli import _MAX_CONVERSATION_BYTES, _conversations_dir, handle_repl_command
from agent.config import AgentConfig
from agent.loop import SYSTEM_PROMPT


def _history() -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "ciao agente"},
        {"role": "assistant", "content": "risposta salvata"},
    ]


# --- /reset -----------------------------------------------------------------

def test_reset_azzera_la_cronologia(config) -> None:
    history = _history()

    msg = handle_repl_command("/reset", history, config)

    assert msg is not None and "azzerata" in msg
    assert len(history) == 1, "resta solo il system prompt"
    assert history[0]["role"] == "system"
    assert history[0]["content"] == SYSTEM_PROMPT


# --- /save e /load: posizione dei file ---------------------------------------

def test_save_e_load_roundtrip(workspace, config) -> None:
    """save scrive SENZA system nella cartella conversazioni; load lo rigenera."""
    history = _history()

    msg = handle_repl_command("/save conversazione", history, config)
    target = config.conversations_dir / "conversazione.json"
    assert msg is not None and "salvata" in msg
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == history[1:], "il messaggio di system non viene mai salvato"
    assert not list(workspace.glob("*.json")), "mai dentro la workspace"

    loaded_history: list[dict] = []
    msg = handle_repl_command("/load conversazione", loaded_history, config)
    assert msg is not None and "caricata" in msg
    assert [m["role"] for m in loaded_history] == ["system", "user", "assistant"]
    assert loaded_history[0]["content"] == SYSTEM_PROMPT, "system prompt corrente"
    assert loaded_history[1]["content"] == "ciao agente"


def test_save_vive_fuori_dalla_workspace(workspace, config) -> None:
    handle_repl_command("/save fuori", _history(), config)

    assert (config.conversations_dir / "fuori.json").exists()
    assert not list(workspace.rglob("*.json")), "nessun file nella workspace"


def test_conversazioni_dir_default(workspace) -> None:
    """Senza chiave in config: ~/.agent/conversations, mai sotto la workspace."""
    plain = AgentConfig(workspace_roots=(workspace,))

    default_dir = _conversations_dir(plain)

    assert default_dir == Path.home() / ".agent" / "conversations"
    assert not default_dir.is_relative_to(workspace.resolve())


def test_save_non_crea_path_fuori_dalla_root(config) -> None:
    """Niente traversal: il nome con separatori o .. viene rifiutato."""
    for nome in ("../fuori", "sub/dir", "sub\\dir", "..", "."):
        msg = handle_repl_command(f"/save {nome}", _history(), config)
        assert msg is not None
        assert "nome non valido" in msg, msg
    assert not config.conversations_dir.exists(), "nessuna cartella creata"


def test_save_senza_nome_mostra_l_uso(config) -> None:
    history = _history()
    msg = handle_repl_command("/save", history, config)
    assert msg == "Uso: /save <nome>"
    msg = handle_repl_command("/load", history, config)
    assert msg == "Uso: /load <nome>"


# --- /load: errori senza crash e senza toccare la cronologia -----------------

def test_load_file_mancante(config) -> None:
    history: list[dict] = []
    msg = handle_repl_command("/load assente", history, config)
    assert msg is not None
    assert "inesistente" in msg
    assert history == []
    assert not (config.conversations_dir / "assente.json").exists()


def test_load_json_rotto(config) -> None:
    config.conversations_dir.mkdir(parents=True)
    (config.conversations_dir / "rotto.json").write_text("{non json", encoding="utf-8")
    history = _history()

    msg = handle_repl_command("/load rotto", history, config)

    assert msg is not None
    assert "JSON non valido" in msg
    assert history == _history(), "un JSON rotto non tocca la cronologia"


def test_load_struttura_non_lista(config) -> None:
    config.conversations_dir.mkdir(parents=True)
    (config.conversations_dir / "oggetto.json").write_text(
        json.dumps({"a": 1}), encoding="utf-8"
    )
    history = _history()

    msg = handle_repl_command("/load oggetto", history, config)

    assert msg is not None
    assert "struttura non valida" in msg or "elenco di messaggi" in msg
    assert history == _history()


# --- /load: schema rigoroso (1.6.6) ------------------------------------------

@pytest.mark.parametrize(
    ("payload", "atteso"),
    [
        ([{"role": "system", "content": "vecchio prompt"}], "system"),
        ([{}], "role"),
        ([{"role": "user"}], "content"),
        ([{"role": "user", "content": 42}], "content"),
        ([{"role": "alieno", "content": "x"}], "ruolo"),
        ([{"role": "assistant", "content": "x", "tool_calls": []}], "tool_calls"),
        ([{"role": "assistant", "content": "x", "tool_calls": "no"}], "tool_calls"),
        (
            [{"role": "assistant", "content": "x", "tool_calls": [{"function": {"name": "t"}}]}],
            "arguments",
        ),
        (
            [
                {
                    "role": "assistant",
                    "content": "x",
                    "tool_calls": [{"function": {"name": "", "arguments": "{}"}}],
                }
            ],
            "name",
        ),
        (
            [
                {
                    "role": "user",
                    "content": "x",
                    "tool_calls": [{"function": {"name": "t", "arguments": "{}"}}],
                }
            ],
            "tool_calls",
        ),
        ([{"role": "tool", "content": "x", "tool_name": 5}], "tool_name"),
    ],
)
def test_load_rifiuta_file_malformato(config, payload: list, atteso: str) -> None:
    """Ruolo system, campi mancanti o tool_calls rotte: errore chiaro, zero crash."""
    config.conversations_dir.mkdir(parents=True)
    (config.conversations_dir / "malformato.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    history = _history()

    msg = handle_repl_command("/load malformato", history, config)

    assert msg is not None
    assert msg.startswith("Caricamento fallito"), msg
    assert atteso in msg, msg
    assert history == _history(), "cronologia intatta dopo il rifiuto"


def test_load_rifiuta_file_enorme(config) -> None:
    """Oltre il limite di dimensione: rifiuto prima ancora di fare il parsing."""
    config.conversations_dir.mkdir(parents=True)
    (config.conversations_dir / "enorme.json").write_bytes(
        b"x" * (_MAX_CONVERSATION_BYTES + 1)
    )
    history = _history()

    msg = handle_repl_command("/load enorme", history, config)

    assert msg is not None
    assert "troppo grande" in msg
    assert history == _history()


def test_load_accetta_schema_valido_con_tool_calls(config) -> None:
    """Il formato prodotto dal loop (tool_calls di assistant) caricato senza errori."""
    config.conversations_dir.mkdir(parents=True)
    payload = [
        {"role": "user", "content": "elenca"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "list_dir", "arguments": '{"path": "."}'}}],
        },
        {"role": "tool", "content": "elenco", "tool_name": "list_dir"},
        {"role": "assistant", "content": "fatto"},
    ]
    (config.conversations_dir / "buona.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    history: list[dict] = []

    msg = handle_repl_command("/load buona", history, config)

    assert msg is not None and "caricata" in msg
    assert [m["role"] for m in history] == ["system", "user", "assistant", "tool", "assistant"]


# --- comandi non REPL --------------------------------------------------------

def test_comando_non_repl_torna_none(config) -> None:
    """Qualsiasi riga non gestita (es. una domanda) torna None → va al modello."""
    assert handle_repl_command("parlami del tempo", _history(), config) is None
    assert handle_repl_command("/help", _history(), config) is None
