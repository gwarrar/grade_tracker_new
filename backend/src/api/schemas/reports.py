"""Response models for the report and analytics endpoints.

Here rather than in the router for the reason every other schema is here: the router
should read as the list of endpoints it serves. `reports.py` was 674 lines of which
about 145 were endpoints -- 196 were these models and 85 were the CSV translation
tables, and the file already imported two models from this package while defining
sixteen more inline.

Report payloads are **structured data, never prose**. The frontend renders the
wording in the reader's language; see `docs/DECISIONS.md` §5.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class CourseResult(BaseModel):
    """One student's standing in one course."""

    course_id: str
    course_name: str
    credits: float = Field(description="What the course is worth, and its weight in the GPA.")
    grade_count: int
    average_percentage: float
    letter: str = Field(description="Band the course average falls in.")
    points: float | None = Field(
        description="What that band is worth, or null when the grading scale prices no points."
    )


class StudentReportResponse(BaseModel):
    """A student's full record."""

    student_id: str
    student_name: str
    email: str
    grades: list[GradeLine]
    courses: list[CourseResult] = Field(
        description="One standing per course, the basis of the GPA."
    )
    average_percentage: float | None
    gpa: float | None = Field(
        description=(
            "Credit-weighted grade point average, or null when the grading scale "
            "prices no bands. Not the same thing as `average_percentage`: that "
            "weights each mark by its own weight, this weights each course by its "
            "credits, so a six-credit course counts six times a one-credit one."
        )
    )
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


class CourseRollup(BaseModel):
    """One course in a teacher's or a term's breakdown."""

    course_id: str
    course_name: str
    term: str | None = None
    student_count: int
    grade_count: int
    average_percentage: float | None = None
    pass_rate: float | None = None


class TeacherReportResponse(BaseModel):
    """A teacher's courses and their totals."""

    user_id: int
    teacher_name: str | None
    course_count: int
    student_count: int
    grade_count: int
    average_percentage: float | None = None
    courses: list[CourseRollup]


class TermCourseRow(CourseRollup):
    """A course in a term, with its owning teacher for the administrator's view."""

    teacher_name: str | None = None


class TermReportResponse(BaseModel):
    """The courses running in one academic term."""

    term: str
    course_count: int
    student_count: int
    grade_count: int
    average_percentage: float | None = None
    pass_rate: float | None = None
    courses: list[TermCourseRow]


class AssessmentRow(BaseModel):
    """One assessment title within a course."""

    title: str
    count: int
    average_score: float
    average_percentage: float
    min_score: float
    max_score: float
    pass_rate: float
    distribution: dict[str, int] = Field(
        description="Band label to count for this assessment, including zeros."
    )


class CourseAssessmentsResponse(BaseModel):
    """A course's grades grouped by assessment title."""

    course_id: str
    course_name: str
    max_grade: float
    passing_grade: float
    assessments: list[AssessmentRow]


class EnrollmentRow(BaseModel):
    """One course's enrolment position."""

    course_id: str
    course_name: str
    capacity: int
    active: int
    withdrawn: int
    completed: int
    utilisation: float = Field(description="Active enrolments as a percentage of capacity.")


class EnrollmentReportResponse(BaseModel):
    """Capacity, take-up and dropout per course."""

    course_count: int
    rows: list[EnrollmentRow]


class DistributionBucket(BaseModel):
    """The band distribution within one time bucket."""

    bucket: str = Field(description="`YYYY-MM` for `month`, the course term for `term`.")
    distribution: dict[str, int]


class DistributionReportResponse(BaseModel):
    """The grade distribution over time, one bucket per row."""

    bucket: Literal["month", "term"]
    buckets: list[DistributionBucket]
