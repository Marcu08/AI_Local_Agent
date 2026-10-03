"""Registry dei tool dell'agente (Fase 1) + costruttore di default."""

from agent.tools.base import Tool, ToolContext, ToolRegistry, ToolResult, clip
from agent.tools.fs_read import list_dir, read_file
from agent.tools.fs_write import edit_file, write_file
from agent.tools.memory_tool import search_memory
from agent.tools.shell import run_command

__all__ = [
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "clip",
    "create_default_registry",
]


def create_default_registry() -> ToolRegistry:
    """Registry con tutti i tool della Fase 1 (pronti per un wrapper MCP futuro)."""
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="list_dir",
            description=(
                "Elenca i file e le cartelle di una cartella che si trova dentro le "
                "workspace_root configurate. Restituisce [D] per le cartelle e "
                "[F] per i file con la dimensione in byte."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Cartella da elencare (relativa alla prima root o assoluta)",
                    }
                },
                "required": ["path"],
            },
            handler=list_dir,
        )
    )
    registry.register(
        Tool(
            name="read_file",
            description=(
                "Legge il contenuto di un file di testo (utf-8) dentro le workspace_root. "
                "Le righe sono numerate da 1."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File da leggere (relativo alla prima root o assoluto)",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Prima riga da leggere (default 1, 1-based)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Numero massimo di righe da leggere",
                    },
                },
                "required": ["path"],
            },
            handler=read_file,
        )
    )
    registry.register(
        Tool(
            name="write_file",
            description=(
                "Crea o sovrascrive un file di testo dentro le workspace_root. "
                "PRIMA di scrivere mostra un diff e chiede all'utente di confermare "
                "con y/N: se l'utente rifiuta, il file resta invariato."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "File da creare/aggiornare (relativo alla prima root o assoluto)"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Contenuto completo del file dopo la modifica",
                    },
                },
                "required": ["path", "content"],
            },
            handler=write_file,
        )
    )
    registry.register(
        Tool(
            name="edit_file",
            description=(
                "Modifica un file ESISTENTE sostituendo un'unica occorrenza di "
                "old_str con new_str, senza riscrivere il contenuto intero. "
                "old_str deve essere UNIVOCO: se compare 0 o più di una volta il "
                "tool restituisce un errore e non tocca il file. PRIMA di scrivere "
                "mostra il diff e chiede all'utente di confermare con y/N."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File da modificare (relativo alla prima root o assoluto)",
                    },
                    "old_str": {
                        "type": "string",
                        "description": (
                            "Stringa esatta da sostituire (deve comparire una sola volta)"
                        ),
                    },
                    "new_str": {
                        "type": "string",
                        "description": "Sostituzione (stringa vuota = cancellare old_str)",
                    },
                },
                "required": ["path", "old_str", "new_str"],
            },
            handler=edit_file,
        )
    )
    registry.register(
        Tool(
            name="run_command",
            description=(
                "Esegue un comando di terminale nella prima workspace_root. I comandi "
                "distruttivi (rm -rf, format, ecc.) sono bloccati a monte; quelli in "
                "allowlist (lettura) partono approvati, gli altri richiedono la "
                "conferma y/N dell'utente."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Comando da eseguire (es. 'git status', 'python -m pytest')",
                    }
                },
                "required": ["command"],
            },
            handler=run_command,
        )
    )
    registry.register(
        Tool(
            name="search_memory",
            description=(
                "Cerca nella memoria RAG dell'agente: documenti locali indicizzati "
                "(progetti, appunti, PDF). Usare per domande sullo storico come "
                "'Come avevo implementato X nel progetto Y?'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Domanda in linguaggio naturale",
                    }
                },
                "required": ["query"],
            },
            handler=search_memory,
        )
    )
    return registry
