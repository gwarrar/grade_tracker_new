"""Both providers must normalise to the same shape.

This is the test that makes the abstraction worth having. If Anthropic and an
OpenAI-compatible endpoint produce different ``ChatResult``s for equivalent
replies, the agent loop needs a branch per provider — and the whole point of
``LLMProvider`` is that it does not.

The two are driven with *their own* wire shapes and checked for *identical*
normalised output.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest

from llm.anthropic_provider import AnthropicProvider, parse_json
from llm.base import (
    ChatResult,
    FinishReason,
    LLMError,
    Message,
    Role,
    ToolCall,
    ToolSpec,
)
from llm.openai_compatible_provider import OpenAICompatibleProvider


def _responds(response: httpx.Response) -> Callable[..., httpx.Response]:
    """Return a typed stand-in for ``httpx.post`` that always answers `response`."""

    def respond(*_args: Any, **_kwargs: Any) -> httpx.Response:
        return response

    return respond


def _returns(value: object) -> Callable[..., object]:
    """Return a typed stand-in for the SDK call that always answers `value`."""

    def call(*_args: Any, **_kwargs: Any) -> object:
        return value

    return call


WEATHER = ToolSpec(
    name="query_grades",
    description="Fetch grades matching a filter.",
    parameters={"type": "object", "properties": {"course_id": {"type": "string"}}},
)


# ── Fakes ────────────────────────────────────────────────────────────────────


def _anthropic_text_response() -> SimpleNamespace:
    """An Anthropic reply containing prose only."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="The average is 72.4%.")],
        stop_reason="end_turn",
        model="claude-opus-5",
        usage=SimpleNamespace(input_tokens=120, output_tokens=18, cache_read_input_tokens=64),
    )


def _anthropic_tool_response() -> SimpleNamespace:
    """An Anthropic reply requesting one tool call."""
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Looking that up."),
            SimpleNamespace(
                type="tool_use",
                id="call_1",
                name="query_grades",
                input={"course_id": "CS101"},
            ),
        ],
        stop_reason="tool_use",
        model="claude-opus-5",
        usage=SimpleNamespace(input_tokens=120, output_tokens=18, cache_read_input_tokens=64),
    )


def _anthropic_thinking_response() -> SimpleNamespace:
    """An Anthropic reply containing a thinking summary and prose."""
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="I compared the weighted marks."),
            SimpleNamespace(type="text", text="The average is 72.4%."),
        ],
        stop_reason="end_turn",
        model="claude-opus-5",
        usage=SimpleNamespace(input_tokens=120, output_tokens=18, cache_read_input_tokens=64),
    )


def _openai_body(*, tool: bool) -> dict[str, Any]:
    """An OpenAI-compatible reply, with or without a tool call."""
    message: dict[str, Any] = (
        {
            "content": "Looking that up.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    # A JSON *string*, where Anthropic sends a decoded object.
                    "function": {
                        "name": "query_grades",
                        "arguments": json.dumps({"course_id": "CS101"}),
                    },
                }
            ],
        }
        if tool
        else {"content": "The average is 72.4%."}
    )
    return {
        "model": "claude-opus-5",
        "choices": [{"message": message, "finish_reason": "tool_calls" if tool else "stop"}],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 18,
            "prompt_tokens_details": {"cached_tokens": 64},
        },
    }


def _anthropic(monkeypatch: pytest.MonkeyPatch, response: object) -> AnthropicProvider:
    """An AnthropicProvider whose SDK call returns `response`."""
    provider = AnthropicProvider(api_key="test-key", model="claude-opus-5")
    monkeypatch.setattr(
        provider.client.messages,
        "create",
        _returns(response),
    )
    return provider


def _openai(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]) -> OpenAICompatibleProvider:
    """An OpenAICompatibleProvider whose HTTP call returns `body`."""
    provider = OpenAICompatibleProvider(
        name="openrouter", model="claude-opus-5", api_key="test-key"
    )
    monkeypatch.setattr(
        httpx,
        "post",
        _responds(httpx.Response(200, json=body)),
    )
    return provider


# ── Conformance ──────────────────────────────────────────────────────────────


def _normalised(result: ChatResult) -> tuple[object, ...]:
    """The parts that must match across providers.

    `raw` and the provider name are deliberately excluded — those are the parts
    allowed to differ.
    """
    return (
        result.text,
        result.tool_calls,
        result.finish_reason,
        result.usage,
        result.model,
    )


def test_text_replies_normalise_identically(monkeypatch: pytest.MonkeyPatch) -> None:
    """A prose reply produces the same ChatResult from either provider."""
    ask = [Message(role=Role.USER, content="What is the average?")]

    anthropic_result = _anthropic(monkeypatch, _anthropic_text_response()).chat(ask)
    openai_result = _openai(monkeypatch, _openai_body(tool=False)).chat(ask)

    assert _normalised(anthropic_result) == _normalised(openai_result)
    assert anthropic_result.text == "The average is 72.4%."
    assert anthropic_result.finish_reason is FinishReason.STOP


def test_tool_calls_normalise_identically(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool call produces the same ChatResult despite entirely different wire shapes.

    Anthropic sends a ``tool_use`` content block with decoded arguments; the
    OpenAI family sends ``tool_calls`` with arguments as a JSON string. Both must
    arrive as the same :class:`ToolCall`.
    """
    ask = [Message(role=Role.USER, content="Grades for CS101?")]

    anthropic_result = _anthropic(monkeypatch, _anthropic_tool_response()).chat(
        ask, tools=[WEATHER]
    )
    openai_result = _openai(monkeypatch, _openai_body(tool=True)).chat(ask, tools=[WEATHER])

    assert _normalised(anthropic_result) == _normalised(openai_result)
    assert anthropic_result.tool_calls == (
        ToolCall(id="call_1", name="query_grades", arguments={"course_id": "CS101"}),
    )
    assert anthropic_result.finish_reason is FinishReason.TOOL_CALLS


def test_usage_including_cache_reads_normalises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cached input tokens are reported separately by both.

    Folded into the total, a prompt cache that has silently stopped working looks
    exactly like one that is working.
    """
    ask = [Message(role=Role.USER, content="hello")]

    for result in (
        _anthropic(monkeypatch, _anthropic_text_response()).chat(ask),
        _openai(monkeypatch, _openai_body(tool=False)).chat(ask),
    ):
        assert result.usage.input_tokens == 120
        assert result.usage.output_tokens == 18
        assert result.usage.cached_tokens == 64


# ── Request encoding ─────────────────────────────────────────────────────────


def test_anthropic_sends_system_as_a_top_level_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic rejects role="system", so it must not appear in the messages."""
    captured: dict[str, Any] = {}
    provider = AnthropicProvider(api_key="k", model="claude-opus-5")

    def capture(**request: Any) -> object:
        captured.update(request)
        return _anthropic_text_response()

    monkeypatch.setattr(provider.client.messages, "create", capture)
    provider.chat([Message(role=Role.USER, content="hi")], system="Be brief.")

    assert captured["system"] == "Be brief."
    assert all(message["role"] != "system" for message in captured["messages"])


def test_openai_sends_system_as_a_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """The OpenAI family has no top-level system field — it is the first message."""
    captured: dict[str, Any] = {}

    def capture(*_: Any, **kwargs: Any) -> httpx.Response:
        captured.update(kwargs["json"])
        return httpx.Response(200, json=_openai_body(tool=False))

    monkeypatch.setattr(httpx, "post", capture)
    provider = OpenAICompatibleProvider(name="x", model="m", api_key="k")
    provider.chat([Message(role=Role.USER, content="hi")], system="Be brief.")

    assert captured["messages"][0] == {"role": "system", "content": "Be brief."}
    assert "system" not in captured


def test_tool_schemas_use_each_provider_s_own_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """input_schema for Anthropic, function.parameters for the OpenAI family."""
    anthropic_request: dict[str, Any] = {}
    openai_request: dict[str, Any] = {}

    provider = AnthropicProvider(api_key="k", model="m")

    def capture_anthropic(**request: Any) -> object:
        anthropic_request.update(request)
        return _anthropic_text_response()

    monkeypatch.setattr(provider.client.messages, "create", capture_anthropic)
    provider.chat([Message(role=Role.USER, content="hi")], tools=[WEATHER])

    def capture_openai(*_: Any, **kwargs: Any) -> httpx.Response:
        openai_request.update(kwargs["json"])
        return httpx.Response(200, json=_openai_body(tool=False))

    monkeypatch.setattr(httpx, "post", capture_openai)
    OpenAICompatibleProvider(name="x", model="m", api_key="k").chat(
        [Message(role=Role.USER, content="hi")], tools=[WEATHER]
    )

    assert anthropic_request["tools"][0]["input_schema"] == WEATHER.parameters
    assert openai_request["tools"][0]["function"]["parameters"] == WEATHER.parameters


def test_tool_results_use_each_provider_s_own_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic carries a tool result on a user turn; the OpenAI family has a tool role."""
    history = [
        Message(role=Role.USER, content="Grades for CS101?"),
        Message(
            role=Role.ASSISTANT,
            tool_calls=(
                ToolCall(id="call_1", name="query_grades", arguments={"course_id": "CS101"}),
            ),
        ),
        Message(role=Role.TOOL, content="[]", tool_call_id="call_1"),
    ]

    anthropic_request: dict[str, Any] = {}
    provider = AnthropicProvider(api_key="k", model="m")

    def capture(**request: Any) -> object:
        anthropic_request.update(request)
        return _anthropic_text_response()

    monkeypatch.setattr(provider.client.messages, "create", capture)
    provider.chat(history)

    result_turn = anthropic_request["messages"][-1]
    assert result_turn["role"] == "user"
    assert result_turn["content"][0]["type"] == "tool_result"
    assert result_turn["content"][0]["tool_use_id"] == "call_1"

    openai_request: dict[str, Any] = {}

    def capture_openai(*_: Any, **kwargs: Any) -> httpx.Response:
        openai_request.update(kwargs["json"])
        return httpx.Response(200, json=_openai_body(tool=False))

    monkeypatch.setattr(httpx, "post", capture_openai)
    OpenAICompatibleProvider(name="x", model="m", api_key="k").chat(history)

    assert openai_request["messages"][-1]["role"] == "tool"
    assert openai_request["messages"][-1]["tool_call_id"] == "call_1"


def test_local_endpoint_sends_no_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty key means a local model, not a broken configuration.

    Sending `Authorization: Bearer ` makes Ollama and LM Studio reject the request,
    so the most private option would be the only one that could not be configured.
    """
    captured: dict[str, Any] = {}

    def capture(*_: Any, **kwargs: Any) -> httpx.Response:
        captured.update(kwargs["headers"])
        return httpx.Response(200, json=_openai_body(tool=False))

    monkeypatch.setattr(httpx, "post", capture)
    OpenAICompatibleProvider(
        name="ollama", model="llama3", api_key="", base_url="http://localhost:11434/v1"
    ).chat([Message(role=Role.USER, content="hi")])

    assert "authorization" not in captured


def test_openai_applies_effort_and_parameters_without_replacing_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider settings may tune generation but may not replace the conversation."""
    captured: dict[str, Any] = {}

    def capture(*_: Any, **kwargs: Any) -> httpx.Response:
        captured.update(kwargs["json"])
        return httpx.Response(200, json=_openai_body(tool=False))

    monkeypatch.setattr(httpx, "post", capture)
    provider = OpenAICompatibleProvider(
        name="nvidia",
        model="deepseek-ai/deepseek-v4-flash",
        api_key="k",
        effort="xhigh",
        params={
            "temperature": 0.6,
            "chat_template_kwargs": {"thinking": True, "reasoning_effort": "low"},
            "model": "must-not-win",
            "messages": [],
            "system": "must-not-win",
        },
    )

    provider.chat([Message(role=Role.USER, content="real question")], system="real system")

    assert captured["model"] == "deepseek-ai/deepseek-v4-flash"
    assert captured["messages"] == [
        {"role": "system", "content": "real system"},
        {"role": "user", "content": "real question"},
    ]
    assert "system" not in captured
    assert "reasoning_effort" not in captured
    assert captured["temperature"] == 0.6
    assert captured["chat_template_kwargs"] == {
        "thinking": True,
        "reasoning_effort": "low",
    }


def test_anthropic_applies_effort_without_enabling_unsigned_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Effort reaches Anthropic without creating blocks the agent cannot replay."""
    captured: dict[str, Any] = {}
    provider = AnthropicProvider(
        api_key="k",
        model="claude-opus-5",
        effort="xhigh",
        params={"temperature": 0.3, "system": "must-not-win"},
    )

    def capture(**request: Any) -> object:
        captured.update(request)
        return _anthropic_text_response()

    monkeypatch.setattr(provider.client.messages, "create", capture)
    provider.chat([Message(role=Role.USER, content="real question")], system="real system")

    assert "thinking" not in captured
    assert captured["output_config"]["effort"] == "xhigh"
    assert captured["temperature"] == 0.3
    assert captured["system"] == "real system"


def test_provider_specific_parameters_override_derived_anthropic_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit provider setting wins over the routing default."""
    captured: dict[str, Any] = {}
    provider = AnthropicProvider(
        api_key="k",
        model="claude-opus-5",
        effort="high",
        params={"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}},
    )

    def capture(**request: Any) -> object:
        captured.update(request)
        return _anthropic_text_response()

    monkeypatch.setattr(provider.client.messages, "create", capture)
    provider.chat([Message(role=Role.USER, content="hi")])

    assert captured["thinking"] == {"type": "disabled"}
    assert captured["output_config"]["effort"] == "low"


def test_anthropic_sends_unknown_body_parameters_through_extra_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vendor extensions use the SDK body escape hatch, not closed keyword arguments."""
    captured: dict[str, Any] = {}
    provider = AnthropicProvider(
        api_key="k",
        model="claude-opus-5",
        params={"vendor_preview": {"mode": "fast"}},
    )

    def capture(
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        output_config: dict[str, Any],
        extra_body: dict[str, Any],
    ) -> object:
        captured.update(
            {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
                "output_config": output_config,
                "extra_body": extra_body,
            }
        )
        return _anthropic_text_response()

    monkeypatch.setattr(provider.client.messages, "create", capture)
    provider.chat([Message(role=Role.USER, content="hi")])

    assert captured["extra_body"] == {"vendor_preview": {"mode": "fast"}}


def test_anthropic_drops_explicit_thinking_when_tools_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool loops cannot enable thinking until signed blocks can be replayed verbatim."""
    captured: dict[str, Any] = {}
    provider = AnthropicProvider(
        api_key="k",
        model="claude-opus-5",
        params={"thinking": {"type": "enabled", "budget_tokens": 1024}},
    )

    def capture(**request: Any) -> object:
        captured.update(request)
        return _anthropic_tool_response()

    monkeypatch.setattr(provider.client.messages, "create", capture)
    provider.chat([Message(role=Role.USER, content="hi")], tools=[WEATHER])

    assert "thinking" not in captured
    assert "thinking" not in captured.get("extra_body", {})


def test_openai_reasoning_content_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    """NVIDIA and DeepSeek reasoning is exposed separately from final prose."""
    body = _openai_body(tool=False)
    body["choices"][0]["message"]["reasoning_content"] = "I compared the weighted marks."

    result = _openai(monkeypatch, body).chat([Message(role=Role.USER, content="average?")])

    assert result.reasoning == "I compared the weighted marks."
    assert result.text == "The average is 72.4%."


def test_anthropic_thinking_blocks_are_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic thinking summaries use the same field as OpenAI-compatible replies."""
    result = _anthropic(monkeypatch, _anthropic_thinking_response()).chat(
        [Message(role=Role.USER, content="average?")]
    )

    assert result.reasoning == "I compared the weighted marks."
    assert result.text == "The average is 72.4%."


# ── Failure modes ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "AI_UNAUTHORIZED"),
        (403, "AI_UNAUTHORIZED"),
        (404, "AI_MODEL_NOT_FOUND"),
        (429, "AI_RATE_LIMITED"),
        (500, "AI_UNAVAILABLE"),
        (503, "AI_UNAVAILABLE"),
        (400, "AI_REQUEST_REJECTED"),
    ],
)
def test_http_failures_map_to_stable_codes(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str
) -> None:
    """The admin page distinguishes a wrong key from a dead service without parsing prose."""
    monkeypatch.setattr(httpx, "post", _responds(httpx.Response(status, text="nope")))
    provider = OpenAICompatibleProvider(name="x", model="m", api_key="k")

    with pytest.raises(LLMError) as caught:
        provider.chat([Message(role=Role.USER, content="hi")])

    assert caught.value.code == code
    assert caught.value.provider == "x"
    assert caught.value.status == status


def test_unreachable_endpoint_is_reported_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused connection has no status, and must not invent one."""

    def refuse(*_: Any, **__: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", refuse)

    with pytest.raises(LLMError) as caught:
        OpenAICompatibleProvider(name="x", model="m", api_key="k").chat(
            [Message(role=Role.USER, content="hi")]
        )

    assert caught.value.code == "AI_UNAVAILABLE"
    assert caught.value.status is None


def test_gateway_error_object_with_200_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Some gateways answer 200 with an error body and no choices.

    Without this, the missing key surfaces as an IndexError far from its cause.
    """
    body = {"error": {"message": "no credit"}}
    monkeypatch.setattr(httpx, "post", _responds(httpx.Response(200, json=body)))

    with pytest.raises(LLMError) as caught:
        OpenAICompatibleProvider(name="x", model="m", api_key="k").chat(
            [Message(role=Role.USER, content="hi")]
        )

    assert caught.value.code == "AI_BAD_OUTPUT"
    assert "no credit" in str(caught.value)


def test_html_response_is_reported_rather_than_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A captive portal or proxy answering with HTML is a provider fault, not a crash."""
    monkeypatch.setattr(httpx, "post", _responds(httpx.Response(200, text="<html>login</html>")))

    with pytest.raises(LLMError) as caught:
        OpenAICompatibleProvider(name="x", model="m", api_key="k").chat(
            [Message(role=Role.USER, content="hi")]
        )

    assert caught.value.code == "AI_BAD_OUTPUT"


def test_malformed_tool_arguments_become_empty_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model emitting broken JSON is the model's fault, and the tool can reject it.

    Raising mid-loop would lose the whole conversation over one bad turn.
    """
    body = _openai_body(tool=True)
    body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{not json"
    monkeypatch.setattr(httpx, "post", _responds(httpx.Response(200, json=body)))

    result = OpenAICompatibleProvider(name="x", model="m", api_key="k").chat(
        [Message(role=Role.USER, content="hi")]
    )

    assert result.tool_calls[0].arguments == {}


def test_parse_json_rejects_a_non_object() -> None:
    """Structured output must be an object; a bare list is a schema failure."""
    with pytest.raises(LLMError) as caught:
        parse_json("[1, 2, 3]")
    assert caught.value.code == "AI_BAD_OUTPUT"


def test_as_message_round_trips_tool_calls() -> None:
    """Appending a result to the history must preserve its tool calls.

    Dropping them breaks the next turn: the provider sees a tool result answering
    a call that is no longer in the conversation.
    """
    call = ToolCall(id="c1", name="query_grades", arguments={"course_id": "CS101"})
    result = ChatResult(text="one moment", tool_calls=(call,))

    message = result.as_message()

    assert message.role is Role.ASSISTANT
    assert message.tool_calls == (call,)


def _raises(error: Exception) -> Callable[..., object]:
    """Return a typed stand-in for the SDK call that always raises `error`."""

    def call(*_args: Any, **_kwargs: Any) -> object:
        raise error

    return call


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "AI_UNAUTHORIZED"),
        (404, "AI_MODEL_NOT_FOUND"),
        (429, "AI_RATE_LIMITED"),
        (500, "AI_UNAVAILABLE"),
    ],
)
def test_anthropic_status_errors_map_to_the_same_codes(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str
) -> None:
    """The same failure reports identically whichever provider produced it.

    That is the point of the abstraction: the admin page has one set of codes to
    translate, not one per backend.
    """
    provider = AnthropicProvider(api_key="k", model="m")
    error = anthropic.APIStatusError(
        "rejected",
        response=httpx.Response(
            status, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        ),
        body=None,
    )
    monkeypatch.setattr(provider.client.messages, "create", _raises(error))

    with pytest.raises(LLMError) as caught:
        provider.chat([Message(role=Role.USER, content="hi")])

    assert caught.value.code == code
    assert caught.value.status == status
    assert caught.value.provider == "anthropic"


def test_anthropic_connection_failure_has_no_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport failure must not invent a status code."""
    provider = AnthropicProvider(api_key="k", model="m")
    error = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    monkeypatch.setattr(provider.client.messages, "create", _raises(error))

    with pytest.raises(LLMError) as caught:
        provider.chat([Message(role=Role.USER, content="hi")])

    assert caught.value.code == "AI_UNAVAILABLE"
    assert caught.value.status is None


def test_check_reports_the_model_that_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backs the admin page's Test-connection button."""
    provider = _anthropic(monkeypatch, _anthropic_text_response())
    assert provider.check() == "claude-opus-5"
