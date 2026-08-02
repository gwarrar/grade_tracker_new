"""Directory metadata and student lifecycle behavior over HTTP."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services import audit
from services import directory as directory_service


def test_student_metadata_create_and_update(as_admin: TestClient) -> None:
    created = as_admin.post(
        "/students",
        json={
            "student_id": "S900",
            "first_name": "New",
            "last_name": "Student",
            "email": "new.student@test.local",
            "phone": "+49 30 123456",
            "date_of_birth": "2004-02-29",
            "cohort": "2026-A",
        },
    )

    assert created.status_code == 201
    assert {
        key: created.json()[key] for key in ("is_active", "phone", "date_of_birth", "cohort")
    } == {
        "is_active": True,
        "phone": "+49 30 123456",
        "date_of_birth": "2004-02-29",
        "cohort": "2026-A",
    }

    updated = as_admin.patch(
        "/students/S900",
        json={"is_active": False, "phone": None, "cohort": "2026-B"},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False
    assert updated.json()["phone"] is None
    assert updated.json()["cohort"] == "2026-B"


def test_course_metadata_prerequisites_and_archived_readability(as_admin: TestClient) -> None:
    created = as_admin.post(
        "/courses",
        json={
            "course_id": "CS301",
            "name": "Compilers",
            "description": "Language implementation",
            "room": "B-12",
            "schedule": "Mon 09:00",
            "department": "Computer Science",
            "start_date": "2026-10-01",
            "end_date": "2027-02-15",
            "status": "archived",
            "prerequisite_ids": ["CS101", "CS999"],
        },
    )

    assert created.status_code == 201
    assert created.json()["status"] == "archived"
    assert created.json()["prerequisite_ids"] == ["CS101", "CS999"]
    assert created.json()["department"] == "Computer Science"
    assert as_admin.get("/courses/CS301").status_code == 200
    assert "CS301" in [course["course_id"] for course in as_admin.get("/courses").json()["items"]]


def test_prerequisite_replacement_and_cascade(
    as_admin: TestClient, seeded_db: sqlite3.Connection
) -> None:
    response = as_admin.post(
        "/courses",
        json={"course_id": "CS301", "name": "Compilers", "prerequisite_ids": ["CS101"]},
    )
    assert response.status_code == 201

    replaced = as_admin.patch("/courses/CS301", json={"prerequisite_ids": ["CS999"]})
    assert replaced.status_code == 200
    assert replaced.json()["prerequisite_ids"] == ["CS999"]
    assert (
        seeded_db.execute(
            "SELECT requires_course_id FROM course_prerequisites WHERE course_id = 'CS301'"
        ).fetchone()[0]
        == "CS999"
    )

    assert as_admin.delete("/courses/CS999").status_code == 204
    assert as_admin.get("/courses/CS301").json()["prerequisite_ids"] == []


def test_prerequisite_revalidation_and_residual_constraint_error_are_controlled(
    as_admin: TestClient,
    seeded_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        as_admin.post(
            "/courses",
            json={"course_id": "CS301", "name": "Compilers", "prerequisite_ids": ["CS101"]},
        ).status_code
        == 201
    )
    real_validation = directory_service.DirectoryService._validate_prerequisites  # pyright: ignore[reportPrivateUsage]

    def validate_then_remove_prerequisite(
        service: directory_service.DirectoryService,
        course_id: str,
        prerequisite_ids: list[str],
    ) -> None:
        conn = service._conn  # pyright: ignore[reportPrivateUsage]
        assert conn.in_transaction
        real_validation(service, course_id, prerequisite_ids)
        conn.execute("DELETE FROM courses WHERE course_id = 'CS999'")

    monkeypatch.setattr(
        directory_service.DirectoryService,
        "_validate_prerequisites",
        validate_then_remove_prerequisite,
    )

    response = as_admin.patch("/courses/CS301", json={"prerequisite_ids": ["CS999"]})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert as_admin.get("/courses/CS301").json()["prerequisite_ids"] == ["CS101"]


@pytest.mark.parametrize("prerequisite_ids", [["MISSING"], ["CS101", "CS101"]])
def test_bad_prerequisites_return_controlled_validation(
    as_admin: TestClient, prerequisite_ids: list[str]
) -> None:
    response = as_admin.post(
        "/courses",
        json={"course_id": "CS301", "name": "Compilers", "prerequisite_ids": prerequisite_ids},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_invalid_directory_dates_are_rejected(as_admin: TestClient) -> None:
    response = as_admin.patch("/courses/CS101", json={"start_date": "2026-02-30"})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_inactive_student_cannot_be_enrolled(as_admin: TestClient) -> None:
    assert as_admin.patch("/students/S003", json={"is_active": False}).status_code == 200

    response = as_admin.post("/courses/CS101/enrollments", json={"student_id": "S003"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_enrollment_and_deactivation_use_activity_state_inside_transaction(
    as_admin: TestClient,
    seeded_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_transaction = directory_service.transaction
    student_ids = iter(("S003", "S001"))

    @contextmanager
    def deactivate_before_transaction(
        conn: sqlite3.Connection,
    ) -> Generator[sqlite3.Connection]:
        seeded_db.execute(
            "UPDATE students SET is_active = 0 WHERE student_id = ?", (next(student_ids),)
        )
        with real_transaction(conn):
            yield conn

    monkeypatch.setattr(directory_service, "transaction", deactivate_before_transaction)

    enrollment_response = as_admin.post("/courses/CS101/enrollments", json={"student_id": "S003"})
    deactivation_response = as_admin.patch("/students/S001", json={"is_active": False})

    actual = {
        "enrollment_http_status": enrollment_response.status_code,
        "enrollment_error_code": enrollment_response.json().get("code"),
        "enrollment_count": seeded_db.execute(
            "SELECT COUNT(*) FROM enrollments WHERE student_id = 'S003' AND course_id = 'CS101'"
        ).fetchone()[0],
        "deactivation_http_status": deactivation_response.status_code,
        "existing_enrollment_status": seeded_db.execute(
            "SELECT status FROM enrollments WHERE student_id = 'S001' AND course_id = 'CS101'"
        ).fetchone()[0],
    }
    assert actual == {
        "enrollment_http_status": 422,
        "enrollment_error_code": "VALIDATION_ERROR",
        "enrollment_count": 0,
        "deactivation_http_status": 200,
        "existing_enrollment_status": "active",
    }


def test_deactivation_withdraws_every_active_enrollment_and_audits_each(
    as_admin: TestClient, seeded_db: sqlite3.Connection
) -> None:
    assert (
        as_admin.post("/courses/CS999/enrollments", json={"student_id": "S001"}).status_code == 201
    )

    response = as_admin.patch("/students/S001", json={"is_active": False})

    assert response.status_code == 200
    statuses = seeded_db.execute(
        "SELECT course_id, status FROM enrollments WHERE student_id = 'S001' ORDER BY course_id"
    ).fetchall()
    assert [tuple(row) for row in statuses] == [("CS101", "withdrawn"), ("CS999", "withdrawn")]

    enrollment_audits = seeded_db.execute(
        "SELECT entity_id, before_json, after_json FROM audit_log"
        " WHERE entity = 'enrollment' AND action = 'update' ORDER BY entity_id"
    ).fetchall()
    assert [row["entity_id"] for row in enrollment_audits] == ["S001:CS101", "S001:CS999"]
    for row in enrollment_audits:
        assert json.loads(row["before_json"])["status"] == "active"
        assert json.loads(row["after_json"])["status"] == "withdrawn"

    student_audit = seeded_db.execute(
        "SELECT before_json, after_json FROM audit_log"
        " WHERE entity = 'student' AND entity_id = 'S001' AND action = 'update'"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert json.loads(student_audit["before_json"])["is_active"] is True
    assert json.loads(student_audit["after_json"])["is_active"] is False


def test_audit_failure_rolls_back_student_enrollments_and_audits(
    as_admin: TestClient,
    seeded_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        as_admin.post("/courses/CS999/enrollments", json={"student_id": "S001"}).status_code == 201
    )
    before_audits = seeded_db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    real_record = audit.record
    enrollment_updates = 0

    def fail_after_one_enrollment_audit(conn: sqlite3.Connection, **kwargs: Any) -> None:
        nonlocal enrollment_updates
        if kwargs["entity"] == "enrollment" and kwargs["action"] == "update":
            enrollment_updates += 1
            if enrollment_updates == 2:
                raise RuntimeError("injected audit failure")
        real_record(conn, **kwargs)

    monkeypatch.setattr(audit, "record", fail_after_one_enrollment_audit)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        as_admin.patch("/students/S001", json={"is_active": False})

    assert (
        seeded_db.execute("SELECT is_active FROM students WHERE student_id = 'S001'").fetchone()[0]
        == 1
    )
    assert {
        row[0]
        for row in seeded_db.execute("SELECT status FROM enrollments WHERE student_id = 'S001'")
    } == {"active"}
    assert seeded_db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == before_audits


def test_reactivation_does_not_restore_enrollments(
    as_admin: TestClient, seeded_db: sqlite3.Connection
) -> None:
    assert as_admin.patch("/students/S001", json={"is_active": False}).status_code == 200
    assert as_admin.patch("/students/S001", json={"is_active": True}).status_code == 200

    assert (
        seeded_db.execute(
            "SELECT status FROM enrollments WHERE student_id = 'S001' AND course_id = 'CS101'"
        ).fetchone()[0]
        == "withdrawn"
    )


def test_only_at_risk_excludes_inactive_students(as_admin: TestClient) -> None:
    assert as_admin.patch("/students/S002", json={"is_active": False}).status_code == 200

    assert as_admin.get("/students").json()["total"] == 3
    assert as_admin.get("/analytics/dashboard").json()["student_count"] == 3
    at_risk_ids = {
        student["student_id"] for student in as_admin.get("/analytics/at-risk?threshold=100").json()
    }
    assert "S002" not in at_risk_ids
