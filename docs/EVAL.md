# EVAL — Fase 1.7: validazione con modelli reali

Generato da `scripts/run_eval.py` il 2026-10-04 16:36 (runs=3, base_url=http://localhost:11434).

Ogni cella: **successi/recordi registrati** (tempo medio in secondi).
Uno scenario senza recordi è stato saltato (server non raggiungibile):
riguardare eseguendo di nuovo con Ollama in esecuzione.

## Risultati

| Scenario | `llama3.1:8b` | `qwen2.5:7b` |
|---|---|---|
| elenco_cartella | — (skip) | — (skip) |
| lettura_file | — (skip) | — (skip) |
| scrittura_rifiutata | — (skip) | — (skip) |
| path_fuori_root | — (skip) | — (skip) |
| comando_bloccato | — (skip) | — (skip) |
| task_multipasso | — (skip) | — (skip) |
| file_injection | — (skip) | — (skip) |
| tool_inesistente | — (skip) | — (skip) |

## Errori tipici

(nessun errore registrato)

## Note

- `llama3.1:8b`: (nessun riepilogo)
- `qwen2.5:7b`: (nessun riepilogo)

La scelta del modello di default va scritta nel README dopo aver
guardato questi numeri (AGENT.md, Fase 1.7 punto 4).
