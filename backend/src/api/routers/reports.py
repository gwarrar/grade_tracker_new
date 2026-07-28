"""Reports, analytics and organisation branding.

Report endpoints return **structured data**, never prose — the frontend renders the
wording in the reader's language. `/export.csv` is the single exception: a downloaded
file has no frontend, so its column headers are translated here from `?locale=`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from api.deps import CurrentUser, DbConn, TeacherUser
from api.schemas.domain import DashboardResponse, RankedStudentResponse
from notenverwaltung.models import SUPPORTED_LOCALES
from services.reporting import ReportingService, load_organization

reports_router = APIRouter(prefix="/reports", tags=["Reports"])
analytics_router = APIRouter(prefix="/analytics", tags=["Analytics"])
org_router = APIRouter(prefix="/org", tags=["Organisation"])

# Only what a CSV needs. The application's own translations live in the frontend;
# duplicating them here would be the message catalogue this design avoids.
CSV_LABELS: dict[str, dict[str, str]] = {
    "en": {},  # the generator's defaults are already English
    "de": {"pass": "BESTANDEN", "fail": "NICHT BESTANDEN"},
    "fr": {"pass": "ADMIS", "fail": "NON ADMIS"},
}
"""Cell values that are words, not data. Headers alone were not enough: a German
file with an English "FAIL" in every failing row is neither language."""

CSV_HEADERS: dict[str, dict[str, str]] = {
    "en": {},  # the generator's defaults are already English
    "de": {
        "student_id": "Matrikelnummer",
        "student_name": "Studierende:r",
        "course_id": "Kurs-ID",
        "course_name": "Kurs",
        "title": "Leistung",
        "score": "Punkte",
        "max_grade": "Maximum",
        "percentage": "Prozent",
        "letter": "Note",
        "weight": "Gewichtung",
        "status": "Status",
        "date": "Datum",
        "notes": "Anmerkungen",
        "metric": "Kennzahl",
        "value": "Wert",
        "rank": "Rang",
        "average": "Durchschnitt",
    },
    "fr": {
        "student_id": "N° étudiant",
        "student_name": "Étudiant",
        "course_id": "Code cours",
        "course_name": "Cours",
        "title": "Évaluation",
        "score": "Note",
        "max_grade": "Maximum",
        "percentage": "Pourcentage",
        "letter": "Mention",
        "weight": "Coefficient",
        "status": "Statut",
        "date": "Date",
        "notes": "Remarques",
        "metric": "Indicateur",
        "value": "Valeur",
        "rank": "Rang",
        "average": "Moyenne",
    },
}

# German and French Windows Excel splits on ';'. A comma-separated file opens as a
# single column there, which reads to the user as corruption rather than a setting.
CSV_DELIMITERS = {"en": ",", "de": ";", "fr": ";"}


def reporting(conn: DbConn, principal: CurrentUser) -> ReportingService:
    """Build the reporting service for this request.

    Args:
        conn: The request's connection.
        principal: The authenticated caller.

    Returns:
        The service.
    """
    return ReportingService(conn, principal)


# ── Report schemas ───────────────────────────────────────────────────────────
#
# These exist because the project's own standard is `response_model=` on every
# route, never a bare dict. Without them the generated TypeScript types for the
# reports are `Record<string, unknown>` — the frontend loses exactly the safety
# the committed-spec pipeline was built to give it, on the one payload it does
# the most rendering from.


class GradeLine(BaseModel):
    """One graded item as it appears in a report."""

    grade_id: int
    course_id: str
    course_name: str
    student_id: str
    student_name: str
    title: str
    score: float
    max_grade: float
    percentage: float
    letter: str = Field(description="Band from the organisation's grading scale.")
    weight: float
    is_passing: bool
    date: str
    notes: str


class RankedLine(BaseModel):
    """A student and their average, for the leaderboards.

    The domain layer carries these as ``(student_id, name, average)`` triples,
    which is documented and tested there. Converting at this boundary keeps the
    core as specified while giving the wire contract named fields — a consumer
    should not have to remember that position 2 is the average.
    """

    student_id: str
    name: str
    average_percentage: float


class StudentReportResponse(BaseModel):
    """A student's full record."""

    student_id: str
    student_name: str
    email: str
    grades: list[GradeLine]
    average_percentage: float | None
    passed_count: int
    failed_count: int
    courses_graded: int


class CourseReportResponse(BaseModel):
    """A course's results."""

    course_id: str
    course_name: str
    max_grade: float
    passing_grade: float
    grades: list[GradeLine]
    average_score: float | None
    pass_rate: float | None
    graded_student_count: int
    distribution: dict[str, int]


class SummaryReportResponse(BaseModel):
    """Institution-wide totals."""

    student_count: int
    course_count: int
    grade_count: int
    overall_average_percentage: float | None
    distribution: dict[str, int]
    top_students: list[RankedLine]
    at_risk_students: list[RankedLine]
    at_risk_threshold: float


def _ranked(triples: list[tuple[str, str, float]]) -> list[RankedLine]:
    """Convert the domain's ``(id, name, average)`` triples into named fields."""
    return [
        RankedLine(student_id=student_id, name=name, average_percentage=average)
        for student_id, name, average in triples
    ]


Reporting = Annotated[ReportingService, Depends(reporting)]
LocaleQuery = Annotated[str, Query(description="Language for CSV column headers.", examples=["de"])]


@reports_router.get(
    "/student/{student_id}",
    response_model=StudentReportResponse,
    summary="A student's report",
    description=(
        "Numbers and identifiers only — no sentences. The client renders the wording.\n\n"
        "A student's own report is complete. A teacher's copy contains only the grades "
        "from courses they own, so the report cannot expose marks a scoped list "
        "endpoint would have hidden."
    ),
    responses={404: {"description": "`STUDENT_NOT_FOUND` — unknown, or outside your scope."}},
)
def student_report(student_id: str, service: Reporting) -> StudentReportResponse:
    """Build a student's report.

    Args:
        student_id: Which student.
        service: The reporting service.

    Returns:
        The student's grades and totals.
    """
    return StudentReportResponse(**service.student_report(student_id))


@reports_router.get(
    "/course/{course_id}",
    response_model=CourseReportResponse,
    summary="A course's report",
    description="A student requesting this sees the class statistics but only their own marks.",
    responses={404: {"description": "`COURSE_NOT_FOUND`."}},
)
def course_report(course_id: str, service: Reporting) -> CourseReportResponse:
    """Build a course's report.

    Args:
        course_id: Which course.
        service: The reporting service.

    Returns:
        The course's grades and statistics.
    """
    return CourseReportResponse(**service.course_report(course_id))


@reports_router.get(
    "/summary",
    response_model=SummaryReportResponse,
    summary="Institution-wide summary",
    description=(
        "Totals, distribution, top students and at-risk students. Staff only: a "
        "summary over every student cannot be meaningfully scoped to one of them."
    ),
)
def summary_report(
    service: Reporting,
    _: TeacherUser,
    at_risk_threshold: Annotated[
        float, Query(ge=0, le=100, description="Percentage below which a student is at risk.")
    ] = 60.0,
) -> SummaryReportResponse:
    """Build the institution-wide summary.

    Args:
        service: The reporting service.
        _: Enforces the teacher role.
        at_risk_threshold: Percentage below which a student counts as at risk.

    Returns:
        Totals, distribution and both leaderboards.
    """
    payload = service.summary_report(at_risk_threshold)
    return SummaryReportResponse(
        **{k: v for k, v in payload.items() if k not in {"top_students", "at_risk_students"}},
        top_students=_ranked(payload["top_students"]),
        at_risk_students=_ranked(payload["at_risk_students"]),
    )


@reports_router.get(
    "/{kind}/{entity_id}/export.csv",
    response_class=PlainTextResponse,
    summary="Download a report as CSV",
    description=(
        "The one endpoint that returns translated prose, because a downloaded file "
        "has no frontend to render it. `?locale=de` or `fr` also switches the "
        "delimiter to `;`, which is what Excel expects in those locales — a "
        "comma-separated file opens there as a single column.\n\n"
        "Use `summary` as both `kind` and `entity_id` for the institution-wide report."
    ),
    responses={
        200: {"content": {"text/csv": {}}, "description": "The CSV file."},
        404: {"description": "`STUDENT_NOT_FOUND` or `COURSE_NOT_FOUND`."},
    },
)
def export_csv(
    kind: str, entity_id: str, service: Reporting, locale: LocaleQuery = "en"
) -> PlainTextResponse:
    """Render a report as a downloadable CSV file."""
    key = locale if locale in SUPPORTED_LOCALES else "en"
    body = service.export_csv(
        kind, entity_id, CSV_HEADERS[key], CSV_DELIMITERS[key], CSV_LABELS[key]
    )
    filename = f"{kind}-{entity_id}.csv"
    return PlainTextResponse(
        # A BOM, because Excel otherwise reads UTF-8 as the local ANSI codepage and
        # renders every accented name as mojibake.
        content="﻿" + body,
        media_type="text/csv; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


@analytics_router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Headline numbers",
    description=(
        "Scoped: a teacher's dashboard describes their own courses, a student's "
        "describes their own record."
    ),
)
def dashboard(service: Reporting) -> DashboardResponse:
    """Return the caller's dashboard figures."""
    return DashboardResponse(**service.dashboard())


@analytics_router.get(
    "/top-students",
    response_model=list[RankedStudentResponse],
    summary="Highest-averaging students",
    description="Students with no grades are excluded rather than ranked as zero.",
)
def top_students(
    service: Reporting,
    _: TeacherUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 5,
) -> list[RankedStudentResponse]:
    """Rank the highest-averaging students in scope."""
    return [RankedStudentResponse(**row) for row in service.top_students(limit)]


@analytics_router.get(
    "/at-risk",
    response_model=list[RankedStudentResponse],
    summary="Students below a threshold",
    description=(
        "Worst first, since that is the order an intervention list is read in. "
        "Ungraded students are excluded: no data is not the same as poor performance."
    ),
)
def at_risk(
    service: Reporting,
    _: TeacherUser,
    threshold: Annotated[float, Query(ge=0, le=100)] = 60.0,
) -> list[RankedStudentResponse]:
    """List at-risk students in scope."""
    return [RankedStudentResponse(**row) for row in service.at_risk_students(threshold)]


@org_router.get(
    "/branding",
    summary="Organisation branding and configuration",
    description=(
        "**Public** — the sign-in page needs the logo and colours before anyone has "
        "signed in.\n\n"
        "Colours carry a `light` and a `dark` variant. The client injects them as CSS "
        "custom properties, so re-theming needs no rebuild; two variants because a "
        "colour legible on white is frequently illegible on near-black.\n\n"
        "Also carries the enabled locales, the default theme, and the grading scale — "
        "the A/B/C/D/F bands are configuration, not code."
    ),
)
def branding(conn: DbConn) -> dict[str, Any]:
    """Return the organisation's public configuration."""
    return load_organization(conn).to_dict()
