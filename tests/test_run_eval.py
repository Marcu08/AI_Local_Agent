"""Test di scripts/run_eval.py con subprocess finto (nessun pytest reale).

Copre il guasto d'interprete: `python -m pytest` eseguito con la python di
sistema invece che della venv esce con "No module named pytest" e il report
non va scritto a metà.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_eval


class _FakeProc:
    """Stand-in per subprocess.CompletedProcess."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.mark.parametrize(
    ("returncode", "stderr"),
    [
        # python -m pytest senza pytest (o con la python sbagliata): rc=1
        (1, r"C:\python\python.exe: No module named pytest"),
        # exit code fuori da {0, 1, 5}: interruzione/errore interno
        (3, "Traceback (most recent call last):\n killed"),
    ],
    ids=["pytest-assente", "returncode-inatteso"],
)
def test_guasto_interprete_termina_col_suggerimento_venv(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    returncode: int,
    stderr: str,
) -> None:
    """Exit 3, nessun report, messaggio sulla venv, ultime righe + rc stampate."""

    def fake_run(*args: object, **kwargs: object) -> _FakeProc:
        return _FakeProc(returncode, "", stderr)

    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)
    out = tmp_path / "EVAL.md"

    code = run_eval.main(["--models", "fake:model", "--runs", "1", "--out", str(out)])

    captured = capsys.readouterr()
    assert code == 3
    # il messaggio va a stderr e indica l'interprete della venv
    assert "venv" in captured.err
    assert "No module named pytest" in captured.err or "returncode=3" in captured.err
    # riepilogo assente → ultime 15 righe + returncode su stdout
    assert "riepilogo assente" in captured.out
    assert f"| returncode: {returncode}" in captured.out
    # termina subito: report non scritto
    assert not out.exists()


def test_run_regolare_produce_il_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Subprocess finto sano: riepilogo trovato, record scritto, exit 0."""

    def fake_run(*args: object, **kwargs: object) -> _FakeProc:
        cmd = list(args[0])  # type: ignore[arg-type]
        # simula il teardown e2e: scrive un record sul JSONL richiesto
        jsonl = Path(cmd[cmd.index("--e2e-json") + 1])
        record = {"model": "fake:model", "scenario": "elenco_cartella",
                  "ok": True, "seconds": 0.5, "error": ""}
        jsonl.write_text(json.dumps(record) + "\n", encoding="utf-8")
        return _FakeProc(0, "8 passed in 0.10s\n", "")

    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)
    out = tmp_path / "EVAL.md"

    code = run_eval.main(["--models", "fake:model", "--runs", "1", "--out", str(out)])

    captured = capsys.readouterr()
    assert code == 0
    assert "riepilogo assente" not in captured.out
    assert "8 passed in 0.10s" in captured.out
    assert out.exists()
    report = out.read_text(encoding="utf-8")
    assert "8 passed in 0.10s" in report
    assert "| elenco_cartella |" in report
