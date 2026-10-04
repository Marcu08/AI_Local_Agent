"""CLI REPL dell'agente (rich): rendering ReAct, conferme y/N, comandi /help."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
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
          /save <nome>  salva la conversazione in ~/.agent/conversations (JSON)
          /load <nome>  ricarica una conversazione salvata (schema validato)
          /quit  esci
Inoltra qualsiasi altra riga all'agente."""


# limite di dimensione di un file di conversazione accettato da /load (1.6.6)
_MAX_CONVERSATION_BYTES = 5_000_000


def _conversations_dir(config: AgentConfig) -> Path:
    """Cartella delle conversazioni: config.conversations_dir o default home.

    Sempre FUORI dalle workspace_root (validato in load_config): i file di
    conversazione non sono contenuto che il modello possa leggere coi tool.
    """
    if config.conversations_dir is not None:
        return config.conversations_dir
    return Path.home() / ".agent" / "conversations"


def _conversation_filename(name: str) -> tuple[str | None, str | None]:
    """Nome file di una conversazione: semplice e senza separatori.

    Ritorna (filename, None) se valido, altrimenti (None, errore).
    Niente path: il file vive solo nella cartella conversazioni (1.6.6).
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


def _validate_conversation(data: object) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Schema di una conversazione salvata (1.6.6): lista valida o errore chiaro.

    Regole: solo ruoli user/assistant/tool (MAI system: il system prompt viene
    rigenerato a ogni /load), content sempre stringa, tool_calls ben formate
    ({function: {name, arguments}}), tool_name stringa se presente.
    """
    if not isinstance(data, list):
        return None, "atteso un elenco di messaggi"
    out: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return None, f"messaggio {i}: atteso un oggetto"
        role = item.get("role")
        if role is None:
            return None, f"messaggio {i}: campo 'role' mancante"
        if role == "system":
            return None, (
                f"messaggio {i}: ruolo 'system' non ammesso "
                "(il system prompt viene rigenerato)"
            )
        if role not in {"user", "assistant", "tool"}:
            return None, f"messaggio {i}: ruolo sconosciuto {role!r}"
        if not isinstance(item.get("content"), str):
            return None, f"messaggio {i}: campo 'content' mancante o non stringa"
        calls = item.get("tool_calls")
        if calls is not None:
            if role != "assistant":
                return None, f"messaggio {i}: 'tool_calls' ammesso solo su assistant"
            if not isinstance(calls, list) or not calls:
                return None, f"messaggio {i}: 'tool_calls' deve essere una lista non vuota"
            for j, call in enumerate(calls):
                if not isinstance(call, dict):
                    return None, f"messaggio {i}: tool_call {j} non è un oggetto"
                fn = call.get("function")
                if not isinstance(fn, dict):
                    return None, f"messaggio {i}: tool_call {j} senza 'function'"
                name = fn.get("name")
                arguments = fn.get("arguments")
                if not isinstance(name, str) or not name:
                    return None, f"messaggio {i}: tool_call {j} con 'name' non valido"
                if not isinstance(arguments, str):
                    return None, f"messaggio {i}: tool_call {j} con 'arguments' non valido"
        tool_name = item.get("tool_name")
        if tool_name is not None and not isinstance(tool_name, str):
            return None, f"messaggio {i}: 'tool_name' deve essere una stringa"
        out.append(item)
    return out, None


def handle_repl_command(
    line: str, history: list[dict[str, Any]], config: AgentConfig
) -> str | None:
    """Gestisce /reset, /save e /load; None = non è un comando REPL gestito.

    I file stanno in conversations_dir (default ~/.agent/conversations, fuori
    dalle workspace_root). /save omette il messaggio di system; /load valida lo
    schema per intero (errore chiaro senza toccare la cronologia) e rigenera
    sempre il system prompt corrente.
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
        path = _conversations_dir(config) / filename

        if cmd == "/save":
            # il system prompt non viene mai salvato: è rigenerato a ogni load
            payload = [
                m
                for m in history
                if isinstance(m, dict) and m.get("role") in {"user", "assistant", "tool"}
            ]
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except OSError as e:
                return f"Salvataggio fallito: {e}"
            return f"Cronologia salvata: {path} ({len(payload)} messaggi)"

        # /load
        if not path.exists():
            return f"Caricamento fallito: file inesistente ({path})"
        try:
            size = path.stat().st_size
        except OSError as e:
            return f"Caricamento fallito: impossibile leggere {path} ({e})"
        if size > _MAX_CONVERSATION_BYTES:
            return (
                f"Caricamento fallito: file troppo grande "
                f"({size} byte, massimo {_MAX_CONVERSATION_BYTES})"
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            return f"Caricamento fallito: JSON non valido ({e})"
        loaded, schema_error = _validate_conversation(data)
        if schema_error is not None or loaded is None:
            return f"Caricamento fallito: {schema_error}"
        history.clear()
        history.extend(_new_history())  # il system prompt è quello corrente
        history.extend(loaded)
        return f"Cronologia caricata: {path} ({len(loaded)} messaggi + system)"

    return None


def force_utf8_stdio() -> None:
    """Forza UTF-8 sugli std stream del processo corrente (1.6.5).

    - TTY Windows: già Unicode nativo (PEP 528), la riconfigurazione non nuoce;
    - pipe/redirect (non-TTY): senza forza l'encoding seguirebbe la code page
      di sistema (cp1252 su it-IT) e i caratteri fuori range darebbero
      UnicodeEncodeError;
    - `errors="replace"`: un carattere non codificabile diventa ``\ufffd``
      invece di far cadere la CLI (nessuna eccezione I/O deve abbatterla);
    - `PYTHONUTF8=1` ereditato dai processi figli (il valore ha effetto solo
      all'avvio di un nuovo interprete, quindi vale per i figli, non per noi).

    Qualsiasi stream senza `reconfigure` (catturati da pytest, binari, chiusi)
    viene ignorato: la codifica resta quella che c'è.
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        # gli stream tipizzati TextIO possono non avere reconfigure (pytest,
        # catture, binari): getattr + try copre sia i tipi che il runtime
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # commentato sopra: mai far cadere la CLI qui dentro


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
            f"num_ctx:  {config.llm.num_ctx} token\n"
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
    force_utf8_stdio()  # 1.6.5: prima di qualunque stampa
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
            # 1.7b: il valore che verrà davvero mandato a Ollama (opzione num_ctx)
            f"contesto: {config.llm.num_ctx} token (num_ctx)\n"
            f"root: {', '.join(str(r) for r in config.workspace_roots)}\n"
            "digita /help per i comandi",
            title="AI Agent Locale v0.1",
            border_style="green",
        )
    )
    if not sys.stdin.isatty():
        return _run_demo(llm, registry, config, console)
    return _run(llm, registry, config, console)
