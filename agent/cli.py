"""CLI REPL dell'agente (rich): rendering ReAct, conferme y/N, comandi /help."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel

from agent.config import AgentConfig, ConfigError, load_config
from agent.llm.base import LLMClient, LLMError
from agent.llm.mock_client import MockClient, final_response, tool_call_response
from agent.loop import SYSTEM_PROMPT, run_turn
from agent.security.audit import AuditLog
from agent.security.confirm import RichConfirmation, ScriptedConfirm
from agent.security.paths import sensitive_root_warnings
from agent.tools import ToolRegistry, create_default_registry

DEMO_INPUT = "Elenca i file della cartella di lavoro"
_MAX_EVENT_CHARS = 2000

_HELP = """\
Comandi:  /help  mostra questo aiuto
          /tools elenca i tool disponibili
          /config mostra la configurazione
          /reset azzera la cronologia della conversazione
          /save <nome>  salva la conversazione nella workspace (JSON)
          /load <nome>  ricarica una conversazione salvata
          /quit  esci
Inoltra qualsiasi altra riga all'agente."""


def _conversation_filename(name: str) -> tuple[str | None, str | None]:
    """Nome file di una conversazione: semplice e senza separatori.

    Ritorna (filename, None) se valido, altrimenti (None, errore).
    Niente path: il file vive sempre nella prima workspace_root (1.6.4).
    """
    if not name or name != name.strip():
        return None, "nome non valido: niente spazi ai bordi"
    if any(ch in name for ch in '/\\:*?"<>|'):
        return None, 'nome non valido: niente separatori o caratteri proibiti'
    if name in {".", ".."} or name.startswith("..") or name.endswith("."):
        return None, "nome non valido"
    if len(name) > 200:
        return None, "nome troppo lungo (max 200 caratteri)"
    return (name if name.endswith(".json") else name + ".json"), None


def handle_repl_command(
    line: str, history: list[dict[str, Any]], config: AgentConfig
) -> str | None:
    """Gestisce /reset, /save e /load; None = non è un comando REPL gestito.

    I file di conversazione stanno nella PRIMA workspace_root, come nome file
    semplice (nessun path, vedi _conversation_filename). /load sostituisce la
    cronologia ma riusa SEMPRE il system prompt corrente.
    """
    parts = line.split(maxsplit=1)
    cmd = parts[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/reset":
        history.clear()
        history.extend(_new_history())
        return "Cronologia azzerata."

    if cmd in {"/save", "/load"}:
        if not arg:
            return f"Uso: {cmd} <nome>"
        filename, error = _conversation_filename(arg)
        if filename is None:
            return f"{cmd} rifiutato: {error or 'nome non valido'}"
        path = config.workspace_roots[0] / filename

        if cmd == "/save":
            try:
                path.write_text(
                    json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except OSError as e:
                return f"Salvataggio fallito: {e}"
            return f"Cronologia salvata: {path} ({len(history)} messaggi)"

        # /load
        if not path.exists():
            return f"Caricamento fallito: file inesistente ({path})"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            return f"Caricamento fallito: JSON non valido ({e})"
        if not isinstance(data, list) or not all(isinstance(m, dict) for m in data):
            return "Caricamento fallito: struttura non valida (atteso un elenco di messaggi)"
        loaded = [
            m
            for m in data
            if m.get("role") in {"user", "assistant", "tool"}
            and isinstance(m.get("content"), (str, type(None)))
        ]
        history.clear()
        history.extend(_new_history())  # il system prompt è quello corrente
        history.extend(loaded)
        return f"Cronologia caricata: {path} ({len(loaded)} messaggi + system)"

    return None


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
    """Rendering delle fasi ReAct: Act/Observation sempre, Thought se presente.

    1.6.3: se il client produce eventi "delta", il testo scorre in tempo reale
    e thought/final successivi NON vengono ridisegnati (nessun duplicato).
    Senza delta (MockClient o provider non-stream) il rendering è identico a
    quello di prima.
    """
    state = {"streaming": False, "streamed": False}

    def on_event(kind: str, payload: str) -> None:
        if kind == "delta":
            if not state["streaming"]:
                state["streaming"] = True
                state["streamed"] = True
            console.print(
                payload, end="", markup=False, highlight=False, soft_wrap=True
            )
            return
        if state["streaming"]:
            console.print()  # chiudi la riga aperta dallo streaming
            state["streaming"] = False
        text = payload
        if len(text) > _MAX_EVENT_CHARS:
            text = text[:_MAX_EVENT_CHARS] + "\n... [evento troncato]"
        if kind == "thought":
            if state["streamed"]:
                state["streamed"] = False  # già mostrato in streaming
                return
            console.print(Panel(text, title="Thought", border_style="dim"))
        elif kind == "act":
            console.print(f"[bold cyan]Act:[/] {text}")
        elif kind == "observation":
            console.print(f"[green]Observation:[/] {text}")
        elif kind == "final":
            if state["streamed"]:
                state["streamed"] = False  # già mostrato in streaming
                return
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
            f"blacklist: {len(config.security.command_blacklist)} voci\n"
            f"allowlist: {len(config.security.command_allowlist)} voci",
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
    audit = AuditLog()
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
        repl_msg = handle_repl_command(user_input, history, config)
        if repl_msg is not None:
            console.print(repl_msg)
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
                audit=audit,
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
            audit=AuditLog(),
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
        config = load_config(
            args.config,
            create_roots=True,
            on_created=lambda p: console.print(f"[yellow]Cartella workspace creata:[/] {p}"),
        )
        llm = build_client(config, args.provider)
    except ConfigError as e:
        console.print(f"[red]Config non valido:[/] {e}")
        return 2

    registry = create_default_registry()
    for warning in sensitive_root_warnings(config.workspace_roots):
        console.print(f"[yellow]Avviso workspace:[/] {warning}")
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
