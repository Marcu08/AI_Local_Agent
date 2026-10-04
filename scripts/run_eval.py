"""Esegue gli scenari e2e N volte per modello e genera docs/EVAL.md (Fase 1.7).

NON scarica modelli: richiede un server Ollama già in esecuzione con i modelli
presenti (`ollama pull ...` è un'operazione manuale dell'utente). Se il server
non risponde, i test si skippano e il report lo dichiara esplicitamente.

Uso:
    python scripts/run_eval.py                        # default: 2 candidati, 3 runs
    python scripts/run_eval.py --models llama3.1:8b --runs 1 --out /tmp/eval.md

Ogni run di pytest scrive i suoi recordi su un JSONL temporaneo (opzione
--e2e-json); alla fine i recordi vengono aggregati per modello x scenario.

Codici d'uscita: 0 = recordi presenti, 1 = nessun record (server assente),
2 = nessun modello, 3 = pytest non eseguibile con l'interprete corrente
(usare quello della venv).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

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


def run_pytest(model: str, jsonl: Path, base_url: str, timeout_s: int) -> tuple[int | None, str]:
    """Un giro di pytest; ritorna (returncode | None se timeout, output)."""
    env = dict(os.environ)
    env["AGENT_E2E_BASE_URL"] = base_url
    cmd = [
        # niente -q qui: addopts ha già -q, un secondo -q (-qq) sopprimerebbe
        # la riga di riepilogo "N skipped in Xs" che viene citata nel report
        sys.executable, "-m", "pytest", "tests/e2e", "-m", "e2e",
        "--e2e-models", model, "--e2e-json", str(jsonl),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        partial = e.stdout or ""
        if isinstance(partial, bytes):  # text=True dovrebbe dare str, ma non si sa mai
            partial = partial.decode("utf-8", errors="replace")
        return None, f"{partial}\nTIMEOUT dopo {timeout_s}s"
    return proc.returncode, proc.stdout + proc.stderr


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
        print(f"   | {line}")
    rc_text = str(returncode) if returncode is not None else "(timeout: nessuno)"
    print(f"   | returncode: {rc_text}")


def _print_interpreter_error(returncode: int | None, output: str) -> None:
    """Messaggio chiaro: pytest non eseguibile con l'interprete corrente."""
    rc_text = str(returncode) if returncode is not None else "(timeout: nessuno)"
    first_line = next((ln for ln in output.splitlines() if ln.strip()), "(nessun output)")
    print(
        f"ERRORE: pytest non eseguibile con l'interprete corrente "
        f"(returncode={rc_text}): {first_line.strip()[:200]}\n"
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

    all_records: list[dict] = []
    outputs: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="eval_e2e_") as tmp:
        for model in models:
            jsonl = Path(tmp) / (model.replace(":", "_").replace("/", "_") + ".jsonl")
            print(f"== {model}: {args.runs} run ==")
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
                print(f"   run {i + 1}/{args.runs}: {(summary or '(nessun riepilogo)').strip()}")
            outputs[model] = last_output
            all_records.extend(load_records(jsonl))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        render_markdown(all_records, models, args.runs, args.base_url, outputs),
        encoding="utf-8",
    )
    print(f"\nReport scritto in {out_path} ({len(all_records)} recordi)")
    if not all_records:
        print(
            "ATTENZIONE: nessun recordi: Ollama non raggiungibile o tutti gli "
            "scenari saltati. Il report lo dichiara: rilanciare col server su.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
