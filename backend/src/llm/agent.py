"""The agent loop. One implementation, every provider.

Small on purpose. This is the whole reason :class:`~llm.base.LLMProvider`
normalises rather than forwards: with the differences absorbed, "call the model,
run what it asks for, feed the results back" is a ``while`` loop and not a
framework.

Two guards that are not optional:

- **A turn cap.** A model that keeps calling tools without concluding will do so
  until the bill stops it. The cap turns an infinite loop into a truncated answer.
- **Every tool result is recorded.** The transcript is returned alongside the
  answer so the interface can show the rows the prose was built from. A wrong
  narrative next to the real numbers is visibly wrong; on its own it is
  convincing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from llm.base import FinishReason, LLMProvider, Message, Role, ToolSpec, Usage
from llm.tools import ToolContext, run

#: Beyond this the model is not converging, and each extra turn costs a full
#: context window. Five is enough for search → resolve → query → summarise.
MAX_TURNS = 5


@dataclass(slots=True)
class ToolRecord:
    """One tool call and what it returned.

    Attributes:
        name: Which tool.
        arguments: What the model asked for.
        result: What it got back.
    """

    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass(slots=True)
class AgentResult:
    """The outcome of an agent run.

    Attributes:
        text: The model's final prose.
        records: Every tool call made, in order. Rendered beside the prose so a
            wrong narrative sits next to the numbers that contradict it.
        usage: Token totals across every turn, for the usage log.
        turns: How many model calls it took.
        truncated: Whether the turn cap stopped it before it concluded. Surfaced
            rather than hidden — a capped answer is incomplete, not merely short.
        model: The model that answered.
    """

    text: str = ""
    records: list[ToolRecord] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    turns: int = 0
    truncated: bool = False
    model: str = ""
    latency_ms: int = 0


def _accumulate(total: Usage, addition: Usage) -> Usage:
    """Sum two usage records.

    Args:
        total: Running total.
        addition: This turn's usage.

    Returns:
        The combined total.
    """
    return Usage(
        input_tokens=total.input_tokens + addition.input_tokens,
        output_tokens=total.output_tokens + addition.output_tokens,
        cached_tokens=total.cached_tokens + addition.cached_tokens,
    )


def converse(
    provider: LLMProvider,
    context: ToolContext,
    *,
    question: str,
    system: str,
    tools: list[ToolSpec],
    max_turns: int = MAX_TURNS,
) -> AgentResult:
    """Run the model until it answers, or until the turn cap.

    Args:
        provider: Any implementation. The loop never learns which.
        context: Connection and principal, passed to every tool.
        question: What the user asked.
        system: The system prompt.
        tools: Tools the model may call.
        max_turns: Most model calls to make.

    Returns:
        The final prose, the tool transcript, and token totals.

    Raises:
        LLMError: If a provider call fails. Not caught here — the caller decides
            whether a failed answer is a 502 or a recorded error, and swallowing
            it would produce a confident empty response.
    """
    started = time.monotonic()
    history: list[Message] = [Message(role=Role.USER, content=question)]
    result = AgentResult()

    for turn in range(1, max_turns + 1):
        reply = provider.chat(history, system=system, tools=tools)

        result.turns = turn
        result.usage = _accumulate(result.usage, reply.usage)
        result.model = reply.model or provider.model

        if reply.finish_reason is not FinishReason.TOOL_CALLS or not reply.tool_calls:
            result.text = reply.text
            break

        # The assistant turn must go back verbatim, tool calls included. Dropping
        # them leaves the next turn's tool results answering calls the provider
        # cannot see, which both families reject.
        history.append(reply.as_message())

        for call in reply.tool_calls:
            output = run(context, call.name, call.arguments)
            result.records.append(
                ToolRecord(name=call.name, arguments=call.arguments, result=output)
            )
            history.append(
                Message(
                    role=Role.TOOL,
                    # Serialised here rather than in the provider: both families
                    # want text, and letting each one stringify differently would
                    # make the same conversation two different conversations.
                    content=json.dumps(output, default=str),
                    tool_call_id=call.id,
                )
            )
    else:
        # Loop finished without breaking: the model was still calling tools on its
        # last allowed turn.
        result.truncated = True

    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result
