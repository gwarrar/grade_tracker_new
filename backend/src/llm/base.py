"""Provider-agnostic chat interface.

One abstract base, several implementations, and callers that never learn which one
they have. Unlike the storage layer -- where a single shipping implementation made the
abstract base a second place to edit rather than a seam -- this one earns its keep:
there are two live providers and they disagree about nearly everything below.

The abstraction **normalises rather than passes through**. Anthropic and the
OpenAI-compatible family disagree on every part of tool use that matters:

======================  ==============================  ================================
Concern                 Anthropic                       OpenAI-compatible
======================  ==============================  ================================
Tool schema             ``tools[].input_schema``        ``tools[].function.parameters``
Tool call in response   ``content[].type == tool_use``  ``choices[].message.tool_calls``
Structured output       ``output_config.format``        ``response_format.json_schema``
Stop signal             ``stop_reason == "tool_use"``   ``finish_reason == "tool_calls"``
System prompt           top-level ``system``            a message with ``role="system"``
======================  ==============================  ================================

A thin wrapper that forwarded these differences would push all five into every
caller, and the agent loop would grow a branch per provider. Instead each provider
translates to and from the vocabulary below, and exactly one agent loop sits on
top of all of them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """Who produced a message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(StrEnum):
    """Why the model stopped generating.

    Normalised: providers spell these differently, and the agent loop branches on
    exactly one of them (:attr:`TOOL_CALLS`).
    """

    STOP = "stop"
    """The model finished its answer."""

    TOOL_CALLS = "tool_calls"
    """The model wants a tool run before it can continue."""

    LENGTH = "length"
    """Output hit ``max_tokens``. The answer is truncated, not complete."""

    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool offered to the model.

    Attributes:
        name: Identifier the model uses to call it.
        description: What it does. The model routes on this text, so it is part of
            the interface rather than documentation.
        parameters: A JSON Schema object describing the arguments.
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A model's request to run one tool.

    Attributes:
        id: Correlates this call with its result. Both providers require the result
            to carry the id back, and mismatching it is silently accepted and then
            answered wrongly.
        name: Which tool.
        arguments: Decoded arguments. Never trusted — the caller validates them
            before acting.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of a conversation.

    Attributes:
        role: Who produced it.
        content: The text. Empty for an assistant turn that only called tools.
        tool_calls: Present on assistant turns that requested tools.
        tool_call_id: Set on ``TOOL`` messages, matching the call being answered.
    """

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class Usage:
    """Token counts for one exchange.

    Attributes:
        input_tokens: Tokens sent, including any served from cache.
        output_tokens: Tokens generated.
        cached_tokens: Input tokens served from a prompt cache. Reported separately
            because they are billed differently, and because a cache that has
            silently stopped working looks identical in the total.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ChatResult:
    """One model response, in the same shape whatever produced it.

    Attributes:
        text: The assistant's prose. Empty when it only called tools.
        tool_calls: Tools it wants run.
        finish_reason: Why it stopped.
        usage: Token counts, for the usage log.
        model: The model that actually answered, which is not always the one asked
            for — routers substitute, and the log should record what ran.
        reasoning: The model's thinking, when it emitted any and the provider exposed
            it separately from the answer. Reasoning models return this alongside
            ``text``; everything else leaves it empty. Surfaced so a UI can offer it
            behind a disclosure — and deliberately **not** fed back into the next
            turn, because providers reject replayed thinking blocks that have lost
            their signatures.
        raw: The undecoded response, for debugging. Never parsed by callers.
    """

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: FinishReason = FinishReason.STOP
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    reasoning: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def as_message(self) -> Message:
        """Return this result as an assistant message, for appending to a history.

        Returns:
            The assistant turn, carrying any tool calls it made.
        """
        return Message(role=Role.ASSISTANT, content=self.text, tool_calls=self.tool_calls)


class LLMError(RuntimeError):
    """A provider call failed.

    Carries a machine ``code`` for the same reason the domain exceptions do: the
    admin page needs to distinguish "your key is wrong" from "the service is down"
    without parsing English.

    Attributes:
        code: Stable identifier, e.g. ``AI_UNAUTHORIZED``.
        provider: Which configured provider failed.
        status: HTTP status, when there was one.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "AI_ERROR",
        provider: str = "",
        status: int | None = None,
    ) -> None:
        """Initialise the error.

        Args:
            message: Human-readable detail, for logs only.
            code: Stable machine identifier.
            provider: Name of the provider that failed.
            status: HTTP status code, if the failure was an HTTP response.
        """
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.status = status


def classify_http_error(status: int) -> str:
    """Map an HTTP status to a stable error code.

    Shared by both providers so that "the key is wrong" reports identically
    whichever backend produced it — which is the whole point of the abstraction.

    Args:
        status: The HTTP status code from the provider.

    Returns:
        A stable machine code.
    """
    match status:
        case 401 | 403:
            return "AI_UNAUTHORIZED"
        case 404:
            return "AI_MODEL_NOT_FOUND"
        case 429:
            return "AI_RATE_LIMITED"
        case s if s >= 500:
            return "AI_UNAVAILABLE"
        case _:
            return "AI_REQUEST_REJECTED"


class LLMProvider(ABC):
    """One configured way to reach a model.

    Implementations are constructed from an ``ai_providers`` row plus the API key
    read from the environment. They hold no per-request state, so one instance
    serves every request to that provider.
    """

    # Keys an administrator may not set through `params`, because they *are* the
    # request rather than a setting on it. A typo in a JSON blob must not be able to
    # replace the conversation, drop the tools, or turn on streaming the caller cannot
    # read. This is a trust boundary, not tidiness.
    _RESERVED = frozenset({"model", "messages", "system", "tools", "response_format", "stream"})

    def __init__(
        self,
        *,
        name: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
        params: dict[str, Any] | None = None,
        effort: str = "medium",
    ) -> None:
        """Initialise the provider.

        Args:
            name: The configured name, used in errors and the usage log.
            model: Default model when a call does not name one.
            api_key: The credential. Read from the environment by the registry —
                the database stores only the variable's name.
            base_url: Endpoint override, or None for the vendor default.
            params: Extra request-body keys for this endpoint — ``temperature``,
                ``top_p``, or a vendor's own such as NVIDIA's
                ``chat_template_kwargs``. **Construction-time configuration, never a
                call-time argument**: that is what keeps the agent loop and the four
                AI features from ever branching on which provider they are talking
                to, which is the whole promise of this abstraction.
            effort: How hard the model should think, from the feature's routing row.
                Each implementation translates it into its own vocabulary.
        """
        self.name = name
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._params = self._sanitise(params or {})
        self._effort = effort

    @classmethod
    def _sanitise(cls, params: dict[str, Any]) -> dict[str, Any]:
        """Drop reserved keys from configured parameters.

        Silently rather than by raising: the reserved key is ignored and everything
        else still applies, which is the behaviour that keeps a stray key from taking
        an AI feature offline. The admin API validates the shape at write time, where
        someone is present to read an error.

        Args:
            params: Whatever the administrator configured.

        Returns:
            The same mapping without any reserved key.
        """
        return {k: v for k, v in params.items() if k not in cls._RESERVED}

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        tools: list[ToolSpec] | None = None,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
    ) -> ChatResult:
        """Send a conversation and return the reply.

        Args:
            messages: The conversation so far, oldest first.
            system: System prompt. Passed separately because Anthropic takes it as
                a top-level field while OpenAI-compatible APIs take it as a message
                — normalising that is this method's job, not the caller's.
            tools: Tools the model may call.
            schema: A JSON Schema the reply must satisfy. Mutually exclusive with
                ``tools`` in practice: a model cannot both call a tool and emit a
                fixed shape in the same turn.
            model: Override the configured default.
            max_tokens: Cap on generated tokens.

        Returns:
            The normalised reply.

        Raises:
            LLMError: On any transport or provider failure.
        """

    def check(self) -> str:
        """Verify the credential and endpoint by making the smallest possible call.

        Backs the admin page's "Test connection" button. A configuration that only
        fails when a user asks a real question is a configuration nobody notices
        until it matters.

        Returns:
            The model that answered.

        Raises:
            LLMError: If the provider is unreachable or rejects the credential.
        """
        result = self.chat(
            [Message(role=Role.USER, content="Reply with OK.")],
            max_tokens=16,
        )
        return result.model or self.model

    def list_models(self) -> list[str]:
        """Return the models this endpoint offers, best effort.

        Typing a model identifier by hand is how an administrator ends up with a
        provider that authenticates perfectly and answers nothing, because the name
        was a guess -- and with a local Ollama the available set is whatever that
        machine happens to have pulled, which no default could know.

        Returns:
            Model identifiers, or an empty list when the provider has no way to
            enumerate them. Never raises: an endpoint that cannot list is a smaller
            problem than one that cannot answer, and the field stays typeable.
        """
        return []
