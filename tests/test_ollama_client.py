"""Test del parser risposte Ollama: supporta dict legacy e pydantic (ollama>=0.6).

Qui si copre anche 1.7b: con un client Ollama FINTO (modulo finto in
sys.modules, nessuna rete) si verifica che le options inviate al server
contengano num_ctx oltre a num_predict.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from agent.config import LLMConfig
from agent.llm.ollama_client import OllamaClient, _parse_response


def _tool_call_ns(name: str, arguments) -> SimpleNamespace:  # noqa: ANN001
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


def test_parse_formato_pydantic_con_tool_call() -> None:
    """ollama>=0.6 restituisce oggetti pydantic: il parsing deve estratto tool_calls."""
    raw = SimpleNamespace(
        message=SimpleNamespace(
            content=None,
            tool_calls=[_tool_call_ns("list_dir", {"path": "."})],
        )
    )
    response = _parse_response(raw)
    assert response.text is None
    assert response.has_tool_calls
    call = response.tool_calls[0]
    assert call.name == "list_dir"
    assert call.arguments == {"path": "."}


def test_parse_formato_pydantic_senza_tool_call() -> None:
    raw = SimpleNamespace(
        message=SimpleNamespace(content="Risposta finale.", tool_calls=None)
    )
    response = _parse_response(raw)
    assert response.text == "Risposta finale."
    assert not response.has_tool_calls


def test_parse_formato_dict_legacy() -> None:
    raw = {"message": {"content": "ciao", "tool_calls": None}}
    response = _parse_response(raw)
    assert response.text == "ciao"
    assert not response.has_tool_calls


def test_parse_dict_con_tool_calls() -> None:
    raw = {
        "message": {
            "content": "",
            "tool_calls": [{"function": {"name": "run_command", "arguments": {"command": "ls"}}}],
        }
    }
    response = _parse_response(raw)
    assert response.has_tool_calls
    assert response.tool_calls[0].name == "run_command"
    assert response.tool_calls[0].arguments == {"command": "ls"}


def test_parse_argumenti_non_dict_degrada_a_vuoto() -> None:
    raw = SimpleNamespace(
        message=SimpleNamespace(
            content=None,
            tool_calls=[_tool_call_ns("list_dir", "non-un-dict")],
        )
    )
    response = _parse_response(raw)
    assert response.tool_calls[0].arguments == {}


def test_parse_risposta_malformata_non_crasha() -> None:
    response = _parse_response(None)
    assert response.text is None
    assert not response.has_tool_calls
    response = _parse_response({})
    assert response.text is None
    assert not response.has_tool_calls


# --- 1.7b: options inviate al server (client finto, nessuna rete) ------------


class _FakeOllamaClient:
    """Client Ollama finto: registra le kwargs di chat e risponde con un dict."""

    def __init__(self, host: str | None = None, timeout: float | None = None) -> None:
        self.host = host
        self.timeout = timeout
        self.kwargs: dict[str, Any] | None = None

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        self.kwargs = kwargs
        return {"message": {"content": "risposta dal client finto", "tool_calls": None}}


class _FakeOllamaModule(ModuleType):
    """Modulo `ollama` finto: sostituisce quello reale in sys.modules."""

    Client: Any

    def __init__(self) -> None:
        super().__init__("ollama")
        self.instances: list[_FakeOllamaClient] = []

        def _client(
            host: str | None = None, timeout: float | None = None
        ) -> _FakeOllamaClient:
            instance = _FakeOllamaClient(host, timeout)
            self.instances.append(instance)
            return instance

        self.Client = _client


def _fake_ollama(monkeypatch: pytest.MonkeyPatch) -> _FakeOllamaModule:
    fake = _FakeOllamaModule()
    monkeypatch.setitem(sys.modules, "ollama", fake)
    return fake


def test_chat_invia_num_ctx_nelle_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """num_ctx finisce in options.accanto a num_predict, con stream disattivato."""
    fake = _fake_ollama(monkeypatch)
    client = OllamaClient(
        LLMConfig(
            model="fake:model",
            base_url="http://fake:11434",
            num_predict=512,
            num_ctx=4096,
        )
    )

    response = client.chat([{"role": "user", "content": "ciao"}])

    assert len(fake.instances) == 1
    sent = fake.instances[0].kwargs
    assert sent is not None
    assert sent["options"] == {"num_predict": 512, "num_ctx": 4096}
    assert sent["model"] == "fake:model"
    assert sent["stream"] is False
    assert response.text == "risposta dal client finto"


def test_chat_num_ctx_default_8192(monkeypatch: pytest.MonkeyPatch) -> None:
    """Senza override il client manda il default della config (8192)."""
    fake = _fake_ollama(monkeypatch)

    OllamaClient(LLMConfig()).chat([{"role": "user", "content": "ciao"}])

    options = fake.instances[0].kwargs
    assert options is not None
    assert options["options"]["num_ctx"] == 8192
