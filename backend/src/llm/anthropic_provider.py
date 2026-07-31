"""Anthropic implementation of :class:`~llm.base.LLMProvider`."""

from __future__ import annotations

import json
from typing import Any

import anthropic

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

DEFAULT_MODEL = "claude-opus-5"


_FINISH: dict[str, FinishReason] = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "tool_use": FinishReason.TOOL_CALLS,
    "max_tokens": FinishReason.LENGTH,
}

# Body fields accepted as named arguments by the installed Anthropic SDK. Unknown
# vendor extensions still belong in the request body, but must travel through the
# SDK's `extra_body` escape hatch rather than becoming invalid Python keywords.
_SDK_BODY_PARAMS = frozenset(
    {
        "cache_control",
        "container",
        "inference_geo",
        "metadata",
        "service_tier",
        "stop_sequences",
        "temperature",
        "thinking",
        "tool_choice",
        "top_k",
        "top_p",
        "user_profile_id",
    }
)


class AnthropicProvider(LLMProvider):
    """Claude, via the official SDK.

    Two shape differences are handled here and nowhere else:

    - The system prompt is a top-level parameter, not a message. Anthropic rejects
      ``role="system"`` outright, so a caller that built one would get a 400 rather
      than a degraded answer.
    - Tool results are ``user`` messages carrying a ``tool_result`` block, not a
      dedicated ``tool`` role.
    """

    def __init__(
        self,
        *,
        name: str = "anthropic",
        model: str = DEFAULT_MODEL,
        api_key: str,
        base_url: str | None = None,
        client: anthropic.Anthropic | None = None,
        params: dict[str, Any] | None = None,
        effort: str = "medium",
    ) -> None:
        """Initialise the provider and its SDK client.

        Args:
            name: Configured name, used in errors and the usage log.
            model: Default model.
            api_key: Anthropic API key.
            base_url: Endpoint override, for a proxy or a gateway.
            client: A pre-built client, for custom timeouts or a proxy. Defaults
                to one constructed from `api_key` and `base_url`. Public rather
                than private so tests can substitute the transport without
                reaching past the class boundary.
            params: Extra request-body keys, split between typed SDK arguments and
                the SDK's arbitrary-body escape hatch.
            effort: Reasoning effort, sent through Anthropic's ``output_config``.
        """
        super().__init__(
            name=name,
            model=model,
            api_key=api_key,
            base_url=base_url,
            params=params,
            effort=effort,
        )
        self.client = client or anthropic.Anthropic(api_key=api_key, base_url=base_url)

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
        """Send a conversation to Claude.

        See :meth:`~llm.base.LLMProvider.chat`.

        Args:
            messages: Conversation so far.
            system: System prompt, sent as a top-level field.
            tools: Tools the model may call.
            schema: JSON Schema constraining the reply.
            model: Model override.
            max_tokens: Cap on generated tokens.

        Returns:
            The normalised reply.

        Raises:
            LLMError: On any API or transport failure.
        """
        params = dict(self._params)
        # Anthropic requires signed thinking/redacted-thinking blocks to be replayed
        # verbatim after tool use. The provider-neutral Message intentionally does
        # not carry those opaque blocks, so a tool loop must keep thinking disabled.
        if tools:
            params.pop("thinking", None)

        configured_output = params.pop("output_config", None)
        output_config: Any = {"effort": self._effort}
        if isinstance(configured_output, dict):
            output_config.update(configured_output)
        elif configured_output is not None:
            output_config = configured_output

        request: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "messages": [_encode(message) for message in messages],
            "output_config": output_config,
        }
        extra_body: dict[str, Any] = {}
        for key, value in params.items():
            if key in _SDK_BODY_PARAMS:
                request[key] = value
            else:
                extra_body[key] = value
        if extra_body:
            request["extra_body"] = extra_body
        if system:
            request["system"] = system
        if tools:
            request["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        if schema:
            # Preserve a configured/derived effort while protecting the response
            # contract selected by the caller.
            configured = request.get("output_config")
            merged_output = dict(configured) if isinstance(configured, dict) else {}
            merged_output["format"] = {"type": "json_schema", "schema": schema}
            request["output_config"] = merged_output

        try:
            response = self.client.messages.create(**request)
        except TypeError as error:
            raise LLMError(str(error), code="AI_BAD_PARAMS", provider=self.name) from error
        except anthropic.APIStatusError as error:
            raise LLMError(
                str(error),
                code=classify_http_error(error.status_code),
                provider=self.name,
                status=error.status_code,
            ) from error
        except anthropic.APIError as error:
            # Connection and timeout failures carry no status. Distinguished from
            # the above so the admin page can say "unreachable" rather than
            # inventing a status code.
            raise LLMError(str(error), code="AI_UNAVAILABLE", provider=self.name) from error

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "thinking":
                thinking = getattr(block, "thinking", "")
                if thinking:
                    reasoning_parts.append(thinking)
            elif block.type == "tool_use":
                arguments = block.input if isinstance(block.input, dict) else {}
                calls.append(ToolCall(id=block.id, name=block.name, arguments=arguments))

        return ChatResult(
            text="".join(text_parts),
            tool_calls=tuple(calls),
            finish_reason=_FINISH.get(response.stop_reason or "", FinishReason.OTHER),
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cached_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            ),
            model=response.model,
            reasoning="\n\n".join(reasoning_parts),
        )


def _encode(message: Message) -> dict[str, Any]:
    """Translate one normalised message into Anthropic's wire shape.

    Args:
        message: The message to translate.

    Returns:
        A message dict for the Messages API.
    """
    if message.role is Role.TOOL:
        # A tool result is a user turn carrying a tool_result block — there is no
        # "tool" role in this API.
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.content,
                }
            ],
        }

    if message.tool_calls:
        content: list[dict[str, Any]] = []
        if message.content:
            content.append({"type": "text", "text": message.content})
        content.extend(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            for call in message.tool_calls
        )
        return {"role": "assistant", "content": content}

    return {"role": message.role.value, "content": message.content}


def parse_json(text: str) -> dict[str, Any]:
    """Decode a structured-output reply.

    Args:
        text: The model's reply.

    Returns:
        The decoded object.

    Raises:
        LLMError: If the reply is not a JSON object. Schema-constrained output
            makes this close to impossible, which is exactly why it must fail
            loudly rather than degrade to an empty dict nobody notices.
    """
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMError(f"reply was not JSON: {text[:200]}", code="AI_BAD_OUTPUT") from error

    if not isinstance(value, dict):
        raise LLMError(f"reply was not a JSON object: {type(value).__name__}", code="AI_BAD_OUTPUT")
    return value
