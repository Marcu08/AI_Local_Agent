"""Fixture e hook della Fase 1.7: modelli reali, reachability e report JSONL.

Questi test sono marcati `e2e` e quindi ESCLUSI di default (`-m "not e2e"`).
Non scaricano modelli: richiedono un server Ollama già in esecuzione, altrimenti
tutti gli scenari si skippano con un messaggio esplicito.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from typing import Any

import pytest

from agent.config import AgentConfig, LLMConfig
from agent.loop import SYSTEM_PROMPT, run_turn
from agent.security.confirm import ScriptedConfirm
from agent.tools import create_default_registry
from scripts.run_eval import warm_up


# modello scelto da --e2e-models / AGENT_E2E_MODELS; default = quello di config
def _requested_models(config: pytest.Config) -> list[str]:
    raw = config.getoption("--e2e-models") or "llama3.1:8b"
    models = [m.strip() for m in raw.split(",") if m.strip()]
    return models or ["llama3.1:8b"]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "model" in metafunc.fixturenames:
        metafunc.parametrize("model", _requested_models(metafunc.config))


@pytest.fixture(scope="session")
def ollama_base() -> str:
    """Base URL del server; skip di sessione se non raggiungibile (nessun modello scaricato)."""
    base = os.environ.get("AGENT_E2E_BASE_URL") or "http://localhost:11434"
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=3):
            pass
    except Exception as e:  # URLError, timeout, connessione rifiutata, HTTPError...
        pytest.skip(
            f"Ollama non raggiungibile su {base} ({e}): avvia il server con i modelli "
            "già scaricati e rilancia (nessun download viene fatto qui)"
        )
    return base


@pytest.fixture(scope="session")
def _warmed_models(ollama_base: str, request: pytest.FixtureRequest) -> None:
    """1.7c: carica ogni modello richiesto PRIMA del primo scenario.

    Stesso warm-up di run_eval (chiamata minima con keep_alive lungo, non
    fatale): anche un `pytest -m e2e` eseguito senza run_eval non fa pagare
    al primo scenario il caricamento a freddo del modello.
    """
    for model in _requested_models(request.config):
        warm_up(ollama_base, model)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[Any]
) -> Generator[Any, Any, None]:
    """Conserva l'esito della fase call sul item, per il record del teardown."""
    outcome: Any = yield
    report = outcome.get_result()
    if report.when == "call":
        setattr(item, "_e2e_call_report", report)


def _concise_error(report: Any) -> str:
    """Riga d'errore leggibile per EVAL: la prima 'E ...' con assert/Error.

    `longreprtext` completo può essere migliaia di righe (HTML, traceback):
    per il report basta la riga che dice cosa è andato storto, con il resto
    della coda come fallback.
    """
    lines = [ln.strip() for ln in report.longreprtext.splitlines() if ln.strip()]
    for line in lines:
        if line.startswith("E ") and (
            "Error" in line or "assert" in line or "Limite" in line
        ):
            return line[:400]
    return report.longreprtext[-600:]


class ScenarioRecorder:
    """Registra scenario (chiamata) e fatti aggiuntivi (1.7b, metodo `note`).

    I fatti passati a `note` finiscono nel record JSONL accanto a ok/seconds:
    servono a separare, in fase di diagnosi, il controllo sugli atti (gli assert
    del test) da ciò che è effettivamente arrivato nella risposta finale.
    """

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state

    def __call__(self, scenario: str) -> None:
        self._state["scenario"] = scenario

    def note(self, key: str, value: Any) -> None:
        """Annota un fatto sullo scenario corrente (es. contenuto in finale)."""
        self._state[key] = value


def _build_entry(
    state: dict[str, Any], model: str, seconds: float, report: Any
) -> dict[str, Any]:
    """Riga JSONL dello scenario: esito, tempi e i fatti annotati con .note().

    I fatti (es. `final_content`: il contenuto atteso compare nella risposta
    finale) restano CHI separati dall'esito complessivo in `ok`: così un record
    fallito dice anche se il modello ha almeno riportato il contenuto.
    """
    entry: dict[str, Any] = {
        "model": model,
        "scenario": str(state.get("scenario")),
        "ok": bool(report is not None and report.passed),
        "seconds": round(seconds, 2),
    }
    for key, value in state.items():
        if key != "scenario":
            entry[key] = value
    if report is not None and report.failed:
        entry["error"] = _concise_error(report)
    return entry


@pytest.fixture
def e2e_record(
    model: str, request: pytest.FixtureRequest
) -> Iterator[ScenarioRecorder]:
    """Registra esito/tempi/fatti dello scenario corrente su --e2e-json (JSONL).

    Il record viene scritto nel teardown (dopo la fase call), quindi `ok` è
    l'esito reale del test; se il test è saltato al setup non si scrive nulla.
    """
    config_path = request.config.getoption("--e2e-json") or ""
    started = time.perf_counter()
    state: dict[str, Any] = {"scenario": None}
    recorder = ScenarioRecorder(state)

    yield recorder

    scenario = state["scenario"]
    if scenario is None or not config_path:
        return
    report = getattr(request.node, "_e2e_call_report", None)
    entry = _build_entry(state, model, time.perf_counter() - started, report)
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


@pytest.fixture
def e2e_env(
    model: str, ollama_base: str, tmp_path: Path, _warmed_models: None
) -> tuple[Path, AgentConfig, Any]:
    """Workspace sintetico + config con modello reale + client Ollama (lazy import)."""
    from agent.llm.ollama_client import OllamaClient  # import pigro: niente ollama alla collection

    root = tmp_path / "workspace"
    root.mkdir()
    config = AgentConfig(
        workspace_roots=(root,),
        llm=LLMConfig(model=model, base_url=ollama_base),
        conversations_dir=tmp_path / "conversations",
    )
    return root, config, OllamaClient(config.llm)


def _events_trace(events: list[tuple[str, str]]) -> str:
    """Traccia act/observation del turno da allegare a un assert fallito (1.7b)."""
    rows = []
    for kind, payload in events:
        if kind not in {"act", "observation"}:
            continue
        text = payload if len(payload) <= 400 else payload[:400] + "... [troncato]"
        rows.append(f"  [{kind}] {text}")
    return "eventi del turno:\n" + ("\n".join(rows) if rows else "  (nessuno)")


def _run_turn(
    user_input: str,
    env: tuple[Path, AgentConfig, Any],
    confirm: ScriptedConfirm,
) -> tuple[str, list[tuple[str, str]], Path]:
    """Un turno ReAct completo col modello reale; ritorna (finale, eventi, root)."""
    root, config, llm = env
    history: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    events: list[tuple[str, str]] = []
    final = run_turn(
        user_input,
        history=history,
        llm=llm,
        registry=create_default_registry(),
        config=config,
        confirm=confirm,
        on_event=lambda kind, payload: events.append((kind, payload)),
    )
    assert not final.startswith("Limite di iterazioni"), (
        f"loop non terminato: {final}\n{_events_trace(events)}"
    )
    return final, events, root


@pytest.fixture
def e2e_turn() -> Callable[..., tuple[str, list[tuple[str, str]], Path]]:
    """Helper iniettabile nei test (i test non importano i conftest)."""
    return _run_turn
