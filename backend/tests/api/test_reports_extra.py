"""The five additional reports and their CSV exports.

Every report composes the caller's scope from `services/scoping.py`, so a teacher
sees only their own courses' rows and an administrator sees the institution. A
student is refused wherever the report spans other students. The assessment
grouping and the month bucket boundary are pinned against hand-computed values on
the fixture data.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient


def _teacher_id(client: TestClient) -> int:
    """Return the signed-in account's user id."""
    return client.get("/auth/me").json()["user_id"]


def _user_id_by_email(admin: TestClient, email: str) -> int:
    """Look up an account id by email, via the admin user listing."""
    users = admin.get("/admin/users").json()
    return next(user["id"] for user in users if user["email"] == email)


def _band_total(distribution: dict[str, int]) -> int:
    """Sum a band distribution back into a grade count."""
    return sum(distribution.values())


@pytest.fixture
def termd(seeded_db: sqlite3.Connection) -> sqlite3.Connection:
    """Give the two fixture courses distinct terms."""
    seeded_db.execute("UPDATE courses SET term = '2026-SS' WHERE course_id = 'CS101'")
    seeded_db.execute("UPDATE courses SET term = '2026-WS' WHERE course_id = 'CS999'")
    seeded_db.commit()
    return seeded_db


@pytest.fixture
def assessed(seeded_db: sqlite3.Connection) -> sqlite3.Connection:
    """Enrol S003 on CS101 and add titled grades to CS101.

    The base fixture already seeds one untitled 85% mark for S001 on CS101. The
    titled marks below are what the grouping test hand-computes from.
    """
    seeded_db.execute("INSERT INTO enrollments (student_id, course_id) VALUES ('S003', 'CS101')")
    rows = [
        ("S001", "CS101", 90.0, "2026-02-10", "Midterm"),
        ("S003", "CS101", 80.0, "2026-02-11", "Midterm"),
        ("S001", "CS101", 60.0, "2026-03-01", "Final"),
    ]
    for student, course, score, date, title in rows:
        seeded_db.execute(
            "INSERT INTO grades (student_id, course_id, score, date, title) VALUES (?, ?, ?, ?, ?)",
            (student, course, score, date, title),
        )
    seeded_db.commit()
    return seeded_db


@pytest.fixture
def month_edges(seeded_db: sqlite3.Connection) -> sqlite3.Connection:
    """Add grades on the boundaries that bracket a month."""
    rows = [
        ("S001", "CS101", 70.0, "2026-01-01", "Boundary"),
        ("S001", "CS101", 70.0, "2026-01-31", "Boundary"),
        ("S001", "CS101", 70.0, "2026-02-01", "Boundary"),
    ]
    for student, course, score, date, title in rows:
        seeded_db.execute(
            "INSERT INTO grades (student_id, course_id, score, date, title) VALUES (?, ?, ?, ?, ?)",
            (student, course, score, date, title),
        )
    seeded_db.commit()
    return seeded_db


class TestTeacherRollup:
    """`GET /reports/teacher/{user_id}` — the teacher, or an administrator."""

    def test_teacher_sees_only_their_own_courses(self, as_teacher: TestClient) -> None:
        response = as_teacher.get(f"/reports/teacher/{_teacher_id(as_teacher)}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert [course["course_id"] for course in body["courses"]] == ["CS101"]
        assert body["teacher_name"] == "Teacher"
        assert (body["course_count"], body["student_count"], body["grade_count"]) == (1, 1, 1)
        assert body["average_percentage"] == pytest.approx(85.0)
        (course,) = body["courses"]
        assert course["average_percentage"] == pytest.approx(85.0)
        assert course["pass_rate"] == pytest.approx(100.0)

    def test_admin_sees_any_teacher(self, as_admin: TestClient) -> None:
        other_id = _user_id_by_email(as_admin, "other@test.local")

        body = as_admin.get(f"/reports/teacher/{other_id}").json()

        assert [course["course_id"] for course in body["courses"]] == ["CS999"]
        assert body["teacher_name"] == "Other_Teacher"

    def test_teacher_cannot_read_a_colleagues_rollup(
        self, as_teacher: TestClient, as_admin: TestClient
    ) -> None:
        """The counterweight to the admin view: a teacher is not an admin."""
        other_id = _user_id_by_email(as_admin, "other@test.local")

        response = as_teacher.get(f"/reports/teacher/{other_id}")

        assert response.status_code == 403, response.text
        assert response.json()["code"] == "FORBIDDEN"

    def test_unknown_teacher_is_not_found(self, as_admin: TestClient) -> None:
        response = as_admin.get("/reports/teacher/999999")

        assert response.status_code == 404, response.text
        assert response.json()["code"] == "USER_NOT_FOUND"

    def test_a_student_is_refused(self, as_student: TestClient) -> None:
        """A rollup spans every student in the teacher's courses."""
        assert as_student.get("/reports/teacher/1").status_code == 403


class TestTermReport:
    """`GET /reports/term/{term}` — scopeable, unlike the summary."""

    def test_teacher_sees_only_their_own_courses_in_that_term(
        self, as_teacher: TestClient, termd: sqlite3.Connection
    ) -> None:
        body = as_teacher.get("/reports/term/2026-SS").json()

        assert [course["course_id"] for course in body["courses"]] == ["CS101"]
        assert body["term"] == "2026-SS"

    def test_teacher_term_with_no_own_courses_is_empty(
        self, as_teacher: TestClient, termd: sqlite3.Connection
    ) -> None:
        """CS999 runs in 2026-WS but belongs to a different teacher."""
        body = as_teacher.get("/reports/term/2026-WS").json()

        assert body["courses"] == []
        assert body["course_count"] == 0

    def test_admin_sees_the_institution(
        self, as_admin: TestClient, termd: sqlite3.Connection
    ) -> None:
        ss = as_admin.get("/reports/term/2026-SS").json()
        ws = as_admin.get("/reports/term/2026-WS").json()

        assert [course["course_id"] for course in ss["courses"]] == ["CS101"]
        assert [course["course_id"] for course in ws["courses"]] == ["CS999"]

    def test_a_student_is_refused(self, as_student: TestClient) -> None:
        """One student's copy would still contain classmates' averages."""
        assert as_student.get("/reports/term/2026-SS").status_code == 403


class TestCourseAssessments:
    """`GET /reports/course/{id}/assessments` — grouping per title."""

    def test_grouping_matches_hand_computed_values(
        self, as_teacher: TestClient, assessed: sqlite3.Connection
    ) -> None:
        body = as_teacher.get("/reports/course/CS101/assessments").json()

        by_title = {row["title"]: row for row in body["assessments"]}
        assert set(by_title) == {"", "Midterm", "Final"}

        overall = by_title[""]
        assert overall["count"] == 1
        assert overall["average_score"] == pytest.approx(85.0)
        assert (overall["min_score"], overall["max_score"]) == (85.0, 85.0)
        assert overall["pass_rate"] == pytest.approx(100.0)
        assert overall["distribution"] == {"A": 0, "B": 1, "C": 0, "D": 0, "F": 0}

        midterm = by_title["Midterm"]
        assert midterm["count"] == 2
        assert midterm["average_score"] == pytest.approx(85.0)
        assert (midterm["min_score"], midterm["max_score"]) == (80.0, 90.0)
        assert midterm["pass_rate"] == pytest.approx(100.0)
        assert midterm["distribution"] == {"A": 1, "B": 1, "C": 0, "D": 0, "F": 0}

        final = by_title["Final"]
        assert final["count"] == 1
        assert final["average_score"] == pytest.approx(60.0)
        assert (final["min_score"], final["max_score"]) == (60.0, 60.0)
        assert final["distribution"] == {"A": 0, "B": 0, "C": 0, "D": 1, "F": 0}

    def test_admin_sees_the_same_grouping(
        self, as_admin: TestClient, assessed: sqlite3.Connection
    ) -> None:
        """The assessments of one course are the same for any staff reader."""
        body = as_admin.get("/reports/course/CS101/assessments").json()

        assert len(body["assessments"]) == 3

    def test_out_of_scope_course_is_not_found(self, as_teacher: TestClient) -> None:
        """CS999 belongs to another teacher and must read as absent, not 403."""
        response = as_teacher.get("/reports/course/CS999/assessments")

        assert response.status_code == 404, response.text
        assert response.json()["code"] == "COURSE_NOT_FOUND"

    def test_a_student_is_refused(self, as_student: TestClient) -> None:
        """Class statistics span every student, even on a course the student sits in."""
        assert as_student.get("/reports/course/CS101/assessments").status_code == 403


class TestEnrollmentReport:
    """`GET /reports/enrollment` — capacity, take-up and dropout."""

    def test_teacher_sees_only_their_own_courses(self, as_teacher: TestClient) -> None:
        body = as_teacher.get("/reports/enrollment").json()

        assert [row["course_id"] for row in body["rows"]] == ["CS101"]
        assert body["course_count"] == 1

    def test_admin_sees_the_institution(self, as_admin: TestClient) -> None:
        body = as_admin.get("/reports/enrollment").json()

        assert [row["course_id"] for row in body["rows"]] == ["CS101", "CS999"]

    def test_counts_withdrawn_and_completed(
        self, as_admin: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        seeded_db.execute(
            "UPDATE enrollments SET status = 'withdrawn'"
            " WHERE student_id = 'S002' AND course_id = 'CS999'"
        )
        seeded_db.commit()

        body = as_admin.get("/reports/enrollment").json()
        by_course = {row["course_id"]: row for row in body["rows"]}
        assert by_course["CS999"]["withdrawn"] == 1
        assert by_course["CS999"]["active"] == 0

    def test_utilisation_is_active_over_capacity(self, as_teacher: TestClient) -> None:
        """CS101 holds one active enrolment against the default capacity of 30."""
        body = as_teacher.get("/reports/enrollment").json()

        (row,) = body["rows"]
        assert row["capacity"] == 30
        assert row["active"] == 1
        assert row["utilisation"] == pytest.approx(3.33)

    def test_a_student_is_refused(self, as_student: TestClient) -> None:
        assert as_student.get("/reports/enrollment").status_code == 403


class TestDistributionReport:
    """`GET /reports/distribution?bucket=month|term`."""

    def test_month_bucket_boundary(
        self, as_teacher: TestClient, month_edges: sqlite3.Connection
    ) -> None:
        """The first and last day of a month share a bucket; the next day does not."""
        body = as_teacher.get("/reports/distribution", params={"bucket": "month"}).json()

        # Base fixture grade on 2026-01-15 joins the two boundary grades on the
        # first and last day of January; 2026-02-01 opens a new bucket.
        assert [bucket["bucket"] for bucket in body["buckets"]] == ["2026-01", "2026-02"]
        totals = {
            bucket["bucket"]: _band_total(bucket["distribution"]) for bucket in body["buckets"]
        }
        assert totals == {"2026-01": 3, "2026-02": 1}

    def test_teacher_sees_only_their_own_grades(
        self, as_teacher: TestClient, month_edges: sqlite3.Connection
    ) -> None:
        """S002's mark in the other teacher's course must never appear."""
        body = as_teacher.get("/reports/distribution", params={"bucket": "month"}).json()

        assert _band_total(body["buckets"][0]["distribution"]) == 3

    def test_admin_sees_the_institution(
        self, as_admin: TestClient, month_edges: sqlite3.Connection
    ) -> None:
        body = as_admin.get("/reports/distribution", params={"bucket": "month"}).json()

        # Adds the base S002/CS999 mark on 2026-01-15.
        assert _band_total(body["buckets"][0]["distribution"]) == 4

    def test_term_bucket_groups_by_course_term(
        self, as_teacher: TestClient, termd: sqlite3.Connection, month_edges: sqlite3.Connection
    ) -> None:
        body = as_teacher.get("/reports/distribution", params={"bucket": "term"}).json()

        assert body["bucket"] == "term"
        assert [bucket["bucket"] for bucket in body["buckets"]] == ["2026-SS"]
        assert _band_total(body["buckets"][0]["distribution"]) == 4

    def test_admin_term_bucket_sees_both_terms(
        self, as_admin: TestClient, termd: sqlite3.Connection
    ) -> None:
        body = as_admin.get("/reports/distribution", params={"bucket": "term"}).json()

        assert [bucket["bucket"] for bucket in body["buckets"]] == ["2026-SS", "2026-WS"]

    def test_an_unknown_bucket_is_rejected(self, as_teacher: TestClient) -> None:
        response = as_teacher.get("/reports/distribution", params={"bucket": "year"})

        assert response.status_code == 422, response.text
        assert response.json()["code"] == "VALIDATION_ERROR"

    def test_a_student_is_refused(self, as_student: TestClient) -> None:
        assert as_student.get("/reports/distribution").status_code == 403


class TestCsvExports:
    """The generic export route dispatches the new kinds with localized headers."""

    @pytest.mark.parametrize(
        ("kind", "entity", "header"),
        [
            ("teacher", None, "Kurs-ID"),
            ("term", "2026-SS", "Kurs-ID"),
            ("assessments", "CS101", "Leistung"),
            ("enrollment", "enrollment", "Kapazität"),
            ("distribution", "distribution", "Zeitraum"),
        ],
    )
    def test_german_headers(
        self,
        as_teacher: TestClient,
        kind: str,
        entity: str,
        header: str,
        termd: sqlite3.Connection,
        assessed: sqlite3.Connection,
    ) -> None:
        if kind == "teacher":
            entity = str(_teacher_id(as_teacher))
        params = {"locale": "de"}
        if kind == "distribution":
            params["bucket"] = "month"

        response = as_teacher.get(f"/reports/{kind}/{entity}/export.csv", params=params)

        assert response.status_code == 200, response.text
        # German Excel reads ';' as the separator; a German file must use it.
        assert ";" in response.text.splitlines()[0]
        assert header in response.text

    def test_a_student_is_refused_every_new_export(self, as_student: TestClient) -> None:
        """The CSV door is guarded by the same service methods as the JSON ones."""
        for url in (
            "/reports/enrollment/enrollment/export.csv",
            "/reports/distribution/distribution/export.csv",
        ):
            assert as_student.get(url).status_code == 403
