"""Plain-text report rendering, for the CLI and for file export."""

from __future__ import annotations

from notenverwaltung.reports.base import (
    CourseReport,
    ReportGenerator,
    StudentReport,
    SummaryReport,
)

_WIDTH = 72

DEFAULT_LABELS: dict[str, str] = {
    "student_report": "STUDENT REPORT",
    "course_report": "COURSE REPORT",
    "summary_report": "SUMMARY REPORT",
    "email": "Email",
    "average": "Average",
    "passed": "Passed",
    "failed": "Failed",
    "courses": "Courses",
    "pass_rate": "Pass rate",
    "students_graded": "Students graded",
    "distribution": "Distribution",
    "top_students": "Top students",
    "at_risk": "At risk",
    "totals": "Totals",
    "no_grades": "No grades recorded.",
    "not_available": "n/a",
}
"""Labels for the plain-text renderer.

Fifteen strings for a command-line and file-export convenience — not a localisation
system. The web application renders reports from the structured payload in the user's
language; see :mod:`notenverwaltung.reports.base`. Callers may pass their own mapping.
"""


class TextReportGenerator(ReportGenerator):
    """Renders reports as fixed-width plain text."""

    def __init__(self, labels: dict[str, str] | None = None) -> None:
        """Create a renderer.

        Args:
            labels: Override any of :data:`DEFAULT_LABELS`. Missing keys fall back
                to the English default.
        """
        self.labels = {**DEFAULT_LABELS, **(labels or {})}

    def _t(self, key: str) -> str:
        """Look up a label."""
        return self.labels.get(key, key)

    @staticmethod
    def _header(title: str) -> list[str]:
        """Return a boxed section header."""
        return ["=" * _WIDTH, title.center(_WIDTH), "=" * _WIDTH]

    @staticmethod
    def _pct(value: float | None) -> str:
        """Format an optional percentage, or a placeholder when there is no data."""
        return f"{value:.1f}%" if value is not None else "n/a"

    def render_student(self, report: StudentReport) -> str:
        """Render a student report as plain text."""
        lines = self._header(f"{self._t('student_report')}: {report.student_name}")
        lines.append(f"{self._t('email')}: {report.email}   ID: {report.student_id}")
        lines.append("-" * _WIDTH)

        if not report.grades:
            lines.append(self._t("no_grades"))
        else:
            for g in report.grades:
                title = f" ({g.title})" if g.title else ""
                mark = "PASS" if g.is_passing else "FAIL"
                lines.append(
                    f"{g.course_name[:28]:<28}{title[:12]:<12}"
                    f"{g.score:>6.1f}/{g.max_grade:<6.0f} {g.letter:>2}  {mark}"
                )
            lines.append("-" * _WIDTH)
            lines.append(
                f"{self._t('average')}: {self._pct(report.average_percentage)}   "
                f"{self._t('passed')}: {report.passed_count}   "
                f"{self._t('failed')}: {report.failed_count}   "
                f"{self._t('courses')}: {report.courses_graded}"
            )
        return "\n".join(lines) + "\n"

    def render_course(self, report: CourseReport) -> str:
        """Render a course report as plain text."""
        lines = self._header(f"{self._t('course_report')}: {report.course_name}")
        lines.append(
            f"ID: {report.course_id}   Max: {report.max_grade:.0f}   "
            f"Pass: {report.passing_grade:.0f}"
        )
        lines.append("-" * _WIDTH)

        if not report.grades:
            lines.append(self._t("no_grades"))
        else:
            for g in report.grades:
                mark = "PASS" if g.is_passing else "FAIL"
                lines.append(
                    f"{g.student_name[:30]:<30}{g.student_id:<10}"
                    f"{g.score:>6.1f}  {g.letter:>2}  {mark}"
                )
            lines.append("-" * _WIDTH)
            average = (
                f"{report.average_score:.1f}"
                if report.average_score is not None
                else self._t("not_available")
            )
            lines.append(
                f"{self._t('average')}: {average}   "
                f"{self._t('pass_rate')}: {self._pct(report.pass_rate)}   "
                f"{self._t('students_graded')}: {report.graded_student_count}"
            )
            bands = "  ".join(f"{label}:{count}" for label, count in report.distribution.items())
            lines.append(f"{self._t('distribution')}: {bands}")
        return "\n".join(lines) + "\n"

    def render_summary(self, report: SummaryReport) -> str:
        """Render a summary report as plain text."""
        lines = self._header(self._t("summary_report"))
        lines.append(
            f"{self._t('totals')}: {report.student_count} students, "
            f"{report.course_count} courses, {report.grade_count} grades"
        )
        lines.append(f"{self._t('average')}: {self._pct(report.overall_average_percentage)}")
        bands = "  ".join(f"{label}:{count}" for label, count in report.distribution.items())
        lines.append(f"{self._t('distribution')}: {bands}")

        if report.top_students:
            lines.extend(["-" * _WIDTH, f"{self._t('top_students')}:"])
            for rank, (student_id, name, avg) in enumerate(report.top_students, start=1):
                lines.append(f"  {rank}. {name[:34]:<34}{student_id:<10}{avg:>6.1f}%")

        if report.at_risk_students:
            lines.extend(
                ["-" * _WIDTH, f"{self._t('at_risk')} (< {report.at_risk_threshold:.0f}%):"]
            )
            for student_id, name, avg in report.at_risk_students:
                lines.append(f"  - {name[:34]:<34}{student_id:<10}{avg:>6.1f}%")

        return "\n".join(lines) + "\n"
