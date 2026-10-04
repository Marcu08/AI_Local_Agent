"""1.7b: parti diagnostiche dell'harness e2e, verificabili SENZA Ollama.

Due meccanismi stanno nei test della Fase 1.7 ma non servono un modello:
1. `_diag` / `_events_trace`: la traccia act+observation allegata a ogni assert
   del turno, così un fallimento si capisce senza rilanciare lo scenario;
2. `ScenarioRecorder.note` + `_build_entry`: il fatto "contenuto atteso nella
   risposta finale" registrato sul JSONL `final_content`, separato dal controllo
   sugli atti (campo `ok`).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from tests.e2e.conftest import ScenarioRecorder, _build_entry, _events_trace
from tests.e2e.test_e2e import _diag

_EVENTS: list[tuple[str, str]] = [
    ("thought", "devo leggere il promemoria"),
    ("act", 'read_file({"path": "promemoria.txt"})'),
    ("observation", '<tool_output untrusted="true">\ncodice: ARANCE77\n</tool_output>'),
    ("final", "Il codice è ARANCE77"),
]


def test_diag_elenca_act_e_observation() -> None:
    """La traccia contiene gli atti e le osservazioni, non i pensieri."""
    trace = _diag(_EVENTS, "Il codice è ARANCE77")
    assert "[act] read_file" in trace
    assert "[observation]" in trace and "ARANCE77" in trace
    assert "risposta finale" in trace
    assert "devo leggere" not in trace  # i thought non fanno parte della traccia


def test_diag_tronca_i_payload_lunghi() -> None:
    """Osservazioni enormi non seppelliscono il messaggio d'errore."""
    trace = _diag([("observation", "x" * 5000)])
    assert "[troncato]" in trace
    assert len(trace) < 700


def test_diag_senza_eventi_lo_dichiara() -> None:
    """Turno finito senza atti: la traccia non è vuota e basta."""
    trace = _diag([("final", "risposta senza atti")], "risposta senza atti")
    assert "(nessuno)" in trace
    assert "risposta finale" in trace


def test_events_trace_del_conftest_copre_lo_stesso_perimetro() -> None:
    """L'assert 'Limite di iterazioni' in _run_turn usa la stessa traccia."""
    trace = _events_trace(_EVENTS)
    lines = trace.splitlines()
    assert lines[0] == "eventi del turno:"
    tagged = [line for line in lines[1:] if line.startswith("  [")]
    assert tagged, lines  # act e observation ci sono
    assert all(
        line.startswith("  [act]") or line.startswith("  [observation]") for line in tagged
    ), lines


def test_note_registra_il_contenuto_in_finale_separato_da_ok() -> None:
    """`final_content` è un campo distinto dall'esito: entrambi finiscono sul JSONL."""
    state: dict[str, Any] = {"scenario": None}
    recorder = ScenarioRecorder(state)
    recorder("lettura_file")
    recorder.note("final_content", False)  # tool usato ma contenuto non riportato

    report = SimpleNamespace(passed=True, failed=False, longreprtext="")
    entry = _build_entry(state, "fake:model", 1.25, report)

    assert entry["scenario"] == "lettura_file"
    assert entry["final_content"] is False
    assert entry["ok"] is True  # l'esito del test resta un campo a sé
    assert entry["seconds"] == 1.25
    json.dumps(entry)  # la riga deve restare serializzabile


def test_record_fallito_con_contenuto_presente_distingue_le_cause() -> None:
    """Atti mancanti ma contenuto nella risposta: il record lo dice esplicitamente."""
    state: dict[str, Any] = {"scenario": "task_multipasso", "final_content": True}
    report = SimpleNamespace(
        passed=False,
        failed=True,
        longreprtext="E AssertionError: manca il passo 2 (lettura)\n",
    )

    entry = _build_entry(state, "fake:model", 0.5, report)

    assert entry["ok"] is False
    assert entry["final_content"] is True
    assert "manca il passo 2" in entry["error"]


def test_entry_senza_note_non_aggiunge_campi() -> None:
    """Nessuna .note() → record identico a quello della Fase 1.7."""
    state: dict[str, Any] = {"scenario": "elenco_cartella"}
    entry = _build_entry(state, "fake:model", 0.5, None)
    assert set(entry) == {"model", "scenario", "ok", "seconds"}
