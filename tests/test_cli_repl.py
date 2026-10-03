"""Test 1.6.4: comandi REPL /reset, /save <nome> e /load <nome>."""

from __future__ import annotations

import json

from agent.cli import handle_repl_command
from agent.loop import SYSTEM_PROMPT


def _history() -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "ciao agente"},
        {"role": "assistant", "content": "risposta salvata"},
    ]


def test_reset_azzera_la_cronologia(config) -> None:
    history = _history()

    msg = handle_repl_command("/reset", history, config)

    assert msg is not None and "azzerata" in msg
    assert len(history) == 1, "resta solo il system prompt"
    assert history[0]["role"] == "system"
    assert history[0]["content"] == SYSTEM_PROMPT


def test_save_e_load_roundtrip(workspace, config) -> None:
    """save scrive JSON nella workspace; load ripristina i messaggi."""
    history = _history()

    msg = handle_repl_command("/save conversazione", history, config)
    target = workspace / "conversazione.json"
    assert msg is not None and "salvata" in msg
    assert target.exists()
    # il file è JSON valido e UTF-8
    assert json.loads(target.read_text(encoding="utf-8")) == history

    # si carica in una cronologia vuota: messaggi + system corrente
    loaded_history: list[dict] = []
    msg = handle_repl_command("/load conversazione", loaded_history, config)
    assert msg is not None and "caricata" in msg
    assert [m["role"] for m in loaded_history] == ["system", "user", "assistant"]
    assert loaded_history[1]["content"] == "ciao agente"
    assert loaded_history[0]["content"] == SYSTEM_PROMPT


def test_save_non_crea_path_fuori_dalla_root(workspace, config) -> None:
    """Niente traversal: il nome con separatori o .. viene rifiutato."""
    for nome in ("../fuori", "sub/dir", "sub\\dir", "..", "."):
        msg = handle_repl_command(f"/save {nome}", _history(), config)
        assert msg is not None
        assert "nome non valido" in msg, msg
    assert not (workspace.parent / "fuori.json").exists()
    assert list(workspace.glob("*.json")) == []


def test_save_senza_nome_mostra_l_uso(config) -> None:
    history = _history()
    msg = handle_repl_command("/save", history, config)
    assert msg == "Uso: /save <nome>"
    msg = handle_repl_command("/load", history, config)
    assert msg == "Uso: /load <nome>"


def test_load_file_mancante(workspace, config) -> None:
    history: list[dict] = []
    msg = handle_repl_command("/load assente", history, config)
    assert msg is not None
    assert "inesistente" in msg
    assert history == [], "un caricamento fallito non tocca la cronologia"
    assert not (workspace / "assente.json").exists()


def test_load_json_rotto(workspace, config) -> None:
    (workspace / "rotto.json").write_text("{non json", encoding="utf-8")
    history: list[dict] = []
    msg = handle_repl_command("/load rotto", history, config)
    assert msg is not None
    assert "JSON non valido" in msg
    assert history == [], "un JSON rotto non tocca la cronologia"


def test_load_struttura_non_lista(workspace, config) -> None:
    (workspace / "oggetto.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    history: list[dict] = []
    msg = handle_repl_command("/load oggetto", history, config)
    assert msg is not None
    assert "struttura non valida" in msg
    assert history == []


def test_load_filtra_messaggi_invalidi(workspace, config) -> None:
    """Ruoli sconosciuti o content non testuale vengono scartati, non rifiutati."""
    payload = [
        {"role": "system", "content": "vecchio system"},
        {"role": "alieno", "content": "x"},
        {"role": "user", "content": 42},
        {"role": "user", "content": "valido"},
        {"role": "assistant", "content": None},
    ]
    (workspace / "mescolato.json").write_text(json.dumps(payload), encoding="utf-8")
    history: list[dict] = []

    handle_repl_command("/load mescolato", history, config)

    assert [m["role"] for m in history] == ["system", "user", "assistant"]
    assert history[0]["content"] == SYSTEM_PROMPT, "system prompt sempre quello corrente"
    assert history[1]["content"] == "valido"


def test_comando_non_repl_torna_none(workspace, config) -> None:
    """Qualsiasi riga non gestita (es. una domanda) torna None → va al modello."""
    assert handle_repl_command("parlami del tempo", _history(), config) is None
    assert handle_repl_command("/help", _history(), config) is None
