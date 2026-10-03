"""Client LLM: protocol comune, provider Ollama, mock per test/smoke."""

from agent.llm.base import LLMClient, LLMError, LLMResponse, ToolCall

__all__ = ["LLMClient", "LLMError", "LLMResponse", "ToolCall"]
