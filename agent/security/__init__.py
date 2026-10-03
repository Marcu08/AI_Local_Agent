"""Modulo sicurezza: whitelist path, blacklist comandi, conferme Human-in-the-Loop."""

from agent.security.blacklist import find_destructive_match, is_destructive
from agent.security.confirm import ConfirmationHandler, RichConfirmation, ScriptedConfirm
from agent.security.paths import PathNotAllowedError, is_allowed, safe_resolve

__all__ = [
    "ConfirmationHandler",
    "PathNotAllowedError",
    "RichConfirmation",
    "ScriptedConfirm",
    "find_destructive_match",
    "is_allowed",
    "is_destructive",
    "safe_resolve",
]
