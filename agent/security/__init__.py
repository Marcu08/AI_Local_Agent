"""Modulo sicurezza: whitelist path, blacklist/allowlist comandi, conferme HIL, audit."""

from agent.security.allowlist import AllowlistEntry, autoapprove_reason
from agent.security.audit import AuditLog, default_audit_path
from agent.security.blacklist import (
    find_destructive_match,
    find_path_based_block,
    is_destructive,
)
from agent.security.confirm import (
    ASK_INTERRUPTED,
    ASK_UNAVAILABLE,
    ConfirmationHandler,
    NonInteractiveConfirm,
    RichConfirmation,
    ScriptedConfirm,
)
from agent.security.paths import PathNotAllowedError, is_allowed, safe_resolve

__all__ = [
    "ASK_INTERRUPTED",
    "ASK_UNAVAILABLE",
    "AllowlistEntry",
    "AuditLog",
    "ConfirmationHandler",
    "NonInteractiveConfirm",
    "PathNotAllowedError",
    "RichConfirmation",
    "ScriptedConfirm",
    "autoapprove_reason",
    "default_audit_path",
    "find_destructive_match",
    "find_path_based_block",
    "is_allowed",
    "is_destructive",
    "safe_resolve",
]
