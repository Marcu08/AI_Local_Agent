"""Protocol comune per i client LLM (Ollama, mock, futuri provider)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(RuntimeError):
    """Errore di comunicazione con il provider LLM (rete, modello assente, ...)."""


@dataclass
class ToolCall:
    """Richiesta di tool emessa dal modello: nome + argomenti JSON."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Risposta normalizzata: testo finale e/o richieste di tool."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient(Protocol):
    """Interfaccia minima: una chiamata chat con optional tool schemas."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        ...
