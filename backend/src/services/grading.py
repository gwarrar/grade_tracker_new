"""Grade use cases: record, amend, retire, and list within the caller's scope.

Owns the transaction boundary and the audit write, so a change and its trail commit
or roll back together.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from notenverwaltung.exceptions import ForbiddenError, GradeNotFoundError
from notenverwaltung.models import Grade
from notenverwaltung.storage import SqliteGradeStore, transaction
from notenverwaltung.storage.queries import Page, SortSpec, exists, paginate
from notenverwaltung.storage.scope import Scope
from services import audit
from services.scoping import Principal, course_scope, grade_scope

SORTABLE = {
    "date": "g.date",
    "score": "g.score",
    "student": "s.last_name",
    "course": "c.name",
    "title": "g.title",
    "created": "g.created_at",
}
"""Fields a client may sort by, mapped to real columns.

An allow-list because a sort column cannot be a bound parameter — it is interpolated,
so it must never come straight from the query string.
"""

_JOIN = (
    "grades AS g"
    " JOIN students AS s ON s.student_id = g.student_id"
    " JOIN courses AS c ON c.course_id = g.course_id"
)

_SELECT = (
    "g.grade_id, g.score, g.date, g.notes, g.title, g.weight, g.graded_by,"
    " g.created_at, g.updated_at,"
    " s.student_id, s.first_name, s.last_name,"
    " c.course_id, c.name AS course_name, c.max_grade, c.passing_grade"
)


class GradingService:
    """Recording and amending grades."""

    def __init__(self, conn: sqlite3.Connection, principal: Principal) -> None:
        """Bind the service to a request.

        Args:
            conn: The request's connection.
            principal: The authenticated caller, whose scope every read applies.
        """
        self._conn = conn
        self._principal = principal
        self._store = SqliteGradeStore(conn)

    @property
    def _scope(self) -> Scope:
        """The caller's grade visibility."""
        return grade_scope(self._principal, "g.student_id", "g.course_id")

    def list_grades(
        self,
        *,
        page: int = 1,
        size: int = 25,
        sort: str | None = None,
        search: str | None = None,
        student_id: str | None = None,
        course_id: str | None = None,
    ) -> Page[dict[str, Any]]:
        """List grades the caller may see.

        Args:
            page: 1-based page number.
            size: Rows per page.
            sort: A field from :data:`SORTABLE`, optionally prefixed with ``-``.
            search: Free text matched against student and course names.
            student_id: Restrict to one student.
            course_id: Restrict to one course.

        Returns:
            One page of grade dictionaries.
        """
        extra = Scope("g.deleted_at IS NULL")
        if student_id:
            extra = extra & Scope("g.student_id = ?", (student_id,))
        if course_id:
            extra = extra & Scope("g.course_id = ?", (course_id,))

        rows, total = paginate(
            self._conn,
            select=_SELECT,
            from_clause=_JOIN,
            scope=self._scope,
            sort=SortSpec.parse(sort, SORTABLE, "-date"),
            page=page,
            size=size,
            search=search,
            search_columns=["s.first_name", "s.last_name", "c.name", "g.title"],
            extra=extra,
        )
        return Page(items=[self._row_to_dict(r) for r in rows], total=total, page=page, size=size)

    def get_grade(self, grade_id: int) -> dict[str, Any]:
        """Fetch one grade the caller may see.

        Args:
            grade_id: Which grade.

        Returns:
            The grade as a dictionary.

        Raises:
            GradeNotFoundError: If it does not exist **or** is outside the caller's
                scope. The two are deliberately indistinguishable: a 403 would confirm
                that a grade with that id exists.
        """
        row = self._conn.execute(
            f"SELECT {_SELECT} FROM {_JOIN}"  # noqa: S608
            f" WHERE g.grade_id = ? AND g.deleted_at IS NULL AND ({self._scope.sql})",
            (grade_id, *self._scope.params),
        ).fetchone()
        if row is None:
            raise GradeNotFoundError(f"No grade with id {grade_id}.", grade_id=grade_id)
        return self._row_to_dict(row)

    def record(
        self,
        *,
        student_id: str,
        course_id: str,
        score: float,
        date: str,
        title: str = "",
        weight: float = 1.0,
        notes: str = "",
    ) -> dict[str, Any]:
        """Record a new grade.

        Args:
            student_id: Who is being graded.
            course_id: What they are being graded on.
            score: Points awarded.
            date: Award date, ISO or ``DD-MM-YYYY``.
            title: Optional assessment name.
            weight: Relative weight in the course average.
            notes: Optional remark.

        Returns:
            The stored grade.

        Raises:
            ForbiddenError: If the caller may not grade this course.
            StudentNotFoundError: If the student does not exist.
            CourseNotFoundError: If the course does not exist.
            ValidationError: If the score, weight or date is invalid.
        """
        self._assert_can_grade(course_id)

        student = self._store.get_student(student_id)
        course = self._store.get_course(course_id)
        grade = Grade(
            student=student,
            course=course,
            score=score,
            date=date,
            title=title,
            weight=weight,
            notes=notes,
            graded_by=self._principal.user_id,
        )

        with transaction(self._conn):
            stored = self._store.record_grade(grade)
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="grade",
                entity_id=str(stored.grade_id),
                action="create",
                after=stored.to_dict(),
            )
        return self.get_grade(stored.grade_id or 0)

    def amend(self, grade_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        """Change an existing grade.

        Args:
            grade_id: Which grade to change.
            changes: Any of ``score``, ``date``, ``title``, ``weight``, ``notes``.

        Returns:
            The updated grade.

        Raises:
            GradeNotFoundError: If it does not exist or is outside the caller's scope.
            ForbiddenError: If the caller may not grade this course.
            ValidationError: If a new value is invalid.
        """
        current = self.get_grade(grade_id)
        self._assert_can_grade(str(current["course_id"]))

        before = self._store.get_grade(grade_id)
        updated = Grade(
            student=before.student,
            course=before.course,
            score=float(changes.get("score", before.score)),
            date=str(changes.get("date", before.date)),
            title=str(changes.get("title", before.title)),
            weight=float(changes.get("weight", before.weight)),
            notes=str(changes.get("notes", before.notes)),
            grade_id=grade_id,
            graded_by=before.graded_by,
        )

        with transaction(self._conn):
            self._store.update_grade(updated)
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="grade",
                entity_id=str(grade_id),
                action="update",
                before=before.to_dict(),
                after=updated.to_dict(),
            )
        return self.get_grade(grade_id)

    def retire(self, grade_id: int) -> None:
        """Soft-delete a grade.

        The row is retained rather than removed: an altered mark is exactly the kind
        of change a student may later dispute.

        Args:
            grade_id: Which grade to retire.

        Raises:
            GradeNotFoundError: If it does not exist or is outside the caller's scope.
            ForbiddenError: If the caller may not grade this course.
        """
        current = self.get_grade(grade_id)
        self._assert_can_grade(str(current["course_id"]))
        before = self._store.get_grade(grade_id)

        with transaction(self._conn):
            self._store.delete_grade(grade_id)
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="grade",
                entity_id=str(grade_id),
                action="delete",
                before=before.to_dict(),
            )

    def history(self, grade_id: int) -> list[dict[str, Any]]:
        """Return a grade's change history.

        Args:
            grade_id: Which grade.

        Returns:
            Audit entries, most recent first.

        Raises:
            GradeNotFoundError: If the grade is outside the caller's scope. Checked
                first, so the trail cannot be used to read a grade indirectly.
        """
        self.get_grade(grade_id)
        return audit.history(self._conn, "grade", str(grade_id))

    def _assert_can_grade(self, course_id: str) -> None:
        """Verify the caller may write grades for a course.

        Args:
            course_id: The course in question.

        Raises:
            ForbiddenError: If the course is outside the caller's write scope.
        """
        if self._principal.is_admin:
            return
        if not exists(self._conn, "courses", "course_id", course_id, course_scope(self._principal)):
            raise ForbiddenError("You cannot grade this course.", course_id=course_id)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a joined row into the API's grade shape.

        Percentage and pass/fail are computed here rather than left to the client:
        two clients computing them independently is two chances to disagree with the
        report the same numbers appear in.
        """
        max_grade = row["max_grade"] or 1
        percentage = row["score"] / max_grade * 100
        return {
            "grade_id": row["grade_id"],
            "student_id": row["student_id"],
            "student_name": f"{row['first_name']} {row['last_name']}",
            "course_id": row["course_id"],
            "course_name": row["course_name"],
            "title": row["title"],
            "score": row["score"],
            "max_grade": row["max_grade"],
            "percentage": round(percentage, 2),
            "is_passing": row["score"] >= row["passing_grade"],
            "weight": row["weight"],
            "date": row["date"],
            "notes": row["notes"],
            "graded_by": row["graded_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
