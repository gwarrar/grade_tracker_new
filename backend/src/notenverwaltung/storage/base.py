"""The :class:`GradeStore` persistence interface.

Every implementation must behave identically — the test suite runs the same cases
against the in-memory and SQLite stores. This is the seam that keeps SQL out of the
service and API layers, and it is what makes a future move to PostgreSQL a matter of
writing one more subclass rather than rewriting the application.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from notenverwaltung.models.course import Course
from notenverwaltung.models.grade import Grade
from notenverwaltung.models.student import Student


class GradeStore(ABC):
    """Persistence interface for students, courses and grades.

    Implementations raise :class:`~notenverwaltung.exceptions.StudentNotFoundError`,
    ``CourseNotFoundError`` or ``GradeNotFoundError` for missing entities — never
    ``KeyError``, so callers need not know which backend they are talking to.

    Transactions are **not** managed here. The service layer decides what constitutes
    a unit of work, because a single use case often spans several store calls plus an
    audit-log write that must commit or roll back together.
    """

    # ── Students ─────────────────────────────────────────────────────────────
    @abstractmethod
    def add_student(self, student: Student) -> None:
        """Insert a student.

        Args:
            student: The student to store.

        Raises:
            DuplicateEntryError: If ``student.student_id`` is already taken.
        """

    @abstractmethod
    def get_student(self, student_id: str) -> Student:
        """Fetch one student.

        Args:
            student_id: The identifier to look up.

        Returns:
            The matching student.

        Raises:
            StudentNotFoundError: If no student has that id.
        """

    @abstractmethod
    def get_all_students(self) -> list[Student]:
        """Return every student, ordered by id."""

    @abstractmethod
    def update_student(self, student: Student) -> None:
        """Overwrite a student's mutable fields, matched on ``student_id``.

        Args:
            student: The desired state.

        Raises:
            StudentNotFoundError: If no student has that id.
        """

    @abstractmethod
    def delete_student(self, student_id: str) -> None:
        """Remove a student and, by cascade, their grades and enrolments.

        Args:
            student_id: The identifier to remove.

        Raises:
            StudentNotFoundError: If no student has that id.
        """

    # ── Courses ──────────────────────────────────────────────────────────────
    @abstractmethod
    def add_course(self, course: Course) -> None:
        """Insert a course.

        Args:
            course: The course to store.

        Raises:
            DuplicateEntryError: If ``course.course_id`` is already taken.
        """

    @abstractmethod
    def get_course(self, course_id: str) -> Course:
        """Fetch one course.

        Args:
            course_id: The identifier to look up.

        Returns:
            The matching course.

        Raises:
            CourseNotFoundError: If no course has that id.
        """

    @abstractmethod
    def get_all_courses(self) -> list[Course]:
        """Return every course, ordered by id."""

    @abstractmethod
    def update_course(self, course: Course) -> None:
        """Overwrite a course's mutable fields, matched on ``course_id``.

        Args:
            course: The desired state.

        Raises:
            CourseNotFoundError: If no course has that id.
        """

    @abstractmethod
    def delete_course(self, course_id: str) -> None:
        """Remove a course and, by cascade, its grades and enrolments.

        Args:
            course_id: The identifier to remove.

        Raises:
            CourseNotFoundError: If no course has that id.
        """

    # ── Grades ───────────────────────────────────────────────────────────────
    @abstractmethod
    def record_grade(self, grade: Grade) -> Grade:
        """Insert a grade.

        Args:
            grade: The grade to store. Its ``grade_id`` must be ``None``.

        Returns:
            The same grade with ``grade_id`` populated, so the caller can address it
            for later edits without a follow-up query.
        """

    @abstractmethod
    def get_grade(self, grade_id: int) -> Grade:
        """Fetch one grade.

        Args:
            grade_id: The identifier to look up.

        Returns:
            The matching grade.

        Raises:
            GradeNotFoundError: If no live grade has that id.
        """

    @abstractmethod
    def update_grade(self, grade: Grade) -> None:
        """Overwrite a grade's mutable fields, matched on ``grade_id``.

        Args:
            grade: The desired state. ``grade_id`` must be set.

        Raises:
            GradeNotFoundError: If no live grade has that id.
            ValidationError: If ``grade.grade_id`` is ``None``.
        """

    @abstractmethod
    def delete_grade(self, grade_id: int) -> None:
        """Soft-delete a grade.

        Grades are never physically removed: an altered mark is exactly the kind of
        change a student may later dispute, so the row is retained and excluded from
        reads instead.

        Args:
            grade_id: The identifier to retire.

        Raises:
            GradeNotFoundError: If no live grade has that id.
        """

    @abstractmethod
    def get_student_grades(self, student_id: str) -> list[Grade]:
        """Return every live grade for a student, most recent first."""

    @abstractmethod
    def get_course_grades(self, course_id: str) -> list[Grade]:
        """Return every live grade for a course, most recent first."""

    @abstractmethod
    def get_all_grades(self) -> list[Grade]:
        """Return every live grade, most recent first."""
