"""Test del parser risposte Ollama: supporta dict legacy e pydantic (ollama>=0.6)."""

from __future__ import annotations

from types import SimpleNamespace

from agent.llm.ollama_client import _parse_response


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
