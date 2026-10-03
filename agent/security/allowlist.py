"""Allowlist di comandi read-only: auto-approvazione solo per comandi puliti.

Ogni voce (`AllowlistEntry`) dichiara l'intestazione del comando E i flag
ammessi: qualsiasi flag non elencato forza la conferma umana. Così `git diff
--output=fuori.diff` (scrive un file) non passa più per "git diff".

Un comando è auto-approvabile SOLO se:
- non contiene metacaratteri shell;
- si tokenizza senza errori (shlex non-posix, compatibile Windows);
- il primo token è un nome di comando (mai un path) e l'intestazione corrisponde
  a una voce di ``security.command_allowlist`` (case-insensitive, senza .exe);
- ogni flag è tra quelli ammessi dalla voce corrispondente;
- nessun argomento è un path assoluto e ogni argomento-path, risolto con
  ``resolve()`` (symlink/junction compresi), resta dentro le workspace_root;
- per ``cat``/``type``, l'argomento che risolve su un file sensibile (``.env``,
  ``*.pem``, ``id_rsa*``, ``*.key``, ``.git/config``) richiede SEMPRE la
  conferma, anche dentro le root (1.6.0).

Per i comandi git auto-approvati il TOOL riscrive il comando con
``harden_auto_git_command`` aggiungendo ``-c core.fsmonitor=false``,
``-c core.pager=cat`` e (dove accettati) ``--no-ext-diff --no-textconv``:
sono il tool a inserirli, mai il modello (1.6.0).

Tutto il resto richiede la conferma umana (default NO). Questa funzione riduce
la superficie: NON è un confine di sicurezza (vedi README "Limiti noti").
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from agent.security.paths import resolves_outside_roots

# separazione/piping/escaping/expansion: mai in un comando auto-approvato
_SHELL_METACHARS = frozenset("&|;<>()`$^%!\n\r")
_EXE_SUFFIXES = (".exe", ".cmd", ".bat", ".com")
_DRIVE_COLON = re.compile(r"^[A-Za-z]:")
# switch Windows brevi tipo /b /s /on: ammessi solo su Windows
_WINDOWS_SWITCH = re.compile(r"^/[A-Za-z]{1,3}$")


@dataclass(frozen=True)
class AllowlistEntry:
    """Voce di allowlist: intestazione comando + flag ammessi senza conferma."""

    command: str
    flags: tuple[str, ...] = ()


# cat/type leggono il contenuto: sui file riservati la conferma è obbligatoria
_CONFIRM_SENSITIVE_COMMANDS = frozenset({"cat", "type"})
_SENSITIVE_PATTERNS = ("*.pem", "*.key", "id_rsa*")

# opzioni git inserite dal TOOL (mai dal modello) sui comandi auto-approvati
_GIT_SAFE_GLOBALS = ("-c", "core.fsmonitor=false", "-c", "core.pager=cat")
# sotto-comandi che accettano --no-ext-diff/--no-textconv
# (git status NO: li rifiuta con exit 129 "unknown option")
_GIT_DIFF_SUBCOMMANDS = frozenset({"diff", "log"})


def _is_sensitive_target(path: Path) -> bool:
    """True se il path risolto punta a un file sensibile (contenuto riservato)."""
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    # .git/config (e sotto-file omonimi) in qualunque root o sottocartella
    if name == "config" and any(part.lower() == ".git" for part in path.parts[:-1]):
        return True
    return any(fnmatchcase(name, pattern) for pattern in _SENSITIVE_PATTERNS)


def _resolve_target(arg: str, roots: Sequence[Path]) -> Path | None:
    """Path risolto rispetto alla prima root (il cwd forzato); None se fallisce."""
    if not roots:
        return None
    try:
        p = Path(arg).expanduser()
        if not p.is_absolute():
            p = Path(roots[0]) / p
        return p.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def harden_auto_git_command(command: str) -> str:
    """Riscrive un comando git auto-approvato con le opzioni di sicurezza.

    Inserisce subito dopo ``git``: ``-c core.fsmonitor=false`` (disattiva
    l'hook fsmonitor, eseguibile dal repo) e ``-c core.pager=cat`` (nessun
    pager esterno); appende ``--no-ext-diff --no-textconv`` ai sotto-comandi
    che li accettano (diff/log). Le opzioni le aggiunge IL TOOL: il modello
    non le chiede e non può ometterle. Comandi non-git: invariati.
    """
    try:
        raw_tokens = shlex.split(command, posix=False)
    except ValueError:
        return command
    if not raw_tokens or _normalize_exe(raw_tokens[0]) != "git":
        return command
    extra: list[str] = []
    if len(raw_tokens) > 1 and _normalize_exe(raw_tokens[1]) in _GIT_DIFF_SUBCOMMANDS:
        extra = ["--no-ext-diff", "--no-textconv"]
    # i token grezzi conservano le virgolette: argomenti con spazi restano intatti
    return " ".join([raw_tokens[0], *_GIT_SAFE_GLOBALS, *raw_tokens[1:], *extra])


def _flag_name(token: str) -> str | None:
    """Token-opzione normalizzato (`--output=/x` → `--output`); None se non è un flag."""
    if token.startswith("-") and len(token) > 1:
        return token.split("=", 1)[0]
    if os.name == "nt" and _WINDOWS_SWITCH.match(token):
        return token.lower()
    return None


def _normalize_flag(flag: str) -> str:
    """Gli switch Windows sono case-insensitive, le opzioni git no."""
    return flag.lower() if flag.startswith("/") else flag


def _strip_quotes(token: str) -> str:
    return token.strip('"').strip("'")


def _normalize_exe(token: str) -> str | None:
    """Nome comando normalizzato; None se il token è un path (mai auto-approvabile)."""
    text = _strip_quotes(token)
    if not text or "/" in text or "\\" in text or _DRIVE_COLON.match(text):
        return None
    lowered = text.lower()
    for suffix in _EXE_SUFFIXES:
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def _is_absoluteish(text: str) -> bool:
    """Path assoluto su ogni piattaforma, più UNC, drive (`C:file`) e switch Windows.

    Su Windows uno switch corto (`/b`, `/on`) non è un path; su POSIX ogni `/x`
    lo è.
    """
    if _DRIVE_COLON.match(text):
        return True
    if text.startswith("\\"):
        return True
    if text.startswith("/"):
        if os.name == "nt" and _WINDOWS_SWITCH.match(text):
            return False
        return True
    if text.startswith("~"):
        try:
            return Path(text).expanduser().is_absolute()
        except (RuntimeError, OSError):
            return True  # home indeterminabile: non auto-approvare
    return Path(text).is_absolute()


def autoapprove_reason(
    command: str,
    allowlist: Sequence[AllowlistEntry],
    roots: Sequence[Path],
) -> str | None:
    """None se il comando è auto-approvabile, altrimenti il motivo della conferma."""
    if any(ch in command for ch in _SHELL_METACHARS):
        return "contiene metacaratteri shell"
    try:
        raw_tokens = shlex.split(command, posix=False)
    except ValueError:
        return "tokenizzazione impossibile (virgolette non bilanciate)"
    tokens = [t for t in (_strip_quotes(tok) for tok in raw_tokens) if t]
    if not tokens:
        return "comando vuoto"
    exe = _normalize_exe(tokens[0])
    if exe is None:
        return "il primo token è un path, non un nome di comando"

    # la voce più lunga vince (es. "python -m pytest" su "python" generico)
    matched: AllowlistEntry | None = None
    matched_len = 0
    for entry in sorted(allowlist, key=lambda e: -len(e.command.split())):
        entry_tokens = [
            t for t in (_normalize_exe(p) for p in entry.command.split()) if t is not None
        ]
        if not entry_tokens or len(entry_tokens) != len(entry.command.split()):
            continue  # voce malformata o con path: non matcha mai
        if len(tokens) < len(entry_tokens):
            continue
        head = [_normalize_exe(t) for t in tokens[: len(entry_tokens)]]
        if head == entry_tokens:
            matched = entry
            matched_len = len(entry_tokens)
            break
    if matched is None:
        return "comando non presente in allowlist"

    allowed_flags = {_normalize_flag(f) for f in matched.flags}
    for arg in tokens[matched_len:]:
        flag = _flag_name(arg)
        if flag is not None:
            if _normalize_flag(flag) not in allowed_flags:
                return f"flag non ammesso ({flag})"
            continue
        if _is_absoluteish(arg):
            return f"argomento con path assoluto ({arg})"
        # Ogni argomento viene risolto (symlink/junction compresi) rispetto
        # alla root di lavoro: un link dentro la root che punta fuori non
        # passa senza conferma (1.5.7). Copre anche `..`.
        try:
            outside = resolves_outside_roots(arg, roots)
        except (OSError, RuntimeError, ValueError):
            return f"argomento non risolvibile ({arg})"
        if outside:
            return f"argomento che esce dalle workspace_root ({arg})"
        # 1.6.0: cat/type su file sensibile → SEMPRE conferma, anche in root.
        # Il check è sul path RISOLTO: un symlink dal nome innocuo scopre .env.
        if matched.command.lower() in _CONFIRM_SENSITIVE_COMMANDS:
            target = _resolve_target(arg, roots)
            if target is None:
                return f"argomento non risolvibile ({arg})"
            if _is_sensitive_target(target):
                return f"file sensibile ({arg}): richiede la conferma"
    return None
