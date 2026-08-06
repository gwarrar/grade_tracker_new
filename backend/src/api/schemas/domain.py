"""Request and response models for students, courses, enrolments and grades.

Every field carries a description and an example, because those become the OpenAPI
documentation and the generated TypeScript types. A `dict` return would produce an
endpoint documented as "object".
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

PageParam = Annotated[int, Field(ge=1, description="1-based page number.", examples=[1])]
SizeParam = Annotated[
    int, Field(ge=1, le=200, description="Rows per page, capped at 200.", examples=[25])
]


class PageResponse[T](BaseModel):
    """One page of results.

    Every list endpoint returns this envelope, so a client writes one pagination
    component rather than one per resource.
    """

    items: list[T] = Field(description="The rows on this page.")
    total: int = Field(description="Rows matching the query overall, ignoring paging.")
    page: int = Field(description="The 1-based page number returned.")
    size: int = Field(description="Rows per page.")
    pages: int = Field(description="Total number of pages.")


# ── Students ─────────────────────────────────────────────────────────────────
class StudentResponse(BaseModel):
    """A student, with the counts a list view needs."""

    student_id: str = Field(description="Institution-assigned identifier.", examples=["S001"])
    first_name: str = Field(description="Given name.", examples=["Anna"])
    last_name: str = Field(description="Family name.", examples=["Schmidt"])
    email: str = Field(description="Contact address.", examples=["anna@example.com"])
    user_id: int | None = Field(
        default=None,
        description="Linked login account, or null. Not every student signs in.",
    )
    is_active: bool = Field(default=True, description="Whether the student may be enrolled.")
    phone: str | None = Field(default=None, description="Contact telephone number.")
    date_of_birth: date | None = Field(default=None, description="ISO calendar date.")
    cohort: str | None = Field(default=None, description="Institution-defined cohort label.")
    enrolled_count: int = Field(default=0, description="Active enrolments.")
    grade_count: int = Field(default=0, description="Grades recorded.")
    created_at: str | None = Field(default=None, description="ISO-8601 UTC.")
    updated_at: str | None = Field(default=None, description="ISO-8601 UTC.")


class StudentCreateRequest(BaseModel):
    """A new student."""

    student_id: str = Field(min_length=1, max_length=32, examples=["S041"])
    first_name: str = Field(min_length=1, max_length=100, examples=["Nadia"])
    last_name: str = Field(min_length=1, max_length=100, examples=["Haddad"])
    email: str = Field(min_length=3, max_length=255, examples=["nadia@example.com"])
    is_active: bool = Field(default=True)
    phone: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = Field(default=None)
    cohort: str | None = Field(default=None, max_length=100)


class StudentUpdateRequest(BaseModel):
    """Changes to a student. Omitted fields are left alone."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    is_active: bool = Field(default=True)
    phone: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = Field(default=None)
    cohort: str | None = Field(default=None, max_length=100)
    user_id: int | None = Field(
        default=None,
        description=(
            "The sign-in account to attach to this record. Until one is linked, a "
            "student who signs in matches no rows and sees an empty application, "
            "because `student_scope` has nothing to scope them to. Send `null` to "
            "detach."
        ),
        examples=[7],
    )


# ── Courses ──────────────────────────────────────────────────────────────────
class CourseResponse(BaseModel):
    """A course, with enrolment counts."""

    course_id: str = Field(description="Institution-assigned code.", examples=["CS101"])
    name: str = Field(description="Display title.", examples=["Intro to Programming"])
    max_grade: float = Field(description="Highest achievable score.", examples=[100.0])
    passing_grade: float = Field(description="Lowest passing score.", examples=[60.0])
    max_students: int = Field(description="Enrolment capacity.", examples=[30])
    teacher_id: int | None = Field(default=None, description="Owning teacher's user id.")
    teacher_name: str | None = Field(default=None, description="Owning teacher's name.")
    term: str | None = Field(default=None, description="Academic term.", examples=["2026-SS"])
    credits: float = Field(description="Weight in a GPA calculation.", examples=[5.0])
    description: str | None = Field(default=None, description="Course description.")
    room: str | None = Field(default=None, description="Teaching room.")
    schedule: str | None = Field(default=None, description="Human-readable meeting schedule.")
    department: str | None = Field(default=None, description="Owning department.")
    start_date: date | None = Field(default=None, description="ISO calendar date.")
    end_date: date | None = Field(default=None, description="ISO calendar date.")
    status: Literal["active", "archived"] = Field(default="active", description="Directory status.")
    prerequisite_ids: list[str] = Field(
        default_factory=list, description="Course identifiers required beforehand."
    )
    enrolled_count: int = Field(
        default=0,
        description=(
            "Students actively enrolled. Distinct from `graded_count`: a student can "
            "be enrolled without having been assessed yet."
        ),
    )
    graded_count: int = Field(default=0, description="Distinct students holding a grade.")
    created_at: str | None = Field(default=None, description="ISO-8601 UTC.")
    updated_at: str | None = Field(default=None, description="ISO-8601 UTC.")


class CourseCreateRequest(BaseModel):
    """A new course."""

    course_id: str = Field(min_length=1, max_length=32, examples=["CS301"])
    name: str = Field(min_length=1, max_length=200, examples=["Compilers"])
    max_grade: float = Field(default=100.0, gt=0)
    passing_grade: float = Field(default=60.0, gt=0)
    max_students: int = Field(default=30, gt=0)
    teacher_id: int | None = Field(
        default=None,
        description=(
            "Owning teacher. A teacher creating a course owns it by default; only an "
            "administrator may set this to somebody else."
        ),
    )
    term: str | None = Field(default=None, max_length=32)
    credits: float = Field(default=1.0, gt=0)
    description: str | None = Field(default=None, max_length=2000)
    room: str | None = Field(default=None, max_length=100)
    schedule: str | None = Field(default=None, max_length=500)
    department: str | None = Field(default=None, max_length=200)
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)
    status: Literal["active", "archived"] = Field(default="active")
    prerequisite_ids: list[str] = Field(default_factory=list)


class CourseUpdateRequest(BaseModel):
    """Changes to a course. Omitted fields are left alone."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    max_grade: float | None = Field(default=None, gt=0)
    passing_grade: float | None = Field(default=None, gt=0)
    max_students: int | None = Field(default=None, gt=0)
    teacher_id: int | None = Field(
        default=None,
        description="Administrators only — reassigning a course changes who can see it.",
    )
    term: str | None = Field(default=None, max_length=32)
    credits: float | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=2000)
    room: str | None = Field(default=None, max_length=100)
    schedule: str | None = Field(default=None, max_length=500)
    department: str | None = Field(default=None, max_length=200)
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)
    status: Literal["active", "archived"] = Field(default="active")
    prerequisite_ids: list[str] = Field(default_factory=list)


# ── Enrolments ───────────────────────────────────────────────────────────────
class EnrollmentResponse(BaseModel):
    """A student's registration on a course."""

    student_id: str = Field(description="The enrolled student.")
    course_id: str = Field(description="The course.")
    status: str = Field(description="`active`, `withdrawn` or `completed`.")
    enrolled_at: str | None = Field(default=None, description="ISO-8601 UTC.")
    enrolled_by: int | None = Field(default=None, description="Who registered them.")
    first_name: str | None = Field(default=None, description="Student's given name.")
    last_name: str | None = Field(default=None, description="Student's family name.")
    email: str | None = Field(default=None, description="Student's contact address.")
    grade_count: int = Field(
        default=0, description="Grades in this course. Zero means enrolled but not yet assessed."
    )


class EnrollRequest(BaseModel):
    """A registration."""

    student_id: str = Field(min_length=1, examples=["S001"])


class EnrollmentStatusRequest(BaseModel):
    """A change of enrolment status."""

    status: str = Field(
        description=(
            "`active`, `withdrawn` or `completed`. Withdrawal is a status change "
            "rather than a deletion, so grades earned beforehand stay attached."
        ),
        examples=["withdrawn"],
    )


class StudentCourseResponse(BaseModel):
    """A course as it appears on a student's record."""

    course_id: str
    name: str
    term: str | None = None
    credits: float
    max_grade: float
    passing_grade: float
    status: str = Field(description="Enrolment status.")
    enrolled_at: str | None = None


# ── Notes ────────────────────────────────────────────────────────────────────
NoteVisibility = Literal["private", "staff", "shared", "course"]


class NoteResponse(BaseModel):
    """A note attached to a student record or a course.

    There is deliberately no edit endpoint: a wrong note is deleted and reposted,
    and the audit entry the delete writes is the tombstone.
    """

    id: int = Field(description="Database identifier.")
    entity: Literal["student", "course"] = Field(description="What the note is attached to.")
    entity_id: str = Field(description="The student or course id.")
    body: str = Field(description="The note text.")
    visibility: NoteVisibility = Field(description="Who may read the note.")
    author_id: int | None = Field(
        default=None, description="Who wrote it, or null once the account is deleted."
    )
    author_name: str = Field(
        description="The author's name, copied at write time so it survives the account."
    )
    created_at: str = Field(description="ISO-8601 UTC.")


class NoteCreateRequest(BaseModel):
    """A new note."""

    body: str = Field(min_length=1, max_length=2000)
    visibility: NoteVisibility | None = Field(
        default=None,
        description="Defaults to `staff` on a student record and `course` on a course.",
    )


# ── Grades ───────────────────────────────────────────────────────────────────
class GradeResponse(BaseModel):
    """A recorded grade.

    `percentage`, `letter` and `is_passing` are computed server-side deliberately: two
    clients deriving them independently is two chances to disagree with the report the
    same numbers appear in. `letter` in particular depends on the organisation's
    grading scale, which the client would otherwise have to fetch and interpret.
    """

    grade_id: int = Field(description="Database identifier.")
    student_id: str = Field(examples=["S001"])
    student_name: str = Field(examples=["Anna Schmidt"])
    course_id: str = Field(examples=["CS101"])
    course_name: str = Field(examples=["Intro to Programming"])
    title: str = Field(description="Assessment name, e.g. `Midterm`. Empty for a single mark.")
    score: float = Field(description="Points awarded.", examples=[85.0])
    max_grade: float = Field(description="The course maximum.", examples=[100.0])
    percentage: float = Field(description="Score as a percentage of the maximum.", examples=[85.0])
    letter: str = Field(
        description="Band label from the organisation's grading scale, e.g. `B`. The "
        "bands are configurable, so do not assume A-F.",
        examples=["B"],
    )
    is_passing: bool = Field(description="Whether the score reaches the course threshold.")
    weight: float = Field(description="Relative weight in the course average.", examples=[1.0])
    date: str = Field(description="Award date, ISO `YYYY-MM-DD`.", examples=["2026-01-15"])
    notes: str = Field(description="Free-text remark.")
    graded_by: int | None = Field(default=None, description="Who recorded it.")
    created_at: str | None = None
    updated_at: str | None = None


class GradeCreateRequest(BaseModel):
    """A new grade."""

    student_id: str = Field(min_length=1, examples=["S001"])
    course_id: str = Field(min_length=1, examples=["CS101"])
    score: float = Field(ge=0, description="Must not exceed the course maximum.", examples=[85.0])
    date: str = Field(
        description="ISO `YYYY-MM-DD`. `DD-MM-YYYY`, `DD.MM.YYYY` and `DD/MM/YYYY` are "
        "also accepted and normalised.",
        examples=["2026-01-15"],
    )
    title: str = Field(default="", max_length=100, examples=["Midterm"])
    weight: float = Field(default=1.0, gt=0)
    notes: str = Field(default="", max_length=2000)


class GradeUpdateRequest(BaseModel):
    """Changes to a grade. Omitted fields are left alone."""

    score: float | None = Field(default=None, ge=0)
    date: str | None = None
    title: str | None = Field(default=None, max_length=100)
    weight: float | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=2000)


class AuditEntryResponse(BaseModel):
    """One entry from an entity's change history."""

    id: int
    action: str = Field(description="`create`, `update` or `delete`.")
    at: str = Field(description="ISO-8601 UTC.")
    actor_user_id: int | None = Field(default=None, description="Who made the change.")
    actor_name: str | None = Field(
        default=None,
        description="Their name, or null if the account was deleted. The entry survives it.",
    )
    before: dict[str, Any] | None = Field(default=None, description="State before the change.")
    after: dict[str, Any] | None = Field(default=None, description="State after the change.")


class AuditFeedEntryResponse(AuditEntryResponse):
    """One entry in the institution-wide activity feed.

    Adds the entity reference, which the per-entity history omits because the caller
    already named the entity.
    """

    entity: str = Field(description="What kind of thing changed, e.g. `grade`.")
    entity_id: str = Field(description="Which one.")


# ── Analytics ────────────────────────────────────────────────────────────────
class DashboardResponse(BaseModel):
    """Headline numbers, scoped to the caller.

    A teacher's dashboard describes their own courses, not the institution.
    """

    student_count: int
    course_count: int
    grade_count: int
    average_percentage: float | None = Field(
        default=None, description="Null when nothing is graded — distinct from 0."
    )
    pass_rate: float | None = Field(default=None, description="Null when nothing is graded.")
    distribution: dict[str, int] = Field(
        description="Grade band label to count, including bands with zero so a chart "
        "renders a complete axis."
    )


class RankedStudentResponse(BaseModel):
    """A student in a ranking."""

    student_id: str
    name: str
    average_percentage: float
