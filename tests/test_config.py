"""Test di caricamento e validazione di config.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.config import ConfigError, default_config_path, load_config


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
