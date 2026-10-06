"""Interazione Human-in-the-Loop: conferme y/N e domande all'utente (1.8.1).

L'interfaccia `ConfirmationHandler` ha ORA due metodi: `confirm` (y/N sulle
azioni sensibili) e `ask` (domanda aperta, tool `ask_user`). Entrambi sono
iniettabili, così i test non toccano mai `input()` reale; nessuno dei due
deve mai bloccare in modalità non interattiva (demo, stdin pipato).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

# Restituito quando una risposta non è proprio possibile (modalità non
# interattiva, stdin chiuso, risposta vuota): ask_user può proseguire senza
# bloccare il turno. Testo prescritto dalla Fase 1.8.1, invariato.
ASK_UNAVAILABLE = "[nessuna risposta disponibile: modalità non interattiva]"
# Ctrl+C o fine stream durante l'attesa: attesa interrotta pulito, mai
# un'eccezione che si propagherebbe fuori dal tool verso il loop.
ASK_INTERRUPTED = "[risposta annullata: attesa interrotta]"


@runtime_checkable
class ConfirmationHandler(Protocol):
    """Interfaccia di interazione: iniettabile, così i test non toccano input()."""

    def confirm(self, action: str = "", detail: str = "") -> bool:
        """Ritorna True solo se l'utente approva esplicitamente."""
        ...

    def ask(self, question: str = "") -> str:
        """Risposta dell'utente a `question`: input fidato, mai bloccante.

        In modalità non interattiva (o se l'attesa viene interrotta) ritorna
        un segnale testuale, NON un'eccezione.
        """
        ...


@dataclass
class ScriptedConfirm:
    """Per i test: risposte pre-programmate, registra tutte le chiamate.

    Se le risposte predefinite finiscono, si applica `default` (False = NO)
    per `confirm`; per `ask` vale ASK_UNAVAILABLE (nessun blocco mai).
    """

    answers: list[bool] = field(default_factory=list)
    default: bool = False
    calls: list[tuple[str, str]] = field(default_factory=list)
    # 1.8.1: risposte testuali predefinite per ask_user, in ordine
    ask_answers: list[str] = field(default_factory=list)
    ask_calls: list[str] = field(default_factory=list)

    def confirm(self, action: str = "", detail: str = "") -> bool:
        self.calls.append((action, detail))
        if self.answers:
            return self.answers.pop(0)
        return self.default

    def ask(self, question: str = "") -> str:
        self.ask_calls.append(question)
        if self.ask_answers:
            return self.ask_answers.pop(0)
        return ASK_UNAVAILABLE


@dataclass
class RichConfirmation:
    """Conferma e domanda da terminale: [y/N] con default NO, domanda libera.

    L'attesa della risposta cattura Ctrl+C (KeyboardInterrupt) e EOF
    (stdin chiuso): restituisce un segnale testuale invece di far cadere il
    turno. La risposta dell'utente è vuota → vale "nessuna risposta".
    """

    console: Console | None = None

    def confirm(self, action: str = "", detail: str = "") -> bool:
        console = self.console or Console()
        if detail:
            console.print(Panel(detail, title=action, border_style="yellow"))
        return Confirm.ask(f"{action}: procedere?", default=False, console=console)

    def ask(self, question: str = "") -> str:
        console = self.console or Console()
        if question:
            console.print(Panel(question, title="Domanda per l'utente", border_style="yellow"))
        try:
            answer = input("Risposta> ").strip()
        except KeyboardInterrupt:
            console.print()  # chiude la riga lasciata aperta dal ^C
            return ASK_INTERRUPTED
        except EOFError:
            return ASK_UNAVAILABLE
        return answer if answer else ASK_UNAVAILABLE


@dataclass
class NonInteractiveConfirm:
    """Modalità non interattiva (demo, stdin pipato): NON blocca mai.

    `confirm` ritorna il proprio default (la demo approva), `ask` ritorna
    sempre ASK_UNAVAILABLE: il tool ask_user può essere chiamato anche qui,
    senza mai fermare il processo in attesa di una tastiera inesistente.
    """

    default: bool = False

    def confirm(self, action: str = "", detail: str = "") -> bool:
        return self.default

    def ask(self, question: str = "") -> str:
        return ASK_UNAVAILABLE
