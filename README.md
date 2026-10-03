# AI Agent Locale — Assistente Personale su PC

Agente AI locale in **Python** che agisce sul tuo PC con **tool calling**, **Memoria RAG** (scaffold) e un modello di permessi **Human-in-the-Loop**: nessuna scrittura o comando rischioso viene eseguito senza la tua conferma `y`.

> Stato: **Fase 1 (Core) completa + scaffold Fase 2 (Memoria)** — v0.1

## Requisiti

- Python 3.14+
- [Ollama](https://ollama.com) installato e in esecuzione (`localhost:11434`)
- Un modello con supporto tool calling:

```bash
ollama pull llama3.1:8b
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Avvio

```bash
# REPL interattivo (usa il provider da config.json, default: ollama)
.venv\Scripts\python -m agent

# Demo offline senza modello (utile per testare il loop)
.venv\Scripts\python -m agent --provider mock

# Config alternativo
.venv\Scripts\python -m agent --config percorso/config.json
```

Comandi REPL: `/help`, `/tools`, `/config`, `/quit`.
Con stdin non-interattivo (piped) esegue un singolo turno di demo e esce.

## Architettura

```
agent/
├── cli.py            # REPL rich: rendering 💭 Thought / 🔧 Act / 👁 Observation
├── loop.py           # ciclo ReAct con limite di iterazioni
├── config.py         # load_config() → AgentConfig (dataclass validate)
├── llm/
│   ├── base.py       # protocol LLMClient, LLMResponse, ToolCall
│   ├── ollama_client.py  # provider reale (tool calling strutturato)
│   └── mock_client.py    # risposte scriptate per test/demo offline
├── tools/
│   ├── base.py       # Tool, ToolRegistry, dispatch senza eccezioni
│   ├── fs_read.py    # list_dir, read_file
│   ├── fs_write.py   # write_file (diff + conferma y/N)
│   ├── shell.py      # run_command (blacklist + conferma + timeout)
│   └── memory_tool.py# search_memory (scaffold Fase 2)
├── security/
│   ├── paths.py      # safe_resolve(): whitelist, anti path-traversal
│   ├── blacklist.py  # regex comandi distruttivi (+ voci da config)
│   └── confirm.py    # ConfirmationHandler iniettabile (test senza input())
└── memory/           # SCAFFOLD Fase 2: ingest, store (ChromaDB lazy), retrieval
```

**Loop ReAct** — per ogni turno: l'LLM risponde con una o più *tool call* → il
dispatcher le esegue (applicando sicurezza e conferme) → le *osservazioni*
rientrano nei messaggi → si ripete fino alla risposta finale o al limite di
`agent.max_iterations`.

## Regole di sicurezza

1. **Lettura** — libera solo dentro le `workspace_root` di `config.json`
   (default: `C:/Users/marzu/OneDrive/Desktop`). I path vengono canonicalizzati:
   `..`, separatori misti e symlink verso l'esterno sono rifiutati.
2. **Scrittura** — `write_file` mostra sempre il diff e si interrompe: si
   procede solo se digiti `y`. Default della conferma: **NO**.
3. **Terminale** — `run_command` viene bloccato a monte dalla blacklist
   (`rm -rf`, `del /f`, `format`, `mkfs`, `dd if=`, `shutdown`, pipe verso
   shell, ...) **prima** di toccare subprocess, e richiede comunque conferma.
   I comandi girano con `cwd` forzato alla prima root e con timeout.

Le sicurezze vivono nel **dispatcher dei tool**, non nel prompt: anche un
modello che "impazzisce" non può bypassarle.

## Configurazione (`config.json`)

| Sezione | Chiave | Significato |
|---|---|---|
| top | `workspace_roots` | cartelle che l'agente può esplorare |
| `llm` | `provider`, `model`, `base_url` | provider: `ollama` \| `mock` |
| `llm` | `num_predict` | max token generati per chiamata (default 1024, anti-runaway) |
| `security` | `require_write_confirmation` | conferma y/N per gli scritture (default true) |
| `security` | `require_command_confirmation` | conferma y/N per i comandi (default true) |
| `security` | `command_blacklist` | stringhe/voci extra da bloccare |
| `security` | `command_timeout_s` | timeout dei comandi (default 30) |
| `agent` | `max_iterations` | limite di step ReAct per turno |
| `agent` | `max_tool_output_chars` | troncamento osservazioni |

## Test

```bash
.venv\Scripts\python -m pytest        # 95 test, nessuna rete/Ollama necessari
.venv\Scripts\python -m ruff check .
```

I test usano fixture sintetiche su `tmp_path` e mock iniettabili: mai `input()`
reale, mai server vivi (convenzione dei progetti JARVIS/BAULI).

## Roadmap

- **Fase 2 — Memoria RAG**: ingestion reale (`scripts/ingest.py` è uno scaffold
  con `--dry-run` funzionante), embeddings + ChromaDB in `memory/store.py`,
  `search_memory` già registrato e pronto.
- **Fase 3 — Study Mode**: cambio di system prompt per il ruolo tutor,
  quiz con punteggi, registro progressi in JSON.
- **Fase 3+ — MCP**: i tool sono già registrati come `{name, description,
  json_schema, handler}`: un wrapper FastMCP potrà esporli ad agenti esterni
  senza riscrivere nulla.
