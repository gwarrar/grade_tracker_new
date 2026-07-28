"""Report building and rendering."""

from __future__ import annotations

import json

import pytest

from notenverwaltung.exceptions import CourseNotFoundError, StudentNotFoundError
from notenverwaltung.gradebook import GradeBook
from notenverwaltung.models import Course
from notenverwaltung.reports import (
    CsvReportGenerator,
    JsonReportGenerator,
    ReportBuilder,
    TextReportGenerator,
)


@pytest.fixture
def builder(gradebook: GradeBook) -> ReportBuilder:
    return ReportBuilder(gradebook)


class TestStudentReport:
    def test_carries_the_numbers_needed_to_render(self, builder: ReportBuilder) -> None:
        report = builder.student_report("S001")
        assert report.student_name == "Anna Schmidt"
        assert len(report.grades) == 2
        assert report.average_percentage == pytest.approx(87.5)
        assert (report.passed_count, report.failed_count, report.courses_graded) == (2, 0, 2)

    def test_contains_no_prose(self, builder: ReportBuilder) -> None:
        """The frontend renders the language; the backend ships no message catalogue.

        Every string in the payload must be data — a name, an id, an ISO date, a band
        label — never a sentence.
        """
        payload = json.loads(JsonReportGenerator().render_student(builder.student_report("S001")))
        assert set(payload) == {
            "student_id",
            "student_name",
            "email",
            "grades",
            "average_percentage",
            "passed_count",
            "failed_count",
            "courses_graded",
        }
        assert " " not in payload["grades"][0]["letter"]

    def test_ungraded_student_yields_none_not_zero(self, builder: ReportBuilder) -> None:
        report = builder.student_report("S003")
        assert report.grades == []
        assert report.average_percentage is None

    def test_unknown_student_raises(self, builder: ReportBuilder) -> None:
        with pytest.raises(StudentNotFoundError):
            builder.student_report("ghost")


class TestCourseReport:
    def test_carries_the_numbers_needed_to_render(self, builder: ReportBuilder) -> None:
        report = builder.course_report("CS101")
        assert report.average_score == pytest.approx(65.0)
        assert report.pass_rate == pytest.approx(50.0)
        assert report.graded_student_count == 2
        assert report.distribution == {"A": 0, "B": 1, "C": 0, "D": 0, "F": 1}

    def test_ungraded_course_yields_none(self, gradebook: GradeBook) -> None:
        gradebook.add_course(Course("CS999", "Empty"))
        report = ReportBuilder(gradebook).course_report("CS999")
        assert (report.average_score, report.pass_rate) == (None, None)

    def test_unknown_course_raises(self, builder: ReportBuilder) -> None:
        with pytest.raises(CourseNotFoundError):
            builder.course_report("ghost")


class TestSummaryReport:
    def test_carries_totals_and_rankings(self, builder: ReportBuilder) -> None:
        report = builder.summary_report()
        assert (report.student_count, report.course_count, report.grade_count) == (3, 2, 3)
        assert [sid for sid, _, _ in report.top_students] == ["S001", "S002"]
        assert [sid for sid, _, _ in report.at_risk_students] == ["S002"]

    def test_threshold_is_echoed_so_the_ui_can_label_it(self, builder: ReportBuilder) -> None:
        assert builder.summary_report(at_risk_threshold=70.0).at_risk_threshold == 70.0


class TestRenderers:
    """Every generator consumes the same dataclasses — that is the polymorphism."""

    def test_all_generators_accept_the_same_report(self, builder: ReportBuilder) -> None:
        report = builder.student_report("S001")
        for generator in (TextReportGenerator(), CsvReportGenerator(), JsonReportGenerator()):
            assert generator.render_student(report)

    def test_text_includes_the_key_figures(self, builder: ReportBuilder) -> None:
        output = TextReportGenerator().render_student(builder.student_report("S001"))
        assert "Anna Schmidt" in output
        assert "87.5%" in output

    def test_text_labels_are_overridable(self, builder: ReportBuilder) -> None:
        output = TextReportGenerator({"average": "Durchschnitt"}).render_student(
            builder.student_report("S001")
        )
        assert "Durchschnitt" in output

    def test_text_handles_an_empty_report(self, builder: ReportBuilder) -> None:
        assert "No grades recorded." in TextReportGenerator().render_student(
            builder.student_report("S003")
        )

    def test_csv_headers_are_translatable(self, builder: ReportBuilder) -> None:
        """A downloaded file has no frontend, so this one format translates server-side."""
        output = CsvReportGenerator({"score": "Note", "date": "Datum"}).render_student(
            builder.student_report("S001")
        )
        header = output.splitlines()[0]
        assert "Note" in header and "Datum" in header

    def test_csv_delimiter_is_configurable(self, builder: ReportBuilder) -> None:
        """German and French Windows Excel expects ';'. With ',' the file opens as
        one column, which reads to the user as corruption."""
        output = CsvReportGenerator(delimiter=";").render_student(builder.student_report("S001"))
        assert ";" in output.splitlines()[0]

    def test_csv_row_count_matches_the_grades(self, builder: ReportBuilder) -> None:
        output = CsvReportGenerator().render_course(builder.course_report("CS101"))
        assert len(output.strip().splitlines()) == 3  # header + 2 grades

    def test_json_is_valid_and_complete(self, builder: ReportBuilder) -> None:
        payload = json.loads(JsonReportGenerator().render_summary(builder.summary_report()))
        assert payload["student_count"] == 3

    def test_text_course_report(self, builder: ReportBuilder) -> None:
        output = TextReportGenerator().render_course(builder.course_report("CS101"))
        assert "Intro to Programming" in output
        assert "Anna Schmidt" in output
        assert "50.0%" in output  # pass rate
        assert "B:1" in output  # distribution

    def test_text_course_report_handles_no_grades(self, gradebook: GradeBook) -> None:
        gradebook.add_course(Course("CS999", "Empty"))
        output = TextReportGenerator().render_course(
            ReportBuilder(gradebook).course_report("CS999")
        )
        assert "No grades recorded." in output

    def test_text_summary_report(self, builder: ReportBuilder) -> None:
        output = TextReportGenerator().render_summary(builder.summary_report())
        assert "3 students, 2 courses, 3 grades" in output
        assert "Top students:" in output
        assert "At risk (< 60%):" in output

    def test_text_summary_omits_empty_sections(self) -> None:
        """An institution with no data should not render an empty 'At risk' heading."""
        from notenverwaltung.storage import InMemoryGradeStore

        output = TextReportGenerator().render_summary(
            ReportBuilder(GradeBook(InMemoryGradeStore())).summary_report()
        )
        assert "Top students:" not in output
        assert "At risk" not in output

    def test_csv_summary_report(self, builder: ReportBuilder) -> None:
        output = CsvReportGenerator().render_summary(builder.summary_report())
        assert "students,3" in output
        assert "band_A,1" in output
        assert "S001" in output  # ranking section

    def test_csv_summary_average_is_blank_when_ungraded(self) -> None:
        """Blank, not 0 — a spreadsheet formula over a 0 would report a false average."""
        from notenverwaltung.storage import InMemoryGradeStore

        output = CsvReportGenerator().render_summary(
            ReportBuilder(GradeBook(InMemoryGradeStore())).summary_report()
        )
        assert "average_percentage," in output
