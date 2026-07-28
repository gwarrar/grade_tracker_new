"""CSV report rendering, for spreadsheet download.

The one format still rendered server-side: a downloaded file has no frontend to
localise it, so column headers are translated here. The API passes the caller's
locale through as a header mapping.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from notenverwaltung.reports.base import (
    CourseReport,
    ReportGenerator,
    StudentReport,
    SummaryReport,
)

DEFAULT_HEADERS: dict[str, str] = {
    "student_id": "Student ID",
    "student_name": "Student",
    "course_id": "Course ID",
    "course_name": "Course",
    "title": "Assessment",
    "score": "Score",
    "max_grade": "Max",
    "percentage": "Percent",
    "letter": "Grade",
    "weight": "Weight",
    "status": "Status",
    "date": "Date",
    "notes": "Notes",
    "metric": "Metric",
    "value": "Value",
    "rank": "Rank",
    "average": "Average",
}
"""English column headers. The API supplies a translated mapping per request."""

DEFAULT_LABELS: dict[str, str] = {"pass": "PASS", "fail": "FAIL"}
"""English cell values that are words. Translated per request, like the headers."""


class CsvReportGenerator(ReportGenerator):
    """Renders reports as CSV text."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        delimiter: str = ",",
        labels: dict[str, str] | None = None,
    ) -> None:
        """Create a renderer.

        Args:
            headers: Override any of :data:`DEFAULT_HEADERS`.
            delimiter: Field separator. Pass ``";"`` for locales where Excel expects
                it — in German and French Windows locales a comma-separated file
                opens as a single column, which reads to the user as corruption.
            labels: Override any of :data:`DEFAULT_LABELS`. Cell values that are
                words rather than data. Translating the headers but leaving the
                cells English produces a German file with "FAIL" in it, which is
                worse than either consistent choice.
        """
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.labels = {**DEFAULT_LABELS, **(labels or {})}
        self.delimiter = delimiter

    def _status(self, is_passing: bool) -> str:
        """Return the pass/fail cell in the caller's language.

        Args:
            is_passing: Whether the grade met the course's threshold.

        Returns:
            The translated label.
        """
        return self.labels["pass"] if is_passing else self.labels["fail"]

    def _writer(self, buffer: io.StringIO) -> Any:
        """Return a writer configured with this renderer's delimiter.

        Typed ``Any`` because :func:`csv.writer` returns an object whose class has no
        public importable name.
        """
        return csv.writer(buffer, delimiter=self.delimiter, lineterminator="\n")

    def _h(self, *keys: str) -> list[str]:
        """Translate a sequence of header keys."""
        return [self.headers.get(k, k) for k in keys]

    def render_student(self, report: StudentReport) -> str:
        """Render a student report as CSV: one row per grade."""
        buffer = io.StringIO()
        writer = self._writer(buffer)
        writer.writerow(
            self._h(
                "course_id",
                "course_name",
                "title",
                "score",
                "max_grade",
                "percentage",
                "letter",
                "weight",
                "status",
                "date",
                "notes",
            )
        )
        for g in report.grades:
            writer.writerow(
                [
                    g.course_id,
                    g.course_name,
                    g.title,
                    g.score,
                    g.max_grade,
                    f"{g.percentage:.2f}",
                    g.letter,
                    g.weight,
                    self._status(g.is_passing),
                    g.date,
                    g.notes,
                ]
            )
        return buffer.getvalue()

    def render_course(self, report: CourseReport) -> str:
        """Render a course report as CSV: one row per grade."""
        buffer = io.StringIO()
        writer = self._writer(buffer)
        writer.writerow(
            self._h(
                "student_id",
                "student_name",
                "title",
                "score",
                "max_grade",
                "percentage",
                "letter",
                "weight",
                "status",
                "date",
                "notes",
            )
        )
        for g in report.grades:
            writer.writerow(
                [
                    g.student_id,
                    g.student_name,
                    g.title,
                    g.score,
                    g.max_grade,
                    f"{g.percentage:.2f}",
                    g.letter,
                    g.weight,
                    self._status(g.is_passing),
                    g.date,
                    g.notes,
                ]
            )
        return buffer.getvalue()

    def render_summary(self, report: SummaryReport) -> str:
        """Render a summary report as CSV: a metric table, then rankings."""
        buffer = io.StringIO()
        writer = self._writer(buffer)

        writer.writerow(self._h("metric", "value"))
        writer.writerow(["students", report.student_count])
        writer.writerow(["courses", report.course_count])
        writer.writerow(["grades", report.grade_count])
        writer.writerow(
            [
                "average_percentage",
                f"{report.overall_average_percentage:.2f}"
                if report.overall_average_percentage is not None
                else "",
            ]
        )
        for label, count in report.distribution.items():
            writer.writerow([f"band_{label}", count])

        if report.top_students:
            writer.writerow([])
            writer.writerow(self._h("rank", "student_id", "student_name", "average"))
            for rank, (student_id, name, avg) in enumerate(report.top_students, start=1):
                writer.writerow([rank, student_id, name, f"{avg:.2f}"])

        if report.at_risk_students:
            writer.writerow([])
            writer.writerow(self._h("student_id", "student_name", "average"))
            for student_id, name, avg in report.at_risk_students:
                writer.writerow([student_id, name, f"{avg:.2f}"])

        return buffer.getvalue()
