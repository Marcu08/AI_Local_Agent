"""Smoke test della CLI: python -m agent --provider mock senza rete né TTY.

Config di test con root temporanee: nessuna dipendenza dal config.json reale
né da path della macchina dell'autore (test portabile).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _write_tmp_config(tmp_path: Path) -> Path:
    """Config di test: root temporanea pre-caricata + provider mock."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "file_di_test.txt").write_text("contenuto", encoding="utf-8")
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "workspace_roots": [str(root)],
                "llm": {"provider": "mock"},
            }
        ),
        encoding="utf-8",
    )
    return cfg


def test_smoke_cli_mock_un_turno_completo(tmp_path: Path) -> None:
    """Un turno ReAct offline: list_dir (tool call) -> osservazione -> risposta finale."""
    cfg = _write_tmp_config(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "agent", "--config", str(cfg)],
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
    # Prova di portabilità: la list_dir ha letto la ROOT TEMPORANEA del test.
    assert "file_di_test.txt" in proc.stdout


def test_smoke_cli_config_non_valido(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "agent", "--config", str(tmp_path / "config_assente.json")],
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


def test_smoke_cli_crea_workspace_mancante(tmp_path: Path) -> None:
    """La root mancante viene creata all'avvio con un messaggio chiaro."""
    root = tmp_path / "workspace_da_creare"
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"workspace_roots": [str(root)], "llm": {"provider": "mock"}}),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "agent", "--config", str(cfg)],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(_PROJECT_ROOT),
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert root.is_dir(), "la cartella workspace deve essere stata creata all'avvio"
    assert "creata" in proc.stdout, "il messaggio di creazione deve essere visibile"


def test_smoke_cli_avviso_root_home(tmp_path: Path) -> None:
    """Root che coincide con la home: avviso all'avvio (home via USERPROFILE)."""
    fakehome = tmp_path / "fakehome"
    fakehome.mkdir()
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"workspace_roots": [str(fakehome)], "llm": {"provider": "mock"}}),
        encoding="utf-8",
    )
    env = dict(os.environ, USERPROFILE=str(fakehome))
    proc = subprocess.run(
        [sys.executable, "-m", "agent", "--config", str(cfg)],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(_PROJECT_ROOT),
        env=env,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "Avviso" in proc.stdout, "l'avviso root sensibili deve essere mostrato"
    assert "home" in proc.stdout
