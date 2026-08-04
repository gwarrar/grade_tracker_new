"""The grade letter and the filters that narrow a listing.

The letter is *derived*, not stored — a percentage measured against the
organisation's configurable scale — so filtering by one means resolving a band label
back to the range it covers. That resolution is the only real logic here, and the
case that matters is the boundary: a band's floor belongs to it, its ceiling belongs
to the band above.

The other property worth pinning is that filters compose onto the caller's scope
rather than replacing it. A query parameter must never widen what a role can see.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def graded(seeded_db: sqlite3.Connection) -> sqlite3.Connection:
    """Add marks across the band boundaries, on a course with max_grade 100.

    90 and 80 are exact boundaries: with A ≥ 90 and B ≥ 80, 90 must be an A and 89.99
    a B. Off-by-one here is the whole risk.
    """
    rows = [
        ("S001", "CS101", 95.0, "2026-01-10", "Quiz"),
        ("S001", "CS101", 90.0, "2026-02-10", "Midterm"),
        ("S001", "CS101", 89.0, "2026-03-10", "Lab"),
        ("S001", "CS101", 80.0, "2026-04-10", "Final"),
        ("S001", "CS101", 55.0, "2026-05-10", "Resit"),
    ]
    for student, course, score, date, title in rows:
        seeded_db.execute(
            "INSERT INTO grades (student_id, course_id, score, date, title) VALUES (?,?,?,?,?)",
            (student, course, score, date, title),
        )
    seeded_db.commit()
    return seeded_db


class TestLetter:
    """Every grade carries the band it falls in."""

    def test_listing_includes_a_letter(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        """The field the grades table needs and never had."""
        rows = as_admin.get("/grades", params={"course_id": "CS101", "size": 100}).json()["items"]

        by_title = {r["title"]: r["letter"] for r in rows if r["title"]}
        assert by_title["Quiz"] == "A"
        assert by_title["Midterm"] == "A", "90 is the floor of A and belongs to it"
        assert by_title["Lab"] == "B", "89 falls below the A floor"
        assert by_title["Final"] == "B"
        assert by_title["Resit"] == "F"

    def test_a_single_grade_carries_it_too(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        """The detail endpoint and the listing must not disagree."""
        listed = as_admin.get("/grades", params={"course_id": "CS101", "size": 100}).json()["items"]
        one = as_admin.get(f"/grades/{listed[0]['grade_id']}").json()

        assert one["letter"] == listed[0]["letter"]


class TestLetterFilter:
    """Filtering by a band resolves it to the percentage range it covers."""

    def test_selects_exactly_that_band(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        """Inclusive floor, exclusive ceiling — the same rule label_for() applies."""
        rows = as_admin.get("/grades", params={"letter": "A", "size": 100}).json()["items"]

        assert {r["title"] for r in rows} == {"Quiz", "Midterm"}
        assert all(r["letter"] == "A" for r in rows)

    def test_the_band_below_gets_the_boundary_cases(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        """The counterweight: 89 and 80 are Bs, not As.

        Titled rows only — the base fixture seeds an untitled 85% mark, which is also
        a B and correctly comes back. Asserting on the titles this test added keeps it
        about the boundary rather than about the fixture.
        """
        rows = as_admin.get("/grades", params={"letter": "B", "size": 100}).json()["items"]

        assert {r["title"] for r in rows if r["title"]} == {"Lab", "Final"}
        assert all(r["letter"] == "B" for r in rows)

    def test_is_case_insensitive(self, as_admin: TestClient, graded: sqlite3.Connection) -> None:
        """`?letter=a` is a reasonable thing for a client to send."""
        assert len(as_admin.get("/grades", params={"letter": "a"}).json()["items"]) == 2

    def test_an_unknown_band_names_the_real_ones(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        """The scale is per-installation, so a client cannot guess the bands."""
        response = as_admin.get("/grades", params={"letter": "Z"})

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert body["context"]["allowed"] == ["A", "B", "C", "D", "F"]


class TestNarrowingFilters:
    """Dates and titles narrow a listing; none of them widen a scope."""

    def test_date_range_is_inclusive_at_both_ends(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        rows = as_admin.get(
            "/grades", params={"date_from": "2026-02-10", "date_to": "2026-04-10", "size": 100}
        ).json()["items"]

        assert {r["title"] for r in rows} == {"Midterm", "Lab", "Final"}

    def test_title_matches_a_substring(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        rows = as_admin.get("/grades", params={"title": "term"}).json()["items"]

        assert {r["title"] for r in rows} == {"Midterm"}

    def test_minimum_score_is_inclusive(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        rows = as_admin.get(
            "/grades", params={"course_id": "CS101", "min_score": 90, "size": 100}
        ).json()["items"]

        assert {r["title"] for r in rows} == {"Quiz", "Midterm"}

    def test_maximum_score_is_inclusive(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        rows = as_admin.get(
            "/grades", params={"course_id": "CS101", "max_score": 80, "size": 100}
        ).json()["items"]

        assert {r["title"] for r in rows} == {"Final", "Resit"}

    def test_minimum_percentage_uses_the_course_maximum(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        graded.execute("UPDATE courses SET max_grade = ? WHERE course_id = ?", (200, "CS101"))
        graded.commit()

        rows = as_admin.get(
            "/grades", params={"course_id": "CS101", "min_percentage": 45, "size": 100}
        ).json()["items"]

        assert {r["title"] for r in rows} == {"Quiz", "Midterm"}

    def test_maximum_percentage_uses_the_course_maximum(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        graded.execute("UPDATE courses SET max_grade = ? WHERE course_id = ?", (200, "CS101"))
        graded.commit()

        rows = as_admin.get(
            "/grades", params={"course_id": "CS101", "max_percentage": 40, "size": 100}
        ).json()["items"]

        assert {r["title"] for r in rows} == {"Final", "Resit"}

    @pytest.mark.parametrize(
        "params",
        [
            {"min_score": 90, "max_score": 80},
            {"min_percentage": 90, "max_percentage": 80},
        ],
    )
    def test_crossed_numeric_ranges_are_rejected(
        self, as_admin: TestClient, params: dict[str, int]
    ) -> None:
        response = as_admin.get("/grades", params=params)

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    def test_a_wildcard_in_the_title_is_a_literal(
        self, as_admin: TestClient, graded: sqlite3.Connection
    ) -> None:
        """`%` must match a percent sign, not everything."""
        assert as_admin.get("/grades", params={"title": "%"}).json()["items"] == []

    def test_sorting_by_percentage(self, as_admin: TestClient, graded: sqlite3.Connection) -> None:
        rows = as_admin.get(
            "/grades", params={"course_id": "CS101", "sort": "percentage", "size": 100}
        ).json()["items"]

        percentages = [r["percentage"] for r in rows]
        assert percentages == sorted(percentages)

    def test_a_filter_cannot_widen_a_student_scope(
        self, as_student: TestClient, graded: sqlite3.Connection
    ) -> None:
        """The property that makes the filters safe to expose at all.

        S001 asking for S002's grades gets nothing — not S002's rows. The filter
        composes onto the scope with AND, so it can only ever subtract.
        """
        rows = as_student.get("/grades", params={"student_id": "S002", "size": 100}).json()["items"]

        assert rows == []
