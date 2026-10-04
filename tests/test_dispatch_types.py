"""1.7b: dispatch tollerante sui tipi degli argomenti.

I piccoli modelli mandano stringhe numeriche al posto dei numeri e "true"/
"false" al posto dei booleani: la conversione va fatta nel dispatch (una volta,
prima dell'handler) e un valore NON convertibile deve produrre un errore d'uso
che dice il tipo atteso, un esempio e l'invito a riprovare — mai un'eccezione
silenziosa né un valore nascosto di default.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent.config import AgentConfig
from agent.security.confirm import ScriptedConfirm
from agent.tools import create_default_registry
from agent.tools.base import Tool, ToolContext, ToolRegistry, ToolResult


@pytest.fixture
def registry() -> ToolRegistry:
    return create_default_registry()


def _ctx(config: AgentConfig, confirm: ScriptedConfirm) -> ToolContext:
    return ToolContext(config=config, confirm=confirm)


# --- interi: la tabella ("1", 1.0, "abc", None, "") --------------------------

@pytest.mark.parametrize(
    ("raw", "atteso_ok"),
    [
        ("1", True),  # stringa numerica → 1
        (1.0, True),  # float intero → 1
        ("abc", False),  # non convertibile → errore d'uso
        (None, True),  # argomento assente → default dell'handler
        ("", False),  # stringa vuota → errore d'uso (mai un default nascosto)
    ],
    ids=["stringa-1", "float-1.0", "abc", "none", "vuoto"],
)
def test_dispatch_offset_tipizzato(
    registry: ToolRegistry,
    config: AgentConfig,
    allow_confirm: ScriptedConfirm,
    raw: Any,
    atteso_ok: bool,
) -> None:
    """offset tipizzato: convertibile → si legge; altrimenti errore d'uso."""
    result = registry.dispatch(
        "read_file", {"path": "notes.md", "offset": raw}, _ctx(config, allow_confirm)
    )
    assert result.ok is atteso_ok, result.error
    if atteso_ok:
        # offset 1 (default o convertito): la prima riga c'è
        assert "1 |" in (result.output or "")
    else:
        error = result.error or ""
        assert "interi" in error  # tipo dichiarato in modo inequivocabile
        assert "offset" in error and "read_file" in error
        assert "Esempio d'uso: offset=3" in error
        assert "Riprova" in error


def test_errore_tipo_non_e_un_eccezione(
    registry: ToolRegistry, config: AgentConfig, allow_confirm: ScriptedConfirm
) -> None:
    """Il dispatch non propaga eccezioni: la coercizione fallita è un ToolResult."""
    result = registry.dispatch(
        "read_file", {"path": "notes.md", "limit": "dieci"}, _ctx(config, allow_confirm)
    )
    assert isinstance(result, ToolResult)
    assert not result.ok
    assert "limit" in (result.error or "")
    assert "Esempio d'uso: limit=3" in (result.error or "")


def test_stringhe_di_testo_non_ricondotte_a_numeri(
    registry: ToolRegistry, config: AgentConfig, allow_confirm: ScriptedConfirm
) -> None:
    """Solo i parametri tipizzati: path resta una stringa e non viene toccato."""
    result = registry.dispatch(
        "read_file", {"path": "notes.md", "offset": "2"}, _ctx(config, allow_confirm)
    )
    assert result.ok, result.error
    assert "2 | ciao mondo" in (result.output or "")


# --- booleani: nessun tool li dichiara oggi, il dispatch li gestisce ---------

def _probe_registry(seen: list[dict[str, Any]]) -> ToolRegistry:
    """Registry con un tool finto che dichiara un argomento booleano."""

    def handler(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        seen.append(args)
        return ToolResult(output="ok")

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="probe",
            description="tool di prova con argomento booleano",
            parameters={
                "type": "object",
                "properties": {"flag": {"type": "boolean", "description": "attivo"}},
                "required": ["flag"],
            },
            handler=handler,
        )
    )
    return registry


@pytest.mark.parametrize(
    ("raw", "atteso"),
    [("true", True), ("false", False), ("True", True), (True, True), (False, False)],
    ids=["true", "false", "True", "bool-vero", "bool-falso"],
)
def test_booleano_convertito(
    config: AgentConfig, allow_confirm: ScriptedConfirm, raw: Any, atteso: bool
) -> None:
    seen: list[dict[str, Any]] = []
    registry = _probe_registry(seen)

    result = registry.dispatch("probe", {"flag": raw}, _ctx(config, allow_confirm))

    assert result.ok, result.error
    assert seen == [{"flag": atteso}]


@pytest.mark.parametrize("raw", ["forse", "", 1], ids=["forse", "vuoto", "uno"])
def test_booleano_non_convertibile_errore_d_uso(
    config: AgentConfig, allow_confirm: ScriptedConfirm, raw: Any
) -> None:
    seen: list[dict[str, Any]] = []
    registry = _probe_registry(seen)

    result = registry.dispatch("probe", {"flag": raw}, _ctx(config, allow_confirm))

    assert not result.ok
    assert seen == []  # l'handler NON viene invocato con un valore inventato
    error = result.error or ""
    assert "booleano (boolean)" in error
    assert "Esempio d'uso: flag=true" in error
    assert 'Riprova con "true" oppure "false"' in error


def test_none_sui_booleani_e_assente(
    config: AgentConfig, allow_confirm: ScriptedConfirm
) -> None:
    """None = argomento non fornito: passa all'handler (che decide il default)."""
    seen: list[dict[str, Any]] = []
    registry = _probe_registry(seen)

    result = registry.dispatch("probe", {"flag": None}, _ctx(config, allow_confirm))

    assert result.ok, result.error
    assert seen == [{"flag": None}]


# --- schema senza proprietà tipizzate ---------------------------------------

def test_argomenti_non_dichiarati_non_coercati(
    config: AgentConfig, allow_confirm: ScriptedConfirm
) -> None:
    """Senza 'properties' nello schema il dispatch non tocca nulla."""
    seen: list[dict[str, Any]] = []

    def handler(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        seen.append(args)
        return ToolResult(output="ok")

    registry = ToolRegistry()
    registry.register(
        Tool("nudo", "senza schema", {"type": "object"}, handler)
    )

    result = registry.dispatch("nudo", {"offset": "abc"}, _ctx(config, allow_confirm))

    assert result.ok, result.error
    assert seen == [{"offset": "abc"}]  # nessuna conversione: nessun tipo dichiarato
