"""Regressions for three defects found in review, not by a failing test.

Two were data leaks that every existing test passed straight over, because each one
tested the *route* that was guarded and not the second route beside it:

- ``GET /reports/summary`` was gated with ``TeacherUser``; the CSV export of the same
  report took no role dependency at all.
- ``GET /courses/{id}/enrollments`` proved the *course* was visible and then selected
  every enrolled student's name and email with no student scope.

The third is the reason no AI provider could authenticate: keys are resolved by
variable name from ``os.environ``, and ``.env`` was only ever parsed into the
pydantic ``Settings`` object.

The shape worth keeping: each test asserts the leak is closed *and* that the
legitimate caller beside it still works. A guard that returns 403 to everyone would
satisfy half a test.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import PASSWORD


class TestSummaryExport:
    """The institution-wide summary is staff-only through every door."""

    def test_student_cannot_export_the_summary(self, as_student: TestClient) -> None:
        """A student asking for the whole institution's ranked averages is refused."""
        response = as_student.get("/reports/summary/summary/export.csv")

        assert response.status_code == 403, response.text
        assert response.json()["code"] == "FORBIDDEN"

    def test_student_can_still_export_their_own_report(self, as_student: TestClient) -> None:
        """The counterweight: the guard must not close the door the student may use.

        The fix deliberately went into ``summary_report`` rather than onto the export
        route, because this request travels through the same route.
        """
        response = as_student.get("/reports/student/S001/export.csv")

        assert response.status_code == 200, response.text
        # A student report is a list of their own marks, so the rows are course-shaped
        # rather than carrying the student's name.
        assert "CS101" in response.text
        assert "85.00" in response.text

    def test_student_cannot_read_the_summary_as_json_either(self, as_student: TestClient) -> None:
        """The route that was already guarded stays guarded."""
        assert as_student.get("/reports/summary").status_code == 403

    def test_teacher_can_export_the_summary(self, as_teacher: TestClient) -> None:
        """Staff keep the report; the fix is about role, not about the format."""
        response = as_teacher.get("/reports/summary/summary/export.csv")

        assert response.status_code == 200, response.text


class TestCourseRegister:
    """A course register shows a student themselves, and staff everyone."""

    def test_student_sees_only_their_own_row(self, as_student: TestClient) -> None:
        """S001 is enrolled on CS101 alongside nobody -- but the query must say why.

        Before the fix this returned every enrolment on the course. The fixture has
        one other student, S002, enrolled on a *different* course, so the count alone
        would not have caught it: the assertion that matters is the student id.
        """
        response = as_student.get("/courses/CS101/enrollments")

        assert response.status_code == 200, response.text
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["student_id"] == "S001"

    def test_no_classmate_email_reaches_a_student(
        self, as_student: TestClient, as_teacher: TestClient
    ) -> None:
        """The leak included email addresses, so assert on the payload as text.

        A teacher enrols a second student first, so there is genuinely someone to
        leak. Without that, the previous test passes against a register that is simply
        empty of classmates.
        """
        enrolled = as_teacher.post("/courses/CS101/enrollments", json={"student_id": "S003"})
        assert enrolled.status_code == 201, enrolled.text

        response = as_student.get("/courses/CS101/enrollments")

        assert response.status_code == 200, response.text
        assert len(response.json()) == 1
        assert "clara@test.local" not in response.text
        assert "Clara" not in response.text

    def test_owning_teacher_sees_the_whole_register(self, as_teacher: TestClient) -> None:
        """The counterweight: scoping a student down must not blind the teacher."""
        as_teacher.post("/courses/CS101/enrollments", json={"student_id": "S003"})

        response = as_teacher.get("/courses/CS101/enrollments")

        assert response.status_code == 200, response.text
        assert {row["student_id"] for row in response.json()} == {"S001", "S003"}

    def test_admin_sees_the_whole_register(self, as_admin: TestClient) -> None:
        """An admin is unrestricted, as everywhere else."""
        response = as_admin.get("/courses/CS101/enrollments")

        assert response.status_code == 200, response.text
        assert [row["student_id"] for row in response.json()] == ["S001"]


class TestDotenvReachesEnviron:
    """Provider API keys are resolved by name from ``os.environ``.

    ``ai_providers.api_key_env`` stores the *name* of a variable, never a key, so the
    name is configured at runtime and cannot be a declared ``Settings`` field --
    which is why ``api.config`` calls ``load_dotenv`` and why that call is load
    bearing rather than decorative.
    """

    def test_config_import_populates_environ_from_dotenv(self) -> None:
        """Every name written in ``.env`` is visible to ``os.environ``.

        Skipped where there is no ``.env`` -- it is git-ignored, so CI and a fresh
        clone legitimately lack one. On a developer machine, which is where the
        failure actually happened, this is the assertion that catches a regression.
        """
        import api.config  # importing it is what calls load_dotenv

        env_file = Path(api.config.__file__).resolve().parents[3] / ".env"
        if not env_file.exists():
            pytest.skip("no .env in this checkout")

        names = [
            line.split("=", 1)[0].strip()
            for line in env_file.read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        ]
        if not names:
            pytest.skip(".env declares no variables")

        missing = [name for name in names if name not in os.environ]
        assert missing == [], f"names in .env never reached os.environ: {missing}"

    def test_a_real_environment_variable_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``load_dotenv`` must not override what the operator already exported.

        The precedence matters in deployment: a secret injected by the environment has
        to beat a stale line in a file someone left in the working tree.
        """
        from dotenv import load_dotenv

        monkeypatch.setenv("GT_PRECEDENCE_PROBE", "from-environment")
        load_dotenv(Path(__file__).parent / "does-not-exist.env")

        assert os.environ["GT_PRECEDENCE_PROBE"] == "from-environment"


class TestReportExportScope:
    """The CSV export must not see further than the JSON report beside it.

    Both routes reach the same builder. The JSON ones trimmed the result to the
    caller's scope afterwards and the export did not, so the download was a way
    around scoping rather than a second rendering of the same thing. The seed puts
    S001 in the first teacher's course only, so each test adds the row that makes
    the leak visible -- without it the report has nothing to hide.
    """

    def test_a_student_exporting_a_course_gets_only_their_own_marks(
        self, seeded_db: sqlite3.Connection, as_student: TestClient
    ) -> None:
        """The register is the classmates' marks; a student may read one row of it."""
        seeded_db.execute("INSERT INTO enrollments (student_id, course_id) VALUES ('S002','CS101')")
        seeded_db.execute(
            "INSERT INTO grades (student_id, course_id, score, date)"
            " VALUES ('S002', 'CS101', 42, '2026-02-01')"
        )
        seeded_db.commit()

        response = as_student.get("/reports/course/CS101/export.csv")

        assert response.status_code == 200, response.text
        assert "S001" in response.text
        assert "S002" not in response.text
        assert "Mueller" not in response.text
        assert "42" not in response.text

    def test_a_teacher_exporting_a_student_sees_only_their_own_courses(
        self, seeded_db: sqlite3.Connection, as_teacher: TestClient
    ) -> None:
        """A student's transcript spans courses; a teacher may read their part of it."""
        seeded_db.execute("INSERT INTO enrollments (student_id, course_id) VALUES ('S001','CS999')")
        seeded_db.execute(
            "INSERT INTO grades (student_id, course_id, score, date)"
            " VALUES ('S001', 'CS999', 91, '2026-02-01')"
        )
        seeded_db.commit()

        response = as_teacher.get("/reports/student/S001/export.csv")

        assert response.status_code == 200, response.text
        assert "CS101" in response.text
        assert "CS999" not in response.text
        assert "91" not in response.text

    def test_the_json_route_and_the_export_agree(
        self, seeded_db: sqlite3.Connection, as_teacher: TestClient
    ) -> None:
        """The counterweight: one filter, so the two doors cannot drift apart again."""
        seeded_db.execute("INSERT INTO enrollments (student_id, course_id) VALUES ('S001','CS999')")
        seeded_db.execute(
            "INSERT INTO grades (student_id, course_id, score, date)"
            " VALUES ('S001', 'CS999', 91, '2026-02-01')"
        )
        seeded_db.commit()

        payload = as_teacher.get("/reports/student/S001").json()
        exported = as_teacher.get("/reports/student/S001/export.csv").text

        assert [g["course_id"] for g in payload["grades"]] == ["CS101"]
        assert exported.count("CS101") == len(payload["grades"])


class TestForcedPasswordChange:
    """A generated password gets you to the change screen and nowhere else.

    ``must_change_password`` was written on account creation and on reset, carried
    on the principal and published at ``/auth/me``, and then read by nobody. An
    administrator importing four hundred students handed out four hundred
    passwords that stayed valid indefinitely. Migration 008 asks the application to
    "insist on the change rather than suggest it"; only the frontend suggested it.
    """

    def test_the_application_is_closed_until_the_password_changes(
        self, seeded_db: sqlite3.Connection, as_student: TestClient
    ) -> None:
        """The flag is set after sign-in, so the very next request is refused."""
        seeded_db.execute(
            "UPDATE users SET must_change_password = 1 WHERE email = 'student@test.local'"
        )
        seeded_db.commit()

        response = as_student.get("/grades")

        assert response.status_code == 403, response.text
        assert response.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    def test_the_way_out_stays_open(
        self, seeded_db: sqlite3.Connection, as_student: TestClient
    ) -> None:
        """The counterweight: refusing everything would include the fix itself."""
        seeded_db.execute(
            "UPDATE users SET must_change_password = 1 WHERE email = 'student@test.local'"
        )
        seeded_db.commit()

        assert as_student.get("/auth/me").status_code == 200
        changed = as_student.post(
            "/profile/password",
            json={"current_password": PASSWORD, "new_password": "a-chosen-one-42"},
        )

        assert changed.status_code == 200, changed.text
        # 401 rather than 200: changing a password closes every session including
        # this one, by design. The point here is that the gate let the change
        # through, not that the session survived it.
        assert as_student.get("/grades").status_code == 401

    def test_an_ordinary_account_is_unaffected(self, as_student: TestClient) -> None:
        """Nobody who chose their own password notices this exists."""
        assert as_student.get("/grades").status_code == 200
