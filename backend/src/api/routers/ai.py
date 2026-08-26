"""The AI endpoints.

Every one of these runs as the signed-in caller, and the tools underneath them
apply that caller's scope. There is no service account and no elevated path: a
student asking the assistant to list everyone's grades gets their own, because
the question is answered by the same queries the rest of the API uses.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.deps import AdminUser, CurrentUser, DbConn, TeacherUser
from services.ai import MAX_HISTORY_TURNS, MAX_QUESTION_LENGTH, AiService
from services.rate_limit import CallQuota

router = APIRouter(prefix="/ai", tags=["AI"])


class HistoryTurn(BaseModel):
    """One earlier turn of the same conversation."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)


class AskRequest(BaseModel):
    """A question about the gradebook, and optionally what came before it."""

    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_LENGTH,
        examples=["Which students are failing Databases?"],
    )
    history: list[HistoryTurn] = Field(
        default_factory=list,
        max_length=MAX_HISTORY_TURNS,
        description=(
            "Earlier turns, oldest first, so a follow-up can resolve against them. "
            "Held by the client rather than the server: there is no conversation "
            "table, no retention policy and nothing to clean up. Safe because a "
            "forged transcript reaches nothing — the model cannot write, and every "
            "tool composes the caller's own scope server-side."
        ),
        examples=[[{"role": "user", "content": "What is Anna's average in CS101?"}]],
    )


class ToolRecordResponse(BaseModel):
    """One tool call the assistant made."""

    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class AskResponse(BaseModel):
    """An answer, with the data it was built from."""

    text: str
    records: list[ToolRecordResponse] = Field(
        description=(
            "Every query the assistant ran, with its results. Rendered beside the "
            "prose so a wrong narrative sits next to the numbers that contradict it."
        )
    )
    truncated: bool = Field(
        description="True when the turn cap stopped the assistant before it concluded."
    )
    model: str
    reasoning: str = Field(
        default="",
        description=(
            "Provider-supplied thinking summary, when available. Kept separate from "
            "the answer and never replayed into a later model turn."
        ),
    )


class CommandRequest(BaseModel):
    """An instruction for the command palette."""

    instruction: str = Field(
        min_length=1, max_length=MAX_QUESTION_LENGTH, examples=["give Anna 88 in CS101"]
    )


class CommandResponse(BaseModel):
    """A proposed action, awaiting confirmation."""

    action: str | None = Field(
        description="The action proposed, or null when the assistant answered in words."
    )
    params: dict[str, Any] = Field(
        description="Arguments the assistant filled in. Nothing has been written."
    )
    message: str = Field(description="Prose, when no action was proposed.")


class InsightResponse(BaseModel):
    """A generated summary of a student's or course's performance."""

    summary: str
    risk_level: str
    trend: str
    factors: list[str]
    suggested_actions: list[str]
    cached: bool = Field(
        description=(
            "True when served from cache. Insights are keyed by a hash of the "
            "statistics, so identical numbers are never regenerated."
        )
    )


class ImportMapRequest(BaseModel):
    """A spreadsheet's header row and a few sample rows."""

    headers: list[str] = Field(min_length=1, examples=[["Matrikelnr", "Kurs", "Punkte"]])
    samples: list[list[str]] = Field(default_factory=list)


class ImportMapResponse(BaseModel):
    """A proposed column mapping."""

    column_mapping: dict[str, str]
    issues: list[str]
    confidence: str


def service(request: Request, conn: DbConn, user: CurrentUser) -> AiService:
    """Build the AI service for this request, once the caller's quota allows it.

    The quota is charged here rather than per route because every route on this
    router reaches a provider, and every one of those is billed. Until this existed
    the only gate was authentication, so any signed-in student could spend without
    limit and the first sign of it was the vendor's invoice.

    Charged against the account, not the address: the bill follows the account, and
    an address is shared by everyone behind one router.

    Args:
        request: The incoming request, which carries the application's quota.
        conn: The request's connection.
        user: The authenticated caller, and the only source of visibility.

    Returns:
        The service.

    Raises:
        QuotaExceededError: If this account has spent its hourly allowance.
    """
    quota: CallQuota = request.app.state.ai_quota
    quota.check(str(user.user_id))
    return AiService(conn, user)


Ai = Annotated[AiService, Depends(service)]


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a question about the gradebook",
    description=(
        "The assistant answers using tools that query the database directly. It "
        "never estimates a figure, and it sees only what you see — a student asking "
        "for everyone's grades receives their own."
    ),
)
def ask(body: AskRequest, ai: Ai) -> AskResponse:
    """Answer a gradebook question.

    Args:
        body: The question, and any earlier turns of the conversation.
        ai: The service.

    Returns:
        The answer and its supporting queries.
    """
    # No transaction wrapper, deliberately. The connection autocommits, and every
    # write these endpoints make is a single independent statement — a usage row,
    # an insight upsert. Wrapping them meant a provider failure rolled back the
    # usage row recording that failure, so the log went blank precisely when a
    # provider started breaking.
    answer = ai.ask(body.question, [(turn.role, turn.content) for turn in body.history])

    return AskResponse(
        text=answer.text,
        records=[ToolRecordResponse(**record) for record in answer.records],
        truncated=answer.truncated,
        model=answer.model,
        reasoning=answer.reasoning,
    )


@router.post(
    "/command",
    response_model=CommandResponse,
    summary="Turn an instruction into a proposed action",
    description=(
        "**Nothing is written.** The assistant fills in a form and the caller "
        "submits it. The write tools are declared to the model but have no "
        "implementation, so there is no path from this endpoint to a change."
    ),
)
def command(body: CommandRequest, ai: Ai) -> CommandResponse:
    """Propose an action from a short instruction.

    Args:
        body: The instruction.
        ai: The service.

    Returns:
        The proposed action, or prose when none matched.
    """
    proposal = ai.command(body.instruction)

    return CommandResponse(action=proposal.action, params=proposal.params, message=proposal.message)


@router.get(
    "/insight/{entity_type}/{entity_id}",
    response_model=InsightResponse,
    summary="Summarise a student's or course's performance",
    description=(
        "Teacher and above. Statistics are computed first and passed to the model, "
        "which never chooses which numbers to fetch — a summary that picks its own "
        "evidence picks the flattering evidence."
    ),
)
def insight(entity_type: str, entity_id: str, _: TeacherUser, ai: Ai) -> InsightResponse:
    """Generate or return a cached insight.

    Args:
        entity_type: ``student`` or ``course``.
        entity_id: Which one.
        _: Enforces the teacher role.
        ai: The service.

    Returns:
        The structured summary.
    """
    payload = ai.insight(entity_type=entity_type, entity_id=entity_id)
    return InsightResponse(**payload)


@router.post(
    "/import-map",
    response_model=ImportMapResponse,
    summary="Propose a column mapping for a spreadsheet",
    description=(
        "Admin and above. Returns a proposal only — the caller reviews it and the "
        "existing import endpoint does the writing."
    ),
)
def import_map(body: ImportMapRequest, _: AdminUser, ai: Ai) -> ImportMapResponse:
    """Propose how spreadsheet columns map onto gradebook fields.

    Args:
        body: Header row and samples.
        _: Enforces the admin role.
        ai: The service.

    Returns:
        The proposed mapping.
    """
    payload = ai.import_map(headers=body.headers, samples=body.samples)
    return ImportMapResponse(**payload)
