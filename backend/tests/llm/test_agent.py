"""The agent loop, driven by a scripted provider.

A fake provider rather than a real one, because the loop's behaviour must be
deterministic to test at all: that it feeds results back correctly, that it stops,
and that it stops *safely* when the model will not.

The fake also records what it was sent, which is how the conversation-shape
assertions below are possible — those are the parts a real provider would reject
at runtime and a mock would happily accept.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from llm.agent import MAX_TURNS, converse
from llm.base import ChatResult, FinishReason, LLMProvider, Message, Role, ToolCall, ToolSpec, Usage
from llm.tools import READ_TOOLS, ToolContext
from notenverwaltung.models.user import Role as UserRole
from notenverwaltung.storage.db import apply_migrations, connect
from services.scoping import Principal


class ScriptedProvider(LLMProvider):
    """A provider that replays a fixed list of replies and records what it was sent."""

    def __init__(self, replies: list[ChatResult]) -> None:
        """Initialise with the replies to return, in order."""
        super().__init__(name="scripted", model="test-model", api_key="")
        self._replies = list(replies)
        self.seen: list[list[Message]] = []

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
        """Return the next scripted reply, recording the conversation sent."""
        self.seen.append(list(messages))
        if self._replies:
            return self._replies.pop(0)
        # Never exhausted in a correct test; if it is, that is the failure.
        return ChatResult(text="(out of script)", finish_reason=FinishReason.STOP)


def _tool_reply(name: str, arguments: dict[str, Any], *, call_id: str = "c1") -> ChatResult:
    """A reply asking for one tool call."""
    return ChatResult(
        tool_calls=(ToolCall(id=call_id, name=name, arguments=arguments),),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=Usage(input_tokens=100, output_tokens=10),
        model="test-model",
    )


def _text_reply(text: str) -> ChatResult:
    """A reply that concludes."""
    return ChatResult(
        text=text,
        finish_reason=FinishReason.STOP,
        usage=Usage(input_tokens=120, output_tokens=30),
        model="test-model",
    )


@pytest.fixture
def context() -> Iterator[ToolContext]:
    """A tool context over a small admin-visible database."""
    conn: sqlite3.Connection = connect(":memory:")
    apply_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, email, password_hash, password_salt, role, full_name)"
        " VALUES (1, 'admin@test', 'x', 'x', 'admin', 'Root')"
    )
    conn.execute(
        "INSERT INTO students (student_id, first_name, last_name, email)"
        " VALUES ('S001', 'Anna', 'Meier', 'anna@test')"
    )
    conn.execute(
        "INSERT INTO courses (course_id, name, teacher_id, max_grade, passing_grade, credits,"
        " max_students) VALUES ('CS101', 'Databases', 1, 100, 50, 5, 30)"
    )
    conn.execute(
        "INSERT INTO grades (student_id, course_id, title, score, date)"
        " VALUES ('S001', 'CS101', 'Midterm', 90, '2026-01-10')"
    )
    principal = Principal(user_id=1, role=UserRole.ADMIN, email="admin@test", full_name="Root")
    yield ToolContext(conn=conn, principal=principal)
    conn.close()


def _run(provider: LLMProvider, context: ToolContext, **kwargs: Any) -> Any:
    """Run the loop with the standard prompt and tools."""
    return converse(
        provider,
        context,
        question="What is the CS101 average?",
        system="Be accurate.",
        tools=READ_TOOLS,
        **kwargs,
    )


# ── The happy path ───────────────────────────────────────────────────────────


def test_a_direct_answer_makes_one_call(context: ToolContext) -> None:
    """No tools needed means no extra turns."""
    provider = ScriptedProvider([_text_reply("72.4%")])

    result = _run(provider, context)

    assert result.text == "72.4%"
    assert result.turns == 1
    assert result.records == []
    assert result.truncated is False


def test_a_tool_call_is_executed_and_fed_back(context: ToolContext) -> None:
    """The loop's whole job, checked end to end against a real tool."""
    provider = ScriptedProvider(
        [
            _tool_reply("get_statistics", {"course_id": "CS101"}),
            _text_reply("The average is 90%."),
        ]
    )

    result = _run(provider, context)

    assert result.turns == 2
    assert result.text == "The average is 90%."
    assert len(result.records) == 1
    assert result.records[0].name == "get_statistics"
    # A real figure from the database, not one the model invented.
    assert result.records[0].result["average_percentage"] == 90.0


def test_the_tool_result_reaches_the_model_as_a_tool_message(context: ToolContext) -> None:
    """The conversation shape the providers require.

    A tool result must answer a call the model can still see, and must carry the
    matching id. Both families reject a mismatch, and a mock would not.
    """
    provider = ScriptedProvider(
        [_tool_reply("get_statistics", {"course_id": "CS101"}, call_id="abc"), _text_reply("done")]
    )

    _run(provider, context)

    second_turn = provider.seen[1]
    assistant, tool_result = second_turn[-2], second_turn[-1]

    assert assistant.role is Role.ASSISTANT
    assert assistant.tool_calls[0].id == "abc"
    assert tool_result.role is Role.TOOL
    assert tool_result.tool_call_id == "abc"
    # Serialised in the loop, so every provider sees identical text.
    assert json.loads(tool_result.content)["average_percentage"] == 90.0


def test_several_tool_calls_in_one_turn_all_run(context: ToolContext) -> None:
    """A model may batch calls; each needs its own result message."""
    provider = ScriptedProvider(
        [
            ChatResult(
                tool_calls=(
                    ToolCall(id="a", name="get_statistics", arguments={"course_id": "CS101"}),
                    ToolCall(id="b", name="query_grades", arguments={"course_id": "CS101"}),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            _text_reply("done"),
        ]
    )

    result = _run(provider, context)

    assert [record.name for record in result.records] == ["get_statistics", "query_grades"]
    tool_messages = [m for m in provider.seen[1] if m.role is Role.TOOL]
    assert [m.tool_call_id for m in tool_messages] == ["a", "b"]


def test_usage_accumulates_across_turns(context: ToolContext) -> None:
    """Billing is per call, so the log must total them rather than keep the last."""
    provider = ScriptedProvider(
        [_tool_reply("get_statistics", {"course_id": "CS101"}), _text_reply("done")]
    )

    result = _run(provider, context)

    assert result.usage.input_tokens == 220  # 100 + 120
    assert result.usage.output_tokens == 40  # 10 + 30


def test_reasoning_is_collected_but_never_replayed(context: ToolContext) -> None:
    """Reasoning is display data, not an unsigned assistant message."""
    provider = ScriptedProvider(
        [
            ChatResult(
                reasoning="I need the course statistics.",
                tool_calls=(
                    ToolCall(
                        id="c1",
                        name="get_statistics",
                        arguments={"course_id": "CS101"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            ChatResult(
                text="The average is 90%.",
                reasoning="The only recorded mark is 90 out of 100.",
                finish_reason=FinishReason.STOP,
            ),
        ]
    )

    result = _run(provider, context)

    assert result.reasoning == (
        "I need the course statistics.\n\nThe only recorded mark is 90 out of 100."
    )
    assistant_turn = provider.seen[1][-2]
    assert assistant_turn.role is Role.ASSISTANT
    assert assistant_turn.content == ""


# ── Stopping ─────────────────────────────────────────────────────────────────


def test_a_model_that_never_concludes_is_stopped(context: ToolContext) -> None:
    """Without the cap this runs until the bill stops it."""
    provider = ScriptedProvider(
        [_tool_reply("get_statistics", {"course_id": "CS101"}) for _ in range(MAX_TURNS + 3)]
    )

    result = _run(provider, context)

    assert result.turns == MAX_TURNS
    assert result.truncated is True


def test_truncation_is_reported_rather_than_hidden(context: ToolContext) -> None:
    """A capped answer is incomplete, not merely short.

    Presenting it as a finished answer is how a truncated analysis gets acted on.
    """
    provider = ScriptedProvider([_tool_reply("query_grades", {}) for _ in range(10)])

    result = _run(provider, context, max_turns=2)

    assert result.truncated is True
    assert result.turns == 2
    assert len(result.records) == 2


def test_a_finished_answer_is_not_marked_truncated(context: ToolContext) -> None:
    """The counterweight: the flag must distinguish, not always fire."""
    provider = ScriptedProvider([_tool_reply("query_grades", {}), _text_reply("all done")])

    assert _run(provider, context, max_turns=2).truncated is False


# ── Failures inside the loop ─────────────────────────────────────────────────


def test_a_bad_tool_call_does_not_end_the_conversation(context: ToolContext) -> None:
    """The model gets the error back and can correct itself.

    Raising here would lose a whole conversation over one malformed argument.
    """
    provider = ScriptedProvider(
        [
            _tool_reply("get_statistics", {"raw_sql": "DROP TABLE users"}),
            _text_reply("Sorry, let me try again properly."),
        ]
    )

    result = _run(provider, context)

    assert "error" in result.records[0].result
    assert result.text.startswith("Sorry")
    assert result.turns == 2


def test_an_unknown_tool_is_reported_to_the_model(context: ToolContext) -> None:
    """A hallucinated tool name is a recoverable mistake, not a crash."""
    provider = ScriptedProvider([_tool_reply("exfiltrate", {}), _text_reply("ok")])

    result = _run(provider, context)

    assert "error" in result.records[0].result


def test_scope_still_applies_to_tools_the_model_calls(context: ToolContext) -> None:
    """The loop must not become a way around the boundary.

    Same tool, same arguments, different principal — the loop passes the context
    through untouched, so the student sees nothing.
    """
    student_context = ToolContext(
        conn=context.conn,
        principal=Principal(
            user_id=2,
            role=UserRole.STUDENT,
            email="s@test",
            full_name="S",
            student_id="S999",
        ),
    )
    provider = ScriptedProvider(
        [_tool_reply("query_grades", {"student_id": "S001"}), _text_reply("nothing found")]
    )

    result = converse(
        provider,
        student_context,
        question="Show me Anna's grades",
        system="Be accurate.",
        tools=READ_TOOLS,
    )

    assert result.records[0].result["grades"] == []
