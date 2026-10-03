"""Modulo sicurezza: whitelist path, blacklist/allowlist comandi, conferme HIL."""

from agent.security.allowlist import autoapprove_reason
from agent.security.blacklist import (
    find_destructive_match,
    find_path_based_block,
    is_destructive,
)
from agent.security.confirm import ConfirmationHandler, RichConfirmation, ScriptedConfirm
from agent.security.paths import PathNotAllowedError, is_allowed, safe_resolve

__all__ = [
    "ConfirmationHandler",
    "PathNotAllowedError",
    "RichConfirmation",
    "ScriptedConfirm",
    "autoapprove_reason",
    "find_destructive_match",
    "find_path_based_block",
    "is_allowed",
    "is_destructive",
    "safe_resolve",
]
