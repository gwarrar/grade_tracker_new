"""SQLite implementation of :class:`~notenverwaltung.storage.base.GradeStore`."""

from __future__ import annotations

import sqlite3

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

# The column lists below are interpolated into the queries in this module. Ruff flags
# that as S608 (SQL injection) and is right to in general -- but these are module-level
# literals, never user input, and every caller-supplied value goes through a `?`
# placeholder. Each site is suppressed individually rather than the whole file, so S608
# still fires on any query added later that interpolates something dynamic.
_STUDENT_COLS = "student_id, first_name, last_name, email, user_id"
_COURSE_COLS = "course_id, name, max_grade, passing_grade, max_students, teacher_id, term, credits"

# Aliased so a joined row carries both entities without column-name collisions
# (`students.name` would otherwise shadow `courses.name`).
_S_ALIASED = ", ".join(f"s.{c.strip()} AS s_{c.strip()}" for c in _STUDENT_COLS.split(","))
_C_ALIASED = ", ".join(f"c.{c.strip()} AS c_{c.strip()}" for c in _COURSE_COLS.split(","))

_GRADE_SELECT = (
    "SELECT g.grade_id, g.score, g.date, g.notes, g.title, g.weight, g.graded_by, "  # noqa: S608
    f"{_S_ALIASED}, {_C_ALIASED} "
    "FROM grades AS g "
    "JOIN students AS s ON s.student_id = g.student_id "
    "JOIN courses AS c ON c.course_id = g.course_id "
    "WHERE g.deleted_at IS NULL"
)
"""One JOIN instead of two follow-up queries per row.

The coursework version rebuilt each grade by calling ``get_student()`` and
``get_course()``, so loading 500 grades issued 1001 queries across 1001 connections.
This fetches everything in one round trip.
"""

_SELECT_STUDENT = f"SELECT {_STUDENT_COLS} FROM students WHERE student_id = ?"  # noqa: S608
_SELECT_STUDENTS = f"SELECT {_STUDENT_COLS} FROM students ORDER BY student_id"  # noqa: S608
_INSERT_STUDENT = f"INSERT INTO students ({_STUDENT_COLS}) VALUES (?, ?, ?, ?, ?)"  # noqa: S608

_SELECT_COURSE = f"SELECT {_COURSE_COLS} FROM courses WHERE course_id = ?"  # noqa: S608
_SELECT_COURSES = f"SELECT {_COURSE_COLS} FROM courses ORDER BY course_id"  # noqa: S608
_INSERT_COURSE = f"INSERT INTO courses ({_COURSE_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"  # noqa: S608

_NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
"""ISO-8601 UTC timestamp. Kept as a named constant so the format is identical
everywhere — mixed timestamp formats in one column sort incorrectly."""


class SqliteGradeStore(GradeStore):
    """Stores the grade book in SQLite.

    The connection is injected rather than created here, so the caller controls
    transaction boundaries and connection lifetime. See
    :func:`notenverwaltung.storage.db.connect` for how one is configured, and
    :func:`~notenverwaltung.storage.db.transaction` for wrapping a unit of work.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Bind the store to an open connection.

        Args:
            conn: A connection from :func:`notenverwaltung.storage.db.connect`.
                Its schema must already be migrated.
        """
        self._conn = conn

    # ── Row mapping ──────────────────────────────────────────────────────────
    @staticmethod
    def _to_student(row: sqlite3.Row, prefix: str = "") -> Student:
        """Build a :class:`Student` from a row, honouring an optional column prefix."""
        return Student(
            student_id=row[f"{prefix}student_id"],
            first_name=row[f"{prefix}first_name"],
            last_name=row[f"{prefix}last_name"],
            email=row[f"{prefix}email"],
            user_id=row[f"{prefix}user_id"],
        )

    @staticmethod
    def _to_course(row: sqlite3.Row, prefix: str = "") -> Course:
        """Build a :class:`Course` from a row, honouring an optional column prefix."""
        return Course(
            course_id=row[f"{prefix}course_id"],
            name=row[f"{prefix}name"],
            max_grade=row[f"{prefix}max_grade"],
            passing_grade=row[f"{prefix}passing_grade"],
            max_students=row[f"{prefix}max_students"],
            teacher_id=row[f"{prefix}teacher_id"],
            term=row[f"{prefix}term"],
            credits=row[f"{prefix}credits"],
        )

    @classmethod
    def _to_grade(cls, row: sqlite3.Row) -> Grade:
        """Build a fully populated :class:`Grade` from one joined row."""
        return Grade(
            student=cls._to_student(row, prefix="s_"),
            course=cls._to_course(row, prefix="c_"),
            score=row["score"],
            date=row["date"],
            notes=row["notes"],
            title=row["title"],
            weight=row["weight"],
            grade_id=row["grade_id"],
            graded_by=row["graded_by"],
        )

    # ── Students ─────────────────────────────────────────────────────────────
    def add_student(self, student: Student) -> None:
        """Insert a student. See :meth:`GradeStore.add_student`."""
        try:
            self._conn.execute(
                _INSERT_STUDENT,
                (
                    student.student_id,
                    student.first_name,
                    student.last_name,
                    student.email,
                    student.user_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEntryError(
                f"A student with id {student.student_id!r} or email {student.email!r} exists.",
                student_id=student.student_id,
            ) from exc

    def get_student(self, student_id: str) -> Student:
        """Fetch one student. See :meth:`GradeStore.get_student`."""
        row = self._conn.execute(_SELECT_STUDENT, (student_id,)).fetchone()
        if row is None:
            raise StudentNotFoundError(f"No student with id {student_id!r}.", student_id=student_id)
        return self._to_student(row)

    def get_all_students(self) -> list[Student]:
        """Return every student, ordered by id."""
        return [self._to_student(r) for r in self._conn.execute(_SELECT_STUDENTS)]

    def update_student(self, student: Student) -> None:
        """Overwrite a student's mutable fields. See :meth:`GradeStore.update_student`."""
        cursor = self._conn.execute(
            "UPDATE students SET first_name = ?, last_name = ?, email = ?, user_id = ?,"  # noqa: S608
            f" updated_at = {_NOW} WHERE student_id = ?",
            (
                student.first_name,
                student.last_name,
                student.email,
                student.user_id,
                student.student_id,
            ),
        )
        if cursor.rowcount == 0:
            raise StudentNotFoundError(
                f"No student with id {student.student_id!r}.", student_id=student.student_id
            )

    def delete_student(self, student_id: str) -> None:
        """Remove a student. See :meth:`GradeStore.delete_student`."""
        cursor = self._conn.execute("DELETE FROM students WHERE student_id = ?", (student_id,))
        if cursor.rowcount == 0:
            raise StudentNotFoundError(f"No student with id {student_id!r}.", student_id=student_id)

    # ── Courses ──────────────────────────────────────────────────────────────
    def add_course(self, course: Course) -> None:
        """Insert a course. See :meth:`GradeStore.add_course`."""
        try:
            self._conn.execute(
                _INSERT_COURSE,
                (
                    course.course_id,
                    course.name,
                    course.max_grade,
                    course.passing_grade,
                    course.max_students,
                    course.teacher_id,
                    course.term,
                    course.credits,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEntryError(
                f"A course with id {course.course_id!r} already exists.",
                course_id=course.course_id,
            ) from exc

    def get_course(self, course_id: str) -> Course:
        """Fetch one course. See :meth:`GradeStore.get_course`."""
        row = self._conn.execute(_SELECT_COURSE, (course_id,)).fetchone()
        if row is None:
            raise CourseNotFoundError(f"No course with id {course_id!r}.", course_id=course_id)
        return self._to_course(row)

    def get_all_courses(self) -> list[Course]:
        """Return every course, ordered by id."""
        return [self._to_course(r) for r in self._conn.execute(_SELECT_COURSES)]

    def update_course(self, course: Course) -> None:
        """Overwrite a course's mutable fields. See :meth:`GradeStore.update_course`."""
        cursor = self._conn.execute(
            "UPDATE courses SET name = ?, max_grade = ?, passing_grade = ?, max_students = ?,"  # noqa: S608
            f" teacher_id = ?, term = ?, credits = ?, updated_at = {_NOW} WHERE course_id = ?",
            (
                course.name,
                course.max_grade,
                course.passing_grade,
                course.max_students,
                course.teacher_id,
                course.term,
                course.credits,
                course.course_id,
            ),
        )
        if cursor.rowcount == 0:
            raise CourseNotFoundError(
                f"No course with id {course.course_id!r}.", course_id=course.course_id
            )

    def delete_course(self, course_id: str) -> None:
        """Remove a course. See :meth:`GradeStore.delete_course`."""
        cursor = self._conn.execute("DELETE FROM courses WHERE course_id = ?", (course_id,))
        if cursor.rowcount == 0:
            raise CourseNotFoundError(f"No course with id {course_id!r}.", course_id=course_id)

    # ── Grades ───────────────────────────────────────────────────────────────
    def record_grade(self, grade: Grade) -> Grade:
        """Insert a grade and return it with its assigned id.

        See :meth:`GradeStore.record_grade`.

        Raises:
            StudentNotFoundError: If the referenced student does not exist.
            CourseNotFoundError: If the referenced course does not exist.
        """
        try:
            cursor = self._conn.execute(
                "INSERT INTO grades"
                " (student_id, course_id, score, date, notes, title, weight, graded_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    grade.student.student_id,
                    grade.course.course_id,
                    grade.score,
                    grade.date,
                    grade.notes,
                    grade.title,
                    grade.weight,
                    grade.graded_by,
                ),
            )
        except sqlite3.IntegrityError as exc:
            # Foreign keys are genuinely enforced here — see storage.db for why that
            # was not true in the coursework version.
            raise self._missing_reference(grade) from exc

        grade.grade_id = cursor.lastrowid
        return grade

    def _missing_reference(self, grade: Grade) -> Exception:
        """Decide which of the two foreign keys a grade insert violated.

        Args:
            grade: The grade whose insert failed.

        Returns:
            The specific not-found error, so the API returns an actionable code
            rather than a generic constraint failure.
        """
        student_exists = self._conn.execute(
            "SELECT 1 FROM students WHERE student_id = ?", (grade.student.student_id,)
        ).fetchone()
        if student_exists is None:
            return StudentNotFoundError(
                f"No student with id {grade.student.student_id!r}.",
                student_id=grade.student.student_id,
            )
        return CourseNotFoundError(
            f"No course with id {grade.course.course_id!r}.", course_id=grade.course.course_id
        )

    def get_grade(self, grade_id: int) -> Grade:
        """Fetch one grade. See :meth:`GradeStore.get_grade`."""
        row = self._conn.execute(f"{_GRADE_SELECT} AND g.grade_id = ?", (grade_id,)).fetchone()
        if row is None:
            raise GradeNotFoundError(f"No grade with id {grade_id}.", grade_id=grade_id)
        return self._to_grade(row)

    def update_grade(self, grade: Grade) -> None:
        """Overwrite a grade's mutable fields. See :meth:`GradeStore.update_grade`."""
        if grade.grade_id is None:
            raise ValidationError("Cannot update a grade that has not been saved yet.")

        cursor = self._conn.execute(
            "UPDATE grades SET score = ?, date = ?, notes = ?, title = ?, weight = ?,"  # noqa: S608
            f" updated_at = {_NOW} WHERE grade_id = ? AND deleted_at IS NULL",
            (grade.score, grade.date, grade.notes, grade.title, grade.weight, grade.grade_id),
        )
        if cursor.rowcount == 0:
            raise GradeNotFoundError(f"No grade with id {grade.grade_id}.", grade_id=grade.grade_id)

    def delete_grade(self, grade_id: int) -> None:
        """Soft-delete a grade. See :meth:`GradeStore.delete_grade`."""
        cursor = self._conn.execute(
            f"UPDATE grades SET deleted_at = {_NOW} WHERE grade_id = ? AND deleted_at IS NULL",  # noqa: S608
            (grade_id,),
        )
        if cursor.rowcount == 0:
            raise GradeNotFoundError(f"No grade with id {grade_id}.", grade_id=grade_id)

    def get_student_grades(self, student_id: str) -> list[Grade]:
        """Return every live grade for a student, most recent first."""
        rows = self._conn.execute(
            f"{_GRADE_SELECT} AND g.student_id = ? ORDER BY g.date DESC, g.grade_id DESC",
            (student_id,),
        )
        return [self._to_grade(r) for r in rows]

    def get_course_grades(self, course_id: str) -> list[Grade]:
        """Return every live grade for a course, most recent first."""
        rows = self._conn.execute(
            f"{_GRADE_SELECT} AND g.course_id = ? ORDER BY g.date DESC, g.grade_id DESC",
            (course_id,),
        )
        return [self._to_grade(r) for r in rows]

    def get_all_grades(self) -> list[Grade]:
        """Return every live grade, most recent first."""
        rows = self._conn.execute(f"{_GRADE_SELECT} ORDER BY g.date DESC, g.grade_id DESC")
        return [self._to_grade(r) for r in rows]
