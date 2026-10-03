"""Tool terminale: blacklist a monte, allowlist o conferma Y/N, timeout e output."""

from __future__ import annotations

import subprocess
from typing import Any

from agent.security.allowlist import autoapprove_reason
from agent.security.blacklist import find_destructive_match, find_path_based_block
from agent.tools.base import ToolContext, ToolResult, clip


def run_command(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Esegue un comando nella prima workspace_root.

    Ordine di valutazione:
    1. blacklist regex (blocco secco);
    2. blocchi dipendenti dai path (move/copy o redirect fuori root);
    3. allowlist → auto-approvato senza conferma;
    4. tutto il resto → conferma y/N con cwd e motivo (default NO).
    """
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return ToolResult.failure("argomento 'command' mancante (stringa)")
    command = command.strip()

    roots = ctx.config.workspace_roots
    match = find_destructive_match(command, ctx.config.security.command_blacklist)
    if match:
        return ToolResult.failure(f"COMANDO BLOCCATO dalla blacklist ({match}): {command}")
    path_block = find_path_based_block(command, roots)
    if path_block:
        return ToolResult.failure(f"COMANDO BLOCCATO ({path_block}): {command}")

    cwd = roots[0]
    if ctx.config.security.require_command_confirmation:
        reason = autoapprove_reason(
            command, ctx.config.security.command_allowlist, roots
        )
        if reason is not None:
            detail = f"comando: {command}\ncwd: {cwd}\nnon auto-approvato: {reason}"
            if ctx.seen_untrusted:
                detail += (
                    "\navviso: azione proposta dopo la lettura di contenuto "
                    "esterno (tool_output non fidato)"
                )
            approved = ctx.confirm.confirm("Esecuzione comando", detail)
            if not approved:
                return ToolResult.failure(
                    "Comando rifiutato dall'utente: nessun comando è stato eseguito."
                )

    timeout = ctx.config.security.command_timeout_s
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ToolResult.failure(f"timeout dopo {timeout}s: {command}")
    except OSError as e:
        return ToolResult.failure(f"esecuzione fallita: {type(e).__name__}: {e}")

    parts = [f"exit code: {proc.returncode}"]
    stdout = (proc.stdout or "").rstrip("\n")
    stderr = (proc.stderr or "").rstrip("\n")
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"[stderr]\n{stderr}")
    output = "\n".join(parts)
    if not stdout and not stderr:
        output += "\n(nessun output)"
    return ToolResult(output=clip(output, ctx.config.max_tool_output_chars))
