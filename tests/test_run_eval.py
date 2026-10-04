"""Test di scripts/run_eval.py con subprocess finto (nessun pytest reale).

Aree (1.7b):
- guasto d'interprete: `python -m pytest` eseguito con la python di sistema
  esce con "No module named pytest" e il report non va scritto a metà (exit 3);
- avanzamento in tempo reale: le righe del figlio escono con prefisso "> "
  mentre il processo gira, non tutte alla fine;
- Ctrl+C: il figlio viene terminato, i record già scritti finiscono in un
  report parziale (exit 130); senza record l'EVAL.md esistente resta intatto;
- encoding: il testo non codificabile del figlio non deve far cadere la
  stampa su una console cp1252 (regressione trovata a mano con run reale);
- Ctrl+Break (Windows): solleva lo stesso KeyboardInterrupt e il handler
  SIGBREAK viene ripristinato a fine run.
"""

from __future__ import annotations

import io
import json
import signal
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scripts import run_eval


class _FakePopen:
    """Stand-in per subprocess.Popen: stdout già pronto, poll/kill registrati.

    `exit_after_read=True` simula un processo che "esce" solo dopo che il suo
    output è stato consumato: se run_pytest aspettasse la fine prima di leggere
    (comportamento di subprocess.run) girerebbe fino al timeout e il test
    fallirebbe. `interrupt=True` fa arrivare il Ctrl+C dal polling di uscita.
    """

    def __init__(
        self,
        returncode: int = 0,
        output: str = "",
        *,
        interrupt: bool = False,
        exit_after_read: bool = False,
    ) -> None:
        self._returncode = returncode
        self._interrupt = interrupt
        self._exhausted = not exit_after_read
        self._lines = output.splitlines(keepends=True)
        self.killed = False
        self.stdout: Any = self._stream()

    def _stream(self) -> Iterator[str]:
        for line in self._lines:
            yield line
        self._exhausted = True

    @property
    def returncode(self) -> int | None:
        return self._returncode if self._exhausted else None

    def poll(self) -> int | None:
        if self._interrupt:
            raise KeyboardInterrupt
        return self.returncode

    def kill(self) -> None:
        self.killed = True


@pytest.mark.parametrize(
    ("returncode", "output"),
    [
        # python -m pytest senza pytest (o con la python sbagliata): rc=1.
        # stderr è unito a stdout nel Popen reale, quindi il messaggio arriva
        # sulla stessa traccia che legge run_pytest.
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
    output: str,
) -> None:
    """Exit 3, nessun report, messaggio sulla venv, ultime righe + rc stampate."""

    def fake_popen(*args: Any, **kwargs: Any) -> _FakePopen:
        return _FakePopen(returncode, output)

    monkeypatch.setattr(run_eval.subprocess, "Popen", fake_popen)
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

    def fake_popen(*args: Any, **kwargs: Any) -> _FakePopen:
        cmd = list(args[0])
        # simula il teardown e2e: scrive un record sul JSONL richiesto
        jsonl = Path(cmd[cmd.index("--e2e-json") + 1])
        record = {"model": "fake:model", "scenario": "elenco_cartella",
                  "ok": True, "seconds": 0.5, "error": ""}
        jsonl.write_text(json.dumps(record) + "\n", encoding="utf-8")
        return _FakePopen(0, "8 passed in 0.10s\n")

    monkeypatch.setattr(run_eval.subprocess, "Popen", fake_popen)
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


def test_print_live_prefisso_e_newline(capsys: pytest.CaptureFixture[str]) -> None:
    """Ogni riga del figlio esce col prefisso '> ', con newline garantita."""
    run_eval._print_live("riga senza fine riga")
    assert capsys.readouterr().out == "   > riga senza fine riga\n"


def test_print_live_non_cade_su_console_cp1252(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressione trovata a mano: � dal figlio + stdout cp1252 non deve
    uccidere il thread di lettura (prima: UnicodeEncodeError e report a metà)."""
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp1252", newline="")
    monkeypatch.setattr(sys, "stdout", stream)

    run_eval._print_live("riga con carattere \ufffd non codificabile\n")

    stream.detach()  # isola il buffer: il GC non deve chiudere BytesIO


def test_safe_text_degrada_senza_perdere_il_resto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_safe_text sostituisce solo i caratteri incompatibili con lo stream."""
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp1252", newline="")
    monkeypatch.setattr(sys, "stdout", stream)

    assert run_eval._safe_text("codice \ufffd qui") == "codice ? qui"
    assert run_eval._safe_text("caff\u00e0") == "caff\u00e0"  # cp1252 conosce la à

    stream.detach()


@pytest.mark.skipif(not hasattr(signal, "SIGBREAK"), reason="SIGBREAK esiste solo su Windows")
def test_break_as_interrupt_e_stesso_keyboard_interrupt() -> None:
    """Ctrl+Break alza l'eccezione che main gestisce già: stesso percorso di Ctrl+C."""
    with pytest.raises(KeyboardInterrupt):
        run_eval._break_as_interrupt(signal.SIGBREAK, None)


@pytest.mark.skipif(not hasattr(signal, "SIGBREAK"), reason="SIGBREAK esiste solo su Windows")
def test_interrupt_pulito_installa_e_ripristina_il_handler() -> None:
    """Il handler c'è solo durante i run: poi torna quello precedente."""
    precedente = signal.getsignal(signal.SIGBREAK)

    with run_eval._interrupt_pulito():
        assert signal.getsignal(signal.SIGBREAK) is run_eval._break_as_interrupt

    assert signal.getsignal(signal.SIGBREAK) is precedente


def test_output_del_figlio_in_tempo_reale(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Le righe vengono lette e stampate mentre il processo gira (non alla fine).

    Il figlio finto "esce" solo quando il suo output è consumato: un'attesa
    alla subprocess.run porterebbe al timeout e a returncode None.
    """

    def fake_popen(*args: Any, **kwargs: Any) -> _FakePopen:
        return _FakePopen(0, "riga uno\nriga due\n", exit_after_read=True)

    monkeypatch.setattr(run_eval.subprocess, "Popen", fake_popen)

    returncode, output = run_eval.run_pytest(
        "fake:model", tmp_path / "x.jsonl", "http://fake", 5
    )

    captured = capsys.readouterr()
    assert returncode == 0, "il processo non deve finire in timeout"
    assert output == "riga uno\nriga due\n"  # raccolto per riepilogo e report
    assert "   > riga uno" in captured.out
    assert "   > riga due" in captured.out


def test_ctrl_c_interrompe_e_scrive_report_parziale(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Primo run ok, secondo interrotto: figlio killato, report col record, exit 130."""
    created: list[_FakePopen] = []
    calls = {"n": 0}

    def fake_popen(*args: Any, **kwargs: Any) -> _FakePopen:
        cmd = list(args[0])
        calls["n"] += 1
        if calls["n"] == 1:
            jsonl = Path(cmd[cmd.index("--e2e-json") + 1])
            record = {
                "model": "fake:model",
                "scenario": "elenco_cartella",
                "ok": True,
                "seconds": 0.5,
            }
            jsonl.write_text(json.dumps(record) + "\n", encoding="utf-8")
            proc = _FakePopen(0, "8 passed in 0.10s\n")
        else:
            proc = _FakePopen(0, "", interrupt=True)
        created.append(proc)
        return proc

    monkeypatch.setattr(run_eval.subprocess, "Popen", fake_popen)
    out = tmp_path / "EVAL.md"

    code = run_eval.main(["--models", "fake:model", "--runs", "2", "--out", str(out)])

    captured = capsys.readouterr()
    assert code == 130
    assert run_eval.EXIT_INTERRUPTED == 130
    assert created[-1].killed, "il subprocess interrotto va terminato"
    assert "run 2/2" not in captured.out, "dopo Ctrl+C il secondo run non parte"
    assert "Interrotto" in captured.err
    assert out.exists(), "con dei record il report parziale va scritto"
    report = out.read_text(encoding="utf-8")
    assert "| elenco_cartella |" in report
    assert "1 recordi" in captured.out
    assert "solo i run completati" in captured.err


def test_ctrl_c_prima_di_ogni_record_non_scrive_il_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Ctrl+C immediato: nessun record → l'EVAL.md esistente resta intatto, exit 130."""

    def fake_popen(*args: Any, **kwargs: Any) -> _FakePopen:
        return _FakePopen(0, "", interrupt=True)

    monkeypatch.setattr(run_eval.subprocess, "Popen", fake_popen)
    out = tmp_path / "EVAL.md"
    out.write_text("# report precedente\n", encoding="utf-8")

    code = run_eval.main(["--models", "fake:model", "--runs", "1", "--out", str(out)])

    captured = capsys.readouterr()
    assert code == 130
    assert out.read_text(encoding="utf-8") == "# report precedente\n"
    assert "nessun report scritto" in captured.err
    assert "Report scritto" not in captured.out
