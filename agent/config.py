"""Caricamento e validazione di config.json."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_COMMAND_BLACKLIST: tuple[str, ...] = (
    "rm -rf",
    "rm -fr",
    "rmdir /s",
    "del /f",
    "format ",
    "mkfs",
    "dd if=",
    "shutdown",
    "Remove-Item -Recurse -Force",
)


class ConfigError(ValueError):
    """config.json mancante, malformato o con valori non validi."""


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "ollama"
    model: str = "llama3.1:8b"
    base_url: str = "http://localhost:11434"
    timeout_s: float = 120.0
    # massimo numero di token generati per chiamata: protegge da runaway
    # generazionale (possibile con modelli piccoli) che causerebbe timeout
    num_predict: int = 1024


@dataclass(frozen=True)
class SecurityConfig:
    require_write_confirmation: bool = True
    require_command_confirmation: bool = True
    command_blacklist: tuple[str, ...] = DEFAULT_COMMAND_BLACKLIST
    command_timeout_s: float = 30.0
    max_output_chars: int = 30000


@dataclass(frozen=True)
class AgentConfig:
    workspace_roots: tuple[Path, ...]
    llm: LLMConfig = field(default_factory=LLMConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    max_iterations: int = 15
    max_tool_output_chars: int = 20000


def default_config_path() -> Path:
    """config.json alla radice del progetto (accanto a agent/)."""
    return Path(__file__).resolve().parent.parent / "config.json"


def _as_bool(value: Any, default: bool, name: str) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"{name} deve essere booleano, trovato: {value!r}")
    return value


def _as_int(value: Any, default: int, name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{name} deve essere un intero >= 1, trovato: {value!r}")
    return value


def _as_float(value: Any, default: float, name: str) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{name} deve essere un numero > 0, trovato: {value!r}")
    return float(value)


def load_config(
    path: str | Path | None = None,
    *,
    create_roots: bool = False,
    on_created: Callable[[Path], None] | None = None,
) -> AgentConfig:
    """Legge e valida config.json, restituendo un AgentConfig immutabile.

    Se ``create_roots=True`` le workspace_root mancanti vengono create (deve
    esistere il genitore) e segnalate via ``on_created``; di default una root
    inesistente è un errore.
    """
    cfg_path = Path(path) if path is not None else default_config_path()
    try:
        raw_text = cfg_path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ConfigError(f"config non trovato: {cfg_path}") from e
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"JSON non valido in {cfg_path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{cfg_path}: il contenuto deve essere un oggetto JSON")

    roots_raw = raw.get("workspace_roots")
    if not isinstance(roots_raw, list) or not roots_raw:
        raise ConfigError("workspace_roots mancante o vuoto")
    roots: list[Path] = []
    for item in roots_raw:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"workspace_root non valida: {item!r}")
        root = Path(item).expanduser().resolve()
        if not root.is_dir():
            if create_roots and root.parent.is_dir():
                try:
                    root.mkdir()
                except OSError as e:
                    raise ConfigError(f"workspace_root non creabile: {root} ({e})") from e
                if on_created is not None:
                    on_created(root)
            else:
                raise ConfigError(f"workspace_root inesistente: {root}")
        roots.append(root)

    llm_raw = raw.get("llm", {})
    if not isinstance(llm_raw, dict):
        raise ConfigError("sezione llm deve essere un oggetto")
    llm = LLMConfig(
        provider=str(llm_raw.get("provider", "ollama")),
        model=str(llm_raw.get("model", "llama3.1:8b")),
        base_url=str(llm_raw.get("base_url", "http://localhost:11434")),
        timeout_s=_as_float(llm_raw.get("timeout_s"), 120.0, "llm.timeout_s"),
        num_predict=_as_int(llm_raw.get("num_predict"), 1024, "llm.num_predict"),
    )

    sec_raw = raw.get("security", {})
    if not isinstance(sec_raw, dict):
        raise ConfigError("sezione security deve essere un oggetto")
    blacklist_raw = sec_raw.get("command_blacklist")
    if blacklist_raw is None:
        command_blacklist = DEFAULT_COMMAND_BLACKLIST
    elif isinstance(blacklist_raw, list) and all(isinstance(x, str) for x in blacklist_raw):
        command_blacklist = tuple(blacklist_raw)
    else:
        raise ConfigError("security.command_blacklist deve essere una lista di stringhe")
    security = SecurityConfig(
        require_write_confirmation=_as_bool(
            sec_raw.get("require_write_confirmation"), True, "security.require_write_confirmation"
        ),
        require_command_confirmation=_as_bool(
            sec_raw.get("require_command_confirmation"),
            True,
            "security.require_command_confirmation",
        ),
        command_blacklist=command_blacklist,
        command_timeout_s=_as_float(
            sec_raw.get("command_timeout_s"), 30.0, "security.command_timeout_s"
        ),
        max_output_chars=_as_int(
            sec_raw.get("max_output_chars"), 30000, "security.max_output_chars"
        ),
    )

    agent_raw = raw.get("agent", {})
    if not isinstance(agent_raw, dict):
        raise ConfigError("sezione agent deve essere un oggetto")
    return AgentConfig(
        workspace_roots=tuple(roots),
        llm=llm,
        security=security,
        max_iterations=_as_int(agent_raw.get("max_iterations"), 15, "agent.max_iterations"),
        max_tool_output_chars=_as_int(
            agent_raw.get("max_tool_output_chars"), 20000, "agent.max_tool_output_chars"
        ),
    )


def validate_blacklist(blacklist: Sequence[str]) -> None:
    """Verifica che le voci della blacklist config siano stringhe non vuote."""
    for item in blacklist:
        if not item.strip():
            raise ConfigError("voci di command_blacklist non vuote non ammesse")
