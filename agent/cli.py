"""CLI REPL dell'agente (rich): rendering ReAct, conferme y/N, comandi /help."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel

from agent.config import AgentConfig, ConfigError, load_config
from agent.llm.base import LLMClient, LLMError
from agent.llm.mock_client import MockClient, final_response, tool_call_response
from agent.loop import SYSTEM_PROMPT, run_turn
from agent.security.confirm import RichConfirmation, ScriptedConfirm
from agent.tools import ToolRegistry, create_default_registry

DEMO_INPUT = "Elenca i file della cartella di lavoro"
_MAX_EVENT_CHARS = 2000

_HELP = """\
Comandi:  /help  mostra questo aiuto
          /tools elenca i tool disponibili
          /config mostra la configurazione
          /quit  esci
Inoltra qualsiasi altra riga all'agente."""


def build_client(cfg: AgentConfig, provider: str | None) -> LLMClient:
    """Client LLM: ollama (reale) o mock (demo/test offline)."""
    chosen = provider or cfg.llm.provider
    if chosen == "ollama":
        from agent.llm.ollama_client import OllamaClient

        return OllamaClient(cfg.llm)
    if chosen == "mock":
        return MockClient(
            [
                tool_call_response("list_dir", path="."),
                final_response(
                    "Demo mock completata: ho chiamato il tool list_dir e questo e' "
                    "il testo finale (nessun modello richiesto)."
                ),
            ]
        )
    raise ConfigError(f"provider sconosciuto: {chosen!r} (attesi: ollama, mock)")


def make_on_event(console: Console):
    """Rendering delle fasi ReAct: Act/Observation sempre, Thought se presente."""

    def on_event(kind: str, payload: str) -> None:
        text = payload
        if len(text) > _MAX_EVENT_CHARS:
            text = text[:_MAX_EVENT_CHARS] + "\n... [evento troncato]"
        if kind == "thought":
            console.print(Panel(text, title="Thought", border_style="dim"))
        elif kind == "act":
            console.print(f"[bold cyan]Act:[/] {text}")
        elif kind == "observation":
            console.print(f"[green]Observation:[/] {text}")
        elif kind == "final":
            console.print(Panel(text, title="Risposta", border_style="blue"))
        elif kind == "limit":
            console.print(f"[red]{text}[/]")

    return on_event


def _new_history() -> list[dict[str, Any]]:
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def _print_config(console: Console, config: AgentConfig) -> None:
    roots = "\n".join(f"  - {root}" for root in config.workspace_roots)
    console.print(
        Panel(
            f"provider: {config.llm.provider}\n"
            f"modello:  {config.llm.model}\n"
            f"root:     {roots}\n"
            f"max iterazioni: {config.max_iterations}\n"
            f"conferma scrittura: {config.security.require_write_confirmation}\n"
            f"conferma comando:   {config.security.require_command_confirmation}\n"
            f"blacklist: {len(config.security.command_blacklist)} voci",
            title="Config",
        )
    )


def _print_tools(console: Console, registry: ToolRegistry) -> None:
    for name in registry.names():
        tool = registry.get(name)
        if tool:
            console.print(f"  [cyan]{name}[/] — {tool.description.splitlines()[0]}")


def _run(llm: LLMClient, registry: ToolRegistry, config: AgentConfig, console: Console) -> int:
    confirm = RichConfirmation(console)
    on_event = make_on_event(console)
    history = _new_history()
    while True:
        try:
            user_input = console.input("[bold yellow]Tu>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nArrivederci!")
            return 0
        if not user_input:
            continue
        if user_input in {"/quit", "/exit", "/q"}:
            console.print("Arrivederci!")
            return 0
        if user_input == "/help":
            console.print(_HELP)
            continue
        if user_input == "/tools":
            _print_tools(console, registry)
            continue
        if user_input == "/config":
            _print_config(console, config)
            continue
        try:
            run_turn(
                user_input,
                history=history,
                llm=llm,
                registry=registry,
                config=config,
                confirm=confirm,
                on_event=on_event,
            )
        except LLMError as e:
            console.print(f"[red]Errore LLM:[/] {e}")
        except KeyboardInterrupt:
            console.print("\n[red]Turno interrotto.[/]")


def _run_demo(llm: LLMClient, registry: ToolRegistry, config: AgentConfig, console: Console) -> int:
    """Modalità non-interattiva (stdin piped): un turno completo e uscita."""
    confirm = ScriptedConfirm(default=True)
    on_event = make_on_event(console)
    try:
        run_turn(
            DEMO_INPUT,
            history=_new_history(),
            llm=llm,
            registry=registry,
            config=config,
            confirm=confirm,
            on_event=on_event,
        )
    except LLMError as e:
        console.print(f"[red]Errore LLM:[/] {e}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent", description="AI Agent locale: ReAct + tool + Human-in-the-Loop"
    )
    parser.add_argument(
        "--config", default=None, help="Path di config.json (default: quello del progetto)"
    )
    parser.add_argument(
        "--provider",
        choices=("ollama", "mock"),
        default=None,
        help="Override del provider LLM da config",
    )
    args = parser.parse_args(argv)

    console = Console()
    try:
        config = load_config(args.config)
        llm = build_client(config, args.provider)
    except ConfigError as e:
        console.print(f"[red]Config non valido:[/] {e}")
        return 2

    registry = create_default_registry()
    console.print(
        Panel(
            f"provider: {config.llm.provider} / {config.llm.model}\n"
            f"root: {', '.join(str(r) for r in config.workspace_roots)}\n"
            "digita /help per i comandi",
            title="AI Agent Locale v0.1",
            border_style="green",
        )
    )
    if not sys.stdin.isatty():
        return _run_demo(llm, registry, config, console)
    return _run(llm, registry, config, console)
