"""Test di caricamento e validazione di config.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.config import (
    DEFAULT_COMMAND_ALLOWLIST,
    ConfigError,
    default_config_path,
    load_config,
)
from agent.security.allowlist import AllowlistEntry


def _write_cfg(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_config_valido(tmp_path: Path) -> None:
    cfg = _write_cfg(
        tmp_path / "config.json",
        {
            "workspace_roots": [str(tmp_path)],
            "llm": {"provider": "ollama", "model": "llama3.1:8b"},
            "security": {"require_write_confirmation": True, "command_blacklist": ["killall"]},
            "agent": {"max_iterations": 7},
        },
    )
    loaded = load_config(cfg)
    assert loaded.workspace_roots == (tmp_path.resolve(),)
    assert loaded.llm.model == "llama3.1:8b"
    assert loaded.llm.num_predict == 1024  # default anti-runaway
    assert loaded.max_iterations == 7
    assert loaded.security.command_blacklist == ("killall",)
    assert loaded.security.require_write_confirmation is True


def test_num_predict_configurabile(tmp_path: Path) -> None:
    cfg = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(tmp_path)], "llm": {"num_predict": 2048}},
    )
    assert load_config(cfg).llm.num_predict == 2048
    cfg2 = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(tmp_path)], "llm": {"num_predict": 0}},
    )
    with pytest.raises(ConfigError, match="num_predict"):
        load_config(cfg2)


def test_num_ctx_configurabile(tmp_path: Path) -> None:
    """llm.num_ctx: default 8192, override dal config e validazione (>= 1)."""
    default = load_config(
        _write_cfg(tmp_path / "config.json", {"workspace_roots": [str(tmp_path)]})
    )
    assert default.llm.num_ctx == 8192

    cfg = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(tmp_path)], "llm": {"num_ctx": 4096}},
    )
    assert load_config(cfg).llm.num_ctx == 4096

    cfg2 = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(tmp_path)], "llm": {"num_ctx": 0}},
    )
    with pytest.raises(ConfigError, match="num_ctx"):
        load_config(cfg2)


def test_history_limiti_configurabili(tmp_path: Path) -> None:
    """agent.history_max_messages / history_max_chars: default e validazione."""
    cfg = _write_cfg(
        tmp_path / "config.json",
        {
            "workspace_roots": [str(tmp_path)],
            "agent": {"history_max_messages": 12, "history_max_chars": 9000},
        },
    )
    loaded = load_config(cfg)
    assert loaded.history_max_messages == 12
    assert loaded.history_max_chars == 9000

    defaults = load_config(
        _write_cfg(tmp_path / "config.json", {"workspace_roots": [str(tmp_path)]})
    )
    assert defaults.history_max_messages == 40
    assert defaults.history_max_chars == 50000

    cfg2 = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(tmp_path)], "agent": {"history_max_messages": 0}},
    )
    with pytest.raises(ConfigError, match="history_max_messages"):
        load_config(cfg2)


def test_load_config_eseguibile_del_progetto() -> None:
    """Struttura del config.json consegnato con il progetto.

    Solo ispezione del JSON: le workspace_root possono non esistere su un'altra
    macchina, quindi non si chiama load_config() (test portabile).
    """
    path = default_config_path()
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    roots = raw.get("workspace_roots")
    assert isinstance(roots, list) and roots
    assert all(isinstance(r, str) and r.strip() for r in roots)
    assert raw.get("llm", {}).get("provider") in {"ollama", "mock"}
    assert raw.get("security", {}).get("require_write_confirmation") is True
    assert raw.get("security", {}).get("require_command_confirmation") is True


def test_config_mancante(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="non trovato"):
        load_config(tmp_path / "assente.json")


def test_config_json_invalido(tmp_path: Path) -> None:
    bad = tmp_path / "config.json"
    bad.write_text("{non json", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON non valido"):
        load_config(bad)


def test_workspace_roots_vuote(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / "config.json", {"workspace_roots": []})
    with pytest.raises(ConfigError, match="workspace_roots"):
        load_config(cfg)


def test_workspace_root_inesistente(tmp_path: Path) -> None:
    cfg = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(tmp_path / "mai_creata")]},
    )
    with pytest.raises(ConfigError, match="inesistente"):
        load_config(cfg)


def test_create_roots_crea_root_mancante(tmp_path: Path) -> None:
    """Con create_roots la root mancante viene creata e segnalata via on_created."""
    root = tmp_path / "agent_workspace"
    cfg = _write_cfg(tmp_path / "config.json", {"workspace_roots": [str(root)]})
    created: list[Path] = []
    loaded = load_config(cfg, create_roots=True, on_created=created.append)
    assert root.is_dir()
    assert created == [root.resolve()]
    assert loaded.workspace_roots == (root.resolve(),)


def test_create_roots_genitore_mancente_fallisce(tmp_path: Path) -> None:
    """Se manca il genitore la root non viene creata: errore chiaro."""
    root = tmp_path / "non_esiste" / "workspace"
    cfg = _write_cfg(tmp_path / "config.json", {"workspace_roots": [str(root)]})
    with pytest.raises(ConfigError, match="inesistente"):
        load_config(cfg, create_roots=True)
    assert not root.exists()


def test_allowlist_letta_da_config(tmp_path: Path) -> None:
    cfg = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(tmp_path)], "security": {"command_allowlist": ["mine"]}},
    )
    assert load_config(cfg).security.command_allowlist == (AllowlistEntry("mine"),)


def test_allowlist_con_flag_da_config(tmp_path: Path) -> None:
    """Voce oggetto {command, flags}: i flag ammessi vivono nella voce stessa."""
    cfg = _write_cfg(
        tmp_path / "config.json",
        {
            "workspace_roots": [str(tmp_path)],
            "security": {
                "command_allowlist": [
                    "cat",
                    {"command": "git diff", "flags": ["--stat", "-n"]},
                ]
            },
        },
    )
    assert load_config(cfg).security.command_allowlist == (
        AllowlistEntry("cat"),
        AllowlistEntry("git diff", ("--stat", "-n")),
    )


def test_allowlist_voce_malformata_rifiutata(tmp_path: Path) -> None:
    for bad in (
        [{"flags": ["--stat"]}],  # manca command
        [{"command": "git diff", "flags": "--stat"}],  # flags non è una lista
        [{"command": "git diff", "flags": [42]}],  # flag non stringa
        [42],  # tipo sconosciuto
    ):
        cfg = _write_cfg(
            tmp_path / "config.json",
            {"workspace_roots": [str(tmp_path)], "security": {"command_allowlist": bad}},
        )
        with pytest.raises(ConfigError, match="command_allowlist"):
            load_config(cfg)


def test_allowlist_default_se_assente(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / "config.json", {"workspace_roots": [str(tmp_path)]})
    assert load_config(cfg).security.command_allowlist == DEFAULT_COMMAND_ALLOWLIST
    # 1.5.7: pytest/ruff fuori dall'auto-approvazione
    commands = {entry.command for entry in DEFAULT_COMMAND_ALLOWLIST}
    assert "pytest" not in commands and "ruff check" not in commands
    git_entry = next(e for e in DEFAULT_COMMAND_ALLOWLIST if e.command == "git diff")
    assert "--output" not in git_entry.flags and "--ext-diff" not in git_entry.flags


def test_allowlist_non_lista_rifiutata(tmp_path: Path) -> None:
    cfg = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(tmp_path)], "security": {"command_allowlist": "dir"}},
    )
    with pytest.raises(ConfigError, match="command_allowlist"):
        load_config(cfg)


def test_bool_non_booleano_rifiutato(tmp_path: Path) -> None:
    cfg = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(tmp_path)], "security": {"require_write_confirmation": "yes"}},
    )
    with pytest.raises(ConfigError, match="booleano"):
        load_config(cfg)


def test_max_iterations_non_valido(tmp_path: Path) -> None:
    cfg = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(tmp_path)], "agent": {"max_iterations": 0}},
    )
    with pytest.raises(ConfigError, match="max_iterations"):
        load_config(cfg)


def test_requires_python_sotto_o_uguale_3_11() -> None:
    """requires-python non deve tornare sopra >=3.11 (Fase 1.5.1, ribadito in 1.5.7)."""
    import tomllib

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    requires = data["project"]["requires-python"]
    min_version = requires.replace(">=", "").split(",")[0].strip()
    parts = tuple(int(p) for p in min_version.split("."))
    assert parts <= (3, 11), f"requires-python alzato oltre 3.11: {requires!r}"


def test_config_json_reale_dichiara_limiti_storico() -> None:
    """Il config.json spedito rende espliciti history_max_messages/chars (1.5.7).

    Solo lettura grezza delle chiavi: path derivato da __file__ (portabile),
    nessun caricamento validato né creazione di workspace.
    """
    root = Path(__file__).resolve().parent.parent
    data = json.loads((root / "config.json").read_text(encoding="utf-8"))
    agent = data["agent"]
    assert agent["history_max_messages"] == 40
    assert agent["history_max_chars"] == 50000


# --- 1.6.6: conversations_dir ------------------------------------------------

def test_conversations_dir_configurabile(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    conv = tmp_path / "altre" / "conversazioni"
    cfg = _write_cfg(
        tmp_path / "config.json",
        {"workspace_roots": [str(root)], "conversations_dir": str(conv)},
    )
    loaded = load_config(cfg)
    assert loaded.conversations_dir == conv.resolve()


def test_conversations_dir_default_none(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / "config.json", {"workspace_roots": [str(tmp_path)]})
    assert load_config(cfg).conversations_dir is None  # fallback ~/.agent al uso


def test_conversations_dir_dentro_workspace_rifiutata(tmp_path: Path) -> None:
    """Deve stare FUORI dalle root: i file di conversazione non sono leggibili."""
    root = tmp_path / "ws"
    root.mkdir()
    cfg = _write_cfg(
        tmp_path / "config.json",
        {
            "workspace_roots": [str(root)],
            "conversations_dir": str(root / "conversazioni"),
        },
    )
    with pytest.raises(ConfigError, match="FUORI"):
        load_config(cfg)
