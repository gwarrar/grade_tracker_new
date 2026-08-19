"""Domain exceptions.

Every exception carries a stable machine-readable ``code``. The API layer maps that
code into an RFC-9457 ``application/problem+json`` body and the frontend translates
it, so **no user-facing prose is produced here**. Adding a language therefore never
requires touching the backend.

The ``message`` attached to an exception is for developers and logs, not for users.
"""

from __future__ import annotations


class GradeBookError(ValueError):
    """Base class for every domain error.

    Subclasses ``ValueError`` so that existing callers written against the coursework
    API keep working.

    Attributes:
        code: Stable identifier the API and frontend agree on, e.g. ``STUDENT_NOT_FOUND``.
        http_status: The status the API layer should use for this class of error.
        context: Structured details (ids, limits) the frontend can interpolate into
            a translated message.
    """

    code: str = "DOMAIN_ERROR"
    http_status: int = 400

    def __init__(self, message: str, **context: object) -> None:
        """Initialise the error.

        Args:
            message: Developer-facing description. Never shown to end users.
            **context: Structured values the frontend may interpolate, such as
                ``student_id`` or ``max_grade``.
        """
        super().__init__(message)
        self.message = message
        self.context: dict[str, object] = context


class ValidationError(GradeBookError):
    """Raised when a value fails a domain invariant."""

    code = "VALIDATION_ERROR"
    http_status = 422


class PayloadTooLargeError(GradeBookError):
    """Raised when an uploaded payload exceeds its configured ceiling."""

    code = "PAYLOAD_TOO_LARGE"
    http_status = 413


class ImportTooManyRowsError(GradeBookError):
    """Raised when a single import would exceed the row cap.

    The cap exists because SQLite is a single writer: a bulk import large enough to
    matter would hold the write lock for every other request, and the preview double-
    reads each row. The path to lifting it is a background job over a staging table.
    """

    code = "IMPORT_TOO_MANY_ROWS"
    http_status = 413


class StudentNotFoundError(GradeBookError):
    """Raised when no student matches the requested identifier."""

    code = "STUDENT_NOT_FOUND"
    http_status = 404


class CourseNotFoundError(GradeBookError):
    """Raised when no course matches the requested identifier."""

    code = "COURSE_NOT_FOUND"
    http_status = 404


class GradeNotFoundError(GradeBookError):
    """Raised when no grade matches the requested identifier."""

    code = "GRADE_NOT_FOUND"
    http_status = 404


class NoteNotFoundError(GradeBookError):
    """Raised when no note matches the requested identifier."""

    code = "NOTE_NOT_FOUND"
    http_status = 404


class DuplicateEntryError(GradeBookError):
    """Raised when creating an entity whose identifier is already taken."""

    code = "DUPLICATE_ENTRY"
    http_status = 409


class NoGradesRecordedError(GradeBookError):
    """Raised when a statistic is requested for an entity that has no grades.

    Separated from :class:`ValidationError` because it is an ordinary empty state the
    UI should render as "no data yet", not as a failure.
    """

    code = "NO_GRADES_RECORDED"
    http_status = 404


class CourseFullError(GradeBookError):
    """Raised when enrolling a student into a course already at capacity."""

    code = "COURSE_FULL"
    http_status = 409


class PrerequisitesNotMetError(GradeBookError):
    """Raised when a student has not completed everything a course requires.

    Its own code rather than a plain validation failure, because the answer is
    actionable and specific: the caller needs to be told which courses are
    outstanding, and "request failed validation" tells whoever is enrolling nothing
    they can act on. ``context["missing"]`` carries the list.
    """

    code = "PREREQUISITES_NOT_MET"
    http_status = 409


class NotAuthenticatedError(GradeBookError):
    """Raised when an operation needs a signed-in user and there is none."""

    code = "NOT_AUTHENTICATED"
    http_status = 401


class ForbiddenError(GradeBookError):
    """Raised when a signed-in user lacks the authority an action requires.

    Distinct from a *row* being out of scope, which surfaces as not-found instead —
    a 403 on a specific id would confirm that a record with that id exists.
    """

    code = "FORBIDDEN"
    http_status = 403


class PasswordChangeRequiredError(ForbiddenError):
    """Raised when the caller is still holding a password they did not choose.

    Its own code rather than a plain ``FORBIDDEN`` because the two need different
    handling: a forbidden action is a dead end, and this one has exactly one way
    out. The frontend routes it to the change-password screen.
    """

    code = "PASSWORD_CHANGE_REQUIRED"
