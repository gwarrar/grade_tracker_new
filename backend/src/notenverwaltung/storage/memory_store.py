"""In-memory implementation of :class:`~notenverwaltung.storage.base.GradeStore`.

Used by tests and by anything that wants a grade book without a file on disk. It
must behave identically to :class:`~notenverwaltung.storage.sqlite_store.SqliteGradeStore`
— the conformance suite runs the same cases against both, which is the whole point
of having the ABC.
"""

from __future__ import annotations

import copy
from typing import Any

from notenverwaltung.exceptions import (
    CourseNotFoundError,
    DuplicateEntryError,
    GradeNotFoundError,
    StudentNotFoundError,
    ValidationError,
)
from notenverwaltung.models.course import Course
from notenverwaltung.models.grade import Grade
from notenverwaltung.models.student import Student
from notenverwaltung.storage.base import GradeStore


class InMemoryGradeStore(GradeStore):
    """Holds the grade book in dictionaries.

    Every accessor returns copies. Handing out references to internal objects would
    let a caller mutate stored state without going through the store — the sort of
    aliasing bug that is very hard to trace back later.
    """

    def __init__(self) -> None:
        """Create an empty store."""
        self._students: dict[str, Student] = {}
        self._courses: dict[str, Course] = {}
        self._grades: dict[int, Grade] = {}
        self._deleted: set[int] = set()
        self._next_id = 1

    def _sorted_live(self, grades: list[Grade]) -> list[Grade]:
        """Sort grades most-recent-first, matching the SQL ``ORDER BY``."""
        return sorted(grades, key=lambda g: (g.date, g.grade_id or 0), reverse=True)

    # ── Students ─────────────────────────────────────────────────────────────
    def add_student(self, student: Student) -> None:
        """Insert a student. See :meth:`GradeStore.add_student`."""
        if student.student_id in self._students:
            raise DuplicateEntryError(
                f"A student with id {student.student_id!r} already exists.",
                student_id=student.student_id,
            )
        if any(s.email == student.email for s in self._students.values()):
            raise DuplicateEntryError(
                f"A student with email {student.email!r} already exists.", email=student.email
            )
        self._students[student.student_id] = copy.copy(student)

    def get_student(self, student_id: str) -> Student:
        """Fetch one student. See :meth:`GradeStore.get_student`."""
        if student_id not in self._students:
            raise StudentNotFoundError(f"No student with id {student_id!r}.", student_id=student_id)
        return copy.copy(self._students[student_id])

    def get_all_students(self) -> list[Student]:
        """Return every student, ordered by id."""
        return [copy.copy(s) for _, s in sorted(self._students.items())]

    def update_student(self, student: Student) -> None:
        """Overwrite a student's mutable fields. See :meth:`GradeStore.update_student`."""
        if student.student_id not in self._students:
            raise StudentNotFoundError(
                f"No student with id {student.student_id!r}.", student_id=student.student_id
            )
        self._students[student.student_id] = copy.copy(student)

    def delete_student(self, student_id: str) -> None:
        """Remove a student and cascade to their grades. See :meth:`GradeStore.delete_student`."""
        if student_id not in self._students:
            raise StudentNotFoundError(f"No student with id {student_id!r}.", student_id=student_id)
        del self._students[student_id]
        for gid, grade in list(self._grades.items()):
            if grade.student.student_id == student_id:
                del self._grades[gid]
                self._deleted.discard(gid)

    # ── Courses ──────────────────────────────────────────────────────────────
    def add_course(self, course: Course) -> None:
        """Insert a course. See :meth:`GradeStore.add_course`."""
        if course.course_id in self._courses:
            raise DuplicateEntryError(
                f"A course with id {course.course_id!r} already exists.",
                course_id=course.course_id,
            )
        self._courses[course.course_id] = copy.copy(course)

    def get_course(self, course_id: str) -> Course:
        """Fetch one course. See :meth:`GradeStore.get_course`."""
        if course_id not in self._courses:
            raise CourseNotFoundError(f"No course with id {course_id!r}.", course_id=course_id)
        return copy.copy(self._courses[course_id])

    def get_all_courses(self) -> list[Course]:
        """Return every course, ordered by id."""
        return [copy.copy(c) for _, c in sorted(self._courses.items())]

    def update_course(self, course: Course) -> None:
        """Overwrite a course's mutable fields. See :meth:`GradeStore.update_course`."""
        if course.course_id not in self._courses:
            raise CourseNotFoundError(
                f"No course with id {course.course_id!r}.", course_id=course.course_id
            )
        self._courses[course.course_id] = copy.copy(course)

    def delete_course(self, course_id: str) -> None:
        """Remove a course and cascade to its grades. See :meth:`GradeStore.delete_course`."""
        if course_id not in self._courses:
            raise CourseNotFoundError(f"No course with id {course_id!r}.", course_id=course_id)
        del self._courses[course_id]
        for gid, grade in list(self._grades.items()):
            if grade.course.course_id == course_id:
                del self._grades[gid]
                self._deleted.discard(gid)

    # ── Grades ───────────────────────────────────────────────────────────────
    def record_grade(self, grade: Grade) -> Grade:
        """Insert a grade and return it with its assigned id.

        See :meth:`GradeStore.record_grade`.

        Raises:
            StudentNotFoundError: If the referenced student does not exist.
            CourseNotFoundError: If the referenced course does not exist.
        """
        # Enforced explicitly, because SQLite enforces it via foreign keys and the
        # two stores must be indistinguishable to callers.
        if grade.student.student_id not in self._students:
            raise StudentNotFoundError(
                f"No student with id {grade.student.student_id!r}.",
                student_id=grade.student.student_id,
            )
        if grade.course.course_id not in self._courses:
            raise CourseNotFoundError(
                f"No course with id {grade.course.course_id!r}.", course_id=grade.course.course_id
            )

        stored = copy.copy(grade)
        stored.grade_id = self._next_id
        self._next_id += 1
        self._grades[stored.grade_id] = stored
        grade.grade_id = stored.grade_id
        return grade

    def get_grade(self, grade_id: int) -> Grade:
        """Fetch one grade. See :meth:`GradeStore.get_grade`."""
        if grade_id not in self._grades or grade_id in self._deleted:
            raise GradeNotFoundError(f"No grade with id {grade_id}.", grade_id=grade_id)
        return copy.copy(self._grades[grade_id])

    def update_grade(self, grade: Grade) -> None:
        """Overwrite a grade's mutable fields. See :meth:`GradeStore.update_grade`."""
        if grade.grade_id is None:
            raise ValidationError("Cannot update a grade that has not been saved yet.")
        if grade.grade_id not in self._grades or grade.grade_id in self._deleted:
            raise GradeNotFoundError(f"No grade with id {grade.grade_id}.", grade_id=grade.grade_id)
        self._grades[grade.grade_id] = copy.copy(grade)

    def delete_grade(self, grade_id: int) -> None:
        """Soft-delete a grade. See :meth:`GradeStore.delete_grade`."""
        if grade_id not in self._grades or grade_id in self._deleted:
            raise GradeNotFoundError(f"No grade with id {grade_id}.", grade_id=grade_id)
        self._deleted.add(grade_id)

    def _live_grades(self) -> list[Grade]:
        """Return copies of every grade that has not been soft-deleted."""
        return [copy.copy(g) for gid, g in self._grades.items() if gid not in self._deleted]

    def get_student_grades(self, student_id: str) -> list[Grade]:
        """Return every live grade for a student, most recent first."""
        return self._sorted_live(
            [g for g in self._live_grades() if g.student.student_id == student_id]
        )

    def get_course_grades(self, course_id: str) -> list[Grade]:
        """Return every live grade for a course, most recent first."""
        return self._sorted_live(
            [g for g in self._live_grades() if g.course.course_id == course_id]
        )

    def get_all_grades(self) -> list[Grade]:
        """Return every live grade, most recent first."""
        return self._sorted_live(self._live_grades())

    def snapshot(self) -> dict[str, Any]:
        """Return the full contents, for debugging and test assertions."""
        return {
            "students": [s.to_dict() for s in self.get_all_students()],
            "courses": [c.to_dict() for c in self.get_all_courses()],
            "grades": [g.to_dict() for g in self.get_all_grades()],
        }
