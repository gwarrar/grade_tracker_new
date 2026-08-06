"""OpenAI-compatible implementation of :class:`~llm.base.LLMProvider`.

One class covers OpenRouter, NVIDIA NIM, OmniRoute, Ollama, LM Studio, Groq,
DeepSeek and Together, because they all speak the same chat-completions shape.
Only ``base_url`` and the credential differ.

Written against ``httpx`` rather than the ``openai`` SDK: the surface used here is
one POST, and the SDK would be a dependency carrying an auth model, a retry
policy and a type hierarchy that all have to be worked around to point it at a
third-party endpoint.

.. warning::

   Providers offering **free pools** route requests through third parties whose
   data-retention terms are unknown. This application holds student names, emails
   and grades. Use free pools for development; for real records use a provider with
   a data-processing agreement, or point at a local model. Rows flagged
   ``is_third_party_pool`` carry a warning in the admin interface.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import httpx

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
    classify_http_error,
)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 60.0

_FINISH: dict[str, FinishReason] = {
    "stop": FinishReason.STOP,
    "tool_calls": FinishReason.TOOL_CALLS,
    "function_call": FinishReason.TOOL_CALLS,
    "length": FinishReason.LENGTH,
}


class OpenAICompatibleProvider(LLMProvider):
    """Any endpoint speaking the OpenAI chat-completions API."""

    #: The five stored effort levels onto the three the wire understands. The extra
    #: levels exist so the admin page can express intent that a future provider may
    #: distinguish; today `high`, `xhigh` and `max` all mean "think hard".
    _EFFORT: ClassVar[dict[str, str]] = {
        "low": "low",
        "medium": "medium",
        "high": "high",
        "xhigh": "high",
        "max": "high",
    }

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
            name: Configured name, used in errors and the usage log.
            model: Default model identifier, in whatever form this endpoint expects.
            api_key: Bearer credential. May be empty for a local endpoint such as
                Ollama, which authenticates nothing.
            base_url: Endpoint root, without ``/chat/completions``.
            params: Extra request-body keys, merged in last. See
                :class:`~llm.base.LLMProvider`.
            effort: Reasoning effort, translated to ``reasoning_effort``.
        """
        super().__init__(
            name=name,
            model=model,
            api_key=api_key,
            base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
            params=params,
            effort=effort,
        )

    def list_models(self) -> list[str]:
        """Enumerate the endpoint's models. See :meth:`~llm.base.LLMProvider.list_models`.

        Every OpenAI-shaped endpoint answers ``GET /models``, which is what makes a
        local Ollama usable without the administrator first running ``ollama list``
        in another window and copying names across.
        """
        headers = {}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        try:
            response = httpx.get(
                f"{self._base_url}/models", headers=headers, timeout=TIMEOUT_SECONDS
            )
            if not response.is_success:
                return []
            body = response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return []
        entries = body.get("data") if isinstance(body, dict) else None
        if not isinstance(entries, list):
            return []
        names = [str(e["id"]) for e in entries if isinstance(e, dict) and e.get("id")]
        return sorted(names)

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
        """Send a conversation to the configured endpoint.

        See :meth:`~llm.base.LLMProvider.chat`.

        Args:
            messages: Conversation so far.
            system: System prompt, prepended as a ``system`` message.
            tools: Tools the model may call.
            schema: JSON Schema constraining the reply.
            model: Model override.
            max_tokens: Cap on generated tokens.

        Returns:
            The normalised reply.

        Raises:
            LLMError: On any HTTP or transport failure.
        """
        wire: list[dict[str, Any]] = []
        if system:
            # A message here, where Anthropic takes a top-level field. Normalising
            # this is the entire reason `system` is a separate parameter.
            wire.append({"role": Role.SYSTEM.value, "content": system})
        wire.extend(_encode(message) for message in messages)

        payload: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "messages": wire,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            }

        # Reasoning effort is opt-in, not derived. The routing column is NOT NULL
        # DEFAULT 'medium', so there is no "unset" to detect, and sending it
        # unconditionally made every model without reasoning support reject the
        # request outright -- Ollama answers 400 `"llama3.2:1b" does not support
        # thinking`. The asymmetry decides it: a reasoning model answers perfectly
        # well without the parameter, while a plain one is broken by it. So a
        # provider asks for effort by naming it in params_json, either top level or
        # inside NVIDIA's `chat_template_kwargs`, and the routing level fills in the
        # value.
        # Three states, no guessing: absent sends nothing, "auto" sends the level the
        # routing table chose, and any other value is the operator's own and wins.
        template_params = self._params.get("chat_template_kwargs")
        nested_effort = isinstance(template_params, dict) and "reasoning_effort" in template_params
        if self._params.get("reasoning_effort") == "auto" and not nested_effort:
            payload["reasoning_effort"] = self._EFFORT.get(self._effort, "medium")
        payload.update(self._params)
        if payload.get("reasoning_effort") == "auto":
            payload["reasoning_effort"] = self._EFFORT.get(self._effort, "medium")

        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"

        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.RequestError as error:
            raise LLMError(str(error), code="AI_UNAVAILABLE", provider=self.name) from error

        if response.status_code >= 400:
            raise LLMError(
                f"{response.status_code}: {response.text[:300]}",
                code=classify_http_error(response.status_code),
                provider=self.name,
                status=response.status_code,
            )

        try:
            body = response.json()
        except ValueError as error:
            # A proxy or a captive portal answering 200 with HTML. Reported as a
            # provider fault rather than crashing on a missing key three lines down.
            raise LLMError(
                f"reply was not JSON: {response.text[:200]}",
                code="AI_BAD_OUTPUT",
                provider=self.name,
            ) from error

        return self._decode(body)

    def _decode(self, body: dict[str, Any]) -> ChatResult:
        """Translate a chat-completions body into a :class:`ChatResult`.

        Args:
            body: The decoded JSON response.

        Returns:
            The normalised reply.

        Raises:
            LLMError: If the body carries no choices — some gateways answer 200
                with an ``error`` object, which would otherwise surface as an
                IndexError far from its cause.
        """
        choices = body.get("choices") or []
        if not choices:
            detail = body.get("error") or body
            raise LLMError(
                f"no choices in reply: {str(detail)[:200]}",
                code="AI_BAD_OUTPUT",
                provider=self.name,
            )

        choice = choices[0]
        message = choice.get("message") or {}

        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            calls.append(
                ToolCall(
                    id=raw.get("id") or "",
                    name=function.get("name") or "",
                    # Arguments arrive as a JSON *string* here, where Anthropic
                    # sends a decoded object. A malformed one is the model's fault,
                    # not the transport's, so it becomes empty arguments the tool
                    # can reject rather than an exception mid-loop.
                    arguments=_decode_arguments(function.get("arguments")),
                )
            )

        usage = body.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}

        return ChatResult(
            text=message.get("content") or "",
            tool_calls=tuple(calls),
            finish_reason=_FINISH.get(choice.get("finish_reason") or "", FinishReason.OTHER),
            usage=Usage(
                input_tokens=usage.get("prompt_tokens") or 0,
                output_tokens=usage.get("completion_tokens") or 0,
                cached_tokens=details.get("cached_tokens") or 0,
            ),
            model=body.get("model") or self.model,
            # Two spellings because the field is not standardised: DeepSeek and NVIDIA
            # NIM send `reasoning_content`, others `reasoning`. Both are read so a
            # deployment does not have to know which flavour it is talking to.
            reasoning=message.get("reasoning_content") or message.get("reasoning") or "",
            raw=body,
        )


def _decode_arguments(raw: object) -> dict[str, Any]:
    """Decode a tool call's arguments.

    Args:
        raw: The ``arguments`` field, normally a JSON string.

    Returns:
        The decoded arguments, or an empty dict if they were not a JSON object.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _encode(message: Message) -> dict[str, Any]:
    """Translate one normalised message into the chat-completions shape.

    Args:
        message: The message to translate.

    Returns:
        A message dict.
    """
    if message.role is Role.TOOL:
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id or "",
            "content": message.content,
        }

    if message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        # Re-encoded as a string, which is what this API expects
                        # both to send and to receive.
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ],
        }

    return {"role": message.role.value, "content": message.content}
