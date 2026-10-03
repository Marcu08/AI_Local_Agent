"""Tool terminale: blacklist a monte, conferma Y/N, timeout e output catturato."""

from __future__ import annotations

import subprocess
from typing import Any

from agent.security.blacklist import find_destructive_match
from agent.tools.base import ToolContext, ToolResult, clip


def run_command(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Esegue un comando nella prima workspace_root (mai se blacklistato/rifiutato)."""
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return ToolResult.failure("argomento 'command' mancante (stringa)")
    command = command.strip()

    match = find_destructive_match(command, ctx.config.security.command_blacklist)
    if match:
        return ToolResult.failure(f"COMANDO BLOCCATO dalla blacklist ({match}): {command}")

    if ctx.config.security.require_command_confirmation:
        approved = ctx.confirm.confirm("Esecuzione comando", command)
        if not approved:
            return ToolResult.failure(
                "Comando rifiutato dall'utente: nessun comando è stato eseguito."
            )

    cwd = ctx.config.workspace_roots[0]
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
