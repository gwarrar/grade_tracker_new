"""Row-level access scopes.

Tests the policy in isolation and then executes the generated SQL against a real
database, because a scope that composes cleanly but selects the wrong rows is worse
than one that fails to compile.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from notenverwaltung.models import Role
from notenverwaltung.storage.scope import ALLOW_ALL, DENY_ALL, Scope
from services.scoping import (
    Principal,
    can_write_course,
    course_scope,
    grade_scope,
    student_scope,
    user_scope,
)

TEACHER_ID = 10
OTHER_TEACHER_ID = 11


def principal(role: Role, *, user_id: int = 1, student_id: str | None = None) -> Principal:
    """Build a principal for a role."""
    return Principal(
        user_id=user_id, role=role, email="a@b.co", full_name="Test", student_id=student_id
    )


@pytest.fixture
def populated(sqlite_conn: sqlite3.Connection) -> sqlite3.Connection:
    """Two teachers, three students, two courses, three grades.

    The smallest arrangement in which "sees only their own" can actually fail. With
    one teacher and one student, an over-broad query returns exactly the right rows
    by accident.
    """
    for uid, email, role in (
        (TEACHER_ID, "t1@x.co", "teacher"),
        (OTHER_TEACHER_ID, "t2@x.co", "teacher"),
    ):
        sqlite_conn.execute(
            "INSERT INTO users (id, email, password_hash, password_salt, role, full_name)"
            " VALUES (?, ?, 'h', 's', ?, 'T')",
            (uid, email, role),
        )
    for sid, email in (("S001", "a@x.co"), ("S002", "b@x.co"), ("S003", "c@x.co")):
        sqlite_conn.execute(
            "INSERT INTO students (student_id, first_name, last_name, email)"
            " VALUES (?, 'F', 'L', ?)",
            (sid, email),
        )
    sqlite_conn.execute(
        "INSERT INTO courses (course_id, name, teacher_id) VALUES ('MINE', 'Mine', ?)",
        (TEACHER_ID,),
    )
    sqlite_conn.execute(
        "INSERT INTO courses (course_id, name, teacher_id) VALUES ('THEIRS', 'Theirs', ?)",
        (OTHER_TEACHER_ID,),
    )
    # S001 in both courses, S002 only in the other teacher's, S003 in neither.
    for sid, cid in (("S001", "MINE"), ("S001", "THEIRS"), ("S002", "THEIRS")):
        sqlite_conn.execute(
            "INSERT INTO enrollments (student_id, course_id) VALUES (?, ?)", (sid, cid)
        )
    grade = "INSERT INTO grades (student_id, course_id, score, date) VALUES (?, ?, ?, '2026-01-01')"
    sqlite_conn.execute(grade, ("S001", "MINE", 80))
    sqlite_conn.execute(grade, ("S001", "THEIRS", 70))
    sqlite_conn.execute(grade, ("S002", "THEIRS", 60))
    return sqlite_conn


def select(conn: sqlite3.Connection, table: str, scope: Scope, column: str) -> set[Any]:
    """Run a scoped query and return the matching values."""
    rows = conn.execute(f"SELECT {column} FROM {table} WHERE {scope.sql}", scope.params)  # noqa: S608
    return {row[0] for row in rows}


class TestScopeComposition:
    def test_deny_all_is_the_default_posture(self) -> None:
        """A forgotten filter must produce an empty result, not every row. Empty
        results get reported; over-broad ones do not."""
        assert DENY_ALL.sql == "1=0"

    def test_and_drops_redundant_allow_all(self) -> None:
        restricted = Scope("x = ?", (1,))
        assert (ALLOW_ALL & restricted) == restricted
        assert (restricted & ALLOW_ALL) == restricted

    def test_and_combines_both_conditions_and_their_params(self) -> None:
        combined = Scope("a = ?", (1,)) & Scope("b = ?", (2,))
        assert combined.sql == "(a = ?) AND (b = ?)"
        assert combined.params == (1, 2)

    def test_is_unrestricted_only_for_allow_all(self) -> None:
        assert ALLOW_ALL.is_unrestricted
        assert not DENY_ALL.is_unrestricted


class TestColumnGuard:
    @pytest.mark.parametrize("column", ["g.course_id", "course_id", "c_1"])
    def test_accepts_identifiers(self, column: str) -> None:
        assert course_scope(principal(Role.TEACHER), column)

    @pytest.mark.parametrize(
        "column", ["course_id; DROP TABLE users", "1=1 OR x", "col--", "a.b.c", ""]
    )
    def test_rejects_anything_else(self, column: str) -> None:
        """Never reachable today -- every caller passes a literal. It exists so that
        stays an enforced property rather than an unwritten rule, in the one module
        where relying on one would be worst."""
        with pytest.raises(ValueError, match="Unsafe column"):
            course_scope(principal(Role.TEACHER), column)


class TestCourseScope:
    def test_admin_sees_every_course(self, populated: sqlite3.Connection) -> None:
        scope = course_scope(principal(Role.ADMIN))
        assert select(populated, "courses", scope, "course_id") == {"MINE", "THEIRS"}

    def test_teacher_sees_only_their_own(self, populated: sqlite3.Connection) -> None:
        scope = course_scope(principal(Role.TEACHER, user_id=TEACHER_ID))
        assert select(populated, "courses", scope, "course_id") == {"MINE"}

    def test_student_sees_only_enrolled_courses(self, populated: sqlite3.Connection) -> None:
        scope = course_scope(principal(Role.STUDENT, student_id="S002"))
        assert select(populated, "courses", scope, "course_id") == {"THEIRS"}

    def test_an_account_with_no_student_record_sees_nothing(
        self, populated: sqlite3.Connection
    ) -> None:
        """The account exists but has no academic identity to scope by, so denying
        everything is the correct answer rather than a bug."""
        scope = course_scope(principal(Role.STUDENT, student_id=None))
        assert scope == DENY_ALL
        assert select(populated, "courses", scope, "course_id") == set()


class TestStudentScope:
    def test_admin_sees_every_student(self, populated: sqlite3.Connection) -> None:
        scope = student_scope(principal(Role.ADMIN))
        assert select(populated, "students", scope, "student_id") == {"S001", "S002", "S003"}

    def test_teacher_sees_only_students_in_their_courses(
        self, populated: sqlite3.Connection
    ) -> None:
        scope = student_scope(principal(Role.TEACHER, user_id=TEACHER_ID))
        assert select(populated, "students", scope, "student_id") == {"S001"}

    def test_student_sees_only_themselves(self, populated: sqlite3.Connection) -> None:
        scope = student_scope(principal(Role.STUDENT, student_id="S001"))
        assert select(populated, "students", scope, "student_id") == {"S001"}

    def test_an_unenrolled_student_is_invisible_to_teachers(
        self, populated: sqlite3.Connection
    ) -> None:
        scope = student_scope(principal(Role.TEACHER, user_id=OTHER_TEACHER_ID))
        assert "S003" not in select(populated, "students", scope, "student_id")


class TestGradeScope:
    def test_admin_sees_every_grade(self, populated: sqlite3.Connection) -> None:
        scope = grade_scope(principal(Role.ADMIN))
        assert len(select(populated, "grades", scope, "grade_id")) == 3

    def test_student_sees_all_of_their_own_grades(self, populated: sqlite3.Connection) -> None:
        scope = grade_scope(principal(Role.STUDENT, student_id="S001"))
        assert select(populated, "grades", scope, "score") == {80.0, 70.0}

    def test_a_teacher_cannot_read_a_shared_students_other_grades(
        self, populated: sqlite3.Connection
    ) -> None:
        """S001 sits in both courses. Their mark from the other teacher's course must
        stay invisible -- which is exactly why a grade requires *both* its student and
        its course to be in scope, not either."""
        scope = grade_scope(principal(Role.TEACHER, user_id=TEACHER_ID))
        assert select(populated, "grades", scope, "score") == {80.0}

    def test_a_teacher_sees_every_grade_in_their_own_course(
        self, populated: sqlite3.Connection
    ) -> None:
        scope = grade_scope(principal(Role.TEACHER, user_id=OTHER_TEACHER_ID))
        assert select(populated, "grades", scope, "score") == {70.0, 60.0}


class TestUserScope:
    def test_admin_sees_every_account(self, populated: sqlite3.Connection) -> None:
        scope = user_scope(principal(Role.ADMIN))
        assert len(select(populated, "users", scope, "id")) == 2

    def test_everyone_else_sees_only_themselves(self, populated: sqlite3.Connection) -> None:
        scope = user_scope(principal(Role.TEACHER, user_id=TEACHER_ID))
        assert select(populated, "users", scope, "id") == {TEACHER_ID}


class TestWritePermission:
    def test_admin_may_write_any_course(self) -> None:
        assert can_write_course(principal(Role.ADMIN), OTHER_TEACHER_ID)

    def test_teacher_may_write_only_their_own(self) -> None:
        teacher = principal(Role.TEACHER, user_id=TEACHER_ID)
        assert can_write_course(teacher, TEACHER_ID)
        assert not can_write_course(teacher, OTHER_TEACHER_ID)

    def test_student_may_never_write(self) -> None:
        """Read access is broader than write: a student can see a course they are
        enrolled on and must not be able to rename it."""
        assert not can_write_course(principal(Role.STUDENT, student_id="S001"), None)

    def test_an_unowned_course_is_not_writable_by_a_teacher(self) -> None:
        assert not can_write_course(principal(Role.TEACHER, user_id=TEACHER_ID), None)
