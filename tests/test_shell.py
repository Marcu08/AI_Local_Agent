"""Test del tool terminale: blacklist a monte, conferma, cwd, timeout."""

from __future__ import annotations

import subprocess

import pytest

from agent.config import AgentConfig, SecurityConfig
from agent.tools import create_default_registry
from agent.tools.base import ToolContext


@pytest.fixture
def calls() -> list[dict]:
    return []


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch, calls: list[dict]):
    """Sostituisce subprocess.run: registra le chiamate senza eseguire nulla."""

    def _run(cmd, **kwargs):  # noqa: ANN001
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout="ok stdout\n", stderr="")

    monkeypatch.setattr("agent.tools.shell.subprocess.run", _run)
    return _run


def _ctx(config, confirm) -> ToolContext:
    return ToolContext(config=config, confirm=confirm)


def test_blacklist_blocca_prima_di_subprocess(
    config, allow_confirm, calls, fake_run
) -> None:
    registry = create_default_registry()
    result = registry.dispatch(
        "run_command", {"command": "rm -rf /"}, _ctx(config, allow_confirm)
    )
    assert not result.ok
    assert "BLOCCATO" in (result.error or "")
    assert calls == [], "subprocess NON deve essere chiamato per comandi blacklistati"


def test_blacklist_config_extra(config, workspace, allow_confirm, calls, fake_run) -> None:
    cfg = AgentConfig(
        workspace_roots=(workspace,),
        security=SecurityConfig(command_blacklist=("killall",)),
    )
    registry = create_default_registry()
    result = registry.dispatch(
        "run_command", {"command": "killall node"}, _ctx(cfg, allow_confirm)
    )
    assert not result.ok
    assert calls == []


def test_conferma_negata_nessuna_esecuzione(config, deny_confirm, calls, fake_run) -> None:
    registry = create_default_registry()
    result = registry.dispatch(
        "run_command", {"command": "echo ciao"}, _ctx(config, deny_confirm)
    )
    assert not result.ok
    assert "rifiutato" in (result.error or "")
    assert calls == [], "un comando rifiutato non deve raggiungere subprocess"


def test_esecuzione_confermata(config, allow_confirm, calls, fake_run, workspace) -> None:
    registry = create_default_registry()
    result = registry.dispatch(
        "run_command", {"command": "echo ciao"}, _ctx(config, allow_confirm)
    )
    assert result.ok
    output = result.output or ""
    assert "exit code: 0" in output
    assert "ok stdout" in output
    assert len(calls) == 1
    # cwd forzato alla prima workspace_root, output catturato
    assert calls[0]["cwd"] == str(workspace)
    assert calls[0]["capture_output"] is True
    assert calls[0]["shell"] is True


def test_timeout_gestito(config, allow_confirm, monkeypatch: pytest.MonkeyPatch) -> None:
    def _timeout(cmd, **kwargs):  # noqa: ANN001
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

    monkeypatch.setattr("agent.tools.shell.subprocess.run", _timeout)
    registry = create_default_registry()
    result = registry.dispatch(
        "run_command", {"command": "echo lento"}, _ctx(config, allow_confirm)
    )
    assert not result.ok
    assert "timeout" in (result.error or "")


def test_comando_non_stringa(config, allow_confirm) -> None:
    registry = create_default_registry()
    result = registry.dispatch("run_command", {}, _ctx(config, allow_confirm))
    assert not result.ok
    assert "command" in (result.error or "")


def test_exit_code_diverso_da_zero_è_osservazione(config, allow_confirm, monkeypatch) -> None:
    def _fail(cmd, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="fallito")

    monkeypatch.setattr("agent.tools.shell.subprocess.run", _fail)
    registry = create_default_registry()
    result = registry.dispatch(
        "run_command", {"command": "git diff"}, _ctx(config, allow_confirm)
    )
    # exit code != 0 non è un errore del tool: è un'osservazione per l'LLM
    assert result.ok
    output = result.output or ""
    assert "exit code: 2" in output
    assert "fallito" in output
