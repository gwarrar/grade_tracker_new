"""GradeBook statistics, search and file interchange.

Runs against both stores via the parametrised `gradebook` fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from notenverwaltung.exceptions import (
    CourseNotFoundError,
    NoGradesRecordedError,
    StudentNotFoundError,
    ValidationError,
)
from notenverwaltung.gradebook import GradeBook
from notenverwaltung.models import Course, Student
from notenverwaltung.storage import InMemoryGradeStore


class TestAverages:
    def test_student_average_uses_percentages_not_raw_scores(self, gradebook: GradeBook) -> None:
        """Anna scored 85/100 (85%) and 18/20 (90%). The mean is 87.5%.

        Averaging the raw scores would give (85+18)/2 = 51.5, which describes nothing —
        the two courses are marked out of different maxima. This is the defect the
        coursework version had, and the reason the fixture deliberately uses two
        different maxima.
        """
        assert gradebook.student_average("S001") == pytest.approx(87.5)

    def test_course_average_uses_raw_scores(self, gradebook: GradeBook) -> None:
        """Within one course every grade shares a maximum, so raw scores are correct."""
        assert gradebook.course_average("CS101") == pytest.approx(65.0)  # (85 + 45) / 2

    def test_weights_are_honoured(self) -> None:
        book = GradeBook(InMemoryGradeStore())
        book.add_student(Student("S001", "Anna", "S", "a@example.com"))
        book.add_course(Course("CS101", "Intro"))
        book.record_grade("S001", "CS101", 50, "2026-01-15", title="Quiz", weight=1)
        book.record_grade("S001", "CS101", 100, "2026-06-15", title="Final", weight=3)
        # (50*1 + 100*3) / 4 = 87.5
        assert book.student_average("S001") == pytest.approx(87.5)

    def test_ungraded_student_raises_rather_than_returning_zero(self, gradebook: GradeBook) -> None:
        """No data is not the same as a score of zero — the UI must show them differently."""
        with pytest.raises(NoGradesRecordedError):
            gradebook.student_average("S003")

    def test_unknown_student_raises_not_found(self, gradebook: GradeBook) -> None:
        with pytest.raises(StudentNotFoundError):
            gradebook.student_average("ghost")

    def test_pass_rate(self, gradebook: GradeBook) -> None:
        assert gradebook.course_pass_rate("CS101") == pytest.approx(50.0)  # 85 passes, 45 fails

    def test_pass_rate_on_ungraded_course_raises(self, gradebook: GradeBook) -> None:
        gradebook.add_course(Course("CS999", "Empty"))
        with pytest.raises(NoGradesRecordedError):
            gradebook.course_pass_rate("CS999")


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


class TestGradedStudentCount:
    def test_counts_distinct_students_not_grades(self, gradebook: GradeBook) -> None:
        """The coursework version returned len(grades), double-counting repeat assessments."""
        gradebook.record_grade("S001", "CS101", 95, "2026-06-15", title="Resit")
        assert len(gradebook.get_course_grades("CS101")) == 3
        assert gradebook.graded_student_count("CS101") == 2

    def test_unknown_course_raises(self, gradebook: GradeBook) -> None:
        with pytest.raises(CourseNotFoundError):
            gradebook.graded_student_count("ghost")


class TestSearch:
    def test_matches_across_name_and_email(self, gradebook: GradeBook) -> None:
        assert [s.student_id for s in gradebook.search_students("anna")] == ["S001"]
        assert [s.student_id for s in gradebook.search_students("mueller")] == ["S002"]
        assert [s.student_id for s in gradebook.search_students("@example.com")] == [
            "S001",
            "S002",
            "S003",
        ]

    def test_is_case_insensitive(self, gradebook: GradeBook) -> None:
        assert gradebook.search_students("ANNA") == gradebook.search_students("anna")

    def test_supports_regex(self, gradebook: GradeBook) -> None:
        assert [s.student_id for s in gradebook.search_students("^Anna$")] == ["S001"]

    @pytest.mark.parametrize("bad", ["[", "(unclosed", "*", "a{2,1}"])
    def test_invalid_regex_raises_validation_not_a_server_error(
        self, gradebook: GradeBook, bad: str
    ) -> None:
        """The coursework version passed user input straight to re.search, so a
        search for "[" raised re.error and surfaced as HTTP 500."""
        with pytest.raises(ValidationError):
            gradebook.search_students(bad)

    def test_course_search_covers_name_and_id(self, gradebook: GradeBook) -> None:
        assert [c.course_id for c in gradebook.search_courses("CS101")] == ["CS101"]
        assert [c.course_id for c in gradebook.search_courses("Structures")] == ["CS102"]


class TestJsonInterchange:
    def test_round_trip_preserves_everything(self, gradebook: GradeBook, tmp_path: Path) -> None:
        path = tmp_path / "book.json"
        gradebook.save_json(path)

        restored = GradeBook(InMemoryGradeStore())
        restored.load_json(path)

        assert len(restored.students) == 3
        assert len(restored.courses) == 2
        assert len(restored.grades) == 3
        assert restored.student_average("S001") == pytest.approx(87.5)

    def test_malformed_json_raises_validation(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValidationError):
            GradeBook(InMemoryGradeStore()).load_json(path)

    def test_non_object_json_raises_validation(self, tmp_path: Path) -> None:
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ValidationError):
            GradeBook(InMemoryGradeStore()).load_json(path)


class TestCsvInterchange:
    def test_export_then_reimport(self, gradebook: GradeBook, tmp_path: Path) -> None:
        export = tmp_path / "grades.csv"
        gradebook.export_csv(export)
        assert "student_id" in export.read_text(encoding="utf-8").splitlines()[0]

    def test_import_records_valid_rows(self, gradebook: GradeBook, tmp_path: Path) -> None:
        path = tmp_path / "import.csv"
        path.write_text(
            "student_id,course_id,score,date\nS002,CS102,15,2026-02-01\nS003,CS101,70,2026-02-01\n",
            encoding="utf-8",
        )
        report = gradebook.import_csv(path)
        assert (report.imported, report.skipped) == (2, 0)
        assert len(gradebook.grades) == 5

    def test_one_bad_row_does_not_abort_the_file(
        self, gradebook: GradeBook, tmp_path: Path
    ) -> None:
        """A teacher pasting 300 rows wants the 297 good ones kept."""
        path = tmp_path / "mixed.csv"
        path.write_text(
            "student_id,course_id,score,date\n"
            "S002,CS102,15,2026-02-01\n"  # ok
            "GHOST,CS101,70,2026-02-01\n"  # unknown student
            "S003,GHOST,70,2026-02-01\n"  # unknown course
            "S003,CS101,not-a-number,2026-02-01\n"
            "S003,CS101,700,2026-02-01\n"  # above max_grade
            "S003,CS101,70,31-31-2026\n"  # impossible date
            "S003,CS101,70,2026-02-02\n",  # ok
            encoding="utf-8",
        )
        report = gradebook.import_csv(path)
        assert (report.imported, report.skipped) == (2, 5)
        assert [line for line, _ in report.errors] == [3, 4, 5, 6, 7]

    def test_error_codes_are_machine_readable(self, gradebook: GradeBook, tmp_path: Path) -> None:
        """The frontend translates these; the backend never emits prose."""
        path = tmp_path / "bad.csv"
        path.write_text(
            "student_id,course_id,score,date\nGHOST,CS101,70,2026-02-01\n", encoding="utf-8"
        )
        assert gradebook.import_csv(path).errors == [(2, "STUDENT_NOT_FOUND")]

    def test_missing_required_column_is_rejected(
        self, gradebook: GradeBook, tmp_path: Path
    ) -> None:
        path = tmp_path / "short.csv"
        path.write_text("student_id,course_id\nS001,CS101\n", encoding="utf-8")
        with pytest.raises(ValidationError) as exc:
            gradebook.import_csv(path)
        assert set(exc.value.context["missing_columns"]) == {"score", "date"}  # type: ignore[arg-type]

    def test_optional_columns_are_used_when_present(
        self, gradebook: GradeBook, tmp_path: Path
    ) -> None:
        path = tmp_path / "full.csv"
        path.write_text(
            "student_id,course_id,score,date,title,weight,notes\n"
            "S003,CS101,70,2026-02-01,Midterm,2.5,Late submission\n",
            encoding="utf-8",
        )
        gradebook.import_csv(path)
        grade = gradebook.get_student_grades("S003")[0]
        assert (grade.title, grade.weight, grade.notes) == ("Midterm", 2.5, "Late submission")

    def test_a_bom_does_not_break_the_header(self, gradebook: GradeBook, tmp_path: Path) -> None:
        """Excel writes UTF-8 with a BOM by default; without utf-8-sig the first
        column name becomes '﻿student_id' and every row fails."""
        path = tmp_path / "excel.csv"
        path.write_text(
            "student_id,course_id,score,date\nS003,CS101,70,2026-02-01\n", encoding="utf-8-sig"
        )
        assert gradebook.import_csv(path).imported == 1


class TestStatistics:
    def test_summary_shape(self, gradebook: GradeBook) -> None:
        stats = gradebook.calculate_statistics()
        assert stats["student_count"] == 3
        assert stats["course_count"] == 2
        assert stats["grade_count"] == 3
        assert stats["overall_average_percentage"] == pytest.approx((85 + 90 + 45) / 3)

    def test_average_is_none_when_nothing_is_graded(self) -> None:
        """None, not 0.0 — zero would read as 'everybody failed'."""
        assert (
            GradeBook(InMemoryGradeStore()).calculate_statistics()["overall_average_percentage"]
            is None
        )
