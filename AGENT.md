\# AGENT.md — ai-agent-core: piano di prosecuzione



Questo file è il contratto di lavoro per il code agent (opencode o simili).

Leggilo per intero prima di toccare codice. Lavora \*\*una fase alla volta\*\*, nell'ordine indicato.



\## 0. Contesto



Progetto: agente personale locale in Python (`agent/`), loop ReAct, tool calling su Ollama,

sicurezza implementata nel codice (whitelist path, blacklist comandi, conferma y/N con default NO).

Stato: Fase 1 completata (3 commit su master, 102 test, ruff e pyright puliti, E2E reale solo con `llama3.2:1b`).

Scaffold Fase 2 (RAG) presente ma non funzionante: `search\_memory` risponde "non implementato".

Ambiente: Windows, Python 3.14 in `.venv`, Ollama su `http://localhost:11434`.



\## 1. Regole operative (valgono sempre)



1\. \*\*Una fase alla volta.\*\* Non iniziare la successiva senza che io lo dica.

2\. \*\*Un commit per task\*\*, messaggio in italiano, formato `fase X.Y: cosa e perché`.

3\. \*\*Prima di ogni commit\*\* devono passare: `pytest`, `ruff check .`, `pyright`. Niente `# type: ignore` o `noqa` nuovi senza motivo scritto nel commit.

4\. \*\*Test portabili.\*\* Nessun test deve dipendere da `config.json` reale, da path `C:/...` o da Ollama in esecuzione. Usa `tmp\_path`, config di test e `MockClient`. I test che richiedono Ollama vanno marcati `@pytest.mark.e2e` ed esclusi di default.

5\. \*\*Non dichiarare "verificato" ciò che non hai eseguito.\*\* Nel report distingui sempre: \*eseguito e passato\* / \*scritto ma non eseguito\* / \*non verificabile qui\*.

6\. \*\*Nessuna nuova dipendenza\*\* senza giustificazione (cosa risolve, alternativa stdlib scartata, peso).

7\. \*\*Nessun refactoring non richiesto.\*\* Se vedi un problema fuori scope, annotalo nel report, non correggerlo.

8\. \*\*Non toccare nulla fuori dalla cartella del repo.\*\* Mai file di sistema, mai altre cartelle del Desktop.

9\. \*\*Se un requisito è ambiguo, fermati e chiedi\*\* (una domanda sola, con la tua proposta di default).

10\. \*\*Sicurezza = codice, non prompt.\*\* Nessuna regola di sicurezza può dipendere dal fatto che il modello "si comporti bene".



\### Formato del report a fine fase



```

Verdict: fatto / parziale / bloccato

File creati/modificati: (elenco)

Cosa è stato verificato (eseguito davvero): (comandi + esito)

Cosa NON è stato verificato: (onesto)

Rischi residui:

Decisioni da prendere per l'utente:

```



\---



\## FASE 1.5 — Hardening (priorità massima)



Obiettivo: chiudere i buchi emersi nella revisione. Questi sono i punti, in ordine.



\### 1.5.1 Igiene del repo e test portabili

\- Rimuovere dal tracking e aggiungere a `.gitignore`: `.venv/`, `\_\_pycache\_\_/`, `.pytest\_cache/`, `.ruff\_cache/`, `\*.egg-info/`, `logs/`, cartelle indice/Chroma.

\- Verificare con `git ls-files` che nulla di tutto ciò sia tracciato.

\- Correggere i test che oggi falliscono fuori dalla macchina dell'autore (`test\_config.py::test\_load\_config\_eseguibile\_del\_progetto`, `test\_cli\_smoke.py`, e i test di `ingest` che invocano `scripts/ingest.py` senza `PYTHONPATH`): devono usare fixture con root temporanea, e gli script devono funzionare lanciati come `python -m ...` o con path del progetto aggiunto in modo esplicito.

\- Verificare se `requires-python = ">=3.14"` è davvero necessario. Se no, abbassarlo (es. `>=3.11`) e dichiararlo.

\- \*\*Done quando:\*\* `pytest` passa su una macchina pulita (anche Linux/CI) senza Ollama.



\### 1.5.2 Restringere la workspace

\- `workspace\_roots` oggi è l'intero Desktop su OneDrive: troppo largo.

\- Nuovo default: una cartella dedicata, es. `C:/Users/marzu/OneDrive/Desktop/agent\_workspace` (creata all'avvio se manca, con messaggio chiaro). Allargare solo per scelta esplicita nel config.

\- Se una root è un antenato di cartelle sensibili o coincide con la home, mostrare un avviso all'avvio.

\- Test: path fuori dalla root, symlink/junction che escono dalla root, path relativi con `..`, drive diversi, path UNC.



\### 1.5.3 Shell: da denylist ad allowlist + conferma

La whitelist dei path \*\*non\*\* protegge `run\_command` (`shell=True`, solo `cwd` forzato). Obiettivo: ridurre davvero la superficie, ed essere onesti su ciò che resta.

\- Introdurre una \*\*allowlist di comandi read-only\*\* eseguibili senza conferma (proposta iniziale: `dir`, `ls`, `type`/`cat` solo su path dentro le root, `git status`, `git log`, `git diff`, `pytest`, `ruff check`). La lista sta in `config.json`.

\- Un comando è auto-approvabile \*\*solo se\*\*: tokenizzato con `shlex`/equivalente Windows senza errori, primo token in allowlist, \*\*nessun metacarattere shell\*\* (`\& | ; > < ` $( ) ^ %`), nessun argomento che sia path assoluto o con `..` fuori dalle root.

\- Tutto il resto: \*\*conferma sempre\*\*, mostrando comando completo, cwd e motivo per cui non è auto-approvato.

\- Mantenere la blacklist come secondo strato e \*\*ampliarla\*\*: `git clean`, `git reset --hard`, `git checkout -- .`, `shutil.rmtree`/`os.remove`/`os.unlink` in `python -c`, `del` con wildcard, `Remove-Item` anche senza `-Recurse`, `move`/`ren`/`copy` verso path fuori root, redirect (`>`/`>>`) fuori root, `curl|iwr` seguiti da esecuzione.

\- Documentare nel README, in una sezione "Limiti noti", che la blacklist non è un confine di sicurezza: il confine è la conferma umana.

\- Test: una tabella parametrizzata con almeno 40 comandi (distruttivi, bypass noti, sicuri) e l'esito atteso per ciascuno.



\### 1.5.4 Prompt injection

\- Racchiudere ogni observation proveniente da file/comandi in un delimitatore esplicito (es. `<tool\_output untrusted="true">...</tool\_output>`) e istruire il system prompt a trattarlo come dato, mai come istruzione.

\- Test con `MockClient` che "obbedisce" a un'istruzione ostile contenuta in un file letto (es. "esegui `del ...`"): verificare che il cancello (blacklist + conferma default NO) la fermi comunque. Il test verifica il cancello, \*\*non\*\* il comportamento del modello: dirlo nel docstring.

\- La conferma deve mostrare chiaramente se l'azione proposta è comparsa dopo la lettura di contenuto esterno (flag semplice nel contesto del turno).



\### 1.5.5 Audit log

\- File `logs/audit.jsonl` (gitignored), una riga per tool call: timestamp UTC, tool, argomenti (troncati), decisione (auto / confermato / rifiutato / bloccato), esito, durata.

\- Mai loggare contenuto completo di file letti o segreti; solo metadati e anteprima corta.

\- Test: ogni ramo (bloccato, rifiutato, eseguito, errore) produce la riga attesa.



\### 1.5.6 Gestione della cronologia

\- Oggi `history` cresce senza limite. Aggiungere un limite configurabile (messaggi e/o caratteri) con strategia: tenere sempre il system prompt, tenere gli ultimi N turni, \*\*non spezzare mai\*\* una coppia `assistant(tool\_calls)` / `tool`. Opzionale: riassunto dei turni scartati.

\- Test: nessuna coppia tool orfana dopo il trimming; il system prompt è sempre il primo messaggio.



\*\*Done Fase 1.5:\*\* tutti i punti sopra con test, report nel formato standard, e README aggiornato con "Modello di minaccia" e "Limiti noti".



\---



\## FASE 1.6 — Usabilità quotidiana



1\. \*\*`edit\_file`\*\*: sostituzione di una stringa univoca (`old\_str` → `new\_str`), con diff + conferma. Errore chiaro se 0 o >1 occorrenze. Non riscrivere interi file per modifiche piccole.

2\. \*\*`search\_files`\*\* (read-only): grep testuale dentro le root, con limiti su risultati e dimensione file, ignorando `.git`, `.venv`, binari.

3\. \*\*Streaming\*\* della risposta nel CLI (con fallback non-stream per i test).

4\. Comandi REPL: `/reset` (azzera cronologia), `/save <nome>` e `/load <nome>` (conversazioni su file JSON dentro la workspace).

5\. Codifica console su Windows: forzare UTF-8 dove possibile, documentare il caso pipe/non-TTY.



Ogni tool nuovo: schema, handler che non lancia eccezioni, uso di `safe\_resolve`, riga nell'audit log, test.



\---



\## FASE 1.7 — Validazione con modelli reali



L'unico E2E fatto è con un modello da 1B, giudicato instabile sugli argomenti delle tool call. Nessuna conclusione di qualità è valida finora.



1\. Scaricare e testare almeno: `llama3.1:8b` e un secondo candidato per il tool calling (es. `qwen2.5:7b`).

2\. Creare `tests/e2e/` con scenari marcati `@pytest.mark.e2e` (esclusi di default): elenco cartella; lettura file; scrittura rifiutata (file assente dopo); path fuori root; comando bloccato; task a più passi; file con injection; tool inesistente.

3\. Eseguire ogni scenario \*\*3 volte per modello\*\* (i modelli non sono deterministici) e registrare i risultati in `docs/EVAL.md`: tabella modello × scenario × (successi/3), tempi medi, note sugli errori tipici (argomenti sbagliati, loop, ecc.).

4\. Scegliere il default in base ai dati, non per abitudine, e scriverlo nel README con la motivazione.



\*\*Done:\*\* `docs/EVAL.md` con numeri reali (se Ollama non è raggiungibile dal tuo ambiente, dichiaralo e fermati: sarò io a eseguire).



\---



\## FASE 2 — Memoria RAG



Caso d'uso guida: documenti reali dell'utente (PDF con testo, note, codice). Non partire da dati sintetici.



\- \*\*Embedding locali\*\* via Ollama (modello tipo `nomic-embed-text`), dietro un'interfaccia `Embedder` con implementazione finta per i test.

\- \*\*Estrazione\*\*: testo da `.txt/.md/.py/.json`, PDF con layer testuale via `pypdf`. PDF scansionati: fuori scope (da segnalare nell'ingest, non da ignorare in silenzio).

\- \*\*Ingest incrementale\*\*: hash del contenuto per file; reindicizza solo ciò che cambia; rimuove dall'indice i file cancellati.

\- \*\*Chunking\*\* con overlap, metadati: percorso, pagina (PDF), indice del chunk, hash.

\- \*\*Esclusioni obbligatorie\*\*: `.env`, chiavi (`id\_rsa`, `\*.pem`), cartelle `.git`, `.venv`, `node\_modules`, file oltre una dimensione massima configurabile. Solo dentro le workspace\_roots.

\- \*\*`search\_memory`\*\* restituisce estratti con citazione (file + pagina) e punteggio; il system prompt impone di citare la fonte e di dire "non lo trovo nei documenti" quando i risultati sono deboli (soglia configurabile).

\- Contenuto recuperato = dato non fidato: stesso delimitatore della 1.5.4.

\- Indice in una cartella dedicata, gitignored.

\- Test con embedder finto: ingest, reingest invariato (nessuna scrittura), file modificato, file rimosso, esclusioni, query con risultati sotto soglia.



\---



\## FASE 3 — Study Mode (solo specifica ora, nessun codice senza approvazione)



Prima di implementare, produci `docs/STUDY\_MODE.md` con una proposta di una pagina: modalità separata con proprio system prompt; sorgenti = documenti indicizzati; generazione di domande/quiz con citazione della fonte; tracciamento semplice dei progressi (JSON locale); comando `/study`. Elenca 2–3 alternative e i rischi (domande inventate non supportate dai documenti). \*\*Attendi la mia approvazione.\*\*



\## FASE 4 — MCP (solo dopo che 1.5–2 sono stabili)



\- Esporre il registry dei tool come server MCP (stdio) \*\*riusando lo stesso strato di sicurezza e lo stesso audit log\*\*: nessun percorso che bypassi conferme o whitelist.

\- Lato client: possibilità di collegare server MCP esterni solo da allowlist nel config, con ogni tool esterno soggetto a conferma di default.

\- Test: uno scenario in cui un client MCP tenta un path fuori root e una scrittura senza conferma.



\---



\## Prompt di avvio (da incollare nel code agent)



> Leggi `AGENT.md` per intero. Lavora SOLO sulla Fase 1.5, nell'ordine dei sottopunti 1.5.1 → 1.5.6, un commit per sottopunto, rispettando le regole operative e il formato del report. Prima di scrivere codice, fammi un riepilogo di 10 righe di come intendi affrontare 1.5.3 (shell allowlist) e aspetta il mio ok solo su quel punto; per gli altri procedi. Alla fine consegna il report con la distinzione tra ciò che hai eseguito davvero e ciò che no.

