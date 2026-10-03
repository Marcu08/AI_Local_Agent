"""Client Ollama reale (lib `ollama`, /api/chat con tool calling strutturato)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent.config import LLMConfig
from agent.llm.base import LLMError, LLMResponse, ToolCall


class OllamaClient:
    """Wrapper sottile del client ufficiale Ollama (streaming disattivato)."""

    def __init__(self, cfg: LLMConfig) -> None:
        try:
            import ollama
        except ImportError as e:  # pragma: no cover - dipendenza dichiarata in pyproject
            raise LLMError("pacchetto 'ollama' non installato: pip install ollama") from e
        self._cfg = cfg
        self._client = ollama.Client(host=cfg.base_url, timeout=cfg.timeout_s)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": self._cfg.num_predict},
        }
        if tools:
            kwargs["tools"] = list(tools)
        try:
            raw = self._client.chat(**kwargs)
        except Exception as e:
            raise LLMError(
                f"chiamata Ollama fallita ({self._cfg.base_url}, modello "
                f"{self._cfg.model!r}): {e}"
            ) from e
        return _parse_response(raw)


def _field(obj: Any, key: str, default: Any = None) -> Any:
    """Legge un campo da dict (formato legacy) o da oggetto (pydantic ollama>=0.6)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
    value = getattr(obj, key, None)
    return default if value is None else value


def _parse_response(raw: Any) -> LLMResponse:
    """Normalizza la risposta Ollama in LLMResponse (dict o pydantic)."""
    message = _field(raw, "message", {})
    content = _field(message, "content") or None
    calls: list[ToolCall] = []
    for item in _field(message, "tool_calls", []) or []:
        function = _field(item, "function", {}) or {}
        name = _field(function, "name")
        if not name:
            continue
        arguments = _field(function, "arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(ToolCall(name=str(name), arguments=arguments))
    return LLMResponse(text=content, tool_calls=calls, raw=raw)
