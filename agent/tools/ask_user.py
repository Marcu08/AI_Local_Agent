"""Tool ask_user (1.8.1): il modello chiede un chiarimento invece di inventare."""

from __future__ import annotations

from typing import Any

from agent.tools.base import ToolContext, ToolResult

# Limite di chiamate ask_user per TURNO (anti-loop): la quarta produce un
# errore che invita a procedere con le informazioni disponibili.
MAX_ASK_PER_TURN = 3
# Lunghezza massima della domanda: una domanda breve, una alla volta.
MAX_QUESTION_CHARS = 300


def ask_user(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Pone all'utente una domanda e ne restituisce la risposta (input fidato).

    Regole della 1.8.1:
    - `question` obbligatoria, stringa non vuota, max 300 caratteri;
    - anti-loop: al massimo MAX_ASK_PER_TURN chiamate per turno, contate sul
      ToolContext (creato una volta per turno dal loop); alla quarta → errore
      che invita a proseguire con ciò che si sa;
    - la risposta dell'utente NON è contenuto esterno: il loop la lascia fuori
      dal delimitatore untrusted (ToolResult output = testo fidato);
    - nessuna eccezione verso il loop: ogni problema è un ToolResult di errore
      con il tipo atteso e l'invito a riprovare;
    - la chiamata è sempre in decisione "auto" (nessuna conferma) e l'audit
      registra la DOMANDA (dagli argomenti), mai la risposta.
    """
    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        return ToolResult.failure(
            "argomento 'question' mancante o vuoto: atteso una stringa. "
            'Esempio d\'uso: question="Quale file intendi: note.md o todo.md?". '
            "Riprova..."
        )
    question = question.strip()
    if len(question) > MAX_QUESTION_CHARS:
        return ToolResult.failure(
            f"domanda troppo lunga: {len(question)} caratteri (massimo "
            f"{MAX_QUESTION_CHARS}). Fai una sola domanda breve alla volta. "
            f'Esempio d\'uso: question="{question[:60]}...". Riprova...'
        )
    if ctx.ask_count >= MAX_ASK_PER_TURN:
        return ToolResult.failure(
            f"limite di {MAX_ASK_PER_TURN} domande per turno raggiunto: "
            "procedi con le informazioni disponibili e, se proprio manca "
            "qualcosa, dillo chiaramente nella risposta finale."
        )
    ctx.ask_count += 1
    answer = ctx.confirm.ask(question)
    return ToolResult(output=answer)
