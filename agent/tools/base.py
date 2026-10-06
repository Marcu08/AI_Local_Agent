"""Registry dei tool: schema JSON, handler e dispatch protetto."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.config import AgentConfig
from agent.security.confirm import ConfirmationHandler


@dataclass
class ToolResult:
    """Esito di un tool: output per l'LLM oppure errore (mai eccezione).

    `decisione` è come il tool è arrivato a eseguirsi: auto / confermato /
    rifiutato / bloccato (None = "auto", valorizzato dai tool con gate).
    """

    output: str | None = None
    error: str | None = None
    decision: str | None = None

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
    def failure(cls, message: str, *, decision: str | None = None) -> ToolResult:
        return cls(error=message, decision=decision)


def clip(text: str, max_chars: int) -> str:
    """Tronca il testo a max_chars con marker esplicito (mai troncamento silenzioso)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [troncato: {len(text) - max_chars} caratteri omessi]"


# 1.7b: tolleranza sui tipi in dispatch. I modelli piccoli mandano "3" al posto
# di 3 oppure "true" al posto di true: la conversione avviene UNA volta qui,
# prima dell'handler, e un valore non convertibile diventa un errore d'uso
# (tipo atteso + esempio + invito a riprovare) invece di un'eccezione a valle.
_TYPE_LABELS: dict[str, str] = {
    "integer": "intero",
    "number": "numero",
    "boolean": "booleano",
}
_TYPE_EXAMPLES: dict[str, str] = {"integer": "3", "number": "1.5", "boolean": "true"}
_RETRY_HINTS: dict[str, str] = {
    "integer": "Riprova con uno degli interi ammessi.",
    "number": "Riprova con un numero.",
    "boolean": 'Riprova con "true" oppure "false".',
}


def _coerce_typed(value: Any, expected: str) -> tuple[Any, str | None]:
    """Converte `value` nel tipo dichiarato dallo schema; (valore, None) se va bene.

    Ritorna (valore originale, motivo) quando la conversione non è possibile:
    il motivo serve solo a dichiarare che il valore è stato rifiutato, il testo
    completo dell'errore lo compone `_type_error` (con tipo atteso ed esempio).
    """
    if expected == "boolean":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str):
            low = value.strip().lower()
            if low == "true":
                return True, None
            if low == "false":
                return False, None
        return value, "non è un booleano"
    if expected == "integer":
        # bool è sottoclasse di int in Python: `true` come offset NON è un intero
        if isinstance(value, bool):
            return value, "non è un intero"
        if isinstance(value, int):
            return value, None
        if isinstance(value, float):
            # 1.0 va bene (è un intero scritto come float), 1.5 no
            return (int(value), None) if value.is_integer() else (value, "non è un intero")
        if isinstance(value, str):
            try:
                return int(value.strip()), None
            except ValueError:
                return value, "non è un intero"
        return value, "non è un intero"
    # expected == "number"
    if isinstance(value, bool):
        return value, "non è un numero"
    if isinstance(value, (int, float)):
        return value, None
    if isinstance(value, str):
        try:
            return float(value.strip()), None
        except ValueError:
            return value, "non è un numero"
    return value, "non è un numero"


def _type_error(tool_name: str, key: str, expected: str, value: Any) -> str:
    """Errore d'uso per un argomento tipizzato non convertibile.

    Dice il tipo atteso, il valore ricevuto, un esempio d'uso e invita a
    riprovare: è il messaggio che l'LLM legge come Observation e corregge.
    """
    label = _TYPE_LABELS[expected]
    return (
        f"argomento {key!r} di {tool_name!r}: tipo atteso {label} ({expected}), "
        f"ricevuto {value!r} ({type(value).__name__}). "
        f"Esempio d'uso: {key}={_TYPE_EXAMPLES[expected]}. "
        f"{_RETRY_HINTS[expected]}"
    )


def _coerce_args(tool: Tool, args: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Applica la coercizione a tutti gli argomenti tipizzati dallo schema.

    Solo le proprietà con type integer/number/boolean vengono toccate: le
    stringhe (path, query, ...) e i parametri non dichiarati passano intatti.
    `None` vale "argomento assente" e viene lasciato al default dell'handler.
    Ritorna (argomenti, None) oppure (argomenti originali, errore d'uso).
    """
    properties = tool.parameters.get("properties")
    if not isinstance(properties, dict):
        return args, None
    out = dict(args)
    for key, spec in properties.items():
        if key not in out or not isinstance(spec, dict):
            continue
        expected = spec.get("type")
        if expected not in _TYPE_LABELS:
            continue
        value = out[key]
        if value is None:
            continue  # assente: il default lo decide l'handler
        converted, reason = _coerce_typed(value, expected)
        if reason is not None:
            return args, _type_error(tool.name, key, str(expected), value)
        out[key] = converted
    return out, None


@dataclass
class ToolContext:
    """Contesto passato a ogni handler: config, conferme HIL e stato del turno.

    `seen_untrusted` diventa True dopo la prima osservazione che espone contenuto
    esterno (file/comandi): le conferme successive lo mostrano all'utente.
    `ask_count` conta le domande `ask_user` già fatte in questo TURNO
    (anti-loop della 1.8.1: massimo 3, la quarta è un errore).
    """

    config: AgentConfig
    confirm: ConfirmationHandler
    seen_untrusted: bool = False
    ask_count: int = 0


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
        # 1.7b: argomenti tipizzati convertiti qui (dispatch tollerante); se la
        # conversione fallisce il modello riceve un errore d'uso e può riprovare
        coerced, type_error = _coerce_args(tool, args)
        if type_error is not None:
            return ToolResult.failure(type_error)
        try:
            result = tool.handler(coerced, ctx)
        except Exception as e:
            return ToolResult.failure(f"{type(e).__name__}: {e}")
        if not isinstance(result, ToolResult):
            return ToolResult.failure(
                f"handler di {name!r} ha restituito {type(result).__name__}, atteso ToolResult"
            )
        return result
