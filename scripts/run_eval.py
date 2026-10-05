"""Esegue gli scenari e2e N volte per modello e genera docs/EVAL.md (Fase 1.7).

NON scarica modelli: richiede un server Ollama già in esecuzione con i modelli
presenti (`ollama pull ...` è un'operazione manuale dell'utente). Se il server
non risponde, i test si skippano e il report lo dichiara esplicitamente.

Uso:
    python scripts/run_eval.py                        # default: 2 candidati, 3 runs
    python scripts/run_eval.py --models llama3.1:8b --runs 1 --out /tmp/eval.md

Ogni run di pytest scrive i suoi recordi su un JSONL temporaneo (opzione
--e2e-json); alla fine i recordi vengono aggregati per modello x scenario.
Prima di ogni modello parte un warm-up (POST /api/generate con keep_alive
lungo): il caricamento a freddo (decine di secondi) lo paga il warm-up, non
il primo scenario.
L'output di pytest viene mostrato in TEMPO REALE (una riga per volta, con
prefisso "> ") così si vede l'avanzamento; Ctrl+C termina il subprocess,
raccoglie i record già scritti, scrive il report parziale ed esce con 130
(senza recordi il report esistente resta intatto). Su Windows anche Ctrl+Break
prosegue per lo stesso percorso (senza handler verrebbe ucciso di botto).

Codici d'uscita: 0 = recordi presenti, 1 = nessun record (server assente),
2 = nessun modello, 3 = pytest non eseguibile con l'interprete corrente
(usare quello della venv), 130 = interrotto con Ctrl+C.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# ordine delle righe in EVAL.md = ordine degli scenari in tests/e2e/test_e2e.py
SCENARIOS: tuple[str, ...] = (
    "elenco_cartella",
    "lettura_file",
    "scrittura_rifiutata",
    "path_fuori_root",
    "comando_bloccato",
    "task_multipasso",
    "file_injection",
    "tool_inesistente",
)

DEFAULT_MODELS = "llama3.1:8b,qwen2.5:7b"

# exit code di pytest: 0 ok, 1 test falliti, 5 nessun test raccolto
_PYTEST_OK_CODES = frozenset({0, 1, 5})
# keyword che compaiono nella riga di riepilogo ("8 passed in 1.2s", ...)
_SUMMARY_KEYWORDS = ("passed", "skipped", "failed", "error")
# righe stampate quando il riepilogo manca (diagnostici a console)
_TAIL_LINES = 15
# 1.7b: polling dell'uscita del figlio (timeout / terminazione) e join del
# thread lettore dopo kill(); prefisso delle righe mostrate in tempo reale
_POLL_INTERVAL_S = 0.05
_READER_JOIN_S = 5.0
_LIVE_PREFIX = "   > "
# exit code su Ctrl+C (128 + SIGINT), convenzione POSIX
EXIT_INTERRUPTED = 130
# 1.7c: warm-up per modello — keep_alive lungo perché il modello resti in
# memoria per tutta la valutazione; 300s reggono anche un caricamento lento
_WARMUP_KEEP_ALIVE = "1h"
_WARMUP_TIMEOUT_S = 300.0


def _break_as_interrupt(signum: int, frame: Any) -> None:
    """Ctrl+Break (Windows) solleva lo stesso KeyboardInterrupt di Ctrl+C."""
    raise KeyboardInterrupt


@contextlib.contextmanager
def _interrupt_pulito() -> Iterator[None]:
    """Fa da Ctrl+Break a Ctrl+C durante i run (solo dove esiste SIGBREAK).

    Senza handler Ctrl+Break uccide il processo di botto (0xC000013A): niente
    figlio terminato, niente report parziale. Con l'handler l'interruzione sale
    dallo stesso percorso di Ctrl+C (`run_pytest` killa il figlio e main
    raccoglie i record). Il handler precedente viene sempre ripristinato.
    """
    if not hasattr(signal, "SIGBREAK"):  # non-Windows: Ctrl+Break non esiste
        yield
        return
    previous = signal.getsignal(signal.SIGBREAK)
    signal.signal(signal.SIGBREAK, _break_as_interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGBREAK, previous)


def _safe_text(text: str) -> str:
    """Rende `text` scrivibile sullo stdout corrente, senza mai far cadere lo script.

    Il figlio viene decodificato con errors="replace": i byte non validi
    diventano �, che una console cp1252 (pipe/redirect su Windows) non sa
    stampare e farrebbe esplodere il thread di lettura. Encode/decode con
    errors="replace" degrada in modo esplicito invece di interrompere il report.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    except LookupError:  # pragma: no cover - encoding esotico dichiarato dallo stream
        return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _force_utf8_stdio() -> None:
    """UTF-8 sugli std stream di QUESTO processo (specchio di agent/cli, 1.6.5).

    Lo script gira da solo (`python scripts/run_eval.py`) quindi non può
    importare `agent.cli` senza mettere la root sul sys.path: la funzione è la
    stessa, commenti inclusi. Senza forza, su Windows una pipe/redirect seguirebbe
    la code page di sistema (cp1252) e una riga non codificabile del figlio
    darebbe UnicodeEncodeError; `PYTHONUTF8=1` vale anche per i figli.
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # stream catturati (pytest), binari o chiusi: mai far cadere lo script


def _print_live(line: str) -> None:
    """Scrive una riga del subprocess NON APPENA arriva (1.7b), con flush.

    Il prefisso "> " distingue l'avanzamento in tempo reale dal riepilogo
    stampato alla fine dallo script ("   | " in _print_output_tail).
    """
    text = line if line.endswith("\n") else line + "\n"
    sys.stdout.write(_safe_text(_LIVE_PREFIX + text))
    sys.stdout.flush()


def _pump(stream: Any, lines: list[str]) -> None:
    """Legge l'output del figlio riga per riga: lo conserva e lo stampa subito.

    Gira in un thread: il processo principale continua a fare polling dell'uscita
    (timeout e Ctrl+C restano reattivi) invece di aspettare la fine del run.
    """
    try:
        for line in stream:
            lines.append(line)
            _print_live(line)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()


def warm_up(
    base_url: str, model: str, timeout_s: float = _WARMUP_TIMEOUT_S
) -> float | None:
    """Carica il modello in memoria con una chiamata minima (1.7c).

    POST /api/generate con un solo token e keep_alive lungo: il caricamento a
    freddo (decine di secondi) lo paga QUI, non il primo scenario. Ritorna i
    secondi impiegati, oppure None se la chiamata fallisce (server via,
    modello assente): il warm-up non è mai fatale, la valutazione prosegue.
    Stessa funzione usata dal fixture e2e (_warmed_models), così anche un
    `pytest -m e2e` eseguito senza run_eval parte già caldo.
    """
    payload = json.dumps(
        {
            "model": model,
            "prompt": "",
            "keep_alive": _WARMUP_KEEP_ALIVE,
            "stream": False,
            "options": {"num_predict": 1},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            response.read()
    except Exception:
        # qualsiasi problema di rete/404: non bloccare la valutazione per questo
        return None
    return time.monotonic() - started


def _print_warm_up(base_url: str, model: str) -> None:
    """Warm-up visibile prima del primo run del modello (1.7c).

    Il flush è essenziale: senza, la riga "warm-up..." resterebbe nel buffer
    proprio mentre il modello ci mette mezzo minuto a caricare.
    """
    print(f"   warm-up {model} (keep_alive={_WARMUP_KEEP_ALIVE})...", flush=True)
    seconds = warm_up(base_url, model)
    if seconds is None:
        print("   warm-up non riuscito: il primo scenario pagherà il caricamento a freddo")
    else:
        print(f"   warm-up ok ({seconds:.1f}s)")


def run_pytest(model: str, jsonl: Path, base_url: str, timeout_s: int) -> tuple[int | None, str]:
    """Un giro di pytest; ritorna (returncode | None se timeout, output).

    1.7b: l'output del figlio esce RIGA PER RIGA mentre il run procede
    (PYTHONUNBUFFERED=1 nel figlio + lettura in un thread), mentre il testo
    completo viene comunque raccolto per il riepilogo e per il report.
    stderr è unito a stdout: una sola traccia da leggere, niente codici morti.
    """
    env = dict(os.environ)
    env["AGENT_E2E_BASE_URL"] = base_url
    env["PYTHONUNBUFFERED"] = "1"  # niente buffer nel figlio: le righe escono subito
    # il figlio scrive UTF-8 indipendentemente dalla code page della console:
    # la decodifica con encoding="utf-8" resta corretta anche su Windows
    env["PYTHONUTF8"] = "1"
    cmd = [
        # niente -q qui: addopts ha già -q, un secondo -q (-qq) sopprimerebbe
        # la riga di riepilogo "N skipped in Xs" che viene citata nel report
        sys.executable, "-m", "pytest", "tests/e2e", "-m", "e2e",
        "--e2e-models", model, "--e2e-json", str(jsonl),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines: list[str] = []
    stream = proc.stdout
    if stream is None:  # pragma: no cover - con PIPE stdout esiste sempre
        proc.kill()
        return None, "stdout del subprocess non disponibile"
    reader = threading.Thread(target=_pump, args=(stream, lines), daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout_s
    timed_out = False
    try:
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                proc.kill()
                break
            time.sleep(_POLL_INTERVAL_S)
    except BaseException:
        # Ctrl+C (o qualsiasi altro errore): il figlio NON resta orfano e
        # l'eccezione risale fino a main, che scrive il report parziale.
        # Il kill può fallire se il figlio è già morto (signal arrivato prima):
        # quel fallimento non deve mascherare l'interruzione originaria.
        try:
            proc.kill()
        except OSError:  # pragma: no cover - solo in corsa con l'uscita del figlio
            pass
        raise
    finally:
        reader.join(timeout=_READER_JOIN_S)
    if timed_out:
        return None, "".join(lines) + f"\nTIMEOUT dopo {timeout_s}s"
    return proc.returncode, "".join(lines)


def _summary_line(output: str) -> str | None:
    """Ultima riga non vuota che sembra un riepilogo di pytest; None se assente."""
    tail = [ln for ln in output.splitlines() if ln.strip()]
    return next(
        (ln for ln in reversed(tail) if any(w in ln for w in _SUMMARY_KEYWORDS)),
        None,
    )


def _print_output_tail(output: str, returncode: int | None) -> None:
    """Diagnostics quando il riepilogo manca: ultime 15 righe + returncode."""
    print(f"   riepilogo assente — ultime {_TAIL_LINES} righe dell'output:")
    for line in output.splitlines()[-_TAIL_LINES:]:
        # le righe arrivano dal figlio: sanificate per non far cadere la stampa
        print(f"   | {_safe_text(line)}")
    rc_text = str(returncode) if returncode is not None else "(timeout: nessuno)"
    print(f"   | returncode: {rc_text}")


def _print_interpreter_error(returncode: int | None, output: str) -> None:
    """Messaggio chiaro: pytest non eseguibile con l'interprete corrente."""
    rc_text = str(returncode) if returncode is not None else "(timeout: nessuno)"
    first_line = next((ln for ln in output.splitlines() if ln.strip()), "(nessun output)")
    print(
        f"ERRORE: pytest non eseguibile con l'interprete corrente "
        f"(returncode={rc_text}): {_safe_text(first_line.strip()[:200])}\n"
        "Rilancia lo script con l'interprete della venv:\n"
        "    .venv\\Scripts\\python scripts\\run_eval.py",
        file=sys.stderr,
    )


def load_records(jsonl: Path) -> list[dict]:
    if not jsonl.exists():
        return []
    records: list[dict] = []
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _first_error_line(error: str) -> str:
    for line in error.splitlines():
        text = line.strip()
        if text and text != "^" and not set(text) <= {"~", "^"}:
            return text[:200]
    return "(errore senza testo)"


def render_markdown(
    records: list[dict],
    models: list[str],
    runs: int,
    base_url: str,
    outputs: dict[str, str],
) -> str:
    """Tabella modello x scenario + errori tipici, in Markdown."""
    by_key: dict[tuple[str, str], list[dict]] = {}
    for rec in records:
        key = (str(rec.get("model", "")), str(rec.get("scenario", "")))
        by_key.setdefault(key, []).append(rec)

    lines = [
        "# EVAL — Fase 1.7: validazione con modelli reali",
        "",
        f"Generato da `scripts/run_eval.py` il {datetime.now():%Y-%m-%d %H:%M} "
        f"(runs={runs}, base_url={base_url}).",
        "",
        "Ogni cella: **successi/recordi registrati** (tempo medio in secondi).",
        "Uno scenario senza recordi è stato saltato (server non raggiungibile):",
        "riguardare eseguendo di nuovo con Ollama in esecuzione.",
        "",
        "## Risultati",
        "",
    ]
    header = "| Scenario | " + " | ".join(f"`{m}`" for m in models) + " |"
    sep = "|---" * (len(models) + 1) + "|"
    lines += [header, sep]
    for scenario in SCENARIOS:
        cells = []
        for model in models:
            entries = by_key.get((model, scenario), [])
            if not entries:
                cells.append("— (skip)")
                continue
            oks = sum(1 for e in entries if e.get("ok"))
            secs = [float(e.get("seconds", 0.0)) for e in entries]
            avg = sum(secs) / len(secs)
            cell = f"{oks}/{len(entries)} ({avg:.1f}s)"
            if len(entries) < runs:
                cell += f" · {runs - len(entries)} mancanti"
            cells.append(cell)
        lines.append(f"| {scenario} | " + " | ".join(cells) + " |")

    lines += ["", "## Errori tipici", ""]
    any_error = False
    for model in models:
        errors: dict[str, list[str]] = {}
        for (m, scenario), entries in sorted(by_key.items()):
            if m != model:
                continue
            for entry in entries:
                if not entry.get("ok") and entry.get("error"):
                    errors.setdefault(scenario, []).append(
                        _first_error_line(str(entry["error"]))
                    )
        if not errors:
            continue
        any_error = True
        lines.append(f"### {model}")
        for scenario, msgs in errors.items():
            first = msgs[0]
            times = f" (x{len(msgs)})" if len(msgs) > 1 else ""
            lines.append(f"- **{scenario}**{times}: {first}")
        lines.append("")
    if not any_error:
        lines.append("(nessun errore registrato)")
        lines.append("")

    lines += ["## Note", ""]
    for model, output in outputs.items():
        summary = _summary_line(output) or "(nessun riepilogo)"
        lines.append(f"- `{model}`: {summary.strip()}")
    lines += [
        "",
        "La scelta del modello di default va scritta nel README dopo aver",
        "guardato questi numeri (AGENT.md, Fase 1.7 punto 4).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=DEFAULT_MODELS, help="modelli separati da virgola")
    parser.add_argument("--runs", type=int, default=3, help="esecuzioni per modello (default 3)")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--out", default=str(ROOT / "docs" / "EVAL.md"))
    parser.add_argument("--timeout", type=int, default=1800, help="timeout (s) per ogni run")
    args = parser.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        print("Nessun modello specificato", file=sys.stderr)
        return 2

    outputs: dict[str, str] = {}
    jsonls: dict[str, Path] = {}
    interrupted = False
    with (
        tempfile.TemporaryDirectory(prefix="eval_e2e_") as tmp,
        _interrupt_pulito(),
    ):
        try:
            for model in models:
                jsonl = Path(tmp) / (model.replace(":", "_").replace("/", "_") + ".jsonl")
                jsonls[model] = jsonl
                print(f"== {model}: {args.runs} run ==")
                _print_warm_up(args.base_url, model)
                last_output = ""
                for i in range(args.runs):
                    returncode, last_output = run_pytest(model, jsonl, args.base_url, args.timeout)
                    summary = _summary_line(last_output)
                    if summary is None:
                        # diagnostici: ultime righe + returncode del subprocess
                        _print_output_tail(last_output, returncode)
                    # pytest morto con l'interprete sbagliato: niente mezzo report,
                    # termina subito col suggerimento della venv (codice 3)
                    if returncode is not None and returncode not in _PYTEST_OK_CODES:
                        _print_interpreter_error(returncode, last_output)
                        return 3
                    if "No module named" in last_output:
                        _print_interpreter_error(returncode, last_output)
                        return 3
                    summary_text = (summary or "(nessun riepilogo)").strip()
                    print(f"   run {i + 1}/{args.runs}: {_safe_text(summary_text)}")
                outputs[model] = last_output
        except KeyboardInterrupt:
            # 1.7b: Ctrl+C — run_pytest ha già terminato il figlio; si continua
            # con i record che i test completati hanno scritto sul JSONL
            interrupted = True
            print(
                "\nInterrotto (Ctrl+C o Ctrl+Break): subprocess terminato, "
                "raccolgo i record già registrati.",
                file=sys.stderr,
            )
        # il JSONL è la fonte dei recordi: vale per l'esecuzione completa e per
        # quella interrotta a metà (i test già terminati hanno scritto i loro)
        all_records = [record for path in jsonls.values() for record in load_records(path)]

    out_path = Path(args.out)
    if interrupted and not all_records:
        # mai sovrascrivere un EVAL.md già buono con un report vuoto
        print(
            "Interrotto prima di raccogliere record: nessun report scritto "
            "(un EVAL.md esistente resta intatto).",
            file=sys.stderr,
        )
        return EXIT_INTERRUPTED
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        render_markdown(all_records, models, args.runs, args.base_url, outputs),
        encoding="utf-8",
    )
    print(f"\nReport scritto in {out_path} ({len(all_records)} recordi)")
    if interrupted:
        print(
            "Uscita per interruzione: il report contiene solo i run completati.",
            file=sys.stderr,
        )
        return EXIT_INTERRUPTED
    if not all_records:
        print(
            "ATTENZIONE: nessun recordi: Ollama non raggiungibile o tutti gli "
            "scenari saltati. Il report lo dichiara: rilanciare col server su.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    _force_utf8_stdio()  # prima di qualunque stampa (come agent/cli 1.6.5)
    raise SystemExit(main())
