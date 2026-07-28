"""Students, courses, enrolments, grades and reports over HTTP.

The fixture cast is deliberately shaped so scoping failures are visible: two
teachers with separate courses, and a student sitting in one teacher's course whose
other grade lives in the other's. With one of each, an over-broad query returns the
right rows by accident.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import sign_in


class TestStudentScoping:
    def test_admin_sees_every_student(self, as_admin: TestClient) -> None:
        assert as_admin.get("/students").json()["total"] == 3

    def test_teacher_sees_only_students_in_their_courses(self, as_teacher: TestClient) -> None:
        body = as_teacher.get("/students").json()
        assert [s["student_id"] for s in body["items"]] == ["S001"]

    def test_student_sees_only_themselves(self, as_student: TestClient) -> None:
        body = as_student.get("/students").json()
        assert [s["student_id"] for s in body["items"]] == ["S001"]

    def test_an_out_of_scope_id_is_not_found_rather_than_forbidden(
        self, as_student: TestClient
    ) -> None:
        """A 403 would confirm that a record with that id exists."""
        response = as_student.get("/students/S002")
        assert response.status_code == 404
        assert response.json()["code"] == "STUDENT_NOT_FOUND"

    def test_a_genuinely_missing_id_looks_identical(self, as_student: TestClient) -> None:
        assert as_student.get("/students/NOPE").json()["code"] == "STUDENT_NOT_FOUND"

    def test_listing_requires_a_session(self, client: TestClient) -> None:
        assert client.get("/students").status_code == 401


class TestStudentWrites:
    def test_admin_can_add_a_student(self, as_admin: TestClient) -> None:
        response = as_admin.post(
            "/students",
            json={
                "student_id": "S900",
                "first_name": "New",
                "last_name": "Person",
                "email": "new@test.local",
            },
        )
        assert response.status_code == 201
        assert response.json()["student_id"] == "S900"

    def test_a_teacher_cannot_add_students(self, as_teacher: TestClient) -> None:
        """A student record belongs to the institution's register. A teacher creating
        one could not read it back either — their scope is defined by enrolment, so
        the new student would be invisible to them the moment it existed."""
        response = as_teacher.post(
            "/students",
            json={"student_id": "S901", "first_name": "A", "last_name": "B", "email": "x@y.co"},
        )
        assert response.status_code == 403

    def test_a_student_cannot_add_students(self, as_student: TestClient) -> None:
        response = as_student.post(
            "/students",
            json={"student_id": "S901", "first_name": "A", "last_name": "B", "email": "x@y.co"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_a_duplicate_id_conflicts(self, as_admin: TestClient) -> None:
        payload = {
            "student_id": "S001",
            "first_name": "Clash",
            "last_name": "Person",
            "email": "clash@test.local",
        }
        assert as_admin.post("/students", json=payload).status_code == 409

    def test_update_only_touches_the_fields_sent(self, as_admin: TestClient) -> None:
        as_admin.patch("/students/S001", json={"last_name": "Fischer"})
        body = as_admin.get("/students/S001").json()
        assert body["last_name"] == "Fischer"
        assert body["first_name"] == "Anna"

    def test_delete_cascades_to_grades(self, as_admin: TestClient) -> None:
        assert as_admin.delete("/students/S001").status_code == 204
        assert as_admin.get("/grades?student_id=S001").json()["total"] == 0


class TestCourseScoping:
    def test_teacher_sees_only_their_own_courses(self, as_teacher: TestClient) -> None:
        body = as_teacher.get("/courses").json()
        assert [c["course_id"] for c in body["items"]] == ["CS101"]

    def test_student_sees_only_enrolled_courses(self, as_student: TestClient) -> None:
        body = as_student.get("/courses").json()
        assert [c["course_id"] for c in body["items"]] == ["CS101"]

    def test_counts_distinguish_enrolled_from_graded(self, as_admin: TestClient) -> None:
        """The state the coursework schema could not represent."""
        as_admin.post("/courses/CS101/enrollments", json={"student_id": "S003"})
        body = as_admin.get("/courses/CS101").json()
        assert body["enrolled_count"] == 2
        assert body["graded_count"] == 1

    def test_a_teacher_cannot_edit_a_colleagues_course(self, as_teacher: TestClient) -> None:
        response = as_teacher.patch("/courses/CS999", json={"name": "Hijacked"})
        assert response.status_code == 404  # not in scope at all, so not found

    def test_reassigning_a_course_is_admin_only(self, as_teacher: TestClient) -> None:
        """Otherwise a teacher could give a course away and lose their grade history."""
        response = as_teacher.patch("/courses/CS101", json={"teacher_id": 99})
        assert response.status_code == 403

    def test_a_teacher_owns_the_course_they_create(self, as_teacher: TestClient) -> None:
        """The alternative is a course they immediately cannot see."""
        as_teacher.post("/courses", json={"course_id": "NEW1", "name": "Mine"})
        assert "NEW1" in [c["course_id"] for c in as_teacher.get("/courses").json()["items"]]


class TestEnrollments:
    def test_register_includes_ungraded_students(self, as_admin: TestClient) -> None:
        as_admin.post("/courses/CS101/enrollments", json={"student_id": "S003"})
        rows = as_admin.get("/courses/CS101/enrollments").json()
        by_id = {r["student_id"]: r for r in rows}
        assert by_id["S003"]["grade_count"] == 0
        assert by_id["S001"]["grade_count"] == 1

    def test_double_enrolment_conflicts(self, as_admin: TestClient) -> None:
        assert (
            as_admin.post("/courses/CS101/enrollments", json={"student_id": "S001"}).status_code
            == 409
        )

    def test_capacity_is_enforced(self, as_admin: TestClient) -> None:
        as_admin.patch("/courses/CS101", json={"max_students": 1})
        response = as_admin.post("/courses/CS101/enrollments", json={"student_id": "S003"})
        assert response.status_code == 409
        assert response.json()["code"] == "COURSE_FULL"

    def test_withdrawal_keeps_the_row(self, as_admin: TestClient) -> None:
        """Grades earned before a withdrawal must stay attached to something."""
        as_admin.patch("/courses/CS101/enrollments/S001", json={"status": "withdrawn"})
        rows = as_admin.get("/courses/CS101/enrollments").json()
        assert rows[0]["status"] == "withdrawn"

    def test_an_unknown_status_is_rejected(self, as_admin: TestClient) -> None:
        response = as_admin.patch("/courses/CS101/enrollments/S001", json={"status": "abducted"})
        assert response.status_code == 422


class TestGradeScoping:
    def test_a_teacher_cannot_read_a_shared_students_other_grades(
        self, app: object, as_teacher: TestClient
    ) -> None:
        """S001 sits in CS101. Enrolling them in the other teacher's course must not
        expose the mark recorded there — which is why a grade needs *both* its student
        and its course in scope."""
        with TestClient(app) as other:  # type: ignore[arg-type]
            sign_in(other, "other_teacher")
            other.post("/courses/CS999/enrollments", json={"student_id": "S001"})
            other.post(
                "/grades",
                json={
                    "student_id": "S001",
                    "course_id": "CS999",
                    "score": 99,
                    "date": "2026-02-01",
                },
            )

        visible = as_teacher.get("/grades?size=100").json()
        assert {g["course_id"] for g in visible["items"]} == {"CS101"}

    def test_student_sees_all_of_their_own_grades(self, as_student: TestClient) -> None:
        body = as_student.get("/grades").json()
        assert body["total"] == 1
        assert body["items"][0]["student_id"] == "S001"

    def test_a_student_cannot_record_grades(self, as_student: TestClient) -> None:
        response = as_student.post(
            "/grades",
            json={"student_id": "S001", "course_id": "CS101", "score": 100, "date": "2026-07-01"},
        )
        assert response.status_code == 403


class TestGradeWrites:
    def test_record_computes_percentage_and_pass_state(self, as_teacher: TestClient) -> None:
        """Server-side, so two clients cannot disagree with the report."""
        response = as_teacher.post(
            "/grades",
            json={
                "student_id": "S001",
                "course_id": "CS101",
                "score": 75,
                "date": "2026-03-01",
                "title": "Midterm",
            },
        )
        body = response.json()
        assert response.status_code == 201
        assert body["percentage"] == 75.0
        assert body["is_passing"] is True  # CS101 passes at 60

    def test_a_legacy_date_format_is_normalised(self, as_teacher: TestClient) -> None:
        body = as_teacher.post(
            "/grades",
            json={"student_id": "S001", "course_id": "CS101", "score": 70, "date": "15-03-2026"},
        ).json()
        assert body["date"] == "2026-03-15"

    def test_a_score_above_the_maximum_is_rejected(self, as_teacher: TestClient) -> None:
        response = as_teacher.post(
            "/grades",
            json={"student_id": "S001", "course_id": "CS101", "score": 500, "date": "2026-03-01"},
        )
        assert response.status_code == 422

    def test_grading_a_course_you_do_not_own_is_refused(self, as_teacher: TestClient) -> None:
        response = as_teacher.post(
            "/grades",
            json={"student_id": "S002", "course_id": "CS999", "score": 70, "date": "2026-03-01"},
        )
        assert response.status_code in (403, 404)

    def test_amend_records_the_previous_value(self, as_teacher: TestClient) -> None:
        grade_id = as_teacher.get("/grades").json()["items"][0]["grade_id"]
        as_teacher.patch(f"/grades/{grade_id}", json={"score": 91})

        history = as_teacher.get(f"/grades/{grade_id}/history").json()
        assert history[0]["action"] == "update"
        assert history[0]["before"]["score"] == 85
        assert history[0]["after"]["score"] == 91

    def test_retire_hides_the_grade_but_keeps_the_trail(self, as_teacher: TestClient) -> None:
        grade_id = as_teacher.get("/grades").json()["items"][0]["grade_id"]
        assert as_teacher.delete(f"/grades/{grade_id}").status_code == 204

        assert as_teacher.get("/grades").json()["total"] == 0
        assert as_teacher.get(f"/grades/{grade_id}").status_code == 404

    def test_history_is_scope_checked_first(
        self, as_student: TestClient, as_admin: TestClient
    ) -> None:
        """Otherwise the trail becomes a way to read a grade indirectly."""
        other = as_admin.get("/grades?student_id=S002").json()["items"][0]["grade_id"]
        assert as_student.get(f"/grades/{other}/history").status_code == 404


class TestPagination:
    def test_envelope_shape(self, as_admin: TestClient) -> None:
        body = as_admin.get("/students?size=2").json()
        assert set(body) == {"items", "total", "page", "size", "pages"}
        assert body["total"] == 3
        assert body["pages"] == 2

    def test_size_is_capped(self, as_admin: TestClient) -> None:
        """Without the cap, ?size=1000000 is a one-request denial of service."""
        assert as_admin.get("/students?size=99999").status_code == 422

    def test_an_unknown_sort_field_names_the_permitted_ones(self, as_admin: TestClient) -> None:
        body = as_admin.get("/students?sort=shoe_size").json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "last_name" in body["context"]["allowed"]

    def test_descending_sort(self, as_admin: TestClient) -> None:
        ids = [s["student_id"] for s in as_admin.get("/students?sort=-id").json()["items"]]
        assert ids == sorted(ids, reverse=True)

    def test_search_matches_name_and_email(self, as_admin: TestClient) -> None:
        assert as_admin.get("/students?q=schmidt").json()["total"] == 1

    def test_a_percent_sign_in_search_is_not_a_wildcard(self, as_admin: TestClient) -> None:
        """Unescaped, "%" would silently match every row."""
        assert as_admin.get("/students?q=%25").json()["total"] == 0


class TestReports:
    def test_a_report_carries_no_prose(self, as_admin: TestClient) -> None:
        """The client renders the wording, which is why the API ships no catalogue."""
        body = as_admin.get("/reports/student/S001").json()
        assert set(body) == {
            "student_id",
            "student_name",
            "email",
            "grades",
            "average_percentage",
            "passed_count",
            "failed_count",
            "courses_graded",
        }

    def test_a_teachers_copy_omits_other_courses(self, app: object, as_teacher: TestClient) -> None:
        """The report must not expose marks a scoped list endpoint would have hidden."""
        with TestClient(app) as other:  # type: ignore[arg-type]
            sign_in(other, "other_teacher")
            other.post("/courses/CS999/enrollments", json={"student_id": "S001"})
            other.post(
                "/grades",
                json={
                    "student_id": "S001",
                    "course_id": "CS999",
                    "score": 99,
                    "date": "2026-02-01",
                },
            )

        report = as_teacher.get("/reports/student/S001").json()
        assert {g["course_id"] for g in report["grades"]} == {"CS101"}

    def test_a_student_sees_class_stats_but_only_their_own_marks(
        self, as_student: TestClient
    ) -> None:
        report = as_student.get("/reports/course/CS101").json()
        assert {g["student_id"] for g in report["grades"]} == {"S001"}
        assert report["course_name"] == "Intro"

    def test_summary_is_staff_only(self, as_student: TestClient) -> None:
        assert as_student.get("/reports/summary").status_code == 403

    def test_csv_export_translates_headers_and_switches_delimiter(
        self, as_admin: TestClient
    ) -> None:
        """A downloaded file has no frontend, so this one format translates server-side."""
        body = as_admin.get("/reports/student/S001/export.csv?locale=de").text
        header = body.splitlines()[0]
        assert "Punkte" in header
        assert ";" in header

    def test_csv_starts_with_a_bom(self, as_admin: TestClient) -> None:
        """Without it Excel reads UTF-8 as the local codepage and mangles accents."""
        assert as_admin.get("/reports/student/S001/export.csv").text.startswith("﻿")

    def test_csv_export_is_scope_checked(self, as_student: TestClient) -> None:
        assert as_student.get("/reports/student/S002/export.csv").status_code == 404


class TestAnalytics:
    def test_dashboard_is_scoped_per_role(
        self, as_admin: TestClient, as_teacher: TestClient
    ) -> None:
        assert as_admin.get("/analytics/dashboard").json()["student_count"] == 3
        assert as_teacher.get("/analytics/dashboard").json()["student_count"] == 1

    def test_distribution_includes_empty_bands(self, as_admin: TestClient) -> None:
        distribution = as_admin.get("/analytics/dashboard").json()["distribution"]
        assert set(distribution) == {"A", "B", "C", "D", "F"}

    def test_average_is_null_when_nothing_is_graded(self, as_admin: TestClient) -> None:
        """Null, not 0 — zero would read as 'everybody failed'."""
        for grade in as_admin.get("/grades?size=100").json()["items"]:
            as_admin.delete(f"/grades/{grade['grade_id']}")
        assert as_admin.get("/analytics/dashboard").json()["average_percentage"] is None

    def test_rankings_are_staff_only(self, as_student: TestClient) -> None:
        assert as_student.get("/analytics/top-students").status_code == 403

    def test_at_risk_excludes_the_ungraded(self, as_admin: TestClient) -> None:
        """No data is not the same as poor performance."""
        listed = as_admin.get("/analytics/at-risk?threshold=100").json()
        assert "S003" not in [s["student_id"] for s in listed]


class TestBranding:
    def test_is_public(self, client: TestClient) -> None:
        """The sign-in page needs the logo and colours before anyone has signed in."""
        assert client.get("/org/branding").status_code == 200

    def test_carries_a_colour_per_theme(self, client: TestClient) -> None:
        colors = client.get("/org/branding").json()["colors"]
        assert colors["primary"]["light"] != colors["primary"]["dark"]

    def test_carries_locales_and_the_grading_scale(self, client: TestClient) -> None:
        body = client.get("/org/branding").json()
        assert body["enabled_locales"] == ["en", "de", "fr"]
        assert [b["label"] for b in body["grading_scale"]] == ["A", "B", "C", "D", "F"]
