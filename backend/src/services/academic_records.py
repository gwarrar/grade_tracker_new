"""Enrollment operations exposed to the academic-records capability."""

from __future__ import annotations

from typing import Any, Protocol


class AcademicRecords(Protocol):
    """Operations controllers need to manage enrollment records."""

    def list_enrollments(self, course_id: str) -> list[dict[str, Any]]:
        """List the students enrolled on a course."""
        ...

    def student_courses(self, student_id: str) -> list[dict[str, Any]]:
        """List the courses recorded for a student."""
        ...

    def enroll(self, course_id: str, student_id: str) -> dict[str, Any]:
        """Enroll a student on a course."""
        ...

    def set_enrollment_status(self, course_id: str, student_id: str, status: str) -> dict[str, Any]:
        """Change a student's enrollment status."""
        ...

    def unenroll(self, course_id: str, student_id: str) -> None:
        """Remove an erroneous enrollment."""
        ...
