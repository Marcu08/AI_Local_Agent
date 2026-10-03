"""Test 1.5.7 (3/5): bypass dei gate, parametrizzati — un caso per bypass.

Copre: flag non elencati su git diff/log (``--output``, ``--ext-diff``,
``--no-index``, ``--textconv``, glifi numerici/pretty), pytest e ruff fuori
dall'auto-approvazione (``-p``, ``-c``, ``--rootdir``, ``--fix``, ``--fix-only``)
e argomenti-path che, risolti con resolve(), escono dalle workspace_root
(symlink/junction dentro la root che punta fuori, ``..``).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from agent.security.confirm import ScriptedConfirm
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
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("agent.tools.shell.subprocess.run", _run)
    return _run


def _dispatch(config, command: str, *, approve: bool):
    confirm = ScriptedConfirm(default=approve)
    registry = create_default_registry()
    result = registry.dispatch(
        "run_command", {"command": command}, ToolContext(config=config, confirm=confirm)
    )
    return result, confirm


def _ids(rows: Sequence[str | tuple[str, ...]]) -> list[str]:
    return [re.sub(r"[^\w./<>-]", "_", row[0] if isinstance(row, tuple) else row) for row in rows]


# --- flag elencati dalla voce: auto-approvati -----------------------------------
_AUTO_FLAGS: list[str] = [
    "git diff --stat",
    "git diff --name-only",
    "git diff --cached",
    "git diff --stat --cached",
    "git diff HEAD~1 --name-only",
    "git log --oneline",
    "git log -n 5",
    "git log --stat -n 3",
    "git log -n 3 --oneline",
    "git status -sb",
]


@pytest.mark.parametrize("command", _AUTO_FLAGS, ids=_ids(_AUTO_FLAGS))
def test_flag_elencato_auto_approvato(config, workspace, calls, fake_run, command) -> None:
    """I flag nella voce allowlist partono senza conferma."""
    result, confirm = _dispatch(config, command, approve=True)
    assert result.ok, result.error
    assert confirm.calls == [], "un flag elencato non deve chiedere conferma"
    assert len(calls) == 1


# --- bypass: flag NON elencati o comandi fuori allowlist → conferma -------------
_FLAG_BYPASS: list[tuple[str, str]] = [
    # git diff: vietati/non elencati → mai auto
    ("git diff --output=fuori.diff", "flag non ammesso (--output)"),
    ("git diff --output fuori.diff", "flag non ammesso (--output)"),
    ("git diff --ext-diff", "flag non ammesso (--ext-diff)"),
    ("git diff --no-index", "flag non ammesso (--no-index)"),
    ("git diff --textconv", "flag non ammesso (--textconv)"),
    ("git diff --color=always", "flag non ammesso (--color)"),
    ("git diff -w", "flag non ammesso (-w)"),
    ("git diff --output=$(id)", "contiene metacaratteri shell"),
    # git log: stessi vincoli
    ("git log --output=out.diff", "flag non ammesso (--output)"),
    ("git log --ext-diff", "flag non ammesso (--ext-diff)"),
    ("git log --no-index", "flag non ammesso (--no-index)"),
    ("git log --textconv", "flag non ammesso (--textconv)"),
    ("git log -p", "flag non ammesso (-p)"),
    ("git log --oneline -5", "flag non ammesso (-5)"),
    ("git log --pretty=fuller", "flag non ammesso (--pretty)"),
    ("git log --oneline --output=x", "flag non ammesso (--output)"),
    # altre voci allowlist: qualsiasi flag non elencato forza la conferma
    ("git status --short", "flag non ammesso (--short)"),
    ("cat --version", "flag non ammesso (--version)"),
    ("git --no-pager diff", "comando non presente in allowlist"),
]

_PYTEST_RUFF: list[tuple[str, str]] = [
    # pytest/ruff fuori dall'auto-approvazione: ogni invocazione fa conferma
    ("pytest", "comando non presente in allowlist"),
    ("pytest -p no:logging", "comando non presente in allowlist"),
    ("pytest -c custom.ini", "comando non presente in allowlist"),
    ("pytest --rootdir=.", "comando non presente in allowlist"),
    ("pytest -k smoke", "comando non presente in allowlist"),
    ("python -m pytest", "comando non presente in allowlist"),
    ("python -m pytest -p x", "comando non presente in allowlist"),
    ("ruff check", "comando non presente in allowlist"),
    ("ruff check --fix", "comando non presente in allowlist"),
    ("ruff check --fix-only", "comando non presente in allowlist"),
    ("ruff check -p someplugin", "comando non presente in allowlist"),
]

_BYPASS_CASES = _FLAG_BYPASS + _PYTEST_RUFF


@pytest.mark.parametrize("command,motivo", _BYPASS_CASES, ids=_ids(_BYPASS_CASES))
def test_bypass_forza_conferma(config, workspace, calls, fake_run, command, motivo) -> None:
    """Ogni bypass elencato arriva alla conferma (default NO) e non esegue."""
    result, confirm = _dispatch(config, command, approve=False)
    assert len(confirm.calls) == 1, f"attesa conferma per: {command}"
    _action, detail = confirm.calls[0]
    assert command in detail, "il dettaglio deve mostrare il comando completo"
    assert motivo in detail, f"motivo atteso {motivo!r} in: {detail!r}"
    assert calls == [], "comando rifiutato: subprocess non deve partire"
    assert not result.ok and "rifiutato" in (result.error or "")


# --- argomenti-path risolti con resolve() ---------------------------------------
def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlink non creabili qui (privilegi Windows/FS)")


def _outside_file(workspace: Path) -> Path:
    outside = workspace.parent / "outside"
    outside.mkdir(exist_ok=True)
    target = outside / "target_link.txt"
    target.write_text("segreto\n", encoding="utf-8")
    return target


def test_symlink_file_verso_fuori_forza_conferma(
    config, workspace, calls, fake_run
) -> None:
    """Un file-symlink dentro la root che punta fuori non passa in auto."""
    link = workspace / "link_esterno.txt"
    _symlink_or_skip(link, _outside_file(workspace))
    result, confirm = _dispatch(config, "cat link_esterno.txt", approve=False)
    assert len(confirm.calls) == 1
    _action, detail = confirm.calls[0]
    assert "esce dalle workspace_root" in detail
    assert calls == []


def test_symlink_cartella_verso_fuori_forza_conferma(
    config, workspace, calls, fake_run
) -> None:
    """Stesso discorso per una cartella-link (junction/symlink di directory)."""
    link = workspace / "link_cartella"
    _symlink_or_skip(link, workspace.parent / "outside", directory=True)
    result, confirm = _dispatch(config, "cat link_cartella/segreto.txt", approve=False)
    assert len(confirm.calls) == 1
    _action, detail = confirm.calls[0]
    assert "esce dalle workspace_root" in detail
    assert calls == []


def test_symlink_verso_dentro_rest_auto(config, workspace, calls, fake_run) -> None:
    """Il controllo non rifiuta i link: un link interno resta auto-approvato."""
    link = workspace / "link_interno.txt"
    _symlink_or_skip(link, workspace / "notes.md")
    result, confirm = _dispatch(config, "cat link_interno.txt", approve=True)
    assert result.ok, result.error
    assert confirm.calls == []
    assert len(calls) == 1


def test_dotdot_fuori_root_forza_conferma(config, workspace, calls, fake_run) -> None:
    """`..` fuori dalle root: stesso check di containment (coperto da resolve)."""
    result, confirm = _dispatch(config, "cat ../../etc/passwd", approve=False)
    assert len(confirm.calls) == 1
    _action, detail = confirm.calls[0]
    assert "esce dalle workspace_root" in detail
    assert calls == []


# --- 1.6.0: cat/type su file sensibili → SEMPRE conferma ----------------------
_SENSITIVE_CASES: list[str] = [
    "cat .env",
    "cat .env.local",
    "cat sub/.env",
    "cat cert.pem",
    "cat id_rsa",
    "cat id_rsa.pub",
    "cat server.key",
    "cat .git/config",
    "type .env",
    "type server.key",
]


@pytest.mark.parametrize("command", _SENSITIVE_CASES, ids=_ids(_SENSITIVE_CASES))
def test_cat_type_file_sensibile_forza_conferma(
    config, workspace, calls, fake_run, command
) -> None:
    """File sensibile dentro la root: la lettura cade sempre sulla conferma."""
    result, confirm = _dispatch(config, command, approve=False)
    assert len(confirm.calls) == 1, f"attesa conferma per: {command}"
    _action, detail = confirm.calls[0]
    assert "file sensibile" in detail, detail
    assert calls == []


def test_cat_file_normale_rest_auto(config, workspace, calls, fake_run) -> None:
    """Il controllo non divampa: un file ordinario nella root resta auto."""
    result, confirm = _dispatch(config, "cat notes.md", approve=True)
    assert result.ok, result.error
    assert confirm.calls == []
    assert len(calls) == 1


def test_symlink_dal_nome_innocuo_verso_env_forza_conferma(
    config, workspace, calls, fake_run
) -> None:
    """Il check è sul path risolto: un link chiamato hint.txt che punta a .env
    viene scoperto, mentre un link verso un file ordinario no."""
    env_target = workspace / ".env"
    env_target.write_text("CHIAVE=segreta\n", encoding="utf-8")
    link = workspace / "hint.txt"
    _symlink_or_skip(link, env_target)
    result, confirm = _dispatch(config, "cat hint.txt", approve=False)
    assert len(confirm.calls) == 1
    _action, detail = confirm.calls[0]
    assert "file sensibile" in detail
    assert calls == []


# --- 1.6.0: opzioni git di sicurezza aggiunte dal TOOL ------------------------
def test_git_diff_auto_eseguito_con_opzioni_difesa(
    config, workspace, calls, fake_run
) -> None:
    """git diff auto: -c core.fsmonitor=false -c core.pager=cat + --no-ext-diff
    --no-textconv, tutti inseriti dal tool (il modello non li chiede)."""
    result, confirm = _dispatch(config, "git diff --stat", approve=True)
    assert result.ok, result.error
    assert confirm.calls == []
    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    assert cmd.startswith("git -c core.fsmonitor=false -c core.pager=cat ")
    assert cmd.endswith(" diff --stat --no-ext-diff --no-textconv")


def test_git_log_auto_stesse_opzioni(config, workspace, calls, fake_run) -> None:
    """Stesse opzioni difesa su git log (sotto-comando che le accetta)."""
    result, confirm = _dispatch(config, "git log --oneline -n 3", approve=True)
    assert result.ok, result.error
    assert confirm.calls == []
    cmd = calls[0]["cmd"]
    assert cmd.startswith("git -c core.fsmonitor=false -c core.pager=cat ")
    assert cmd.endswith(" log --oneline -n 3 --no-ext-diff --no-textconv")


def test_git_status_auto_solo_opzioni_globali(config, workspace, calls, fake_run) -> None:
    """git status NON accetta --no-ext-diff/--no-textconv (exit 129):
    il tool aggiunge solo le opzioni globali e non rompe il comando."""
    result, confirm = _dispatch(config, "git status -s", approve=True)
    assert result.ok, result.error
    assert confirm.calls == []
    cmd = calls[0]["cmd"]
    assert cmd.startswith("git -c core.fsmonitor=false -c core.pager=cat ")
    assert "--no-ext-diff" not in cmd and "--no-textconv" not in cmd


def test_git_confermato_dall_utente_non_riscritto(
    config, workspace, calls, fake_run
) -> None:
    """La riscrittura vale per il path auto: un comando approvato dall'utente
    viene eseguito esattamente come mostrato nella conferma."""
    result, confirm = _dispatch(config, "git diff --ext-diff", approve=True)
    assert result.ok, result.error
    assert len(confirm.calls) == 1
    assert calls[0]["cmd"] == "git diff --ext-diff"


def test_comando_non_git_non_riscritto(config, workspace, calls, fake_run) -> None:
    """Solo git viene riscritto: gli altri comandi auto partono invariati."""
    result, confirm = _dispatch(config, "ls -la", approve=True)
    assert result.ok, result.error
    assert confirm.calls == []
    assert calls[0]["cmd"] == "ls -la"
