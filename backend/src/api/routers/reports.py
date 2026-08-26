"""Reports and analytics.

Report endpoints return **structured data**, never prose — the frontend renders the
wording in the reader's language. `/export.csv` is the single exception: a downloaded
file has no frontend, so its column headers come from `api.csv_localization`.

The response models live in `api.schemas.reports`, which is what leaves this file
readable as the list of endpoints it serves.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from api.csv_localization import CSV_DELIMITERS, CSV_HEADERS, CSV_LABELS
from api.deps import CurrentUser, DbConn, TeacherUser
from api.schemas.domain import DashboardResponse, RankedStudentResponse
from api.schemas.reports import (
    CourseAssessmentsResponse,
    CourseReportResponse,
    DistributionReportResponse,
    EnrollmentReportResponse,
    RankedLine,
    StudentReportResponse,
    SummaryReportResponse,
    TeacherReportResponse,
    TermReportResponse,
)
from notenverwaltung.grading_scale import AT_RISK_THRESHOLD
from notenverwaltung.models import SUPPORTED_LOCALES
from services.reporting import ReportingService

reports_router = APIRouter(prefix="/reports", tags=["Reports"])
analytics_router = APIRouter(prefix="/analytics", tags=["Analytics"])

# Only what a CSV needs. The application's own translations live in the frontend;
# duplicating them here would be the message catalogue this design avoids.


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
    ] = AT_RISK_THRESHOLD,
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


BucketQuery = Annotated[
    Literal["month", "term"],
    Query(description="How to group the distribution: by ISO month or by course term."),
]


@reports_router.get(
    "/teacher/{user_id}",
    response_model=TeacherReportResponse,
    summary="A teacher's rollup",
    description=(
        "The teacher themselves, or any administrator. A teacher asking for a "
        "colleague's rollup is refused with `FORBIDDEN`. Courses outside the "
        "caller's scope never appear, so an administrator's view is the only one "
        "that spans the institution."
    ),
    responses={
        403: {"description": "`FORBIDDEN` — below staff, or another teacher's rollup."},
        404: {"description": "`USER_NOT_FOUND` — no account carries that id."},
    },
)
def teacher_report(user_id: int, _: TeacherUser, service: Reporting) -> TeacherReportResponse:
    """Build a teacher's rollup.

    Args:
        user_id: Whose rollup.
        _: Enforces the teacher role.
        service: The reporting service.

    Returns:
        The teacher's totals and course breakdown.
    """
    return TeacherReportResponse(**service.teacher_report(user_id))


@reports_router.get(
    "/term/{term}",
    response_model=TermReportResponse,
    summary="A term's courses",
    description=(
        "Scopeable where the institution-wide summary is not: a teacher gets their "
        "own courses in that term, an administrator the whole institution's. "
        "Students are refused, because any one student's copy would still contain "
        "their classmates' averages."
    ),
    responses={403: {"description": "`FORBIDDEN` — below staff."}},
)
def term_report(term: str, _: TeacherUser, service: Reporting) -> TermReportResponse:
    """Build a course breakdown for one term.

    Args:
        term: The academic term label.
        _: Enforces the teacher role.
        service: The reporting service.

    Returns:
        The term's courses and totals.
    """
    return TermReportResponse(**service.term_report(term))


@reports_router.get(
    "/course/{course_id}/assessments",
    response_model=CourseAssessmentsResponse,
    summary="A course's assessments",
    description=(
        "Grades grouped by assessment title, each with its own average, spread, "
        'pass rate and band distribution. Answers "was the midterm too hard" — '
        "the one question a teacher opens a gradebook to find out. Class statistics "
        "span every student, so a student is refused."
    ),
    responses={
        403: {"description": "`FORBIDDEN` — a student, or the course is outside your scope."},
        404: {"description": "`COURSE_NOT_FOUND`."},
    },
)
def course_assessments(
    course_id: str, _: TeacherUser, service: Reporting
) -> CourseAssessmentsResponse:
    """Build the assessment analysis for one course.

    Args:
        course_id: Which course.
        _: Enforces the teacher role.
        service: The reporting service.

    Returns:
        One row per assessment title.
    """
    return CourseAssessmentsResponse(**service.course_assessments_report(course_id))


@reports_router.get(
    "/enrollment",
    response_model=EnrollmentReportResponse,
    summary="Enrolment capacity and utilisation",
    description=(
        "Per course: capacity, active, withdrawn and completed enrolments, and "
        "utilisation as a percentage of capacity. Finds both over-subscribed and "
        "dead courses. Students are refused — the report spans every student."
    ),
    responses={403: {"description": "`FORBIDDEN` — below staff."}},
)
def enrollment_report(service: Reporting, _: TeacherUser) -> EnrollmentReportResponse:
    """Build the enrolment report.

    Args:
        service: The reporting service.
        _: Enforces the teacher role.

    Returns:
        One row per visible course.
    """
    return EnrollmentReportResponse(**service.enrollment_report())


@reports_router.get(
    "/distribution",
    response_model=DistributionReportResponse,
    summary="Grade distribution over time",
    description=(
        "Grades bucketed by ISO month of the award date (`bucket=month`) or by "
        "the course's term (`bucket=term`), each bucket carrying the band "
        "distribution. One payload drives a stacked area chart and the "
        "at-risk-trend question. Students are refused — the report spans every "
        "student."
    ),
    responses={403: {"description": "`FORBIDDEN` — below staff."}},
)
def distribution_report(
    service: Reporting, _: TeacherUser, bucket: BucketQuery = "month"
) -> DistributionReportResponse:
    """Build the time distribution.

    Args:
        service: The reporting service.
        _: Enforces the teacher role.
        bucket: How to group the buckets.

    Returns:
        The ordered buckets and their distributions.
    """
    return DistributionReportResponse(**service.distribution_report(bucket))


@reports_router.get(
    "/{kind}/{entity_id}/export.csv",
    response_class=PlainTextResponse,
    summary="Download a report as CSV",
    description=(
        "The one endpoint that returns translated prose, because a downloaded file "
        "has no frontend to render it. `?locale=de` or `fr` also switches the "
        "delimiter to `;`, which is what Excel expects in those locales — a "
        "comma-separated file opens there as a single column.\n\n"
        "Use `summary` as both `kind` and `entity_id` for the institution-wide "
        "report, and the same convention for `enrollment` and `distribution`. "
        "Assessments export with the course id as the entity, e.g. "
        "`/reports/assessments/CS101/export.csv`."
    ),
    responses={
        200: {"content": {"text/csv": {}}, "description": "The CSV file."},
        404: {"description": "`STUDENT_NOT_FOUND` or `COURSE_NOT_FOUND`."},
    },
)
def export_csv(
    kind: str,
    entity_id: str,
    service: Reporting,
    locale: LocaleQuery = "en",
    bucket: BucketQuery = "month",
) -> PlainTextResponse:
    """Render a report as a downloadable CSV file."""
    key = locale if locale in SUPPORTED_LOCALES else "en"
    body = service.export_csv(
        kind, entity_id, CSV_HEADERS[key], CSV_DELIMITERS[key], CSV_LABELS[key], bucket
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
    threshold: Annotated[float, Query(ge=0, le=100)] = AT_RISK_THRESHOLD,
) -> list[RankedStudentResponse]:
    """List at-risk students in scope."""
    return [RankedStudentResponse(**row) for row in service.at_risk_students(threshold)]
