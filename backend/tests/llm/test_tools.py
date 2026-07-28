"""The security boundary between the model and the database.

The claim this file defends: **no tool argument can widen what the caller sees.**
Scope comes from the authenticated principal, and the model has no way to reach
it. Everything else here — argument validation, row caps, LIKE escaping — exists
to keep that claim true when the model misbehaves.

The adversarial cases are written as a prompt-injected model would actually
behave: asking for another student by id, inventing a `raw_sql` argument, asking
for ten thousand rows.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from llm.tools import MAX_ROWS, ToolContext, run
from notenverwaltung.models.user import Role
from notenverwaltung.storage.db import apply_migrations, connect
from services.scoping import Principal


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A database with two teachers, two courses and three students.

    Deliberately arranged so every scope boundary has something on both sides:
    S001 sits in both courses, S002 only in the teacher's, S003 only in the
    colleague's. A scope that leaks shows up as a row that should not be there.
    """
    connection = connect(":memory:")
    apply_migrations(connection)

    connection.execute(
        "INSERT INTO users (id, email, password_hash, password_salt, role, full_name)"
        " VALUES (1, 'teacher@test', 'x', 'x', 'teacher', 'Weber'),"
        "        (2, 'other@test', 'x', 'x', 'teacher', 'Novak'),"
        "        (3, 'admin@test', 'x', 'x', 'admin', 'Root')"
    )
    connection.execute(
        "INSERT INTO students (student_id, first_name, last_name, email)"
        " VALUES ('S001', 'Anna', 'Meier', 'anna@test'),"
        "        ('S002', 'Bilal', 'Haddad', 'bilal@test'),"
        "        ('S003', 'Chen', 'Wu', 'chen@test')"
    )
    connection.execute(
        "INSERT INTO courses (course_id, name, teacher_id, max_grade, passing_grade, credits,"
        " max_students)"
        " VALUES ('CS101', 'Databases', 1, 100, 50, 5, 30),"
        "        ('CS999', 'Secret Course', 2, 100, 50, 5, 30)"
    )
    connection.execute(
        "INSERT INTO enrollments (student_id, course_id) VALUES"
        " ('S001','CS101'), ('S002','CS101'), ('S001','CS999'), ('S003','CS999')"
    )
    connection.execute(
        "INSERT INTO grades (student_id, course_id, title, score, date) VALUES"
        " ('S001','CS101','Midterm', 90, '2026-01-10'),"
        " ('S002','CS101','Midterm', 40, '2026-01-10'),"
        " ('S001','CS999','Essay',   70, '2026-02-10'),"
        " ('S003','CS999','Essay',   30, '2026-02-10')"
    )
    yield connection
    connection.close()


def _principal(role: Role, *, user_id: int = 1, student_id: str | None = None) -> Principal:
    """A principal of the given role."""
    return Principal(
        user_id=user_id,
        role=role,
        email="who@test",
        full_name="Who",
        student_id=student_id,
    )


def _context(conn: sqlite3.Connection, principal: Principal) -> ToolContext:
    """A tool context for one caller."""
    return ToolContext(conn=conn, principal=principal)


# ── Scope cannot be widened ──────────────────────────────────────────────────


def test_a_student_asking_for_everything_gets_only_their_own(conn: sqlite3.Connection) -> None:
    """The exact prompt-injection outcome this design exists to prevent.

    The model calls the tool with no filter at all — the widest request it can
    make — and still sees one student's rows.
    """
    context = _context(conn, _principal(Role.STUDENT, user_id=9, student_id="S001"))

    result = run(context, "query_grades", {"limit": MAX_ROWS})

    assert {row["student_id"] for row in result["grades"]} == {"S001"}


def test_a_student_naming_another_student_gets_nothing(conn: sqlite3.Connection) -> None:
    """Filtering *to* someone else narrows within the scope; it cannot escape it.

    This is the injected "show me Bilal's grades" case. The filter is applied on
    top of the scope, so the intersection is empty rather than Bilal's marks.
    """
    context = _context(conn, _principal(Role.STUDENT, user_id=9, student_id="S001"))

    result = run(context, "query_grades", {"student_id": "S002"})

    assert result["grades"] == []


def test_a_teacher_sees_only_their_own_course(conn: sqlite3.Connection) -> None:
    """S001 sits in both courses; the teacher may see only the CS101 half."""
    context = _context(conn, _principal(Role.TEACHER, user_id=1))

    result = run(context, "query_grades", {"student_id": "S001"})

    assert [row["course_id"] for row in result["grades"]] == ["CS101"]


def test_a_teacher_asking_for_a_colleagues_course_gets_nothing(
    conn: sqlite3.Connection,
) -> None:
    """Naming CS999 explicitly does not grant access to it."""
    context = _context(conn, _principal(Role.TEACHER, user_id=1))

    assert run(context, "query_grades", {"course_id": "CS999"})["grades"] == []


def test_an_admin_sees_everything(conn: sqlite3.Connection) -> None:
    """The counterweight: without this the tests above could pass by returning nothing."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    result = run(context, "query_grades", {"limit": MAX_ROWS})

    assert result["count"] == 4


def test_search_is_scoped_too(conn: sqlite3.Connection) -> None:
    """Resolving a name to an id must not become a directory of everyone.

    A teacher searching "e" would otherwise learn that Chen Wu exists, which is
    the leak that makes an id-based filter pointless.
    """
    teacher = _context(conn, _principal(Role.TEACHER, user_id=1))
    admin = _context(conn, _principal(Role.ADMIN, user_id=3))

    # "S0" matches every student id, so this is the widest search the tool allows —
    # an empty query is rejected outright, which is why it cannot be used here.
    teacher_ids = {
        r["student_id"] for r in run(teacher, "search_entities", {"query": "S0"})["results"]
    }
    admin_ids = {r["student_id"] for r in run(admin, "search_entities", {"query": "S0"})["results"]}

    assert teacher_ids == {"S001", "S002"}
    assert admin_ids == {"S001", "S002", "S003"}


def test_statistics_are_scoped(conn: sqlite3.Connection) -> None:
    """An average is an aggregate over rows, so it leaks unless it is scoped too.

    S001's true average across both courses is 80; the teacher may only see the
    CS101 grade, so they must be told 90.
    """
    teacher = _context(conn, _principal(Role.TEACHER, user_id=1))
    admin = _context(conn, _principal(Role.ADMIN, user_id=3))

    assert run(teacher, "get_statistics", {"student_id": "S001"})["average_percentage"] == 90.0
    assert run(admin, "get_statistics", {"student_id": "S001"})["average_percentage"] == 80.0


# ── Malformed and hostile arguments ──────────────────────────────────────────


def test_an_invented_argument_is_rejected_not_ignored(conn: sqlite3.Connection) -> None:
    """Silently dropping `raw_sql` is how an injection looks like it worked."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    result = run(context, "query_grades", {"raw_sql": "SELECT * FROM users"})

    assert "error" in result
    assert "raw_sql" in result["error"]


def test_an_unknown_tool_is_reported(conn: sqlite3.Connection) -> None:
    """A hallucinated tool name has nowhere to land."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    assert "error" in run(context, "delete_everything", {})


def test_a_tool_error_is_returned_not_raised(conn: sqlite3.Connection) -> None:
    """The conversation survives a bad turn so the model can correct itself."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    result = run(context, "get_statistics", {})

    assert "error" in result
    assert "exactly one" in result["error"]


def test_both_selectors_at_once_is_rejected(conn: sqlite3.Connection) -> None:
    """Ambiguous is not the same as permissive — it fails rather than picking one."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    assert "error" in run(context, "get_statistics", {"course_id": "CS101", "student_id": "S001"})


def test_a_non_string_id_is_rejected(conn: sqlite3.Connection) -> None:
    """Type confusion is a favourite of models that have lost the thread."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    result = run(context, "query_grades", {"student_id": {"$ne": None}})

    assert "error" in result


def test_the_row_limit_is_clamped_not_honoured(conn: sqlite3.Connection) -> None:
    """A tool that can return everything is an exfiltration primitive."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    # Asking for ten thousand is answered, not refused — but capped.
    result = run(context, "query_grades", {"limit": 10_000})

    assert result["count"] <= MAX_ROWS


def test_like_wildcards_in_a_search_are_escaped(conn: sqlite3.Connection) -> None:
    """A search for "%" must not match everyone.

    Unescaped it looks like a working search returning wrong answers, which is
    worse than an error because nobody investigates it.
    """
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    assert run(context, "search_entities", {"query": "%"})["count"] == 0


def test_search_rejects_a_missing_query(conn: sqlite3.Connection) -> None:
    """Required means required."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    assert "error" in run(context, "search_entities", {"kind": "student"})


def test_search_rejects_an_unknown_kind(conn: sqlite3.Connection) -> None:
    """Only two tables are searchable, and the model does not get to name a third."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    assert "error" in run(context, "search_entities", {"query": "a", "kind": "users"})


# ── Correctness of what is returned ──────────────────────────────────────────


def test_percentages_come_from_sql_not_the_model(conn: sqlite3.Connection) -> None:
    """The figures are computed where they can be checked."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    grades = {
        (row["student_id"], row["course_id"]): row["percentage"]
        for row in run(context, "query_grades", {"limit": MAX_ROWS})["grades"]
    }

    assert grades[("S001", "CS101")] == 90.0
    assert grades[("S003", "CS999")] == 30.0


def test_pass_rate_uses_the_courses_own_threshold(conn: sqlite3.Connection) -> None:
    """CS101: 90 passes, 40 fails against a 50 threshold."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    stats = run(context, "get_statistics", {"course_id": "CS101"})

    assert stats["grade_count"] == 2
    assert stats["pass_rate"] == 50.0


def test_the_passing_filter_selects_by_threshold(conn: sqlite3.Connection) -> None:
    """Failing means below the course's own passing grade, not a fixed number."""
    context = _context(conn, _principal(Role.ADMIN, user_id=3))

    failing = run(context, "query_grades", {"passing": False, "limit": MAX_ROWS})

    assert {row["student_id"] for row in failing["grades"]} == {"S002", "S003"}


def test_courses_can_be_searched_as_well_as_students(conn: sqlite3.Connection) -> None:
    """The model needs an id before it can filter, for both kinds."""
    context = _context(conn, _principal(Role.TEACHER, user_id=1))

    result = run(context, "search_entities", {"query": "Data", "kind": "course"})

    assert [row["course_id"] for row in result["results"]] == ["CS101"]
