"""Fixtures for API tests: an app wired to a throwaway database, plus signed-in clients."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.config import Settings, get_settings
from api.deps import get_db
from api.main import create_app
from api.security import hash_password
from notenverwaltung.models import Role
from notenverwaltung.storage import apply_migrations, connect

PASSWORD = "test-password-2026"

ACCOUNTS = {
    "superadmin": ("root@test.local", Role.SUPERADMIN),
    "admin": ("admin@test.local", Role.ADMIN),
    "teacher": ("teacher@test.local", Role.TEACHER),
    "other_teacher": ("other@test.local", Role.TEACHER),
    "student": ("student@test.local", Role.STUDENT),
    "other_student": ("other.student@test.local", Role.STUDENT),
    "orphan": ("orphan@test.local", Role.STUDENT),
    "disabled": ("disabled@test.local", Role.TEACHER),
}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A throwaway database file.

    A file rather than ``:memory:`` because the app opens its own connection per
    request; an in-memory database would be a different, empty one each time.
    """
    return tmp_path / "test.db"


@pytest.fixture
def seeded_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    """A migrated database with a fixed cast for authorization testing.

    The shape matters more than the size. Two teachers with separate courses and two
    students with separate enrolments is the smallest arrangement in which "sees only
    their own" can actually fail — with one of each, an over-broad query looks correct.
    """
    conn = connect(db_path)
    apply_migrations(conn)

    ids: dict[str, int] = {}
    for key, (email, role) in ACCOUNTS.items():
        digest, salt = hash_password(PASSWORD)
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, password_salt, role, full_name, is_active)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (email, digest, salt, str(role), key.title(), 0 if key == "disabled" else 1),
        )
        ids[key] = cursor.lastrowid or 0

    conn.execute(
        "INSERT INTO students (student_id, first_name, last_name, email, user_id)"
        " VALUES ('S001', 'Anna', 'Schmidt', 'anna@test.local', ?)",
        (ids["student"],),
    )
    conn.execute(
        "INSERT INTO students (student_id, first_name, last_name, email, user_id)"
        " VALUES ('S002', 'Ben', 'Mueller', 'ben@test.local', ?)",
        (ids["other_student"],),
    )
    conn.execute(
        "INSERT INTO students (student_id, first_name, last_name, email)"
        " VALUES ('S003', 'Clara', 'Dubois', 'clara@test.local')"
    )

    conn.execute(
        "INSERT INTO courses (course_id, name, passing_grade, teacher_id)"
        " VALUES ('CS101', 'Intro', 60, ?)",
        (ids["teacher"],),
    )
    conn.execute(
        "INSERT INTO courses (course_id, name, passing_grade, teacher_id)"
        " VALUES ('CS999', 'Someone Elses Course', 60, ?)",
        (ids["other_teacher"],),
    )

    # S001 sits in the first teacher's course; S002 only in the other teacher's.
    conn.execute("INSERT INTO enrollments (student_id, course_id) VALUES ('S001', 'CS101')")
    conn.execute("INSERT INTO enrollments (student_id, course_id) VALUES ('S002', 'CS999')")

    insert_grade = "INSERT INTO grades (student_id, course_id, score, date) VALUES (?, ?, ?, ?)"
    conn.execute(insert_grade, ("S001", "CS101", 85, "2026-01-15"))
    conn.execute(insert_grade, ("S002", "CS999", 45, "2026-01-15"))

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def app(db_path: Path, seeded_db: sqlite3.Connection) -> Generator[FastAPI]:
    """The application, pointed at the throwaway database."""
    settings = Settings(
        database_path=str(db_path),
        secret_key="test-secret-key-not-used-in-production",
        cors_origins="http://localhost:3000",
    )

    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings

    def _db() -> Generator[sqlite3.Connection]:
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    application.dependency_overrides[get_db] = _db
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """An unauthenticated client."""
    with TestClient(app) as test_client:
        yield test_client


def sign_in(test_client: TestClient, key: str) -> TestClient:
    """Sign a client in as one of the fixture accounts.

    Args:
        test_client: The client to authenticate.
        key: An entry in :data:`ACCOUNTS`.

    Returns:
        The same client, now carrying a session cookie.
    """
    email, _ = ACCOUNTS[key]
    response = test_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return test_client


@pytest.fixture
def as_admin(client: TestClient) -> TestClient:
    """A client signed in as an administrator."""
    return sign_in(client, "admin")


@pytest.fixture
def as_teacher(client: TestClient) -> TestClient:
    """A client signed in as the teacher who owns CS101."""
    return sign_in(client, "teacher")


@pytest.fixture
def as_student(client: TestClient) -> TestClient:
    """A client signed in as the student linked to S001."""
    return sign_in(client, "student")
