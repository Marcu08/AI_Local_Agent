"""Conferme Human-in-the-Loop: nessuna azione sensibile senza y esplicito."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm


@runtime_checkable
class ConfirmationHandler(Protocol):
    """Interfaccia di conferma: iniettabile, così i test non toccano input()."""

    def confirm(self, action: str = "", detail: str = "") -> bool:
        """Ritorna True solo se l'utente approva esplicitamente."""
        ...


@dataclass
class ScriptedConfirm:
    """Per i test: risposte pre-programmate, registra tutte le chiamate.

    Se le risposte predefinite finiscono, si applica `default` (False = NO).
    """

    answers: list[bool] = field(default_factory=list)
    default: bool = False
    calls: list[tuple[str, str]] = field(default_factory=list)

    def confirm(self, action: str = "", detail: str = "") -> bool:
        self.calls.append((action, detail))
        if self.answers:
            return self.answers.pop(0)
        return self.default


@dataclass
class RichConfirmation:
    """Conferma da terminale: mostra il dettaglio (es. diff) e chiede [y/N]."""

    console: Console | None = None

    def confirm(self, action: str = "", detail: str = "") -> bool:
        console = self.console or Console()
        if detail:
            console.print(Panel(detail, title=action, border_style="yellow"))
        return Confirm.ask(f"{action}: procedere?", default=False, console=console)
