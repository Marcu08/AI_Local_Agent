"""Client LLM finto: risposte pre-scriptate per test e smoke offline."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Any

from agent.llm.base import LLMResponse, ToolCall


class MockClient:
    """Consuma una lista di LLMResponse in ordine (l'ultima si ripete).

    Registra ogni chiamata (`received`) così i test possono verificare che
    tool schemas e messaggi siano stati passati correttamente.
    """

    def __init__(self, responses: list[LLMResponse]) -> None:
        if not responses:
            raise ValueError("MockClient richiede almeno una risposta")
        self._responses = list(responses)
        self.received: list[dict[str, Any]] = []
        self.calls = 0

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Fallback non-stream (1.6.3): `on_delta` è ignorato di proposito."""
        del on_delta  # i test girano senza streaming
        self.received.append(
            {"messages": deepcopy(messages), "tools": deepcopy(list(tools)) if tools else None}
        )
        index = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[index]


def tool_call_response(name: str, **arguments: Any) -> LLMResponse:
    """Comodo costruttore: risposta contente una sola tool call."""
    return LLMResponse(text=None, tool_calls=[ToolCall(name=name, arguments=arguments)])


def final_response(text: str) -> LLMResponse:
    """Comodo costruttore: risposta finale senza tool."""
    return LLMResponse(text=text, tool_calls=[])
