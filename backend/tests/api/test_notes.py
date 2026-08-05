"""Notes on students and courses over HTTP.

Covers the visibility matrix per role, the entity-scope 404s on write, the
author-or-admin delete rule, the audit tombstone, and the schema CHECKs.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from notenverwaltung.exceptions import ForbiddenError
from notenverwaltung.models import Role
from services.notes import NotesService
from services.scoping import Principal
from tests.api.conftest import ACCOUNTS, sign_in


def seed_note(
    conn: sqlite3.Connection,
    *,
    body: str,
    visibility: str,
    author: str,
    entity: str = "course",
    entity_id: str = "CS101",
) -> int:
    """Insert a note directly, so each test controls author and visibility."""
    row = conn.execute(
        "SELECT id, full_name FROM users WHERE email = ?", (ACCOUNTS[author][0],)
    ).fetchone()
    cursor = conn.execute(
        "INSERT INTO notes (entity, entity_id, body, visibility, author_id, author_name)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (entity, entity_id, body, visibility, row["id"], row["full_name"]),
    )
    return cursor.lastrowid or 0


def visible_bodies(client: TestClient, path: str) -> set[str]:
    """Return the note bodies a caller can read on one entity."""
    response = client.get(path)
    assert response.status_code == 200, response.text
    return {note["body"] for note in response.json()}


def seed_full_course_thread(conn: sqlite3.Connection) -> None:
    """One note per visibility by the teacher, plus private notes by two students."""
    seed_note(conn, body="t-private", visibility="private", author="teacher")
    seed_note(conn, body="t-staff", visibility="staff", author="teacher")
    seed_note(conn, body="t-shared", visibility="shared", author="teacher")
    seed_note(conn, body="t-course", visibility="course", author="teacher")
    seed_note(conn, body="s-private", visibility="private", author="student")
    seed_note(conn, body="o-private", visibility="private", author="other_student")


class TestCourseNoteVisibility:
    def test_admin_sees_every_visibility(
        self, as_admin: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        seed_full_course_thread(seeded_db)
        assert visible_bodies(as_admin, "/courses/CS101/notes") == {
            "t-private",
            "t-staff",
            "t-shared",
            "t-course",
            "s-private",
            "o-private",
        }

    def test_superadmin_sees_every_visibility(
        self, as_superadmin: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        seed_full_course_thread(seeded_db)
        assert len(visible_bodies(as_superadmin, "/courses/CS101/notes")) == 6

    def test_teacher_sees_staff_shared_course_and_their_own_private(
        self, as_teacher: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        seed_full_course_thread(seeded_db)
        assert visible_bodies(as_teacher, "/courses/CS101/notes") == {
            "t-private",
            "t-staff",
            "t-shared",
            "t-course",
        }

    def test_teacher_cannot_read_a_private_note_authored_by_someone_else(
        self, as_teacher: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        seed_note(seeded_db, body="s-private", visibility="private", author="student")
        assert visible_bodies(as_teacher, "/courses/CS101/notes") == set()

    def test_student_sees_shared_course_and_their_own_private(
        self, as_student: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        seed_full_course_thread(seeded_db)
        assert visible_bodies(as_student, "/courses/CS101/notes") == {
            "t-shared",
            "t-course",
            "s-private",
        }

    def test_a_student_does_not_see_another_students_private_note(
        self, as_student: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        seed_note(seeded_db, body="o-private", visibility="private", author="other_student")
        assert visible_bodies(as_student, "/courses/CS101/notes") == set()

    def test_a_student_cannot_read_a_staff_note(
        self, as_student: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        seed_note(seeded_db, body="t-staff", visibility="staff", author="teacher")
        assert visible_bodies(as_student, "/courses/CS101/notes") == set()

    def test_listing_requires_a_session(self, client: TestClient) -> None:
        assert client.get("/courses/CS101/notes").status_code == 401

    def test_an_unenrolled_student_gets_not_found(self, client: TestClient) -> None:
        """The entity is out of scope, so the notes on it are 404 rather than empty."""
        sign_in(client, "orphan")
        response = client.get("/courses/CS101/notes")
        assert response.status_code == 404
        assert response.json()["code"] == "COURSE_NOT_FOUND"


class TestStudentNoteVisibility:
    def test_teacher_sees_staff_shared_course_and_their_own_private(
        self, as_teacher: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        seed_note(
            seeded_db,
            body="n-staff",
            visibility="staff",
            author="teacher",
            entity="student",
            entity_id="S001",
        )
        seed_note(
            seeded_db,
            body="n-shared",
            visibility="shared",
            author="admin",
            entity="student",
            entity_id="S001",
        )
        seed_note(
            seeded_db,
            body="n-course",
            visibility="course",
            author="teacher",
            entity="student",
            entity_id="S001",
        )
        seed_note(
            seeded_db,
            body="n-own-private",
            visibility="private",
            author="teacher",
            entity="student",
            entity_id="S001",
        )
        seed_note(
            seeded_db,
            body="n-other-private",
            visibility="private",
            author="other_teacher",
            entity="student",
            entity_id="S001",
        )
        assert visible_bodies(as_teacher, "/students/S001/notes") == {
            "n-staff",
            "n-shared",
            "n-course",
            "n-own-private",
        }

    def test_admin_sees_every_visibility(
        self, as_admin: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        seed_note(
            seeded_db,
            body="n-private",
            visibility="private",
            author="teacher",
            entity="student",
            entity_id="S001",
        )
        seed_note(
            seeded_db,
            body="n-staff",
            visibility="staff",
            author="teacher",
            entity="student",
            entity_id="S001",
        )
        assert visible_bodies(as_admin, "/students/S001/notes") == {"n-private", "n-staff"}

    def test_student_notes_are_staff_only_to_read(self, as_student: TestClient) -> None:
        """A note on a student record is staff-written and staff-read."""
        response = as_student.get("/students/S001/notes")
        assert response.status_code == 403

    def test_an_out_of_scope_student_is_not_found(self, as_teacher: TestClient) -> None:
        """S002 sits only in the other teacher's course."""
        response = as_teacher.get("/students/S002/notes")
        assert response.status_code == 404
        assert response.json()["code"] == "STUDENT_NOT_FOUND"


class TestNoteWrites:
    def test_a_course_note_defaults_to_course_visibility(self, as_student: TestClient) -> None:
        """`staff` would hide a student's note from their classmates."""
        response = as_student.post("/courses/CS101/notes", json={"body": "When is the exam?"})
        assert response.status_code == 201, response.text
        note = response.json()
        assert note["visibility"] == "course"
        assert note["entity"] == "course"
        assert note["entity_id"] == "CS101"
        assert note["author_name"] == "Student"

    def test_a_student_note_defaults_to_staff_visibility(self, as_teacher: TestClient) -> None:
        response = as_teacher.post("/students/S001/notes", json={"body": "Admission interview."})
        assert response.status_code == 201, response.text
        assert response.json()["visibility"] == "staff"

    def test_an_explicit_visibility_is_respected(self, as_student: TestClient) -> None:
        response = as_student.post(
            "/courses/CS101/notes", json={"body": "Reminder.", "visibility": "private"}
        )
        assert response.status_code == 201
        assert response.json()["visibility"] == "private"

    def test_a_student_cannot_write_a_student_note(self, as_student: TestClient) -> None:
        response = as_student.post("/students/S001/notes", json={"body": "Me?"})
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_posting_to_an_out_of_scope_course_is_not_found(self, as_teacher: TestClient) -> None:
        response = as_teacher.post("/courses/CS999/notes", json={"body": "Hello?"})
        assert response.status_code == 404
        assert response.json()["code"] == "COURSE_NOT_FOUND"

    def test_posting_to_an_out_of_scope_student_is_not_found(self, as_teacher: TestClient) -> None:
        response = as_teacher.post("/students/S002/notes", json={"body": "Hello?"})
        assert response.status_code == 404
        assert response.json()["code"] == "STUDENT_NOT_FOUND"

    def test_an_unknown_visibility_is_rejected(self, as_teacher: TestClient) -> None:
        response = as_teacher.post(
            "/courses/CS101/notes", json={"body": "X", "visibility": "public"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    def test_an_empty_body_is_rejected(self, as_teacher: TestClient) -> None:
        assert as_teacher.post("/courses/CS101/notes", json={"body": ""}).status_code == 422


class TestNoteDelete:
    def test_the_author_may_delete_their_own_note(
        self, as_teacher: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        note_id = seed_note(seeded_db, body="gone", visibility="staff", author="teacher")
        assert as_teacher.delete(f"/notes/{note_id}").status_code == 204
        assert visible_bodies(as_teacher, "/courses/CS101/notes") == set()

    def test_a_student_author_may_delete_their_own_note(
        self, as_student: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        note_id = seed_note(seeded_db, body="mine", visibility="private", author="student")
        assert as_student.delete(f"/notes/{note_id}").status_code == 204

    def test_an_admin_may_delete_someone_elses_note(
        self, as_admin: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        note_id = seed_note(seeded_db, body="by teacher", visibility="course", author="teacher")
        assert as_admin.delete(f"/notes/{note_id}").status_code == 204

    def test_a_student_cannot_delete_someone_elses_note(
        self, as_student: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        note_id = seed_note(seeded_db, body="by teacher", visibility="course", author="teacher")
        response = as_student.delete(f"/notes/{note_id}")
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_a_teacher_cannot_delete_a_colleagues_visible_note(
        self, as_teacher: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        """A `staff` note by an admin is readable but not deletable by a teacher."""
        note_id = seed_note(seeded_db, body="by admin", visibility="staff", author="admin")
        assert as_teacher.delete(f"/notes/{note_id}").status_code == 403

    def test_an_invisible_note_is_not_found_rather_than_forbidden(
        self, as_teacher: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        note_id = seed_note(seeded_db, body="s-private", visibility="private", author="student")
        response = as_teacher.delete(f"/notes/{note_id}")
        assert response.status_code == 404
        assert response.json()["code"] == "NOTE_NOT_FOUND"

    def test_a_missing_note_is_not_found(self, as_admin: TestClient) -> None:
        assert as_admin.delete("/notes/99999").status_code == 404

    def test_delete_requires_a_session(
        self, client: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        note_id = seed_note(seeded_db, body="x", visibility="course", author="teacher")
        assert client.delete(f"/notes/{note_id}").status_code == 401

    def test_delete_writes_the_full_before_snapshot_to_the_audit_log(
        self, as_teacher: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        note_id = seed_note(seeded_db, body="tombstone", visibility="staff", author="teacher")
        assert as_teacher.delete(f"/notes/{note_id}").status_code == 204

        row = seeded_db.execute(
            "SELECT actor_user_id, before_json FROM audit_log"
            " WHERE entity = 'note' AND entity_id = ? AND action = 'delete'",
            (str(note_id),),
        ).fetchone()
        assert row is not None
        before = json.loads(row["before_json"])
        assert before["body"] == "tombstone"
        assert before["visibility"] == "staff"
        assert before["entity"] == "course"
        assert before["entity_id"] == "CS101"
        actor = seeded_db.execute(
            "SELECT id FROM users WHERE email = ?", (ACCOUNTS["teacher"][0],)
        ).fetchone()
        assert row["actor_user_id"] == actor["id"]


class TestSchemaConstraints:
    def test_the_entity_check_rejects_unknown_entities(self, seeded_db: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            seed_note(seeded_db, body="x", visibility="staff", author="teacher", entity="grade")

    def test_the_visibility_check_rejects_unknown_visibilities(
        self, seeded_db: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            seed_note(seeded_db, body="x", visibility="public", author="teacher")


class TestServiceGuards:
    def test_the_service_itself_refuses_a_student_writing_a_student_note(
        self, seeded_db: sqlite3.Connection
    ) -> None:
        """The route gate is TeacherUser; the service does not trust that alone."""
        principal = Principal(
            user_id=99, role=Role.STUDENT, email="s@x.co", full_name="S", student_id="S001"
        )
        service = NotesService(seeded_db, principal)
        with pytest.raises(ForbiddenError):
            service.create_student_note("S001", "sneaky")
