"""Test dei tool filesystem: lettura whitelist, scrittura con diff e conferma."""

from __future__ import annotations

import pytest

from agent.config import AgentConfig, SecurityConfig
from agent.security.confirm import ScriptedConfirm
from agent.tools import create_default_registry
from agent.tools.base import ToolContext, ToolRegistry, ToolResult


@pytest.fixture
def registry() -> ToolRegistry:
    return create_default_registry()


def _ctx(config, confirm) -> ToolContext:
    return ToolContext(config=config, confirm=confirm)


# --- list_dir ---------------------------------------------------------------

def test_list_dir_contenuto(registry, config, allow_confirm, workspace) -> None:
    result = registry.dispatch("list_dir", {"path": "."}, _ctx(config, allow_confirm))
    assert result.ok
    assert "notes.md" in result.output
    assert "[D] sub" in result.output
    assert "elementi" in result.output


def test_list_dir_fuori_whitelist(registry, config, allow_confirm, tmp_path) -> None:
    result = registry.dispatch(
        "list_dir", {"path": str(tmp_path / "outside")}, _ctx(config, allow_confirm)
    )
    assert not result.ok
    assert "non permesso" in (result.error or "")


def test_list_dir_cartella_assente(registry, config, allow_confirm, workspace) -> None:
    result = registry.dispatch("list_dir", {"path": "mai_creata"}, _ctx(config, allow_confirm))
    assert not result.ok
    assert "inesistente" in (result.error or "")


def test_list_dir_path_mancante(registry, config, allow_confirm) -> None:
    result = registry.dispatch("list_dir", {}, _ctx(config, allow_confirm))
    assert not result.ok
    assert "path" in (result.error or "")


# --- read_file --------------------------------------------------------------

def test_read_file_con_numerazione(registry, config, allow_confirm) -> None:
    result = registry.dispatch("read_file", {"path": "notes.md"}, _ctx(config, allow_confirm))
    assert result.ok
    assert "ciao mondo" in result.output
    assert "1 |" in result.output and "2 |" in result.output


def test_read_file_offset_limit(registry, config, allow_confirm) -> None:
    result = registry.dispatch(
        "read_file",
        {"path": "notes.md", "offset": 2, "limit": 1},
        _ctx(config, allow_confirm),
    )
    assert result.ok
    assert "2 | ciao mondo" in result.output
    assert "1 |" not in result.output


def test_read_file_fuori_whitelist(registry, config, allow_confirm, tmp_path) -> None:
    result = registry.dispatch(
        "read_file", {"path": str(tmp_path / "outside" / "secret.txt")}, _ctx(config, allow_confirm)
    )
    assert not result.ok
    assert "non permesso" in (result.error or "")


def test_read_file_troncato(registry, allow_confirm, workspace) -> None:
    big = workspace / "grande.txt"
    big.write_text("x" * 500, encoding="utf-8")
    config = AgentConfig(workspace_roots=(workspace,), max_tool_output_chars=100)
    result = registry.dispatch("read_file", {"path": "grande.txt"}, _ctx(config, allow_confirm))
    assert result.ok
    assert "troncato" in result.output
    assert len(result.output) < 300


def test_read_file_offset_invalido(registry, config, allow_confirm) -> None:
    result = registry.dispatch(
        "read_file", {"path": "notes.md", "offset": "abc"}, _ctx(config, allow_confirm)
    )
    assert not result.ok
    assert "interi" in (result.error or "")


# --- write_file -------------------------------------------------------------

def test_write_file_nuovo_confermato(registry, config, allow_confirm, workspace) -> None:
    result = registry.dispatch(
        "write_file",
        {"path": "nuovo.txt", "content": "salve\n"},
        _ctx(config, allow_confirm),
    )
    assert result.ok
    assert "Creato" in result.output
    assert (workspace / "nuovo.txt").read_text(encoding="utf-8") == "salve\n"
    # la conferma ha ricevuto il diff
    assert len(allow_confirm.calls) == 1
    _action, detail = allow_confirm.calls[0]
    assert "+++" in detail


def test_write_file_rifiutato(registry, config, deny_confirm, workspace) -> None:
    result = registry.dispatch(
        "write_file",
        {"path": "rifiutato.txt", "content": "mai scritto\n"},
        _ctx(config, deny_confirm),
    )
    assert not result.ok
    assert "rifiutata" in (result.error or "")
    assert not (workspace / "rifiutato.txt").exists()
    assert len(deny_confirm.calls) == 1


def test_write_file_modifica_esistente_diff(registry, config, allow_confirm, workspace) -> None:
    result = registry.dispatch(
        "write_file",
        {"path": "notes.md", "content": "# Note\nnuova riga\n"},
        _ctx(config, allow_confirm),
    )
    assert result.ok
    assert "Aggiornato" in result.output
    assert (workspace / "notes.md").read_text(encoding="utf-8") == "# Note\nnuova riga\n"
    _action, detail = allow_confirm.calls[0]
    assert "cia" in detail  # la riga vecchia compare nel diff con -
    assert "---" in detail


def test_write_file_noop_nessuna_conferma(registry, config, allow_confirm, workspace) -> None:
    result = registry.dispatch(
        "write_file",
        {"path": "notes.md", "content": "# Note\nciao mondo\n"},
        _ctx(config, allow_confirm),
    )
    assert result.ok
    assert "Nessuna modifica" in result.output
    assert allow_confirm.calls == []


def test_write_file_senza_conferza_config(registry, workspace) -> None:
    """Con require_write_confirmation=False scrive senza chiedere."""
    config = AgentConfig(
        workspace_roots=(workspace,),
        security=SecurityConfig(require_write_confirmation=False),
    )
    confirm = ScriptedConfirm(default=False)  # risponderebbe NO se interrogato
    result = registry.dispatch(
        "write_file",
        {"path": "silenzioso.txt", "content": "ok\n"},
        ToolContext(config=config, confirm=confirm),
    )
    assert result.ok
    assert confirm.calls == []
    assert (workspace / "silenzioso.txt").exists()


def test_write_file_content_mancante(registry, config, allow_confirm) -> None:
    result = registry.dispatch("write_file", {"path": "x.txt"}, _ctx(config, allow_confirm))
    assert not result.ok
    assert "content" in (result.error or "")


# --- dispatch robustezza ----------------------------------------------------

def test_tool_sconosciuto(registry, config, allow_confirm) -> None:
    result = registry.dispatch("inesistente", {}, _ctx(config, allow_confirm))
    assert not result.ok
    assert "sconosciuto" in (result.error or "")


def test_handler_che_lancia_non_crasha(registry, config, allow_confirm) -> None:
    def bomb(args, ctx):  # noqa: ANN001
        raise RuntimeError("boom")

    from agent.tools.base import Tool

    registry.register(Tool("bomb", "test", {"type": "object", "properties": {}}, bomb))
    result = registry.dispatch("bomb", {}, _ctx(config, allow_confirm))
    assert not result.ok
    assert "boom" in (result.error or "")
    assert isinstance(result, ToolResult)


def test_eccezione_path_whitelist_diventa_errore(registry, config, allow_confirm, tmp_path) -> None:
    result = registry.dispatch(
        "read_file", {"path": str(tmp_path / "outside" / "secret.txt")}, _ctx(config, allow_confirm)
    )
    assert isinstance(result, ToolResult)
    assert not result.ok


def test_to_schemas_formato_ollama(registry) -> None:
    schemas = registry.to_schemas()
    assert len(schemas) == 5
    for schema in schemas:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"


def test_safe_resolve_usato_dai_tool(config, allow_confirm, workspace) -> None:
    """Garanzia esplicita: path traversal negato anche via tool."""
    registry = create_default_registry()
    result = registry.dispatch(
        "read_file",
        {"path": str(workspace / ".." / "outside" / "secret.txt")},
        _ctx(config, allow_confirm),
    )
    assert not result.ok
    assert "non permesso" in (result.error or "")
