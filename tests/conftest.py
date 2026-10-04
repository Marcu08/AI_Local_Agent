"""Fixture condivise: workspace sintetico, config di test, conferme mock."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.config import AgentConfig
from agent.security.confirm import ScriptedConfirm


def pytest_addoption(parser: pytest.Parser) -> None:
    """Opzioni della Fase 1.7 (scenari e2e): modello e report JSONL.

    I valori di default arrivano da variabile d'ambiente, così lo script
    scripts/run_eval.py e un utente manuale possono entrambi usarle.
    """
    parser.addoption(
        "--e2e-models",
        action="store",
        default=os.environ.get("AGENT_E2E_MODELS", ""),
        help="modelli e2e separati da virgola (o env AGENT_E2E_MODELS)",
    )
    parser.addoption(
        "--e2e-json",
        action="store",
        default=os.environ.get("AGENT_E2E_JSON", ""),
        help="file JSONL per esiti/tempi degli scenari e2e (o env AGENT_E2E_JSON)",
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Cartella radice sintetica con qualche file, più una zona 'fuori whitelist'."""
    root = tmp_path / "workspace"
    (root / "sub").mkdir(parents=True)
    (root / "notes.md").write_text("# Note\nciao mondo\n", encoding="utf-8")
    (root / "sub" / "a.txt").write_text("contenuto a\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("segreto\n", encoding="utf-8")
    return root


@pytest.fixture
def config(workspace: Path, tmp_path: Path) -> AgentConfig:
    """Config di test: root = workspace sintetico, conversazioni in tmp (1.6.6)."""
    return AgentConfig(
        workspace_roots=(workspace,),
        conversations_dir=tmp_path / "conversations",
    )


@pytest.fixture
def allow_confirm() -> ScriptedConfirm:
    """Conferma che risponde SI a ogni richiesta (per test di percorso felice)."""
    return ScriptedConfirm(answers=[True], default=True)


@pytest.fixture
def deny_confirm() -> ScriptedConfirm:
    """Conferma che risponde NO a ogni richiesta (per test Human-in-the-Loop)."""
    return ScriptedConfirm(default=False)
