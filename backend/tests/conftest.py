"""Shared fixtures."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from notenverwaltung.gradebook import GradeBook
from notenverwaltung.models import Course, Student
from notenverwaltung.storage import GradeStore, apply_migrations, connect


@pytest.fixture
def sqlite_conn() -> Iterator[sqlite3.Connection]:
    """A migrated in-memory SQLite connection."""
    conn = connect(":memory:")
    apply_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def store() -> Iterator[GradeStore]:
    """A store over a migrated in-memory database.

    On SQLite, `:memory:` is the real engine rather than a stand-in, so these tests
    exercise the same SQL, constraints and cascades that production runs.
    """
    conn = connect(":memory:")
    apply_migrations(conn)
    yield GradeStore(conn)
    conn.close()


@pytest.fixture
def sample_students() -> list[Student]:
    """Three students."""
    return [
        Student("S001", "Anna", "Schmidt", "anna@example.com"),
        Student("S002", "Ben", "Mueller", "ben@example.com"),
        Student("S003", "Clara", "Dubois", "clara@example.com"),
    ]


@pytest.fixture
def sample_courses() -> list[Course]:
    """Two courses with different maxima, so percentage-vs-score bugs surface."""
    return [
        Course("CS101", "Intro to Programming", max_grade=100.0, passing_grade=50.0),
        Course("CS102", "Data Structures", max_grade=20.0, passing_grade=10.0),
    ]


@pytest.fixture
def gradebook(
    store: GradeStore, sample_students: list[Student], sample_courses: list[Course]
) -> GradeBook:
    """A populated grade book.

    Anna: 85/100 (85%) and 18/20 (90%)  → average 87.5%
    Ben:  45/100 (45%)                  → average 45%, at risk
    Clara: no grades                    → excluded from averages entirely
    """
    book = GradeBook(store)
    for student in sample_students:
        book.add_student(student)
    for course in sample_courses:
        book.add_course(course)
    book.record_grade("S001", "CS101", 85, "2026-01-15", title="Midterm")
    book.record_grade("S001", "CS102", 18, "2026-01-20", title="Final")
    book.record_grade("S002", "CS101", 45, "2026-01-15", title="Midterm")
    return book
