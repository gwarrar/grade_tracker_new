"""What a course marks, and what each piece is worth.

`grades.title` was free text and `grades.weight` a float on every row, which made a
course-level fact behave like a per-row one — and `course_assessments_report` groups
by exact string equality, so "Midterm" and "midterm" already split one assessment in
two and nobody was told.

The scheme says what a course *offers*. It is deliberately not a foreign key on
`grades`: reweighting a Final would otherwise re-average every mark already awarded
under the old scheme, and a transcript that moves because somebody edited a course is
worse than a duplicate string.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi.testclient import TestClient

SCHEME = [
    {"name": "Midterm", "weight": 1.0},
    {"name": "Coursework", "weight": 1.5},
    {"name": "Final", "weight": 2.5},
]


def _course(client: TestClient, course_id: str, **extra: Any) -> Any:
    body: dict[str, Any] = {"course_id": course_id, "name": f"Course {course_id}"}
    body.update(extra)
    return client.post("/courses", json=body)


class TestDefiningTheScheme:
    def test_a_course_round_trips_its_assessments(self, as_admin: TestClient) -> None:
        response = _course(as_admin, "CS500", assessments=SCHEME)

        assert response.status_code == 201, response.text
        assert response.json()["assessments"] == SCHEME

    def test_the_order_given_is_the_order_returned(self, as_admin: TestClient) -> None:
        """A scheme reads as a sequence — Midterm before Final — so `position` keeps
        the order rather than sorting alphabetically and putting Coursework first."""
        _course(as_admin, "CS501", assessments=SCHEME)

        names = [row["name"] for row in as_admin.get("/courses/CS501").json()["assessments"]]

        assert names == ["Midterm", "Coursework", "Final"]

    def test_a_course_may_define_none(self, as_admin: TestClient) -> None:
        """Nothing may break before an administrator has filled one in."""
        response = _course(as_admin, "CS502")

        assert response.status_code == 201, response.text
        assert response.json()["assessments"] == []

    def test_the_scheme_can_be_replaced(self, as_admin: TestClient) -> None:
        _course(as_admin, "CS503", assessments=SCHEME)

        response = as_admin.patch(
            "/courses/CS503", json={"assessments": [{"name": "Portfolio", "weight": 1.0}]}
        )

        assert response.status_code == 200, response.text
        assert [row["name"] for row in response.json()["assessments"]] == ["Portfolio"]

    def test_an_unrelated_edit_leaves_it_alone(self, as_admin: TestClient) -> None:
        """Omission means unchanged. Rewriting on every edit would delete the scheme
        for any client that patches one field at a time."""
        _course(as_admin, "CS504", assessments=SCHEME)

        as_admin.patch("/courses/CS504", json={"room": "B12"})

        assert len(as_admin.get("/courses/CS504").json()["assessments"]) == 3

    def test_deleting_the_course_removes_the_scheme(
        self, as_admin: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        _course(as_admin, "CS505", assessments=SCHEME)

        as_admin.delete("/courses/CS505")

        remaining = seeded_db.execute(
            "SELECT COUNT(*) FROM course_assessments WHERE course_id = 'CS505'"
        ).fetchone()[0]
        assert remaining == 0


class TestRefusals:
    def test_duplicate_names_are_refused(self, as_admin: TestClient) -> None:
        response = _course(
            as_admin,
            "CS510",
            assessments=[{"name": "Final", "weight": 1.0}, {"name": "Final", "weight": 2.0}],
        )

        assert response.status_code == 422

    def test_duplicates_are_compared_after_stripping(self, as_admin: TestClient) -> None:
        """ "Final" and "Final " would otherwise pass validation and then collide on
        the primary key — the same duplicate the report has been splitting on."""
        response = _course(
            as_admin,
            "CS511",
            assessments=[{"name": "Final", "weight": 1.0}, {"name": "Final ", "weight": 2.0}],
        )

        assert response.status_code == 422

    def test_a_blank_name_is_refused(self, as_admin: TestClient) -> None:
        response = _course(as_admin, "CS512", assessments=[{"name": "   ", "weight": 1.0}])

        assert response.status_code == 422

    def test_a_zero_weight_is_refused(self, as_admin: TestClient) -> None:
        """An assessment worth nothing is not an assessment."""
        response = _course(as_admin, "CS513", assessments=[{"name": "Final", "weight": 0}])

        assert response.status_code == 422

    def test_a_negative_weight_is_refused(self, as_admin: TestClient) -> None:
        response = _course(as_admin, "CS514", assessments=[{"name": "Final", "weight": -1}])

        assert response.status_code == 422


class TestGradesAreUntouched:
    """The scheme is what a course offers, not a constraint on what was recorded."""

    def test_a_grade_may_still_carry_a_name_outside_the_scheme(
        self, as_teacher: TestClient
    ) -> None:
        """The CSV importer accepts free text and always will; rejecting it here would
        make a spreadsheet unimportable because a course was tidied up afterwards."""
        response = as_teacher.post(
            "/grades",
            json={
                "student_id": "S001",
                "course_id": "CS101",
                "score": 70,
                "date": "2026-04-01",
                "title": "Resit",
            },
        )

        assert response.status_code == 201, response.text

    def test_reweighting_a_course_does_not_move_a_recorded_mark(self, as_admin: TestClient) -> None:
        """The reason the scheme is not a foreign key. A transcript that changes
        because somebody edited a course setting is worse than a duplicate string."""
        as_admin.patch("/courses/CS101", json={"assessments": [{"name": "Exam", "weight": 1.0}]})
        before = as_admin.get("/grades", params={"course_id": "CS101"}).json()["items"]

        as_admin.patch("/courses/CS101", json={"assessments": [{"name": "Exam", "weight": 9.0}]})

        after = as_admin.get("/grades", params={"course_id": "CS101"}).json()["items"]
        assert [row["weight"] for row in after] == [row["weight"] for row in before]
