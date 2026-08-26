"""Students, courses and enrolments.

Every handler parses, delegates and serialises. No SQL, no business logic — the
architecture test enforces both.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from api.deps import AdminUser, CurrentUser, DbConn, TeacherUser
from api.schemas.domain import (
    PAGE_SIZE,
    CourseCreateRequest,
    CourseResponse,
    CourseUpdateRequest,
    CreatedStudentResponse,
    EnrollmentResponse,
    EnrollmentStatusRequest,
    EnrollRequest,
    PageResponse,
    SizeQuery,
    StudentCourseResponse,
    StudentCreateRequest,
    StudentResponse,
    StudentUpdateRequest,
)
from services.directory import DirectoryService

students_router = APIRouter(prefix="/students", tags=["Students"])
courses_router = APIRouter(prefix="/courses", tags=["Courses"])

SCOPE_NOTE = (
    "\n\nResults are filtered to what your role permits: a student sees only "
    "themselves, a teacher sees students enrolled on a course they own, an "
    "administrator sees everyone. An out-of-scope id returns `404`, not `403` — a "
    "`403` would confirm that a record with that id exists."
)


def directory(conn: DbConn, principal: CurrentUser) -> DirectoryService:
    """Build the directory service for this request.

    Args:
        conn: The request's connection.
        principal: The authenticated caller.

    Returns:
        The service.
    """
    return DirectoryService(conn, principal)


Directory = Annotated[DirectoryService, Depends(directory)]


# ── Students ─────────────────────────────────────────────────────────────────
@students_router.get(
    "",
    response_model=PageResponse[StudentResponse],
    summary="List students",
    description="Paginated, sortable and searchable." + SCOPE_NOTE,
)
def list_students(
    service: Directory,
    page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
    size: SizeQuery = PAGE_SIZE,
    sort: Annotated[
        str | None,
        Query(description="`id`, `first_name`, `last_name`, `email` or `created`; `-` to reverse."),
    ] = None,
    q: Annotated[str | None, Query(description="Free text over name, email and id.")] = None,
    course_id: Annotated[str | None, Query(description="Only students on this course.")] = None,
) -> PageResponse[StudentResponse]:
    """List students within the caller's scope."""
    result = service.list_students(page=page, size=size, sort=sort, search=q, course_id=course_id)
    return PageResponse[StudentResponse](
        items=[StudentResponse(**item) for item in result.items],
        total=result.total,
        page=result.page,
        size=result.size,
        pages=result.pages,
    )


@students_router.post(
    "",
    response_model=CreatedStudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a student",
    description=(
        "Administrators only. A student record belongs to the institution's register, "
        "not to a course — and a teacher creating one could not read it back, since "
        "their scope is defined by enrolment. Teachers enrol existing students instead."
        "\n\nThe record comes with a sign-in account unless `create_account` is false. "
        "Its one-time password is in `initial_password` and is available nowhere else."
    ),
    responses={
        403: {"description": "`FORBIDDEN` — administrators only."},
        409: {"description": "`DUPLICATE_ENTRY` — the id or email is taken."},
    },
)
def create_student(
    payload: StudentCreateRequest, service: Directory, _: AdminUser
) -> CreatedStudentResponse:
    """Add a student, and by default the account they sign in with."""
    student, password = service.create_student(**payload.model_dump())
    return CreatedStudentResponse(**student, initial_password=password)


@students_router.get(
    "/{student_id}",
    response_model=StudentResponse,
    summary="Fetch one student",
    responses={404: {"description": "`STUDENT_NOT_FOUND` — unknown, or outside your scope."}},
)
def get_student(student_id: str, service: Directory) -> StudentResponse:
    """Fetch one student."""
    return StudentResponse(**service.get_student(student_id))


@students_router.patch(
    "/{student_id}",
    response_model=StudentResponse,
    summary="Update a student",
    description="Administrators only — see `POST /students`.",
    responses={
        403: {"description": "`FORBIDDEN` — administrators only."},
        404: {"description": "`STUDENT_NOT_FOUND`."},
        409: {"description": "`DUPLICATE_ENTRY`."},
    },
)
def update_student(
    student_id: str, payload: StudentUpdateRequest, service: Directory, _: AdminUser
) -> StudentResponse:
    """Update a student's details."""
    return StudentResponse(
        **service.update_student(student_id, payload.model_dump(exclude_unset=True))
    )


@students_router.delete(
    "/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a student",
    description=(
        "Removes the student and, by cascade, their grades and enrolments. Their "
        "audit history survives."
    ),
    responses={404: {"description": "`STUDENT_NOT_FOUND`."}},
)
def delete_student(student_id: str, service: Directory, _: AdminUser) -> None:
    """Delete a student."""
    service.delete_student(student_id)


@students_router.get(
    "/{student_id}/courses",
    response_model=list[StudentCourseResponse],
    summary="List a student's courses",
    responses={404: {"description": "`STUDENT_NOT_FOUND`."}},
)
def student_courses(student_id: str, service: Directory) -> list[StudentCourseResponse]:
    """List the courses a student is enrolled on."""
    return [StudentCourseResponse(**row) for row in service.student_courses(student_id)]


# ── Courses ──────────────────────────────────────────────────────────────────
@courses_router.get(
    "",
    response_model=PageResponse[CourseResponse],
    summary="List courses",
    description="Paginated, sortable and searchable." + SCOPE_NOTE,
)
def list_courses(
    service: Directory,
    page: Annotated[int, Query(ge=1)] = 1,
    size: SizeQuery = PAGE_SIZE,
    sort: Annotated[
        str | None, Query(description="`id`, `name`, `term`, `credits` or `created`.")
    ] = None,
    q: Annotated[str | None, Query(description="Free text over name and id.")] = None,
    term: Annotated[str | None, Query(description="Only this academic term.")] = None,
    status: Annotated[
        str | None,
        Query(
            description=(
                "`active` or `archived`. Omitted returns both, which is what the "
                "course list wants — archiving is not deletion. A picker offering a "
                "course to enrol on or grade should ask for `active`."
            )
        ),
    ] = None,
) -> PageResponse[CourseResponse]:
    """List courses within the caller's scope."""
    result = service.list_courses(
        page=page, size=size, sort=sort, search=q, term=term, status=status
    )
    return PageResponse[CourseResponse](
        items=[CourseResponse(**item) for item in result.items],
        total=result.total,
        page=result.page,
        size=result.size,
        pages=result.pages,
    )


@courses_router.post(
    "",
    response_model=CourseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a course",
    description=(
        "A teacher creating a course owns it by default — the alternative is a course "
        "they immediately cannot see."
    ),
    responses={409: {"description": "`DUPLICATE_ENTRY` — the id is taken."}},
)
def create_course(
    payload: CourseCreateRequest, service: Directory, _: TeacherUser
) -> CourseResponse:
    """Add a course."""
    return CourseResponse(**service.create_course(payload.model_dump(exclude_unset=True)))


@courses_router.get(
    "/{course_id}",
    response_model=CourseResponse,
    summary="Fetch one course",
    responses={404: {"description": "`COURSE_NOT_FOUND` — unknown, or outside your scope."}},
)
def get_course(course_id: str, service: Directory) -> CourseResponse:
    """Fetch one course."""
    return CourseResponse(**service.get_course(course_id))


@courses_router.patch(
    "/{course_id}",
    response_model=CourseResponse,
    summary="Update a course",
    description=(
        "Read access is broader than write access: a student can see a course they "
        "are enrolled on and cannot rename it. Reassigning `teacher_id` is "
        "administrators only, since it changes who can see the course."
    ),
    responses={403: {"description": "`FORBIDDEN` — you do not own this course."}},
)
def update_course(
    course_id: str, payload: CourseUpdateRequest, service: Directory, _: TeacherUser
) -> CourseResponse:
    """Update a course."""
    return CourseResponse(
        **service.update_course(course_id, payload.model_dump(exclude_unset=True))
    )


@courses_router.delete(
    "/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a course",
    responses={403: {"description": "`FORBIDDEN` — you do not own this course."}},
)
def delete_course(course_id: str, service: Directory, _: TeacherUser) -> None:
    """Delete a course and, by cascade, its grades and enrolments."""
    service.delete_course(course_id)


# ── Enrolments ───────────────────────────────────────────────────────────────
@courses_router.get(
    "/{course_id}/enrollments",
    response_model=list[EnrollmentResponse],
    summary="List a course's register",
    description=(
        "Includes students with no grades yet — `grade_count` of zero. That state is "
        "the reason enrolments exist as their own table rather than being inferred "
        "from grades."
    ),
    responses={404: {"description": "`COURSE_NOT_FOUND`."}},
)
def list_enrollments(course_id: str, service: Directory) -> list[EnrollmentResponse]:
    """List a course's enrolments."""
    return [EnrollmentResponse(**row) for row in service.list_enrollments(course_id)]


@courses_router.post(
    "/{course_id}/enrollments",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enrol a student",
    responses={
        403: {"description": "`FORBIDDEN` — you do not own this course."},
        409: {"description": "`COURSE_FULL` or `DUPLICATE_ENTRY`."},
    },
)
def enroll(
    course_id: str, payload: EnrollRequest, service: Directory, _: TeacherUser
) -> EnrollmentResponse:
    """Enrol a student on a course."""
    return EnrollmentResponse(**service.enroll(course_id, payload.student_id))


@courses_router.patch(
    "/{course_id}/enrollments/{student_id}",
    response_model=EnrollmentResponse,
    summary="Change an enrolment's status",
    description=(
        "Use `withdrawn` for a student who left; the enrolment row and any grades "
        "earned before it are retained."
    ),
)
def set_enrollment_status(
    course_id: str,
    student_id: str,
    payload: EnrollmentStatusRequest,
    service: Directory,
    _: TeacherUser,
) -> EnrollmentResponse:
    """Change an enrolment's status."""
    return EnrollmentResponse(
        **service.set_enrollment_status(course_id, student_id, payload.status)
    )


@courses_router.delete(
    "/{course_id}/enrollments/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an enrolment",
    description=(
        "For correcting a registration made in error. For a student who left, prefer "
        "setting the status to `withdrawn` so the record survives."
    ),
)
def unenroll(course_id: str, student_id: str, service: Directory, _: TeacherUser) -> None:
    """Remove an enrolment outright."""
    service.unenroll(course_id, student_id)
