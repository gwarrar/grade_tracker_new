"""The :class:`Enrollment` domain model.

The link the coursework version lacked. There, a grade was the only connection
between a student and a course, so a student who was enrolled but not yet graded
simply did not appear — and "how many students are in CS101" could only be answered
by counting grade rows, which double-counts anyone with more than one assessment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from notenverwaltung.exceptions import ValidationError


class EnrollmentStatus(StrEnum):
    """Where a student stands in a course.

    ``WITHDRAWN`` rather than deletion: a withdrawal is part of the academic record,
    and any grades earned before it must remain attached to something.
    """

    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    COMPLETED = "completed"


@dataclass
class Enrollment:
    """A student's registration on a course.

    Attributes:
        student_id: The enrolled student.
        course_id: The course enrolled on.
        status: Active, withdrawn or completed.
        enrolled_at: ISO timestamp of registration.
        enrolled_by: User id of whoever registered them, for the audit trail.
    """

    student_id: str
    course_id: str
    status: EnrollmentStatus = EnrollmentStatus.ACTIVE
    enrolled_at: str | None = field(default=None)
    enrolled_by: int | None = field(default=None)

    def __post_init__(self) -> None:
        """Normalise identifiers and validate the status.

        Raises:
            ValidationError: If an identifier is blank or the status is unrecognised.
        """
        self.student_id = self.student_id.strip()
        self.course_id = self.course_id.strip()

        if not self.student_id:
            raise ValidationError("Student ID cannot be empty.", field="student_id")
        if not self.course_id:
            raise ValidationError("Course ID cannot be empty.", field="course_id")

    @classmethod
    def from_row(cls, row: Any) -> Enrollment:
        """Build an enrolment from an ``enrollments`` table row.

        Args:
            row: A mapping with the table's column names.

        Returns:
            The reconstructed enrolment.

        Raises:
            ValidationError: If the stored status is not a recognised value.
        """
        try:
            status = EnrollmentStatus(row["status"])
        except ValueError as exc:
            raise ValidationError(
                f"Unknown enrolment status: {row['status']!r}", field="status"
            ) from exc

        return cls(
            student_id=row["student_id"],
            course_id=row["course_id"],
            status=status,
            enrolled_at=row["enrolled_at"],
            enrolled_by=row["enrolled_by"],
        )

    @property
    def is_active(self) -> bool:
        """Whether the student currently counts towards the course's capacity."""
        return self.status is EnrollmentStatus.ACTIVE

    def __str__(self) -> str:
        """Return a readable representation for logs."""
        return f"{self.student_id} -> {self.course_id} ({self.status})"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "student_id": self.student_id,
            "course_id": self.course_id,
            "status": str(self.status),
            "enrolled_at": self.enrolled_at,
            "enrolled_by": self.enrolled_by,
        }
