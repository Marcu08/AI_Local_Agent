"""Smoke test della CLI: python -m agent --provider mock senza rete né TTY."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_smoke_cli_mock_un_turno_completo() -> None:
    """Un turno ReAct offline: list_dir (tool call) -> osservazione -> risposta finale."""
    proc = subprocess.run(
        [sys.executable, "-m", "agent", "--provider", "mock"],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(_PROJECT_ROOT),
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "Act:" in proc.stdout, "la tool call list_dir deve essere renderizzata"
    assert "Observation:" in proc.stdout, "l'osservazione del tool deve essere renderizzata"
    assert "Demo mock completata" in proc.stdout, "risposta finale attesa"


def test_smoke_cli_config_non_valido() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "agent", "--config", "config_assente.json"],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(_PROJECT_ROOT),
    )
    assert proc.returncode == 2
    assert "non valido" in (proc.stdout + proc.stderr)
