"""The four AI features, each using the mechanism that fits it.

They are deliberately *not* the same shape:

============  ==================  ==========================================
Feature       Mechanism           Why
============  ==================  ==========================================
ask           tool loop           The question decides which data is needed.
insight       structured output   The data is known; only the prose varies.
command       halted tool loop    The model proposes; a person disposes.
import_map    structured output   A mapping, not a conversation.
============  ==================  ==========================================

``insight`` in particular does **not** use tools. The statistics are computed
first and passed in, because letting a model choose which numbers to fetch for a
summary invites it to fetch the flattering ones.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm.agent import AgentResult, converse
from llm.base import LLMError, LLMProvider, Message, Role
from llm.registry import Feature, Registry
from llm.tools import READ_TOOLS, WRITE_TOOLS, ToolContext, get_statistics
from notenverwaltung.exceptions import ValidationError
from services.ai_admin import AiAdminService
from services.scoping import Principal

MAX_QUESTION_LENGTH = 500

#: Locale tag to the language name used in the prompt. A tag like "de" is not
#: reliably understood as an instruction; "German" is.
_LANGUAGE = {"en": "English", "de": "German", "fr": "French"}

_ASK_SYSTEM = """You answer questions about a school gradebook.

Rules:
- Use the tools for every number. Never estimate, and never do arithmetic yourself.
- The tools already restrict results to what this person is allowed to see. If a
  tool returns nothing, say so plainly — do not guess at what might be hidden.
- Be brief. One or two sentences unless asked for more.
- Respond in {language}."""

_INSIGHT_SYSTEM = """You write short, factual summaries of a student's or course's
performance for a teacher.

You are given the statistics. Do not invent figures that are not in them.
Be specific and unsentimental: name what the numbers show, not how it feels.
Respond in {language}."""

_COMMAND_SYSTEM = """You turn a short instruction into exactly one proposed action.

Call the single tool that matches the instruction. Do not explain. If no tool
matches, or the instruction is ambiguous about who or what, reply in words instead
of calling a tool.
Respond in {language}."""

_IMPORT_SYSTEM = """You map spreadsheet columns onto gradebook fields.

Given the header row and a few sample rows, decide which column feeds which field.
Report anything that looks wrong rather than guessing past it.
Respond in {language}."""

#: Shape of an insight. Constrained so the interface can render fields rather than
#: parsing prose.
INSIGHT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Two or three sentences."},
        "risk_level": {"type": "string", "enum": ["none", "low", "medium", "high"]},
        "trend": {"type": "string", "enum": ["improving", "steady", "declining", "unknown"]},
        "factors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What the numbers show, one point each.",
        },
        "suggested_actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "risk_level", "trend", "factors", "suggested_actions"],
    "additionalProperties": False,
}

#: Shape of a proposed import mapping.
IMPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "column_mapping": {
            "type": "object",
            "description": "Gradebook field name to source column name.",
            "additionalProperties": {"type": "string"},
        },
        "issues": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["column_mapping", "issues", "confidence"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class Answer:
    """A reply to a gradebook question.

    Attributes:
        text: The prose.
        records: Every tool call and its result, so the interface can show the rows
            the prose was built from. A wrong narrative beside the real numbers is
            visibly wrong; alone it is convincing.
        truncated: Whether the turn cap stopped it short.
        model: Which model answered.
        reasoning: Provider-supplied thinking summaries, kept separate from prose.
    """

    text: str
    records: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    model: str = ""
    reasoning: str = ""


@dataclass(frozen=True, slots=True)
class Proposal:
    """A command the model proposes, awaiting confirmation.

    Attributes:
        action: The tool the model chose, or None when it declined to choose one.
        params: The arguments it filled in. Not validated here — the endpoint that
            performs the action validates them, exactly as it would for a form.
        message: Prose, when the model answered instead of proposing.
    """

    action: str | None
    params: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class AiService:
    """The four AI features, over whatever providers are configured."""

    def __init__(self, conn: sqlite3.Connection, principal: Principal) -> None:
        """Initialise the service.

        Args:
            conn: The request's database connection.
            principal: Who is asking. Passed to every tool, and the only source of
                what they may see.
        """
        self._conn = conn
        self._principal = principal
        self._registry = Registry(conn)
        self._admin = AiAdminService(conn)
        self._context = ToolContext(conn=conn, principal=principal)

    # ── Ask ──────────────────────────────────────────────────────────────────

    def ask(self, question: str) -> Answer:
        """Answer a question about the gradebook.

        Args:
            question: What the user typed.

        Returns:
            The answer and the tool transcript behind it.

        Raises:
            ValidationError: If the question is empty or absurdly long.
            LLMError: If the feature is unconfigured or the provider fails.
        """
        text = self._check_question(question)
        provider = self._registry.resolve(Feature.ASK)

        result = self._record(
            Feature.ASK,
            lambda: converse(
                provider,
                self._context,
                question=text,
                system=self._system(_ASK_SYSTEM),
                tools=READ_TOOLS,
            ),
        )

        return Answer(
            text=result.text,
            records=[
                {"tool": record.name, "arguments": record.arguments, "result": record.result}
                for record in result.records
            ],
            truncated=result.truncated,
            model=result.model,
            reasoning=result.reasoning,
        )

    # ── Command ──────────────────────────────────────────────────────────────

    def command(self, instruction: str) -> Proposal:
        """Turn an instruction into a proposed action, without performing it.

        The loop is capped at a single turn and the write tools have no handlers,
        so there is no path from here to a database write. The model fills in a
        form; a person submits it.

        Args:
            instruction: What the user typed into the palette.

        Returns:
            The proposed action, or prose when the model declined to choose one.

        Raises:
            ValidationError: If the instruction is empty or too long.
            LLMError: If the feature is unconfigured or the provider fails.
        """
        text = self._check_question(instruction)
        provider = self._registry.resolve(Feature.COMMAND)

        # One turn. The loop stops at the first tool call because none of the write
        # tools is in HANDLERS, so there is nothing to execute and feed back.
        result = self._record(
            Feature.COMMAND,
            lambda: converse(
                provider,
                self._context,
                question=text,
                system=self._system(_COMMAND_SYSTEM),
                tools=WRITE_TOOLS,
                max_turns=1,
            ),
        )

        if result.records:
            record = result.records[0]
            return Proposal(action=record.name, params=record.arguments)
        return Proposal(action=None, message=result.text)

    # ── Insight ──────────────────────────────────────────────────────────────

    def insight(self, *, entity_type: str, entity_id: str) -> dict[str, Any]:
        """Summarise a student's or course's performance.

        Cached against a hash of the statistics rather than a clock: the same
        numbers always produce the same summary, so regenerating them is waste.
        Recording a grade changes the hash and the next request regenerates.

        Args:
            entity_type: ``student`` or ``course``.
            entity_id: Which one.

        Returns:
            The structured insight, with ``cached`` indicating its provenance.

        Raises:
            ValidationError: If the entity type is unrecognised.
            LLMError: If the feature is unconfigured or the provider fails.
        """
        if entity_type not in {"student", "course"}:
            raise ValidationError(
                "entity_type must be 'student' or 'course'",
                field="entity_type",
                value=entity_type,
            )

        selector = {f"{entity_type}_id": entity_id}
        stats = get_statistics(self._context, selector)

        if not stats.get("grade_count"):
            # Nothing to summarise, and a model asked to summarise nothing will
            # produce something. Refusing costs nothing and cannot mislead.
            raise ValidationError("no grades to summarise", field="entity_id", value=entity_id)

        digest = hashlib.sha256(json.dumps(stats, sort_keys=True, default=str).encode()).hexdigest()
        locale = self._principal.locale

        cached = self._conn.execute(
            "SELECT payload_json, stats_sha256 FROM ai_insights"
            " WHERE entity_type = ? AND entity_id = ? AND locale = ?",
            (entity_type, entity_id, locale),
        ).fetchone()

        if cached is not None and cached["stats_sha256"] == digest:
            return {**json.loads(cached["payload_json"]), "cached": True}

        provider = self._registry.resolve(Feature.INSIGHT)
        prompt = (
            f"Summarise this {entity_type}'s performance.\n\n"
            f"Statistics: {json.dumps(stats, default=str)}"
        )

        result = self._record(
            Feature.INSIGHT,
            lambda: _single_turn(
                provider,
                prompt,
                system=self._system(_INSIGHT_SYSTEM),
                schema=INSIGHT_SCHEMA,
            ),
        )

        payload = _decode(result.text)
        self._conn.execute(
            "INSERT INTO ai_insights"
            " (entity_type, entity_id, stats_sha256, locale, payload_json, model)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (entity_type, entity_id, locale) DO UPDATE SET"
            "   stats_sha256 = excluded.stats_sha256,"
            "   payload_json = excluded.payload_json,"
            "   model = excluded.model",
            (entity_type, entity_id, digest, locale, json.dumps(payload), result.model),
        )

        return {**payload, "cached": False}

    # ── Import mapping ───────────────────────────────────────────────────────

    def import_map(self, *, headers: list[str], samples: list[list[str]]) -> dict[str, Any]:
        """Propose how spreadsheet columns map onto gradebook fields.

        Args:
            headers: The header row.
            samples: A handful of data rows, for disambiguation.

        Returns:
            The proposed mapping, any issues found, and a confidence level.

        Raises:
            ValidationError: If there are no headers.
            LLMError: If the feature is unconfigured or the provider fails.
        """
        if not headers:
            raise ValidationError("no header row", field="headers", value=headers)

        provider = self._registry.resolve(Feature.IMPORT_MAP)
        prompt = (
            "Gradebook fields:\n"
            "- students: student_id, first_name, last_name, email, is_active, phone,"
            " date_of_birth, cohort\n"
            "- courses: course_id, name, max_grade, passing_grade, max_students, term,"
            " credits, description, room, schedule, department, start_date, end_date\n"
            "- grades: student_id, course_id, title, score, date, weight, notes\n"
            f"Header row: {json.dumps(headers)}\n"
            # Capped: twenty rows is plenty to disambiguate a column, and a whole
            # file would be both expensive and a needless disclosure.
            f"Sample rows: {json.dumps(samples[:20])}"
        )

        result = self._record(
            Feature.IMPORT_MAP,
            lambda: _single_turn(
                provider, prompt, system=self._system(_IMPORT_SYSTEM), schema=IMPORT_SCHEMA
            ),
        )
        return _decode(result.text)

    # ── Internals ────────────────────────────────────────────────────────────

    def _system(self, template: str) -> str:
        """Fill a system prompt with the caller's language.

        Args:
            template: One of the module's prompt templates.

        Returns:
            The prompt, instructing the model which language to answer in.
        """
        return template.format(language=_LANGUAGE.get(self._principal.locale, "English"))

    def _check_question(self, text: str) -> str:
        """Validate free text before it reaches a provider.

        Args:
            text: What the user typed.

        Returns:
            The trimmed text.

        Raises:
            ValidationError: If empty or over the length cap. Checked here rather
                than by the provider, which would bill for the rejection.
        """
        trimmed = text.strip()
        if not trimmed:
            raise ValidationError("question is empty", field="question", value=text)
        if len(trimmed) > MAX_QUESTION_LENGTH:
            raise ValidationError(
                f"question is too long (max {MAX_QUESTION_LENGTH})",
                field="question",
                value=len(trimmed),
            )
        return trimmed

    def _record(self, feature: Feature, call: Callable[[], AgentResult]) -> AgentResult:
        """Run a provider call and log its usage, successful or not.

        Failures are logged too. A usage page showing only successes hides exactly
        the pattern that matters — a provider that has started rejecting
        everything.

        Args:
            feature: Which capability is calling.
            call: A zero-argument callable returning an :class:`AgentResult`.

        Returns:
            Whatever the call returned.

        Raises:
            LLMError: Re-raised after logging.
        """
        provider_id = self._provider_id(feature)
        try:
            result = call()
        except LLMError:
            self._admin.record_usage(
                feature=feature,
                provider_id=provider_id,
                model="",
                user_id=self._principal.user_id,
                was_error=True,
            )
            raise

        self._admin.record_usage(
            feature=feature,
            provider_id=provider_id,
            model=result.model,
            user_id=self._principal.user_id,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cached_tokens=result.usage.cached_tokens,
            latency_ms=result.latency_ms,
        )
        return result

    def _provider_id(self, feature: Feature) -> int | None:
        """Look up which provider serves a feature, for the usage log.

        Args:
            feature: Which capability.

        Returns:
            The provider's id, or None if the routing has since gone.
        """
        row = self._conn.execute(
            "SELECT provider_id FROM ai_feature_models WHERE feature = ?", (feature.value,)
        ).fetchone()
        return row["provider_id"] if row else None


def _single_turn(
    provider: LLMProvider, prompt: str, *, system: str, schema: dict[str, Any]
) -> AgentResult:
    """Make one schema-constrained call and wrap it as an :class:`AgentResult`.

    Wrapped so usage logging has one shape to handle rather than two.

    Args:
        provider: The resolved provider.
        prompt: The user message.
        system: The system prompt.
        schema: The JSON Schema the reply must satisfy.

    Returns:
        The reply, in the same shape the agent loop returns.
    """
    reply = provider.chat([Message(role=Role.USER, content=prompt)], system=system, schema=schema)
    _decode(reply.text)
    return AgentResult(
        text=reply.text,
        usage=reply.usage,
        turns=1,
        model=reply.model,
        reasoning=reply.reasoning,
    )


def _decode(text: str) -> dict[str, Any]:
    """Decode a schema-constrained reply.

    Args:
        text: The model's reply.

    Returns:
        The decoded object.

    Raises:
        LLMError: If it is not a JSON object. Schema-constrained output makes this
            nearly impossible, which is why it must fail loudly rather than degrade
            to an empty dict nobody notices.
    """
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMError(f"reply was not JSON: {text[:200]}", code="AI_BAD_OUTPUT") from error
    if not isinstance(value, dict):
        raise LLMError("reply was not a JSON object", code="AI_BAD_OUTPUT")
    return value
