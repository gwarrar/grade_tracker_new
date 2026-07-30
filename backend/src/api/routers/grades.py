"""Recording, amending and retiring grades."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from api.deps import CurrentUser, DbConn, TeacherUser
from api.schemas.domain import (
    AuditEntryResponse,
    GradeCreateRequest,
    GradeResponse,
    GradeUpdateRequest,
    PageResponse,
)
from services.grading import GradingService

router = APIRouter(prefix="/grades", tags=["Grades"])


def grading(conn: DbConn, principal: CurrentUser) -> GradingService:
    """Build the grading service for this request.

    Args:
        conn: The request's connection.
        principal: The authenticated caller.

    Returns:
        The service.
    """
    return GradingService(conn, principal)


Grading = Annotated[GradingService, Depends(grading)]


@router.get(
    "",
    response_model=PageResponse[GradeResponse],
    summary="List grades",
    description=(
        "Paginated, sortable and searchable, filtered to what your role permits.\n\n"
        "A grade is visible only when **both** its student and its course are. That "
        "is why a teacher cannot read a shared student's marks from a colleague's "
        "course, even though the student is otherwise in their scope."
    ),
)
def list_grades(
    service: Grading,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 25,
    sort: Annotated[
        str | None,
        Query(
            description="`date`, `score`, `percentage`, `student`, `course`, `title` or "
            "`created`; `-` reverses."
        ),
    ] = None,
    q: Annotated[str | None, Query(description="Free text over student, course and title.")] = None,
    student_id: Annotated[str | None, Query(description="Only this student's grades.")] = None,
    course_id: Annotated[str | None, Query(description="Only this course's grades.")] = None,
    date_from: Annotated[
        str | None, Query(description="Earliest date, ISO `YYYY-MM-DD`, inclusive.")
    ] = None,
    date_to: Annotated[
        str | None, Query(description="Latest date, ISO `YYYY-MM-DD`, inclusive.")
    ] = None,
    letter: Annotated[
        str | None,
        Query(
            description="A band from the organisation's grading scale, e.g. `B`. The "
            "bands are configurable — read them from `/org/branding`."
        ),
    ] = None,
    title: Annotated[str | None, Query(description="Substring of the assessment name.")] = None,
) -> PageResponse[GradeResponse]:
    """List grades within the caller's scope."""
    result = service.list_grades(
        page=page,
        size=size,
        sort=sort,
        search=q,
        student_id=student_id,
        course_id=course_id,
        date_from=date_from,
        date_to=date_to,
        letter=letter,
        title=title,
    )
    return PageResponse[GradeResponse](
        items=[GradeResponse(**item) for item in result.items],
        total=result.total,
        page=result.page,
        size=result.size,
        pages=result.pages,
    )


@router.post(
    "",
    response_model=GradeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a grade",
    description=(
        "The date accepts ISO `YYYY-MM-DD` as well as `DD-MM-YYYY`, `DD.MM.YYYY` and "
        "`DD/MM/YYYY`, and is normalised to ISO on the way in.\n\n"
        "Use `title` and `weight` for several assessments in one course — a midterm "
        "and a final with different weights."
    ),
    responses={
        403: {"description": "`FORBIDDEN` — you cannot grade this course."},
        404: {"description": "`STUDENT_NOT_FOUND` or `COURSE_NOT_FOUND`."},
        422: {"description": "`VALIDATION_ERROR` — score out of range, or an unparseable date."},
    },
)
def record_grade(payload: GradeCreateRequest, service: Grading, _: TeacherUser) -> GradeResponse:
    """Record a grade."""
    return GradeResponse(**service.record(**payload.model_dump()))


@router.get(
    "/{grade_id}",
    response_model=GradeResponse,
    summary="Fetch one grade",
    responses={404: {"description": "`GRADE_NOT_FOUND` — unknown, or outside your scope."}},
)
def get_grade(grade_id: int, service: Grading) -> GradeResponse:
    """Fetch one grade."""
    return GradeResponse(**service.get_grade(grade_id))


@router.patch(
    "/{grade_id}",
    response_model=GradeResponse,
    summary="Amend a grade",
    description="The previous values are written to the audit trail.",
    responses={
        403: {"description": "`FORBIDDEN` — you cannot grade this course."},
        404: {"description": "`GRADE_NOT_FOUND`."},
    },
)
def amend_grade(
    grade_id: int, payload: GradeUpdateRequest, service: Grading, _: TeacherUser
) -> GradeResponse:
    """Amend a grade."""
    return GradeResponse(**service.amend(grade_id, payload.model_dump(exclude_unset=True)))


@router.delete(
    "/{grade_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire a grade",
    description=(
        "Soft delete. The row is retained and excluded from reads, because an altered "
        "mark is exactly the kind of change a student may later dispute."
    ),
    responses={404: {"description": "`GRADE_NOT_FOUND`."}},
)
def retire_grade(grade_id: int, service: Grading, _: TeacherUser) -> None:
    """Retire a grade."""
    service.retire(grade_id)


@router.get(
    "/{grade_id}/history",
    response_model=list[AuditEntryResponse],
    summary="A grade's change history",
    description=(
        "Who changed this mark, when, and from what. Scope is checked first, so the "
        "trail cannot be used to read a grade indirectly."
    ),
    responses={404: {"description": "`GRADE_NOT_FOUND`."}},
)
def grade_history(grade_id: int, service: Grading) -> list[AuditEntryResponse]:
    """Return a grade's change history."""
    return [AuditEntryResponse(**entry) for entry in service.history(grade_id)]
