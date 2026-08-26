"""Reading the audit trail.

Writing happens inside each use case, in the same transaction as the change itself
(``services.audit.record``). Reading is here, and only here: the whole trail is
admin-only, with one grade-scoped exception that lives with the grades.

The table itself is append-only — the database rejects any attempt to alter or
remove an entry (see migration 007) — so what this router returns is what happened.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from api.deps import AdminUser, DbConn
from api.schemas.domain import (
    PAGE_SIZE,
    AuditEntryResponse,
    AuditFeedEntryResponse,
    PageResponse,
    SizeQuery,
)
from services import audit

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get(
    "",
    response_model=PageResponse[AuditFeedEntryResponse],
    summary="Activity feed",
    description=(
        "Every recorded change across the institution, most recent first, filtered "
        "and paginated. The trail is append-only: entries can neither be altered "
        "nor removed, so this feed is a record of what happened, not of what "
        "someone remembers."
    ),
    responses={403: {"description": "`FORBIDDEN` — administrators and above only."}},
)
def audit_feed(
    conn: DbConn,
    _: AdminUser,
    actor_user_id: Annotated[
        int | None, Query(description="Only changes made by this account.")
    ] = None,
    entity: Annotated[
        str | None, Query(description="Only this kind of thing, e.g. `grade`.")
    ] = None,
    action: Annotated[str | None, Query(description="`create`, `update` or `delete`.")] = None,
    date_from: Annotated[
        str | None, Query(description="Earliest day, ISO `YYYY-MM-DD`, inclusive.")
    ] = None,
    date_to: Annotated[
        str | None, Query(description="Latest day, ISO `YYYY-MM-DD`, inclusive.")
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: SizeQuery = PAGE_SIZE,
) -> PageResponse[AuditFeedEntryResponse]:
    """Return one page of the activity feed."""
    result = audit.feed(
        conn,
        actor_user_id=actor_user_id,
        entity=entity,
        action=action,
        date_from=date_from,
        date_to=date_to,
        page=page,
        size=size,
    )
    return PageResponse[AuditFeedEntryResponse](
        items=[AuditFeedEntryResponse(**item) for item in result.items],
        total=result.total,
        page=result.page,
        size=result.size,
        pages=result.pages,
    )


# Two doors to the same trail, deliberately. /grades/{grade_id}/history stays where
# it is because it is scoped to that grade, so the teacher who owns the course can
# answer "who changed this mark"; the door below is admin-only and covers every
# entity. Do not deduplicate them — merging the two would either lock the teacher
# out or let a teacher read the institution's trail.
@router.get(
    "/{entity}/{entity_id}",
    response_model=list[AuditEntryResponse],
    summary="One entity's change history",
    description=(
        "The full trail for one entity, most recent first. Unlike the grade-scoped "
        "history endpoint, this one is admin-only and answers for any entity kind."
    ),
    responses={403: {"description": "`FORBIDDEN` — administrators and above only."}},
)
def entity_history(
    entity: str, entity_id: str, conn: DbConn, _: AdminUser
) -> list[AuditEntryResponse]:
    """Return one entity's change history."""
    return [AuditEntryResponse(**entry) for entry in audit.history(conn, entity, entity_id)]
