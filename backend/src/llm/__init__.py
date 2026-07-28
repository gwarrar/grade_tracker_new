"""Provider-agnostic AI: one interface, several backends, one agent loop.

The public vocabulary lives in :mod:`llm.base`; everything else is an
implementation of it. Callers import from here and never learn which provider
answered.
"""

from llm.base import (
    ChatResult,
    FinishReason,
    LLMError,
    LLMProvider,
    Message,
    Role,
    ToolCall,
    ToolSpec,
    Usage,
)
from llm.registry import Feature, ProviderConfig, Registry, build

__all__ = [
    "ChatResult",
    "Feature",
    "FinishReason",
    "LLMError",
    "LLMProvider",
    "Message",
    "ProviderConfig",
    "Registry",
    "Role",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "build",
]
