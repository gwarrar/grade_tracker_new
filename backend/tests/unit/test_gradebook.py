"""GradeBook statistics, search and file interchange.

Runs against both stores via the parametrised `gradebook` fixture.
"""

from __future__ import annotations

import sqlite3

import pytest

from notenverwaltung.gradebook import GradeBook
from notenverwaltung.models import Course, Student
from notenverwaltung.storage import GradeStore


class TestRankings:
    def test_top_students_orders_by_average_descending(self, gradebook: GradeBook) -> None:
        top = gradebook.top_students()
        assert [s.student_id for s, _ in top] == ["S001", "S002"]

    def test_top_students_excludes_the_ungraded(self, gradebook: GradeBook) -> None:
        """Clara has no grades. Ranking her as 0% would put her last on merit she never earned."""
        assert "S003" not in [s.student_id for s, _ in gradebook.top_students()]

    def test_top_students_respects_n(self, gradebook: GradeBook) -> None:
        assert len(gradebook.top_students(n=1)) == 1

    def test_at_risk_is_worst_first(self, gradebook: GradeBook) -> None:
        at_risk = gradebook.students_at_risk(threshold=60.0)
        assert [s.student_id for s, _ in at_risk] == ["S002"]

    def test_at_risk_excludes_the_ungraded(self, gradebook: GradeBook) -> None:
        assert "S003" not in [s.student_id for s, _ in gradebook.students_at_risk(100.0)]

    def test_at_risk_threshold_is_applied(self, gradebook: GradeBook) -> None:
        assert len(gradebook.students_at_risk(threshold=90.0)) == 2  # both graded students


class TestDistribution:
    def test_includes_empty_bands(self, gradebook: GradeBook) -> None:
        """A chart needs a complete axis, not only the categories that happen to be non-zero."""
        distribution = gradebook.grade_distribution()
        assert set(distribution) == {"A", "B", "C", "D", "F"}

    def test_counts_by_percentage_band(self, gradebook: GradeBook) -> None:
        # Anna 85% -> B, Anna 90% -> A, Ben 45% -> F
        assert gradebook.grade_distribution() == {"A": 1, "B": 1, "C": 0, "D": 0, "F": 1}

    def test_can_be_scoped_to_one_course(self, gradebook: GradeBook) -> None:
        assert gradebook.grade_distribution("CS101") == {"A": 0, "B": 1, "C": 0, "D": 0, "F": 1}


class TestStatistics:
    def test_summary_shape(self, gradebook: GradeBook) -> None:
        stats = gradebook.calculate_statistics()
        assert stats["student_count"] == 3
        assert stats["course_count"] == 2
        assert stats["grade_count"] == 3
        assert stats["overall_average_percentage"] == pytest.approx((85 + 90 + 45) / 3)

    def test_average_is_none_when_nothing_is_graded(self, store: GradeStore) -> None:
        """None, not 0.0 — zero would read as 'everybody failed'."""
        assert GradeBook(store).calculate_statistics()["overall_average_percentage"] is None


class TestRankingQueryCost:
    """Both rankings walked every student issuing a query each, and a summary report
    calls both — so one request cost 2*(2N+1) queries for N students, with neither
    pass reusing the other's work.

    Counted rather than timed. A timing assertion on a three-student fixture measures
    nothing; the query count is the thing that grew with the register.
    """

    def test_ranking_reads_the_grades_once(self, sqlite_conn: sqlite3.Connection) -> None:
        book = GradeBook(GradeStore(sqlite_conn))
        book.add_course(Course("C1", "Course", max_grade=100.0))
        for index in range(6):
            student_id = f"S{index:03d}"
            book.add_student(Student(student_id, "First", f"Last{index}", f"s{index}@test.local"))
            sqlite_conn.execute(
                "INSERT INTO enrollments (student_id, course_id) VALUES (?, 'C1')", (student_id,)
            )
            book.record_grade(student_id, "C1", 50 + index * 5, "2026-01-15")

        statements: list[str] = []
        sqlite_conn.set_trace_callback(statements.append)
        try:
            book.top_students()
            book.students_at_risk()
        finally:
            sqlite_conn.set_trace_callback(None)

        # Two rankings, and the count must not scale with the six students. Each pass
        # reads the grades and the students once; the old shape issued a query per
        # student per pass on top of that.
        selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
        assert len(selects) <= 6, selects

    def test_the_rankings_still_agree_with_the_averages(self, gradebook: GradeBook) -> None:
        """The refactor must not change a single number. Anna averages 87.5%, Ben 45%,
        and Clara has no grades at all — she appears in neither list."""
        top = gradebook.top_students()
        at_risk = gradebook.students_at_risk()

        assert [(s.student_id, round(avg, 1)) for s, avg in top] == [("S001", 87.5), ("S002", 45.0)]
        assert [(s.student_id, round(avg, 1)) for s, avg in at_risk] == [("S002", 45.0)]
