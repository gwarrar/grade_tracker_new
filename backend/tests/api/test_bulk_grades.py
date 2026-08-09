"""Recording one assessment's marks for a whole class.

The guarantee that matters is partial success: a teacher entering thirty marks with
one typo wants twenty-nine recorded and to be told precisely which one failed. That
works because `record()` opens its own transaction, which nests inside the batch's as
a savepoint — the same mechanism the file importer uses, tested here for the path a
teacher actually takes.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

ENDPOINT = "/grades/bulk"


@pytest.fixture
def classroom(as_teacher: TestClient) -> TestClient:
    """CS101 with both seeded students on the register.

    The seed enrols S001 only. A mark is refused for anybody with no enrolment --
    that row is the evidence they were in the room -- so a test about marking a
    *class* has to build one first.
    """
    response = as_teacher.post("/courses/CS101/enrollments", json={"student_id": "S002"})
    assert response.status_code == 201, response.text
    return as_teacher


def _payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "course_id": "CS101",
        "title": "Midterm",
        "date": "2026-03-14",
        "weight": 1.0,
        "scores": [{"student_id": "S001", "score": 85}],
    }
    body.update(overrides)
    return body


def test_a_teacher_records_a_whole_class_at_once(classroom: TestClient) -> None:
    response = classroom.post(
        ENDPOINT,
        json=_payload(
            scores=[{"student_id": "S001", "score": 85}, {"student_id": "S002", "score": 62}]
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"imported": 2, "skipped": 0, "errors": []}

    recorded = classroom.get("/grades", params={"course_id": "CS101", "title": "Midterm"}).json()
    assert {row["student_id"] for row in recorded["items"]} == {"S001", "S002"}


def test_the_assessment_is_applied_to_every_mark(classroom: TestClient) -> None:
    """Stated once, because marking a test is one act with many results."""
    classroom.post(
        ENDPOINT,
        json=_payload(
            title="Final",
            date="2026-05-02",
            weight=3.0,
            scores=[{"student_id": "S001", "score": 90}, {"student_id": "S002", "score": 70}],
        ),
    )

    rows = classroom.get("/grades", params={"course_id": "CS101", "title": "Final"}).json()["items"]

    assert {row["date"] for row in rows} == {"2026-05-02"}
    assert {row["weight"] for row in rows} == {3.0}


def test_one_bad_mark_costs_only_itself(classroom: TestClient) -> None:
    """The whole reason this returns a report rather than succeeding or failing."""
    response = classroom.post(
        ENDPOINT,
        json=_payload(
            scores=[
                {"student_id": "S001", "score": 85},
                {"student_id": "S002", "score": 5000},  # above the course maximum
                {"student_id": "ghost", "score": 70},
            ]
        ),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 1
    assert body["skipped"] == 2
    assert {error["student_id"] for error in body["errors"]} == {"S002", "ghost"}
    assert {error["code"] for error in body["errors"]} == {"VALIDATION_ERROR", "STUDENT_NOT_FOUND"}


def test_the_good_marks_survive_the_bad_ones(
    as_teacher: TestClient, seeded_db: sqlite3.Connection
) -> None:
    """A savepoint rolls back the failing row alone; the batch still commits."""
    before = seeded_db.execute("SELECT COUNT(*) FROM grades").fetchone()[0]

    as_teacher.post(
        ENDPOINT,
        json=_payload(
            scores=[{"student_id": "S001", "score": 85}, {"student_id": "ghost", "score": 70}]
        ),
    )

    assert seeded_db.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == before + 1


def test_every_mark_is_audited(classroom: TestClient, seeded_db: sqlite3.Connection) -> None:
    """A batch is not an exception to the trail — thirty marks are thirty decisions."""
    before = seeded_db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE entity = 'grade' AND action = 'create'"
    ).fetchone()[0]

    classroom.post(
        ENDPOINT,
        json=_payload(
            scores=[{"student_id": "S001", "score": 85}, {"student_id": "S002", "score": 62}]
        ),
    )

    after = seeded_db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE entity = 'grade' AND action = 'create'"
    ).fetchone()[0]
    assert after == before + 2


def test_a_teacher_cannot_mark_someone_elses_course(as_teacher: TestClient) -> None:
    """Refused outright rather than reported as N rejected rows: one cause, one answer."""
    response = as_teacher.post(ENDPOINT, json=_payload(course_id="CS999"))

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_a_student_cannot_mark_anything(as_student: TestClient) -> None:
    assert as_student.post(ENDPOINT, json=_payload()).status_code == 403


def test_an_empty_batch_is_refused(as_teacher: TestClient) -> None:
    """Nothing to record is a mistake worth reporting, not a no-op worth accepting."""
    assert as_teacher.post(ENDPOINT, json=_payload(scores=[])).status_code == 422


def test_the_batch_is_capped(as_teacher: TestClient) -> None:
    """A list body with no bound is a denial of service dressed up as a spreadsheet."""
    scores = [{"student_id": f"S{index:03d}", "score": 50} for index in range(501)]

    assert as_teacher.post(ENDPOINT, json=_payload(scores=scores)).status_code == 422


def test_an_unparseable_date_refuses_the_whole_batch(as_teacher: TestClient) -> None:
    """The date is stated once, so a bad one is wrong for every mark, not some."""
    response = as_teacher.post(ENDPOINT, json=_payload(date="not-a-date"))

    assert response.status_code == 200
    assert response.json()["imported"] == 0
    assert response.json()["skipped"] == 1
