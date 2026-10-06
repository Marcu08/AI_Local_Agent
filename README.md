# AI Agent Locale — Assistente Personale su PC

Agente AI locale in **Python** che agisce sul tuo PC con **tool calling**, **Memoria RAG** (scaffold) e un modello di permessi **Human-in-the-Loop**: nessuna scrittura o comando rischioso viene eseguito senza la tua conferma `y`.

> Stato: **Fase 1 (Core) completa + scaffold Fase 2 (Memoria)** — v0.1

## Requisiti

- Python 3.11+
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
├── loop.py           # ciclo ReAct, limite iterazioni, trimming cronologia
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
│   ├── ask_user.py   # ask_user (1.8.1): chiarimenti, max 3 per turno
│   └── memory_tool.py# search_memory (scaffold Fase 2)
├── security/
│   ├── paths.py      # safe_resolve(): whitelist, anti path-traversal
│   ├── blacklist.py  # regex comandi distruttivi (+ voci da config)
│   ├── allowlist.py  # autoapprove_reason(): comandi read-only senza conferma
│   ├── audit.py      # AuditLog JSONL: una riga per tool call
│   └── confirm.py    # ConfirmationHandler (confirm + ask) iniettabile (test senza input())
└── memory/           # SCAFFOLD Fase 2: ingest, store (ChromaDB lazy), retrieval
```

**Loop ReAct** — per ogni turno: l'LLM risponde con una o più *tool call* → il
dispatcher le esegue (applicando sicurezza e conferme) → le *osservazioni*
rientrano nei messaggi → si ripete fino alla risposta finale o al limite di
`agent.max_iterations`.

## Tool

| Tool | Cosa fa | Conferma |
|---|---|---|
| `list_dir` | elenca una cartella dentro le `workspace_root` | no (sola lettura) |
| `read_file` | legge un file di testo dentro le `workspace_root` | solo per file sensibili |
| `search_files` | ricerca testuale dentro le `workspace_root` | no (sola lettura) |
| `search_memory` | ricerca nella memoria RAG (scaffold Fase 2) | no (sola lettura) |
| `write_file` | crea o sovrascrive un file (mostra il diff) | **sempre** `y/N` |
| `edit_file` | sostituzione univoca `old_str` → `new_str` (mostra il diff) | **sempre** `y/N` |
| `run_command` | esegue un comando nella prima root (blacklist + timeout) | allowlist → auto, altrimenti `y/N` |
| `ask_user` | chiede all'utente un chiarimento invece di inventare (1.8.1) | no — max 3 domande per turno |

## Regole di sicurezza

1. **Lettura** — libera solo dentro le `workspace_root` di `config.json`
   (default: `C:/Users/marzu/OneDrive/Desktop/agent_workspace`, creata al primo
   avvio se manca). Allargare le root è una scelta esplicita nel config. I path
   vengono canonicalizzati: `..`, separatori misti e symlink verso l'esterno
   sono rifiutati. Se una root contiene la home o cartelle sensibili
   (`~/.ssh`, `~/.aws`, cartelle di sistema), all'avvio compare un avviso.
2. **Scrittura** — `write_file` mostra sempre il diff e si interrompe: si
   procede solo se digiti `y`. Default della conferma: **NO**.
3. **Terminale** — `run_command` viene bloccato a monte dalla blacklist
   (`rm -rf`, `del /f`, `format`, `mkfs`, `dd if=`, `shutdown`, pipe verso
   shell, ...) **prima** di toccare subprocess, e richiede comunque conferma.
   I comandi girano con `cwd` forzato alla prima root e con timeout.

Le sicurezze vivono nel **dispatcher dei tool**, non nel prompt: anche un
modello che "impazzisce" non può bypassarle.

## Modello di minaccia

Cosa l'agente si propone di difendere, e da chi:

- **Contenuto esterno che cerca di dettare ordini all'LLM** (prompt injection
  da file letti, output di comandi, documenti): le osservazioni arrivano
  racchiuse in `<tool_output untrusted="true">` e il system prompt vieta di
  trattarle come istruzioni; ogni azione resta comunque dietro blacklist e
  conferma. Il delimitatore riduce il rischio, non lo elimina (vedi Limiti noti).
- **Un modello che "sbaglia" o viene convinto** a compiere azioni dannose:
  la sicurezza vive nel dispatcher (path whitelist, blacklist, allowlist,
  diff + conferma con default NO), non nella bontà del prompt.
- **Azioni distruttive accidentali** (`rm -rf`, `format`, sovrascritture):
  blacklist a monte di subprocess, diff always-on, conferma `y/N` (default NO),
  `cwd` forzato e timeout sui comandi.
- **Lettura di path sensibili** (`~/.ssh`, chiavi, cartelle di sistema):
  path canonicalizzati dentro le `workspace_root`, avviso all'avvio se una
  root è sensibile.
- **Verifica a posteriori**: `logs/audit.jsonl` registra ogni tool call
  (decisione `auto`/`confermato`/`rifiutato`/`bloccato`, esito, durata) con
  argomenti troncati a un'anteprima: mai il contenuto completo di un file.

**Fuori perimetro**: chi controlla la macchina o il processo Ollama può già
fare tutto ciò che l'agente può fare; attacchi al provider LLM, all'host o
alla rete non rientrano in questa fase.

## Limiti noti

La sicurezza è **difensiva in profondità**, non un sandbox:

- **La blacklist non è un confine di sicurezza.** È fatta di regex: ha falsi
  positivi (blocca anche cose innocue) e falsi negativi (alias, encoding,
  variabili d'ambiente la aggirano). Il confine reale è la **conferma umana
  con default NO**: tutto ciò che non è auto-approvato passa da lì.
- **L'allowlist riduce la superficie, non è una gabbia.** Ogni voce dichiara i
  flag ammessi (`{command, flags}`): qualsiasi flag non elencato — per esempio
  `--output` su `git diff`, che scrive un file — torna in conferma.
  `pytest` e `ruff` **non** sono in allowlist: eseguono codice della
  repository (conftest, plugin) e richiedono la conferma a ogni invocazione.
  Un eseguibile omonimo presente prima su PATH verrebbe eseguito al posto di
  quello atteso.
- **Un comando approvato esplicitamente** passa anche con metacaratteri e path
  arbitrari: la responsabilità dell'approvazione è di chi digita `y`.
- **`cwd` forzato alla prima root non è un jail**: con `shell=True` un comando
  approvato può raggiungere il filesystem con i permessi dell'utente.
- **`ask_user` non è una linea diretta con l'utente.** Max **3 domande per
  turno** (alla quarta il tool risponde con un errore che invita a proseguire
  con le informazioni disponibili) e domande di max 300 caratteri. In modalità
  **non interattiva** (demo, stdin pipato) non blocca mai: la risposta è
  `[nessuna risposta disponibile: modalità non interattiva]`, mentre Ctrl+C
  durante l'attesa produce `[risposta annullata: attesa interrotta]`. La
  risposta dell'utente è input fidato ed **esce** dal delimitatore
  `untrusted` (nel audit viene registrata la domanda, non la risposta).

## Codifica (Windows, pipe e non-TTY)

All'avvio la CLI forza UTF-8 su `stdout`, `stderr` e `stdin` con
`errors="replace"` (funzione `agent.cli.force_utf8_stdio`):

- **TTY Windows**: l'I/O della console è già Unicode nativo (PEP 528) e la
  forzatura non cambia nulla.
- **Pipe/redirect** (`python -m agent > out.txt`, pipe verso un altro tool):
  senza la forza, l'encoding seguirebbe la code page di sistema (cp1252 su
  it-IT) e i caratteri fuori range darebbero `UnicodeEncodeError`. Con la
  forza, **l'output è UTF-8**: un lettore che dichiari UTF-8 lo legge bene, uno
  che assuma la code page di sistema vedrebbe i byte interpretati male
  (dichiarare UTF-8 lato lettore).
- **`errors="replace"`**: un carattere non codificabile diventa `�` invece
  di abbattere la CLI.
- I processi figli ereditano `PYTHONUTF8=1`: anche gli interpreter figli
  avviano in UTF-8 mode (le variabili valgono solo all'avvio del figlio).

## Configurazione (`config.json`)

| Sezione | Chiave | Significato |
|---|---|---|
| top | `workspace_roots` | cartelle che l'agente può esplorare |
| top | `conversations_dir` | cartella di `/save` `/load` (default `~/.agent/conversations`, deve stare fuori dalle workspace) |
| `llm` | `provider`, `model`, `base_url` | provider: `ollama` \| `mock` |
| `llm` | `num_predict` | max token generati per chiamata (default 1024, anti-runaway) |
| `llm` | `num_ctx` | finestra di contesto (token) inviata a Ollama come `options.num_ctx` (default 8192; mostrata all'avvio del REPL) |
| `llm` | `timeout_seconds` | timeout della chiamata Ollama in secondi (default 120; 300 negli e2e) |
| `security` | `require_write_confirmation` | conferma y/N per gli scritture (default true) |
| `security` | `require_command_confirmation` | conferma y/N per i comandi (default true) |
| `security` | `command_blacklist` | stringhe/voci extra da bloccare |
| `security` | `command_allowlist` | voci `{command, flags}`: auto solo con intestazione e flag elencati |
| `security` | `command_timeout_s` | timeout dei comandi (default 30) |
| `agent` | `max_iterations` | limite di step ReAct per turno |
| `agent` | `max_tool_output_chars` | troncamento osservazioni |
| `agent` | `history_max_messages` | max messaggi in cronologia (default 40, system incluso) |
| `agent` | `history_max_chars` | max caratteri in cronologia (default 50000) |

## Test

```bash
.venv\Scripts\python -m pytest        # nessuna rete/Ollama necessari
.venv\Scripts\python -m ruff check .
```

I test usano fixture sintetiche su `tmp_path` e mock iniettabili: mai `input()`
reale, mai server vivi (convenzione dei progetti JARVIS/BAULI).

Gli **scenari e2e** (`tests/e2e/`, Fase 1.7 + 1.8) sono l'unica eccezione: usano un
modello reale, sono marcati `e2e` ed **esclusi di default**. Si eseguono solo
con Ollama già in esecuzione (nessun modello viene scaricato da qui):

```bash
# 9 scenari x 3 con un modello scelto via CLI o env AGENT_E2E_MODELS
.venv\Scripts\python -m pytest -m e2e --e2e-models llama3.1:8b

# 3 giri per modello → docs/EVAL.md (tabella modello x scenario x successi/3)
.venv\Scripts\python scripts\run_eval.py --models llama3.1:8b,qwen2.5:7b
```

## Roadmap

- **Fase 2 — Memoria RAG**: ingestion reale (`scripts/ingest.py` è uno scaffold
  con `--dry-run` funzionante), embeddings + ChromaDB in `memory/store.py`,
  `search_memory` già registrato e pronto.
- **Fase 3 — Study Mode**: cambio di system prompt per il ruolo tutor,
  quiz con punteggi, registro progressi in JSON.
- **Fase 3+ — MCP**: i tool sono già registrati come `{name, description,
  json_schema, handler}`: un wrapper FastMCP potrà esporli ad agenti esterni
  senza riscrivere nulla.
