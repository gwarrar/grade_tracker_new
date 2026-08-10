"""Schema constraints and the seed script.

Verifies the guarantees the database itself makes, independently of the models. The
models validate too — that redundancy is deliberate, because the database is the last
line of defence for anything written by a migration, a fixture, or a future service
that forgets.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from api.seed import seed
from notenverwaltung.storage import apply_migrations

#: Migration 010's own text, so the second spelling it has to recognise is pinned
#: against the exact string `json.dumps` produces rather than a copy of it.
_MIGRATION_TEXT = (
    Path(__file__).resolve().parents[2] / "migrations" / "010_grade_points.sql"
).read_text(encoding="utf-8")


class TestOrganizationTable:
    def test_holds_exactly_one_row(self, sqlite_conn: sqlite3.Connection) -> None:
        """The CHECK (id = 1) makes a second organisation impossible to insert, which
        is cheaper than defending against one everywhere it would be read."""
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute("INSERT INTO organization (id, name) VALUES (2, 'Other')")

    def test_is_seeded_by_the_migration(self, sqlite_conn: sqlite3.Connection) -> None:
        assert sqlite_conn.execute("SELECT COUNT(*) FROM organization").fetchone()[0] == 1

    def test_rejects_an_unknown_theme(self, sqlite_conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute("UPDATE organization SET default_theme = 'neon' WHERE id = 1")

    def test_the_background_columns_are_backfilled(self, sqlite_conn: sqlite3.Connection) -> None:
        """An ALTER without a DEFAULT would leave the seeded row NULL, and the
        frontend would render `--bg: null` over the whole application. These values
        must also match the shipped `--bg` in web/app/tokens.css, which is what
        renders in the moment before the branding response arrives."""
        row = sqlite_conn.execute(
            "SELECT color_background_light, color_background_dark FROM organization WHERE id = 1"
        ).fetchone()

        assert (row[0], row[1]) == ("#FBFBFA", "#08080A")


class TestUsersTable:
    def test_rejects_an_unknown_role(self, sqlite_conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute(
                "INSERT INTO users (email, password_hash, password_salt, role, full_name)"
                " VALUES ('a@b.co', 'h', 's', 'wizard', 'A')"
            )

    def test_email_uniqueness_ignores_case(self, sqlite_conn: sqlite3.Connection) -> None:
        """Anna@school.de and anna@school.de are one account, not two."""
        sqlite_conn.execute(
            "INSERT INTO users (email, password_hash, password_salt, role, full_name)"
            " VALUES ('Anna@School.de', 'h', 's', 'teacher', 'Anna')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute(
                "INSERT INTO users (email, password_hash, password_salt, role, full_name)"
                " VALUES ('anna@school.de', 'h', 's', 'teacher', 'Anna Again')"
            )


class TestCascades:
    @pytest.fixture
    def wired(self, sqlite_conn: sqlite3.Connection) -> sqlite3.Connection:
        sqlite_conn.execute(
            "INSERT INTO users (id, email, password_hash, password_salt, role, full_name)"
            " VALUES (1, 't@b.co', 'h', 's', 'teacher', 'T')"
        )
        sqlite_conn.execute(
            "INSERT INTO students (student_id, first_name, last_name, email, user_id)"
            " VALUES ('S1', 'A', 'B', 'a@b.co', 1)"
        )
        sqlite_conn.execute(
            "INSERT INTO courses (course_id, name, teacher_id) VALUES ('C1', 'Course', 1)"
        )
        sqlite_conn.execute("INSERT INTO enrollments (student_id, course_id) VALUES ('S1', 'C1')")
        sqlite_conn.execute(
            "INSERT INTO grades (student_id, course_id, score, date, graded_by)"
            " VALUES ('S1', 'C1', 80, '2026-01-01', 1)"
        )
        return sqlite_conn

    def test_deleting_a_user_keeps_the_academic_record(self, wired: sqlite3.Connection) -> None:
        """SET NULL, not CASCADE. Removing a login must not erase the grades that
        login happened to be attached to."""
        wired.execute("DELETE FROM users WHERE id = 1")

        assert wired.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 1
        assert wired.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 1
        assert wired.execute("SELECT user_id FROM students").fetchone()[0] is None
        assert wired.execute("SELECT teacher_id FROM courses").fetchone()[0] is None
        assert wired.execute("SELECT graded_by FROM grades").fetchone()[0] is None

    def test_deleting_a_student_removes_their_grades_and_enrolments(
        self, wired: sqlite3.Connection
    ) -> None:
        wired.execute("DELETE FROM students WHERE student_id = 'S1'")
        assert wired.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 0
        assert wired.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0] == 0

    def test_deleting_a_course_removes_its_grades_and_enrolments(
        self, wired: sqlite3.Connection
    ) -> None:
        wired.execute("DELETE FROM courses WHERE course_id = 'C1'")
        assert wired.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 0
        assert wired.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0] == 0


class TestEnrollments:
    def test_a_student_cannot_enrol_twice(self, sqlite_conn: sqlite3.Connection) -> None:
        sqlite_conn.execute(
            "INSERT INTO students (student_id, first_name, last_name, email)"
            " VALUES ('S1', 'A', 'B', 'a@b.co')"
        )
        sqlite_conn.execute("INSERT INTO courses (course_id, name) VALUES ('C1', 'Course')")
        sqlite_conn.execute("INSERT INTO enrollments (student_id, course_id) VALUES ('S1', 'C1')")

        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute(
                "INSERT INTO enrollments (student_id, course_id) VALUES ('S1', 'C1')"
            )

    def test_rejects_an_unknown_status(self, sqlite_conn: sqlite3.Connection) -> None:
        sqlite_conn.execute(
            "INSERT INTO students (student_id, first_name, last_name, email)"
            " VALUES ('S1', 'A', 'B', 'a@b.co')"
        )
        sqlite_conn.execute("INSERT INTO courses (course_id, name) VALUES ('C1', 'Course')")
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute(
                "INSERT INTO enrollments (student_id, course_id, status)"
                " VALUES ('S1', 'C1', 'abducted')"
            )


class TestAiTables:
    def test_provider_kind_is_constrained(self, sqlite_conn: sqlite3.Connection) -> None:
        """Only kinds an LLMProvider subclass actually implements."""
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute(
                "INSERT INTO ai_providers (name, kind, default_model)"
                " VALUES ('X', 'telepathy', 'm')"
            )

    def test_feature_routing_is_constrained(self, sqlite_conn: sqlite3.Connection) -> None:
        sqlite_conn.execute(
            "INSERT INTO ai_providers (id, name, kind, default_model)"
            " VALUES (1, 'A', 'anthropic', 'claude-opus-5')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute(
                "INSERT INTO ai_feature_models (feature, provider_id, model)"
                " VALUES ('telepathy', 1, 'm')"
            )

    def test_insights_are_cached_per_locale(self, sqlite_conn: sqlite3.Connection) -> None:
        """The same numbers rendered in German are a different artefact, not a cache hit."""
        for locale in ("en", "de"):
            sqlite_conn.execute(
                "INSERT INTO ai_insights (entity_type, entity_id, stats_sha256, locale,"
                " payload_json) VALUES ('student', 'S1', 'abc', ?, '{}')",
                (locale,),
            )
        assert sqlite_conn.execute("SELECT COUNT(*) FROM ai_insights").fetchone()[0] == 2


class TestSeed:
    @pytest.fixture
    def seeded(self, sqlite_conn: sqlite3.Connection) -> dict[str, int]:
        return seed(sqlite_conn, student_count=12)

    def test_creates_every_entity(self, seeded: dict[str, int]) -> None:
        assert seeded["users"] == 6  # five staff, one student
        assert seeded["courses"] == 6
        assert seeded["students"] == 12
        assert seeded["enrollments"] > 0
        assert seeded["grades"] > 0

    def test_is_deterministic(self, sqlite_conn: sqlite3.Connection) -> None:
        """A seeded RNG, so a screenshot or an assertion does not drift between runs."""
        from notenverwaltung.storage import apply_migrations, connect

        first = seed(sqlite_conn, student_count=12)
        other = connect(":memory:")
        apply_migrations(other)
        second = seed(other, student_count=12)
        other.close()

        assert first == second

    def test_leaves_some_enrolments_ungraded(
        self, sqlite_conn: sqlite3.Connection, seeded: dict[str, int]
    ) -> None:
        """The state the coursework schema could not represent: enrolled, not yet
        assessed. The UI needs real examples of it."""
        ungraded = sqlite_conn.execute(
            "SELECT COUNT(*) FROM enrollments e WHERE NOT EXISTS ("
            "  SELECT 1 FROM grades g WHERE g.student_id = e.student_id"
            "  AND g.course_id = e.course_id AND g.deleted_at IS NULL)"
        ).fetchone()[0]
        assert ungraded > 0

    def test_links_one_student_to_a_login(
        self, sqlite_conn: sqlite3.Connection, seeded: dict[str, int]
    ) -> None:
        """Every scoping rule for Role.STUDENT falls through to DENY_ALL unless a
        students row points at the account, so an unlinked student account would make
        the role unreachable in a running app while still passing every other test."""
        row = sqlite_conn.execute(
            "SELECT s.student_id, s.email, u.role FROM students s JOIN users u ON u.id = s.user_id"
        ).fetchone()
        assert row is not None
        assert row["role"] == "student"
        assert (
            row["email"]
            == sqlite_conn.execute("SELECT email FROM users WHERE role = 'student'").fetchone()[0]
        )

    def test_the_linked_student_has_grades_to_look_at(
        self, sqlite_conn: sqlite3.Connection, seeded: dict[str, int]
    ) -> None:
        """A student who signs in to an empty transcript cannot tell a working scope
        from a broken one."""
        count = sqlite_conn.execute(
            "SELECT COUNT(*) FROM grades g JOIN students s ON s.student_id = g.student_id"
            " WHERE s.user_id IS NOT NULL AND g.deleted_at IS NULL"
        ).fetchone()[0]
        assert count > 0

    def test_passing_marks_align_with_the_grading_scale(
        self, sqlite_conn: sqlite3.Connection, seeded: dict[str, int]
    ) -> None:
        """Otherwise a row renders as 'F ... PASS' and reads as a defect."""
        rows = sqlite_conn.execute("SELECT max_grade, passing_grade FROM courses").fetchall()
        for max_grade, passing in rows:
            assert passing / max_grade == pytest.approx(0.6)

    def test_passwords_are_stored_hashed(
        self, sqlite_conn: sqlite3.Connection, seeded: dict[str, int]
    ) -> None:
        for row in sqlite_conn.execute("SELECT password_hash, password_salt FROM users"):
            assert len(row["password_hash"]) == 128  # 64 bytes, hex
            assert "demo-password" not in row["password_hash"]


class TestGradePoints:
    """Migration 010 prices the shipped A-F scale so a GPA works out of the box."""

    def test_the_seeded_scale_is_priced(self, sqlite_conn: sqlite3.Connection) -> None:
        stored = sqlite_conn.execute(
            "SELECT grading_scale_json FROM organization WHERE id = 1"
        ).fetchone()[0]

        assert [band.get("points") for band in json.loads(stored)] == [4.0, 3.0, 2.0, 1.0, 0.0]

    def test_a_rewritten_default_is_priced_too(self, sqlite_conn: sqlite3.Connection) -> None:
        """The same document comes back from `json.dumps` spelled differently — spaced
        separators, float thresholds — and an installation that merely saved its
        colours has not customised its grading scale."""
        rewritten = json.dumps(
            [
                {"min_percentage": 90.0, "label": "A"},
                {"min_percentage": 80.0, "label": "B"},
                {"min_percentage": 70.0, "label": "C"},
                {"min_percentage": 60.0, "label": "D"},
                {"min_percentage": 0.0, "label": "F"},
            ]
        )

        assert rewritten in _MIGRATION_TEXT

    def test_a_customised_scale_is_left_alone(self, sqlite_conn: sqlite3.Connection) -> None:
        """There is no correct guess to make on an institution's behalf: a German 1-6
        scale awards its lowest number to its best grade, and inferring points from
        position would silently invert it."""
        custom = json.dumps([{"min_percentage": 0, "label": "pass"}])
        sqlite_conn.execute("UPDATE organization SET grading_scale_json = ?", (custom,))

        apply_migrations(sqlite_conn)

        stored = sqlite_conn.execute(
            "SELECT grading_scale_json FROM organization WHERE id = 1"
        ).fetchone()[0]
        assert stored == custom


class TestCourseAssessments:
    """Migration 011 seeds each course from the marks it has already recorded."""

    def _grade(self, conn: sqlite3.Connection, course_id: str, title: str, weight: float) -> None:
        conn.execute(
            "INSERT INTO grades (student_id, course_id, score, date, title, weight)"
            " VALUES ('S1', ?, 70, '2026-01-01', ?, ?)",
            (course_id, title, weight),
        )

    def _seed_course(self, conn: sqlite3.Connection, course_id: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO students (student_id, first_name, last_name, email)"
            " VALUES ('S1', 'A', 'B', 'a@b.co')"
        )
        conn.execute("INSERT INTO courses (course_id, name) VALUES (?, 'Course')", (course_id,))

    def _rerun_011(self, conn: sqlite3.Connection) -> None:
        """Replay migration 011 against a database that already holds grades.

        The fixture migrates on creation, so by the time a test has inserted marks
        the migration has already run and found nothing -- `apply_migrations` records
        each version and will not repeat it. Dropping the table and forgetting the
        version reproduces the real upgrade: an existing installation, full of marks,
        meeting this migration for the first time.
        """
        conn.execute("DROP TABLE course_assessments")
        conn.execute("DELETE FROM schema_migrations WHERE version = '011_course_assessments'")
        apply_migrations(conn)

    def test_the_scheme_is_backfilled_from_existing_marks(
        self, sqlite_conn: sqlite3.Connection
    ) -> None:
        """So no course arrives empty and none loses the scheme it has been using."""
        self._seed_course(sqlite_conn, "C1")
        self._grade(sqlite_conn, "C1", "Midterm", 1.0)
        self._grade(sqlite_conn, "C1", "Final", 2.5)

        self._rerun_011(sqlite_conn)

        rows = sqlite_conn.execute(
            "SELECT name, weight FROM course_assessments WHERE course_id = 'C1' ORDER BY name"
        ).fetchall()
        assert [(row[0], row[1]) for row in rows] == [("Final", 2.5), ("Midterm", 1.0)]

    def test_untitled_marks_seed_nothing(self, sqlite_conn: sqlite3.Connection) -> None:
        """An empty title is "one overall grade", not an assessment called ""."""
        self._seed_course(sqlite_conn, "C2")
        self._grade(sqlite_conn, "C2", "", 1.0)

        self._rerun_011(sqlite_conn)

        assert (
            sqlite_conn.execute(
                "SELECT COUNT(*) FROM course_assessments WHERE course_id = 'C2'"
            ).fetchone()[0]
            == 0
        )

    def test_one_title_with_two_weights_collapses_deterministically(
        self, sqlite_conn: sqlite3.Connection
    ) -> None:
        """Nothing ever stopped the same title carrying different weights on different
        rows. MAX is a decision rather than a coin toss; an administrator who
        disagrees edits the course."""
        self._seed_course(sqlite_conn, "C3")
        self._grade(sqlite_conn, "C3", "Final", 1.0)
        self._grade(sqlite_conn, "C3", "Final", 3.0)

        self._rerun_011(sqlite_conn)

        rows = sqlite_conn.execute(
            "SELECT name, weight FROM course_assessments WHERE course_id = 'C3'"
        ).fetchall()
        assert [(row[0], row[1]) for row in rows] == [("Final", 3.0)]

    def test_a_blank_name_cannot_be_stored(self, sqlite_conn: sqlite3.Connection) -> None:
        self._seed_course(sqlite_conn, "C4")
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute(
                "INSERT INTO course_assessments (course_id, name) VALUES ('C4', '  ')"
            )

    def test_a_name_is_unique_within_a_course(self, sqlite_conn: sqlite3.Connection) -> None:
        self._seed_course(sqlite_conn, "C5")
        sqlite_conn.execute("INSERT INTO course_assessments (course_id, name) VALUES ('C5', 'F')")
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute(
                "INSERT INTO course_assessments (course_id, name) VALUES ('C5', 'F')"
            )
