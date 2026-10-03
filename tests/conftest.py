"""Fixture condivise: workspace sintetico, config di test, conferme mock."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.config import AgentConfig
from agent.security.confirm import ScriptedConfirm


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
def config(workspace: Path) -> AgentConfig:
    """Config di test: una sola root (il workspace sintetico), conferme attive."""
    return AgentConfig(workspace_roots=(workspace,))


@pytest.fixture
def allow_confirm() -> ScriptedConfirm:
    """Conferma che risponde SI a ogni richiesta (per test di percorso felice)."""
    return ScriptedConfirm(answers=[True], default=True)


@pytest.fixture
def deny_confirm() -> ScriptedConfirm:
    """Conferma che risponde NO a ogni richiesta (per test Human-in-the-Loop)."""
    return ScriptedConfirm(default=False)
