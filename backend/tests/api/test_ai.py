"""The AI endpoints.

No network: the registry is patched to hand back a scripted provider, so these
tests exercise the endpoints, the authorization, the caching and the usage log
without a key or a bill.

What they defend, beyond the plumbing:

- ``/ai/command`` cannot write. The write tools are declared but unimplemented,
  and the response is a proposal.
- ``/ai/ask`` answers as the caller. Same question, different role, different data.
- Insights are cached against the statistics, so identical numbers are not
  regenerated — and *change* when the numbers change.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from llm.base import (
    ChatResult,
    FinishReason,
    LLMError,
    LLMProvider,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)
from llm.registry import Registry


class StubProvider(LLMProvider):
    """A provider that replays scripted replies."""

    def __init__(self, replies: list[ChatResult]) -> None:
        """Initialise with the replies to return in order."""
        super().__init__(name="stub", model="stub-model", api_key="")
        self._replies = list(replies)

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
        """Return the next scripted reply."""
        if self._replies:
            return self._replies.pop(0)
        return ChatResult(text="", finish_reason=FinishReason.STOP, model="stub-model")


def _resolves_to(provider: LLMProvider) -> Callable[..., LLMProvider]:
    """A typed stand-in for Registry.resolve that always hands back `provider`."""

    def resolve(*_args: Any, **_kwargs: Any) -> LLMProvider:
        return provider

    return resolve


def _install(monkeypatch: pytest.MonkeyPatch, *replies: ChatResult) -> None:
    """Make every feature resolve to a provider replaying `replies`."""
    monkeypatch.setattr(Registry, "resolve", _resolves_to(StubProvider(list(replies))))


def _text(payload: str) -> ChatResult:
    """A concluding reply."""
    return ChatResult(
        text=payload,
        finish_reason=FinishReason.STOP,
        usage=Usage(input_tokens=50, output_tokens=20),
        model="stub-model",
    )


def _insight_json() -> str:
    """A valid structured insight."""
    return json.dumps(
        {
            "summary": "Consistent performance.",
            "risk_level": "low",
            "trend": "steady",
            "factors": ["Average of 78%."],
            "suggested_actions": ["No action needed."],
        }
    )


# ── Authorization ────────────────────────────────────────────────────────────


def test_asking_requires_a_session(client: TestClient) -> None:
    """The assistant is not public."""
    assert client.post("/ai/ask", json={"question": "hello"}).status_code == 401


def test_a_student_cannot_generate_insights(as_student: TestClient) -> None:
    """Insights are a teaching tool, and they summarise a cohort."""
    assert as_student.get("/ai/insight/course/CS101").status_code == 403


def test_a_student_cannot_map_an_import(as_student: TestClient) -> None:
    """Importing is not a student capability, so neither is planning one."""
    response = as_student.post("/ai/import-map", json={"headers": ["a"], "samples": []})
    assert response.status_code == 403


# ── Ask ──────────────────────────────────────────────────────────────────────


def test_ask_returns_the_answer_and_its_supporting_queries(
    as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transcript is the point: prose alone cannot be checked."""
    _install(
        monkeypatch,
        ChatResult(
            tool_calls=(
                ToolCall(id="c1", name="get_statistics", arguments={"course_id": "CS101"}),
            ),
            finish_reason=FinishReason.TOOL_CALLS,
            usage=Usage(input_tokens=40, output_tokens=5),
            model="stub-model",
        ),
        _text("The CS101 average is 72%."),
    )

    body = as_admin.post("/ai/ask", json={"question": "CS101 average?"}).json()

    assert body["text"] == "The CS101 average is 72%."
    assert len(body["records"]) == 1
    assert body["records"][0]["tool"] == "get_statistics"
    # A real figure from the seeded database, not one the stub invented.
    assert "average_percentage" in body["records"][0]["result"]
    assert body["truncated"] is False


def test_ask_returns_reasoning_separately_from_the_answer(
    as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reasoning model's explanation is available for an opt-in disclosure."""
    _install(
        monkeypatch,
        ChatResult(
            text="The CS101 average is 72%.",
            reasoning="I used the weighted course statistics.",
            finish_reason=FinishReason.STOP,
            model="stub-model",
        ),
    )

    body = as_admin.post("/ai/ask", json={"question": "CS101 average?"}).json()

    assert body["text"] == "The CS101 average is 72%."
    assert body["reasoning"] == "I used the weighted course statistics."


def test_ask_answers_as_the_caller(
    as_student: TestClient, as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same question, asked by two roles, must not return the same data.

    This is the injection case at the HTTP boundary: the student's assistant runs
    the identical tool call and sees only their own rows.
    """

    def scripted() -> list[ChatResult]:
        return [
            ChatResult(
                tool_calls=(ToolCall(id="c1", name="query_grades", arguments={}),),
                finish_reason=FinishReason.TOOL_CALLS,
                model="stub-model",
            ),
            _text("done"),
        ]

    _install(monkeypatch, *scripted())
    student_rows = as_student.post("/ai/ask", json={"question": "everything"}).json()["records"][0][
        "result"
    ]["grades"]

    _install(monkeypatch, *scripted())
    admin_rows = as_admin.post("/ai/ask", json={"question": "everything"}).json()["records"][0][
        "result"
    ]["grades"]

    assert len({row["student_id"] for row in student_rows}) == 1
    assert len(admin_rows) > len(student_rows)


def test_an_empty_question_is_rejected_before_the_provider(as_admin: TestClient) -> None:
    """Rejected at the schema, so a blank submit does not cost a token."""
    assert as_admin.post("/ai/ask", json={"question": "   "}).status_code == 422


def test_an_overlong_question_is_rejected(as_admin: TestClient) -> None:
    """A cap the provider would otherwise bill for."""
    assert as_admin.post("/ai/ask", json={"question": "x" * 5000}).status_code == 422


def test_an_unconfigured_feature_reports_rather_than_crashing(as_admin: TestClient) -> None:
    """No provider routed to `ask` is a configuration gap with a stable code."""
    response = as_admin.post("/ai/ask", json={"question": "hello"})

    assert response.status_code == 404
    assert response.json()["code"] == "AI_NOT_CONFIGURED"


def test_a_provider_failure_is_a_bad_gateway(
    as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fault is upstream and the caller cannot fix it."""

    class Failing(StubProvider):
        def chat(self, *args: Any, **kwargs: Any) -> ChatResult:
            raise LLMError("upstream is down", code="AI_UNAVAILABLE", provider="stub")

    monkeypatch.setattr(Registry, "resolve", _resolves_to(Failing([])))

    response = as_admin.post("/ai/ask", json={"question": "hello"})

    assert response.status_code == 502
    assert response.json()["code"] == "AI_UNAVAILABLE"


# ── Command ──────────────────────────────────────────────────────────────────


def test_command_proposes_and_writes_nothing(
    as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The security property of the palette, checked against the database.

    The model asks to record a grade; the response is a proposal and the grade
    count is unchanged.
    """
    before = as_admin.get("/grades", params={"size": 1}).json()["total"]

    _install(
        monkeypatch,
        ChatResult(
            tool_calls=(
                ToolCall(
                    id="c1",
                    name="record_grade",
                    arguments={"student_id": "S001", "course_id": "CS101", "score": 88},
                ),
            ),
            finish_reason=FinishReason.TOOL_CALLS,
            model="stub-model",
        ),
    )

    body = as_admin.post("/ai/command", json={"instruction": "give Anna 88 in CS101"}).json()

    assert body["action"] == "record_grade"
    assert body["params"]["score"] == 88
    assert as_admin.get("/grades", params={"size": 1}).json()["total"] == before


def test_command_can_decline_to_propose(
    as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ambiguous instruction gets words, not a guessed action.

    Guessing which student was meant is how the wrong person receives a grade.
    """
    _install(monkeypatch, _text("Which student did you mean?"))

    body = as_admin.post("/ai/command", json={"instruction": "give them 88"}).json()

    assert body["action"] is None
    assert body["message"].startswith("Which student")


# ── Insight ──────────────────────────────────────────────────────────────────


def test_insight_is_generated_then_served_from_cache(
    as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same numbers must not be paid for twice.

    The stub has exactly one reply; a second generation would return empty text
    and fail to parse, so a cache miss here is a visible failure rather than a
    silent extra call.
    """
    _install(monkeypatch, _text(_insight_json()))

    first = as_admin.get("/ai/insight/course/CS101").json()
    second = as_admin.get("/ai/insight/course/CS101").json()

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["summary"] == first["summary"]


def test_insight_regenerates_when_the_numbers_change(
    as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cached against a hash of the statistics, not a clock.

    Recording a grade changes the hash, so the next request must regenerate rather
    than serve a summary that no longer describes the data.
    """
    _install(monkeypatch, _text(_insight_json()))
    assert as_admin.get("/ai/insight/course/CS101").json()["cached"] is False

    as_admin.post(
        "/grades",
        json={
            "student_id": "S001",
            "course_id": "CS101",
            "title": "Extra",
            "score": 10,
            "date": "2026-03-01",
        },
    )

    updated = json.loads(_insight_json())
    updated["summary"] = "Now including the new mark."
    _install(monkeypatch, _text(json.dumps(updated)))

    refreshed = as_admin.get("/ai/insight/course/CS101").json()

    assert refreshed["cached"] is False
    assert refreshed["summary"] == "Now including the new mark."


def test_an_insight_for_an_ungraded_course_is_refused(
    as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model asked to summarise nothing will produce something.

    Refusing costs nothing and cannot mislead.
    """
    _install(monkeypatch, _text(_insight_json()))

    as_admin.post(
        "/courses",
        json={
            "course_id": "EMPTY1",
            "name": "Empty",
            "max_grade": 100,
            "passing_grade": 50,
            "credits": 5,
            "max_students": 10,
        },
    )

    assert as_admin.get("/ai/insight/course/EMPTY1").status_code == 422


def test_an_unknown_entity_type_is_rejected(
    as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only two things can be summarised, and the caller does not get to name a third."""
    _install(monkeypatch, _text(_insight_json()))

    assert as_admin.get("/ai/insight/teacher/1").status_code == 422


# ── Usage accounting ─────────────────────────────────────────────────────────


def test_every_call_is_logged(
    as_admin: TestClient, as_superadmin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spend is only visible if it is recorded at the point of use."""
    _install(monkeypatch, _text("An answer."))
    as_admin.post("/ai/ask", json={"question": "anything"})

    usage = as_superadmin.get("/admin/ai/usage").json()

    assert len(usage) == 1
    assert usage[0]["feature"] == "ask"
    assert usage[0]["input_tokens"] == 50
    assert usage[0]["errors"] == 0


def test_a_failed_call_is_logged_as_an_error(
    as_admin: TestClient, as_superadmin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A usage page showing only successes hides a provider that has started failing."""

    class Failing(StubProvider):
        def chat(self, *args: Any, **kwargs: Any) -> ChatResult:
            raise LLMError("down", code="AI_UNAVAILABLE", provider="stub")

    monkeypatch.setattr(Registry, "resolve", _resolves_to(Failing([])))

    as_admin.post("/ai/ask", json={"question": "anything"})
    usage = as_superadmin.get("/admin/ai/usage").json()

    assert len(usage) == 1
    assert usage[0]["errors"] == 1
