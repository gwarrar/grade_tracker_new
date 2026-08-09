"""Three features that were modelled and never connected.

Each had a column, a validated shape and a screen, and nothing that read them: an
enrolment could hold ``completed`` that nothing could write, a course could name
prerequisites that nothing checked, and a course could be archived without leaving
any picker. They are tested together because they are one chain — a prerequisite is
satisfied by a completed enrolment, so completion had to be reachable before
enforcement could be anything but a wall.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _course(client: TestClient, course_id: str, **extra: object) -> None:
    """Create a course, failing loudly if the fixture cannot."""
    body: dict[str, object] = {"course_id": course_id, "name": f"Course {course_id}"}
    body.update(extra)
    response = client.post("/courses", json=body)
    assert response.status_code == 201, response.text


class TestEnrolmentCompletion:
    """`EnrollmentStatus.COMPLETED` existed, reports counted it, nothing set it."""

    def test_an_active_enrolment_can_be_completed(self, as_admin: TestClient) -> None:
        response = as_admin.patch("/courses/CS101/enrollments/S001", json={"status": "completed"})

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed"

    def test_the_register_reports_it(self, as_admin: TestClient) -> None:
        as_admin.patch("/courses/CS101/enrollments/S001", json={"status": "completed"})

        register = as_admin.get("/courses/CS101/enrollments").json()

        assert [row["status"] for row in register if row["student_id"] == "S001"] == ["completed"]

    def test_completion_keeps_the_grades(self, as_admin: TestClient) -> None:
        """The reason status is a column rather than a deletion."""
        before = as_admin.get("/grades", params={"student_id": "S001"}).json()["total"]

        as_admin.patch("/courses/CS101/enrollments/S001", json={"status": "completed"})

        assert as_admin.get("/grades", params={"student_id": "S001"}).json()["total"] == before

    def test_an_unknown_status_is_refused(self, as_admin: TestClient) -> None:
        response = as_admin.patch("/courses/CS101/enrollments/S001", json={"status": "graduated"})

        assert response.status_code == 422


class TestPrerequisites:
    """The table and the editor shipped long ago; `enroll()` never read either."""

    def test_an_uncompleted_prerequisite_blocks_enrolment(self, as_admin: TestClient) -> None:
        _course(as_admin, "CS300", prerequisite_ids=["CS101"])

        response = as_admin.post("/courses/CS300/enrollments", json={"student_id": "S002"})

        assert response.status_code == 409
        assert response.json()["code"] == "PREREQUISITES_NOT_MET"
        assert response.json()["context"]["missing"] == ["CS101"]

    def test_a_completed_prerequisite_admits_the_student(self, as_admin: TestClient) -> None:
        """The other half, and the reason completion had to come first: without a way
        to reach `completed`, this check would make every prerequisite unpassable."""
        _course(as_admin, "CS301", prerequisite_ids=["CS101"])
        as_admin.patch("/courses/CS101/enrollments/S001", json={"status": "completed"})

        response = as_admin.post("/courses/CS301/enrollments", json={"student_id": "S001"})

        assert response.status_code == 201, response.text

    def test_an_active_enrolment_does_not_count_as_completed(self, as_admin: TestClient) -> None:
        """Sitting in a course is not finishing it. S001 is enrolled on CS101 and has
        marks there; neither is the same as having completed it."""
        _course(as_admin, "CS302", prerequisite_ids=["CS101"])

        response = as_admin.post("/courses/CS302/enrollments", json={"student_id": "S001"})

        assert response.status_code == 409

    def test_a_withdrawn_prerequisite_does_not_count_either(self, as_admin: TestClient) -> None:
        _course(as_admin, "CS303", prerequisite_ids=["CS101"])
        as_admin.patch("/courses/CS101/enrollments/S001", json={"status": "withdrawn"})

        response = as_admin.post("/courses/CS303/enrollments", json={"student_id": "S001"})

        assert response.status_code == 409

    def test_every_outstanding_prerequisite_is_named(self, as_admin: TestClient) -> None:
        """The first one is not enough: somebody fixing this wants the whole list."""
        _course(as_admin, "CS310")
        _course(as_admin, "CS311")
        _course(as_admin, "CS312", prerequisite_ids=["CS310", "CS311"])

        response = as_admin.post("/courses/CS312/enrollments", json={"student_id": "S001"})

        assert response.json()["context"]["missing"] == ["CS310", "CS311"]

    def test_a_course_without_prerequisites_is_unaffected(self, as_admin: TestClient) -> None:
        _course(as_admin, "CS320")

        assert (
            as_admin.post("/courses/CS320/enrollments", json={"student_id": "S001"}).status_code
            == 201
        )


class TestArchivedCourses:
    """`courses.status` could be set and nothing could filter on it, so archiving a
    course changed a badge and left it in every picker.
    """

    def test_the_list_shows_both_by_default(self, as_admin: TestClient) -> None:
        """Archiving is not deletion; the register still has to show what was archived."""
        _course(as_admin, "CS400", status="archived")

        listed = as_admin.get("/courses", params={"size": 200}).json()["items"]

        assert "CS400" in {course["course_id"] for course in listed}

    def test_active_can_be_asked_for(self, as_admin: TestClient) -> None:
        _course(as_admin, "CS401", status="archived")

        listed = as_admin.get("/courses", params={"size": 200, "status": "active"}).json()["items"]

        assert "CS401" not in {course["course_id"] for course in listed}
        assert "CS101" in {course["course_id"] for course in listed}

    def test_archived_can_be_asked_for(self, as_admin: TestClient) -> None:
        _course(as_admin, "CS402", status="archived")

        listed = as_admin.get("/courses", params={"size": 200, "status": "archived"}).json()[
            "items"
        ]

        assert {course["course_id"] for course in listed} == {"CS402"}

    def test_the_filter_combines_with_the_others(self, as_admin: TestClient) -> None:
        """Two filters used to be one `extra` scope with room for exactly one."""
        _course(as_admin, "CS403", status="archived", term="2026-SS")
        _course(as_admin, "CS404", status="archived", term="2026-WS")

        listed = as_admin.get(
            "/courses", params={"size": 200, "status": "archived", "term": "2026-SS"}
        ).json()["items"]

        assert {course["course_id"] for course in listed} == {"CS403"}

    def test_an_unknown_status_is_refused_rather_than_matching_nothing(
        self, as_admin: TestClient
    ) -> None:
        response = as_admin.get("/courses", params={"status": "retired"})

        assert response.status_code == 422
        assert response.json()["context"]["allowed"] == ["active", "archived"]
