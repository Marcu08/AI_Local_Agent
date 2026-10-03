"""Loop ReAct: Thought -> Act (tool) -> Observation, con limite di iterazioni."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from agent.config import AgentConfig
from agent.llm.base import LLMClient, LLMResponse, ToolCall
from agent.security.confirm import ConfirmationHandler
from agent.tools import ToolContext, ToolRegistry

SYSTEM_PROMPT = """\
Sei un assistente operativo che agisce sul PC dell'utente in modo sicuro.

Regole fondamentali:
- Per leggere file, scrivere file o eseguire comandi USA SEMPRE i tool forniti
  (list_dir, read_file, write_file, run_command, search_memory). Non fingere mai
  di aver eseguito un'azione: se non chiami il tool, l'azione non avviene.
- Scritture e comandi richiedono la conferma y/N dell'utente. Se un tool riporta
  un rifiuto o un blocco, NON riprovare all'infinito: spiega la situazione e
  chiedi istruzioni.
- Le letture sono libere solo dentro le cartelle autorizzate: se un path viene
  rifiutato, proponi alternative dentro l'area di lavoro.
- Quando hai tutte le informazioni, dai la risposta finale senza altri tool.
- Rispondi in italiano, in modo conciso e concreto.
"""

# kind: thought | act | observation | final | limit
EventHandler = Callable[[str, str], None]


def _noop(kind: str, payload: str) -> None:
    return None


def _to_tool_calls(calls: list[ToolCall]) -> list[dict[str, Any]]:
    return [
        {"function": {"name": call.name, "arguments": call.arguments}}
        for call in calls
    ]


def _fmt_args(arguments: dict[str, Any]) -> str:
    if not arguments:
        return ""
    text = json.dumps(arguments, ensure_ascii=False)
    return text if len(text) <= 200 else text[:200] + "..."


def run_turn(
    user_input: str,
    *,
    history: list[dict[str, Any]],
    llm: LLMClient,
    registry: ToolRegistry,
    config: AgentConfig,
    confirm: ConfirmationHandler,
    on_event: EventHandler | None = None,
) -> str:
    """Esegue un turno ReAct completo e ritorna la risposta finale.

    `history` deve iniziare con il messaggio di system e viene esteso in place
    con tutto ciò che il turno produce (user, assistant, tool observations).
    """
    emit = on_event or _noop
    ctx = ToolContext(config=config, confirm=confirm)
    history.append({"role": "user", "content": user_input})
    tools = registry.to_schemas()

    for _iteration in range(config.max_iterations):
        response: LLMResponse = llm.chat(history, tools)

        if not response.has_tool_calls:
            final = response.text or ""
            history.append({"role": "assistant", "content": final})
            emit("final", final)
            return final

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": response.text or ""}
        assistant_msg["tool_calls"] = _to_tool_calls(response.tool_calls)
        history.append(assistant_msg)
        if response.text:
            emit("thought", response.text)

        for call in response.tool_calls:
            emit("act", f"{call.name}({_fmt_args(call.arguments)})")
            result = registry.dispatch(call.name, call.arguments, ctx)
            observation = result.as_observation
            emit("observation", observation)
            history.append(
                {"role": "tool", "content": observation, "tool_name": call.name}
            )

    message = (
        f"Limite di iterazioni raggiunto ({config.max_iterations}): "
        "turno interrotto prima della risposta finale."
    )
    history.append({"role": "assistant", "content": message})
    emit("limit", message)
    return message
