"""Student, course and enrolment use cases.

One module because the three are read together on almost every screen — a course
list wants enrolment counts, a student detail wants their courses — and splitting
them would mean three services importing each other.

Every read applies the caller's scope; every write records an audit entry inside the
same transaction as the change.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from notenverwaltung.exceptions import (
    CourseFullError,
    CourseNotFoundError,
    DuplicateEntryError,
    ForbiddenError,
    StudentNotFoundError,
    ValidationError,
)
from notenverwaltung.models import Course, Enrollment, EnrollmentStatus, Student
from notenverwaltung.storage import SqliteGradeStore, transaction
from notenverwaltung.storage.queries import Page, SortSpec, exists, paginate
from notenverwaltung.storage.scope import Scope
from services import audit
from services.scoping import Principal, can_write_course, course_scope, student_scope

STUDENT_SORTABLE = {
    "id": "s.student_id",
    "first_name": "s.first_name",
    "last_name": "s.last_name",
    "email": "s.email",
    "created": "s.created_at",
}

COURSE_SORTABLE = {
    "id": "c.course_id",
    "name": "c.name",
    "term": "c.term",
    "credits": "c.credits",
    "created": "c.created_at",
}

# Counted in the projection rather than fetched per row: a list of 200 courses would
# otherwise issue 400 follow-up queries to show two numbers per row.
_COURSE_SELECT = (
    "c.course_id, c.name, c.max_grade, c.passing_grade, c.max_students,"
    " c.teacher_id, c.term, c.credits, c.created_at, c.updated_at,"
    " u.full_name AS teacher_name,"
    " (SELECT COUNT(*) FROM enrollments e"
    "   WHERE e.course_id = c.course_id AND e.status = 'active') AS enrolled_count,"
    " (SELECT COUNT(DISTINCT g.student_id) FROM grades g"
    "   WHERE g.course_id = c.course_id AND g.deleted_at IS NULL) AS graded_count"
)
_COURSE_FROM = "courses AS c LEFT JOIN users AS u ON u.id = c.teacher_id"

_STUDENT_SELECT = (
    "s.student_id, s.first_name, s.last_name, s.email, s.user_id,"
    " s.created_at, s.updated_at,"
    " (SELECT COUNT(*) FROM enrollments e"
    "   WHERE e.student_id = s.student_id AND e.status = 'active') AS enrolled_count,"
    " (SELECT COUNT(*) FROM grades g"
    "   WHERE g.student_id = s.student_id AND g.deleted_at IS NULL) AS grade_count"
)
_STUDENT_FROM = "students AS s"


class DirectoryService:
    """Students, courses and the enrolments joining them."""

    def __init__(self, conn: sqlite3.Connection, principal: Principal) -> None:
        """Bind the service to a request.

        Args:
            conn: The request's connection.
            principal: The authenticated caller.
        """
        self._conn = conn
        self._principal = principal
        self._store = SqliteGradeStore(conn)

    # ── Students ─────────────────────────────────────────────────────────────
    def list_students(
        self,
        *,
        page: int = 1,
        size: int = 25,
        sort: str | None = None,
        search: str | None = None,
        course_id: str | None = None,
    ) -> Page[dict[str, Any]]:
        """List students the caller may see.

        Args:
            page: 1-based page number.
            size: Rows per page.
            sort: A field from :data:`STUDENT_SORTABLE`, optionally ``-`` prefixed.
            search: Free text matched against name and email.
            course_id: Restrict to students enrolled on one course.

        Returns:
            One page of student dictionaries.
        """
        extra = None
        if course_id:
            extra = Scope(
                "s.student_id IN (SELECT student_id FROM enrollments WHERE course_id = ?)",
                (course_id,),
            )

        rows, total = paginate(
            self._conn,
            select=_STUDENT_SELECT,
            from_clause=_STUDENT_FROM,
            scope=student_scope(self._principal, "s.student_id"),
            sort=SortSpec.parse(sort, STUDENT_SORTABLE, "last_name"),
            page=page,
            size=size,
            search=search,
            search_columns=["s.first_name", "s.last_name", "s.email", "s.student_id"],
            extra=extra,
        )
        return Page(items=[dict(r) for r in rows], total=total, page=page, size=size)

    def get_student(self, student_id: str) -> dict[str, Any]:
        """Fetch one student the caller may see.

        Args:
            student_id: Which student.

        Returns:
            The student as a dictionary.

        Raises:
            StudentNotFoundError: If they do not exist **or** are outside the caller's
                scope. Reported identically, so a 403 cannot be used to confirm that a
                record with that id exists.
        """
        scope = student_scope(self._principal, "s.student_id")
        row = self._conn.execute(
            f"SELECT {_STUDENT_SELECT} FROM {_STUDENT_FROM}"  # noqa: S608
            f" WHERE s.student_id = ? AND ({scope.sql})",
            (student_id, *scope.params),
        ).fetchone()
        if row is None:
            raise StudentNotFoundError(f"No student with id {student_id!r}.", student_id=student_id)
        return dict(row)

    def create_student(
        self, *, student_id: str, first_name: str, last_name: str, email: str
    ) -> dict[str, Any]:
        """Add a student.

        Args:
            student_id: Institution-assigned identifier.
            first_name: Given name.
            last_name: Family name.
            email: Contact address.

        Returns:
            The stored student.

        Raises:
            DuplicateEntryError: If the id or email is taken.
            ValidationError: If a field is invalid.
        """
        student = Student(student_id, first_name, last_name, email)
        with transaction(self._conn):
            self._store.add_student(student)
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="student",
                entity_id=student.student_id,
                action="create",
                after=student.to_dict(),
            )
        return self.get_student(student.student_id)

    def update_student(self, student_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Change a student's details.

        Args:
            student_id: Which student.
            changes: Any of ``first_name``, ``last_name``, ``email``.

        Returns:
            The updated student.

        Raises:
            StudentNotFoundError: If they do not exist or are outside the caller's scope.
            DuplicateEntryError: If the new email is taken.
            ValidationError: If a new value is invalid.
        """
        self.get_student(student_id)  # scope check before any write
        before = self._store.get_student(student_id)

        updated = Student(
            student_id=student_id,
            first_name=str(changes.get("first_name", before.first_name)),
            last_name=str(changes.get("last_name", before.last_name)),
            email=str(changes.get("email", before.email)),
            user_id=before.user_id,
        )
        with transaction(self._conn):
            try:
                self._store.update_student(updated)
            except sqlite3.IntegrityError as exc:
                raise DuplicateEntryError(
                    f"Email {updated.email!r} is already in use.", email=updated.email
                ) from exc
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="student",
                entity_id=student_id,
                action="update",
                before=before.to_dict(),
                after=updated.to_dict(),
            )
        return self.get_student(student_id)

    def delete_student(self, student_id: str) -> None:
        """Remove a student and, by cascade, their grades and enrolments.

        Args:
            student_id: Which student.

        Raises:
            StudentNotFoundError: If they do not exist or are outside the caller's scope.
        """
        self.get_student(student_id)
        before = self._store.get_student(student_id)
        with transaction(self._conn):
            self._store.delete_student(student_id)
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="student",
                entity_id=student_id,
                action="delete",
                before=before.to_dict(),
            )

    # ── Courses ──────────────────────────────────────────────────────────────
    def list_courses(
        self,
        *,
        page: int = 1,
        size: int = 25,
        sort: str | None = None,
        search: str | None = None,
        term: str | None = None,
    ) -> Page[dict[str, Any]]:
        """List courses the caller may see.

        Args:
            page: 1-based page number.
            size: Rows per page.
            sort: A field from :data:`COURSE_SORTABLE`, optionally ``-`` prefixed.
            search: Free text matched against name and id.
            term: Restrict to one academic term.

        Returns:
            One page of course dictionaries, each carrying enrolment counts.
        """
        rows, total = paginate(
            self._conn,
            select=_COURSE_SELECT,
            from_clause=_COURSE_FROM,
            scope=course_scope(self._principal, "c.course_id"),
            sort=SortSpec.parse(sort, COURSE_SORTABLE, "id"),
            page=page,
            size=size,
            search=search,
            search_columns=["c.name", "c.course_id"],
            extra=Scope("c.term = ?", (term,)) if term else None,
        )
        return Page(items=[dict(r) for r in rows], total=total, page=page, size=size)

    def get_course(self, course_id: str) -> dict[str, Any]:
        """Fetch one course the caller may see.

        Args:
            course_id: Which course.

        Returns:
            The course as a dictionary.

        Raises:
            CourseNotFoundError: If it does not exist or is outside the caller's scope.
        """
        scope = course_scope(self._principal, "c.course_id")
        row = self._conn.execute(
            f"SELECT {_COURSE_SELECT} FROM {_COURSE_FROM}"  # noqa: S608
            f" WHERE c.course_id = ? AND ({scope.sql})",
            (course_id, *scope.params),
        ).fetchone()
        if row is None:
            raise CourseNotFoundError(f"No course with id {course_id!r}.", course_id=course_id)
        return dict(row)

    def create_course(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Add a course.

        Args:
            payload: Course fields. A teacher creating a course owns it by default,
                since the alternative is a course they immediately cannot see.

        Returns:
            The stored course.

        Raises:
            DuplicateEntryError: If the id is taken.
            ValidationError: If a field is invalid.
        """
        teacher_id = payload.get("teacher_id")
        if teacher_id is None and not self._principal.is_admin:
            teacher_id = self._principal.user_id

        course = Course(
            course_id=str(payload["course_id"]),
            name=str(payload["name"]),
            max_grade=float(payload.get("max_grade", 100.0)),
            passing_grade=float(payload.get("passing_grade", 50.0)),
            max_students=int(payload.get("max_students", 30)),
            teacher_id=teacher_id,
            term=payload.get("term"),
            credits=float(payload.get("credits", 1.0)),
        )
        with transaction(self._conn):
            self._store.add_course(course)
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="course",
                entity_id=course.course_id,
                action="create",
                after=course.to_dict(),
            )
        return self.get_course(course.course_id)

    def update_course(self, course_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Change a course's details.

        Args:
            course_id: Which course.
            changes: Any writable course field.

        Returns:
            The updated course.

        Raises:
            CourseNotFoundError: If it does not exist or is outside the caller's scope.
            ForbiddenError: If the caller does not own it.
            ValidationError: If a new value is invalid, including a passing grade
                above the maximum.
        """
        current = self.get_course(course_id)
        self._assert_can_write(current)
        before = self._store.get_course(course_id)

        updated = Course(
            course_id=course_id,
            name=str(changes.get("name", before.name)),
            max_grade=float(changes.get("max_grade", before.max_grade)),
            passing_grade=float(changes.get("passing_grade", before.passing_grade)),
            max_students=int(changes.get("max_students", before.max_students)),
            teacher_id=changes.get("teacher_id", before.teacher_id),
            term=changes.get("term", before.term),
            credits=float(changes.get("credits", before.credits)),
        )

        # Only an administrator may hand a course to somebody else -- otherwise a
        # teacher could give away a course and lose access to their own grade history.
        if updated.teacher_id != before.teacher_id and not self._principal.is_admin:
            raise ForbiddenError("Only an administrator can reassign a course.")

        with transaction(self._conn):
            self._store.update_course(updated)
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="course",
                entity_id=course_id,
                action="update",
                before=before.to_dict(),
                after=updated.to_dict(),
            )
        return self.get_course(course_id)

    def delete_course(self, course_id: str) -> None:
        """Remove a course and, by cascade, its grades and enrolments.

        Args:
            course_id: Which course.

        Raises:
            CourseNotFoundError: If it does not exist or is outside the caller's scope.
            ForbiddenError: If the caller does not own it.
        """
        current = self.get_course(course_id)
        self._assert_can_write(current)
        before = self._store.get_course(course_id)

        with transaction(self._conn):
            self._store.delete_course(course_id)
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="course",
                entity_id=course_id,
                action="delete",
                before=before.to_dict(),
            )

    # ── Enrolments ───────────────────────────────────────────────────────────
    def list_enrollments(self, course_id: str) -> list[dict[str, Any]]:
        """List a course's enrolments, including students with no grades yet.

        The distinction the coursework schema could not express: a student who is
        enrolled but not yet assessed is a real state, and a register that omits them
        is wrong.

        Args:
            course_id: Which course.

        Returns:
            One entry per enrolment the caller may see, ordered by name. A teacher who
            owns the course, and any admin, get the whole register; a student gets
            only their own row.

        Raises:
            CourseNotFoundError: If the course is outside the caller's scope.
        """
        # `get_course` proves the *course* is visible, which for a student means only
        # that they are enrolled on it. It says nothing about the *students* in it --
        # so without the scope below, an enrolled student read every classmate's name,
        # email and grade count off their own course page. This is the failure mode
        # `Scope` exists to prevent, and the query simply did not use one.
        self.get_course(course_id)
        scope = student_scope(self._principal, "e.student_id")
        # Only `scope.sql` is interpolated, and it is composed here rather than
        # supplied by a caller; every value still travels as a bound parameter.
        sql = (
            "SELECT e.student_id, e.course_id, e.status, e.enrolled_at, e.enrolled_by,"  # noqa: S608
            "       s.first_name, s.last_name, s.email,"
            "       (SELECT COUNT(*) FROM grades g WHERE g.student_id = e.student_id"
            "         AND g.course_id = e.course_id AND g.deleted_at IS NULL) AS grade_count"
            "  FROM enrollments e JOIN students s ON s.student_id = e.student_id"
            f" WHERE e.course_id = ? AND ({scope.sql})"
            " ORDER BY s.last_name, s.first_name"
        )
        rows = self._conn.execute(sql, (course_id, *scope.params))
        return [dict(row) for row in rows]

    def enroll(self, course_id: str, student_id: str) -> dict[str, Any]:
        """Enrol a student on a course.

        Args:
            course_id: Which course.
            student_id: Which student.

        Returns:
            The enrolment.

        Raises:
            CourseNotFoundError: If the course is outside the caller's scope.
            StudentNotFoundError: If the student does not exist.
            ForbiddenError: If the caller does not own the course.
            CourseFullError: If the course is at capacity.
            DuplicateEntryError: If the student is already enrolled.
        """
        course = self.get_course(course_id)
        self._assert_can_write(course)
        self._store.get_student(student_id)

        if int(course["enrolled_count"]) >= int(course["max_students"]):
            raise CourseFullError(
                f"{course_id} is at capacity.",
                course_id=course_id,
                capacity=course["max_students"],
            )

        enrollment = Enrollment(
            student_id=student_id, course_id=course_id, enrolled_by=self._principal.user_id
        )
        with transaction(self._conn):
            try:
                self._conn.execute(
                    "INSERT INTO enrollments (student_id, course_id, status, enrolled_by)"
                    " VALUES (?, ?, ?, ?)",
                    (student_id, course_id, str(enrollment.status), self._principal.user_id),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateEntryError(
                    f"{student_id} is already enrolled on {course_id}.",
                    student_id=student_id,
                    course_id=course_id,
                ) from exc
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="enrollment",
                entity_id=f"{student_id}:{course_id}",
                action="create",
                after=enrollment.to_dict(),
            )
        return enrollment.to_dict()

    def set_enrollment_status(self, course_id: str, student_id: str, status: str) -> dict[str, Any]:
        """Change an enrolment's status.

        Withdrawal is a status change rather than a deletion: grades earned before it
        must remain attached to something.

        Args:
            course_id: Which course.
            student_id: Which student.
            status: ``active``, ``withdrawn`` or ``completed``.

        Returns:
            The updated enrolment.

        Raises:
            CourseNotFoundError: If the course is outside the caller's scope.
            ForbiddenError: If the caller does not own the course.
            ValidationError: If the status is unknown or there is no such enrolment.
        """
        course = self.get_course(course_id)
        self._assert_can_write(course)

        row = self._conn.execute(
            "SELECT student_id, course_id, status, enrolled_at, enrolled_by FROM enrollments"
            " WHERE student_id = ? AND course_id = ?",
            (student_id, course_id),
        ).fetchone()
        if row is None:
            raise ValidationError(
                f"{student_id} is not enrolled on {course_id}.",
                student_id=student_id,
                course_id=course_id,
            )

        try:
            new_status = EnrollmentStatus(status)
        except ValueError as exc:
            raise ValidationError(
                f"Unknown enrolment status {status!r}.",
                field="status",
                allowed=[s.value for s in EnrollmentStatus],
            ) from exc

        before = Enrollment.from_row(row)
        updated = Enrollment(
            student_id=student_id,
            course_id=course_id,
            status=new_status,
            enrolled_at=before.enrolled_at,
            enrolled_by=before.enrolled_by,
        )

        with transaction(self._conn):
            self._conn.execute(
                "UPDATE enrollments SET status = ? WHERE student_id = ? AND course_id = ?",
                (str(updated.status), student_id, course_id),
            )
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="enrollment",
                entity_id=f"{student_id}:{course_id}",
                action="update",
                before=before.to_dict(),
                after=updated.to_dict(),
            )
        return updated.to_dict()

    def unenroll(self, course_id: str, student_id: str) -> None:
        """Remove an enrolment outright.

        Prefer :meth:`set_enrollment_status` with ``withdrawn`` for a student who
        left; this is for correcting a registration made in error.

        Args:
            course_id: Which course.
            student_id: Which student.

        Raises:
            CourseNotFoundError: If the course is outside the caller's scope.
            ForbiddenError: If the caller does not own the course.
            ValidationError: If there is no such enrolment.
        """
        course = self.get_course(course_id)
        self._assert_can_write(course)

        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM enrollments WHERE student_id = ? AND course_id = ?",
                (student_id, course_id),
            )
            if cursor.rowcount == 0:
                raise ValidationError(
                    f"{student_id} is not enrolled on {course_id}.",
                    student_id=student_id,
                    course_id=course_id,
                )
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="enrollment",
                entity_id=f"{student_id}:{course_id}",
                action="delete",
                before={"student_id": student_id, "course_id": course_id},
            )

    def student_courses(self, student_id: str) -> list[dict[str, Any]]:
        """List the courses a student is enrolled on.

        Args:
            student_id: Which student.

        Returns:
            One entry per enrolment, restricted to courses the caller may see.

        Raises:
            StudentNotFoundError: If the student is outside the caller's scope.
        """
        self.get_student(student_id)
        scope = course_scope(self._principal, "c.course_id")
        rows = self._conn.execute(
            "SELECT c.course_id, c.name, c.term, c.credits, c.max_grade, c.passing_grade,"  # noqa: S608
            "       e.status, e.enrolled_at"
            "  FROM enrollments e JOIN courses c ON c.course_id = e.course_id"
            f" WHERE e.student_id = ? AND ({scope.sql})"
            " ORDER BY c.name",
            (student_id, *scope.params),
        )
        return [dict(row) for row in rows]

    def _assert_can_write(self, course: dict[str, Any]) -> None:
        """Verify the caller may modify a course.

        Read access is deliberately broader than write access: a student can see a
        course they are enrolled on and must not be able to rename it.

        Args:
            course: The course record.

        Raises:
            ForbiddenError: If the caller does not own it and is not an administrator.
        """
        if not can_write_course(self._principal, course.get("teacher_id")):
            raise ForbiddenError("You do not own this course.", course_id=course.get("course_id"))

    def visible(self, table: str, column: str, value: str) -> bool:
        """Report whether a row is within the caller's scope.

        Args:
            table: ``"students"`` or ``"courses"``.
            column: The identifying column.
            value: The identifier.

        Returns:
            ``True`` if visible.
        """
        scope = (
            student_scope(self._principal, column)
            if table == "students"
            else course_scope(self._principal, column)
        )
        return exists(self._conn, table, column, value, scope)
