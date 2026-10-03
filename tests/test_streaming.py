"""Test 1.6.3: streaming dei delta con fallback non-stream per i test."""

from __future__ import annotations

import sys
import types
from collections.abc import Callable, Sequence
from io import StringIO
from typing import Any

import pytest
from rich.console import Console

from agent.cli import make_on_event
from agent.llm.base import LLMError, LLMResponse
from agent.llm.mock_client import MockClient, final_response
from agent.loop import SYSTEM_PROMPT, run_turn
from agent.security.confirm import ScriptedConfirm
from agent.tools import create_default_registry


def _history() -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}]


class _StreamClient:
    """Client di test che emette i frammenti come farebbe Ollama in stream."""

    def __init__(self, chunks: list[str], final_text: str) -> None:
        self.chunks = chunks
        self.final_text = final_text
        self.saw_on_delta = False

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        assert on_delta is not None, "il loop deve passare on_delta ai client stream"
        self.saw_on_delta = True
        for chunk in self.chunks:
            on_delta(chunk)
        return LLMResponse(text=self.final_text, tool_calls=[])


def test_loop_emette_delta_e_finale(workspace, config) -> None:
    """Il loop inoltra ogni frammento come evento e conserva la risposta finale."""
    events: list[tuple[str, str]] = []
    client = _StreamClient(["Cia", "o mon", "do"], "Ciao mondo")

    answer = run_turn(
        "saluta",
        history=_history(),
        llm=client,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(default=False),
        on_event=lambda kind, payload: events.append((kind, payload)),
    )

    assert answer == "Ciao mondo"
    assert client.saw_on_delta
    assert [payload for kind, payload in events if kind == "delta"] == [
        "Cia",
        "o mon",
        "do",
    ]
    assert events[-1] == ("final", "Ciao mondo")


def test_mock_client_fallback_non_stream(workspace, config) -> None:
    """Fallback per i test: MockClient non produce alcun delta."""
    events: list[tuple[str, str]] = []
    mock = MockClient([final_response("risposta secca")])

    answer = run_turn(
        "ciao",
        history=_history(),
        llm=mock,
        registry=create_default_registry(),
        config=config,
        confirm=ScriptedConfirm(default=False),
        on_event=lambda kind, payload: events.append((kind, payload)),
    )

    assert answer == "risposta secca"
    assert [kind for kind, _ in events] == ["final"], "nessun evento delta"


def test_cli_rendering_streaming_non_duplica_il_testo() -> None:
    """Thought e final già mostrati dai delta non vengono ridisegnati."""
    buf = StringIO()
    console = Console(file=buf, width=100)
    on_event = make_on_event(console)

    # risposta 1: streamata in live → il thought non va in pannello
    on_event("delta", "sto pen")
    on_event("delta", "sando")
    on_event("thought", "sto pensando")
    on_event("act", "read_file(path=nota.md)")
    on_event("observation", "1: contenuto")
    # risposta 2: streamata in live → il final non va in pannello
    on_event("delta", "ecco fi")
    on_event("delta", "nito")
    on_event("final", "ecco finito")

    out = buf.getvalue()
    assert out.count("sto pensando") == 1, "thought streamato, nessun pannello"
    assert out.count("ecco finito") == 1, "final streamato, nessun pannello"
    assert "Act:" in out and "Observation:" in out
    assert "Risposta" not in out, "nessun pannello finale duplicato"


def test_cli_final_senza_delta_dopo_uno_stream_stampa_il_pannello() -> None:
    """Solo la risposta streamata salta il pannello: un final non-streamato
    (nessun delta prima di lui) continua a usare il pannello classico."""
    buf = StringIO()
    console = Console(file=buf, width=100)
    on_event = make_on_event(console)

    on_event("delta", "pensie")
    on_event("delta", "ro lungo")
    on_event("thought", "pensiero lungo")
    on_event("act", "list_dir(path=.)")
    on_event("observation", "[F] notes.md")
    on_event("final", "risposta secca")

    out = buf.getvalue()
    assert out.count("pensiero lungo") == 1, "il thought streamato non si duplica"
    assert out.count("risposta secca") == 1
    assert "Risposta" in out, "il final non streamato resta un pannello"


def test_cli_rendering_senza_stream_usa_i_pannelli() -> None:
    """Fallback non-stream: thought e final restano pannelli come prima."""
    buf = StringIO()
    console = Console(file=buf, width=100)
    on_event = make_on_event(console)

    on_event("thought", "sto pensando")
    on_event("final", "ecco la risposta")

    out = buf.getvalue()
    assert "sto pensando" in out
    assert "ecco la risposta" in out
    assert "Risposta" in out, "il pannello finale ha ancora il suo titolo"


# --- OllamaClient: stream=True solo con on_delta (lib finta via sys.modules) ---
class _FakeOllamaClient:
    """Client ollama finto: registra i kwargs e restituisce risposta/chunk."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def chat(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if not kwargs.get("stream"):
            return {"message": {"content": "risposta intera", "tool_calls": []}}

        def gen():
            yield {"message": {"content": "Cia"}}
            yield {"message": {"content": "o"}}
            yield {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "list_dir", "arguments": {"path": "."}}}
                    ],
                },
                "done": True,
            }

        return gen()


def _ollama_client(monkeypatch: pytest.MonkeyPatch):
    from agent.config import LLMConfig
    from agent.llm.ollama_client import OllamaClient

    fake_client = _FakeOllamaClient()
    monkeypatch.setitem(
        sys.modules, "ollama", types.SimpleNamespace(Client=lambda **_kw: fake_client)
    )
    return OllamaClient(LLMConfig(model="finto")), fake_client


def test_ollama_stream_true_accumula_e_distribuisce(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con on_delta: stream=True, frammenti consegnati, testo e tool call accumulati."""
    client, fake = _ollama_client(monkeypatch)
    deltas: list[str] = []

    response = client.chat([{"role": "user", "content": "hi"}], on_delta=deltas.append)

    assert fake.kwargs["stream"] is True
    assert deltas == ["Cia", "o"]
    assert response.text == "Ciao"
    assert response.has_tool_calls
    assert response.tool_calls[0].name == "list_dir"
    assert response.tool_calls[0].arguments == {"path": "."}


def test_ollama_senza_on_delta_rest_non_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback: nessun on_delta → stream=False, chiamata singola."""
    client, fake = _ollama_client(monkeypatch)

    response = client.chat([{"role": "user", "content": "hi"}])

    assert fake.kwargs["stream"] is False
    assert response.text == "risposta intera"


def test_ollama_errore_in_stream_diventa_llmerror(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un errore a metà stream resta un LLMError (il loop non vede eccezioni)."""
    from agent.config import LLMConfig
    from agent.llm.ollama_client import OllamaClient

    class _Broken:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def chat(self, **kwargs: Any) -> Any:
            def gen():
                yield {"message": {"content": "parziale"}}
                raise OSError("connessione persa")

            return gen()

    monkeypatch.setitem(sys.modules, "ollama", types.SimpleNamespace(Client=_Broken))
    client = OllamaClient(LLMConfig(model="finto"))

    with pytest.raises(LLMError, match="connessione persa"):
        client.chat([{"role": "user", "content": "hi"}], on_delta=lambda _c: None)
