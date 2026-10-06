"""Scenario e2e 1.8.1: un file richiesto senza nome → ask_user, niente invenzioni.

Marcato `e2e` ed escluso di default: richiede Ollama in esecuzione. Il successo
è: il tool ask_user viene chiamato e NON compaiono read_file/list_dir inventati
(il modello non indovina un nome di file che l'utente non gli ha dato).
"""

from __future__ import annotations

import pytest

from agent.security.confirm import ScriptedConfirm
from tests.e2e.test_e2e import _diag

pytestmark = pytest.mark.e2e


def test_file_richiesto_senza_nome(e2e_env, e2e_record, e2e_turn) -> None:
    """'Leggi il file di cui ti ho parlato': il modello deve CHIEDERE il nome."""
    e2e_record("chiedi_nome_file")
    root, _config, _llm = e2e_env
    # i file esistono davvero: se il modello li "indovina" non è merito di ask_user
    (root / "promemoria.txt").write_text("codice: ARANCE77\n", encoding="utf-8")
    (root / "spese.txt").write_text("totale: 42\n", encoding="utf-8")

    final, events, _ = e2e_turn(
        "Leggi il file di cui ti ho parlato.",
        e2e_env,
        ScriptedConfirm(default=True),  # ask → ASK_UNAVAILABLE, mai blocco
    )

    acts = [p for k, p in events if k == "act"]
    assert any(a.startswith("ask_user") for a in acts), (
        f"nessuna ask_user: {acts}\n{_diag(events, final)}"
    )
    inventati = [
        a
        for a in acts
        if a.startswith("read_file") or a.startswith("list_dir")
    ]
    assert not inventati, (
        f"il modello ha provato a leggere/elencare senza chiedere: {inventati}\n"
        f"{_diag(events, final)}"
    )
    assert final.strip(), f"risposta finale vuota\n{_diag(events, final)}"
