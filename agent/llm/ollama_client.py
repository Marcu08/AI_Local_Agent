"""Client Ollama reale (lib `ollama`, /api/chat con tool calling strutturato)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from agent.config import LLMConfig
from agent.llm.base import LLMError, LLMResponse, ToolCall


class OllamaClient:
    """Wrapper sottile del client ufficiale Ollama.

    Con `on_delta` (1.6.3) passa a `stream=True` e consegna ogni frammento di
    testo al chiamante mentre arriva; senza `on_delta` resta non-stream
    (fallback usato dai test e dai client senza rendering live).
    """

    def __init__(self, cfg: LLMConfig) -> None:
        try:
            import ollama
        except ImportError as e:  # pragma: no cover - dipendenza dichiarata in pyproject
            raise LLMError("pacchetto 'ollama' non installato: pip install ollama") from e
        self._cfg = cfg
        # 1.7c: timeout della chiamata passato dalla config (llm.timeout_seconds)
        self._client = ollama.Client(host=cfg.base_url, timeout=cfg.timeout_seconds)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "stream": on_delta is not None,
            # 1.7b: num_ctx = finestra di contesto effettiva inviata al server:
            # senza di essa Ollama usa il default del modello (spesso 2048) e la
            # cronologia con le osservazioni dei tool viene tagliata a sua insaputa
            "options": {
                "num_predict": self._cfg.num_predict,
                "num_ctx": self._cfg.num_ctx,
            },
        }
        if tools:
            kwargs["tools"] = list(tools)
        try:
            raw = self._client.chat(**kwargs)
            if on_delta is None:
                return _parse_response(raw)
            return _accumulate_stream(raw, on_delta)
        except Exception as e:
            raise LLMError(
                f"chiamata Ollama fallita ({self._cfg.base_url}, modello "
                f"{self._cfg.model!r}): {e}"
            ) from e


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


def _parse_tool_calls(items: Any) -> list[ToolCall]:
    """Normalizza `tool_calls` Ollama (dict o pydantic) in ToolCall."""
    calls: list[ToolCall] = []
    for item in items or []:
        function = _field(item, "function", {}) or {}
        name = _field(function, "name")
        if not name:
            continue
        arguments = _field(function, "arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(ToolCall(name=str(name), arguments=arguments))
    return calls


def _parse_response(raw: Any) -> LLMResponse:
    """Normalizza la risposta Ollama in LLMResponse (dict o pydantic)."""
    message = _field(raw, "message", {})
    content = _field(message, "content") or None
    calls = _parse_tool_calls(_field(message, "tool_calls", []))
    return LLMResponse(text=content, tool_calls=calls, raw=raw)


def _accumulate_stream(raw: Any, on_delta: Callable[[str], None]) -> LLMResponse:
    """Accumula lo stream: ogni contenuto va in `on_delta`, le tool call sono
    prese dall'ultimo chunk che le contiene (Ollama le manda complete)."""
    parts: list[str] = []
    calls: list[ToolCall] = []
    for chunk in raw:
        message = _field(chunk, "message", {})
        content = _field(message, "content") or ""
        if content:
            parts.append(content)
            on_delta(content)
        chunk_calls = _field(message, "tool_calls", None)
        if chunk_calls:
            calls = _parse_tool_calls(chunk_calls)
    text = "".join(parts)
    return LLMResponse(text=text or None, tool_calls=calls)
