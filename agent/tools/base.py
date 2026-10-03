"""Registry dei tool: schema JSON, handler e dispatch protetto."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.config import AgentConfig
from agent.security.confirm import ConfirmationHandler


@dataclass
class ToolResult:
    """Esito di un tool: output per l'LLM oppure errore (mai eccezione)."""

    output: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def as_observation(self) -> str:
        """Testo mostrato all'LLM come osservazione (Observation del loop ReAct)."""
        if self.error is not None:
            return f"ERRORE: {self.error}"
        return self.output or ""

    @classmethod
    def failure(cls, message: str) -> ToolResult:
        return cls(error=message)


def clip(text: str, max_chars: int) -> str:
    """Tronca il testo a max_chars con marker esplicito (mai troncamento silenzioso)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [troncato: {len(text) - max_chars} caratteri omessi]"


@dataclass
class ToolContext:
    """Contesto passato a ogni handler: config, conferme HIL e stato del turno.

    `seen_untrusted` diventa True dopo la prima osservazione che espone contenuto
    esterno (file/comandi): le conferme successive lo mostrano all'utente.
    """

    config: AgentConfig
    confirm: ConfirmationHandler
    seen_untrusted: bool = False


Handler = Callable[[dict[str, Any], ToolContext], ToolResult]


@dataclass(frozen=True)
class Tool:
    """Un tool: nome, descrizione per l'LLM, JSON schema degli argomenti, handler."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler

    def to_schema(self) -> dict[str, Any]:
        """Formato tool di Ollama/OpenAI: {"type": "function", "function": {...}}."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Inventario dei tool + dispatch che non propaga mai eccezioni al loop."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool duplicato: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def to_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]

    def dispatch(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        ctx: ToolContext,
    ) -> ToolResult:
        """Esegue un tool catturando ogni eccezione → ToolResult(error)."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(f"tool sconosciuto: {name!r}")
        args: dict[str, Any] = arguments if isinstance(arguments, dict) else {}
        try:
            result = tool.handler(args, ctx)
        except Exception as e:
            return ToolResult.failure(f"{type(e).__name__}: {e}")
        if not isinstance(result, ToolResult):
            return ToolResult.failure(
                f"handler di {name!r} ha restituito {type(result).__name__}, atteso ToolResult"
            )
        return result
