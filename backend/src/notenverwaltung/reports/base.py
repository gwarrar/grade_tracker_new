"""Report generation: the abstract base and the shared data shapes.

**Reports are built in two steps.** :class:`ReportBuilder` turns the grade book into
plain data — numbers and identifiers, no prose. A :class:`ReportGenerator` then
renders that data into a concrete format.

The split exists because of localisation. The coursework version assembled English
sentences inside the generator, which would have meant shipping a German and French
message catalogue in the backend. Instead the API returns the structured payload and
the frontend renders it in the user's language. The abstract base and its
polymorphism — the point of the exercise — are unchanged; only the leaf formatters
moved.

CSV export is the one format still rendered server-side, because a downloaded file
has no frontend to render it. It takes a locale argument for its headers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from notenverwaltung.gradebook import GradeBook, weighted_mean


@dataclass
class GradeLine:
    """One grade as it appears in a report.

    Attributes:
        grade_id: Database identifier, so the UI can link to the grade.
        course_id: The course graded.
        course_name: Its display name.
        student_id: The student graded.
        student_name: Their display name.
        title: What the grade was for, e.g. ``"Midterm"``.
        score: Points awarded.
        max_grade: The course maximum.
        percentage: ``score`` as a percentage of ``max_grade``.
        letter: Band label under the active grading scale.
        weight: Relative weight in the average.
        is_passing: Whether the score reaches the passing threshold.
        date: ISO award date.
        notes: Free-text remark.
    """

    grade_id: int | None
    course_id: str
    course_name: str
    student_id: str
    student_name: str
    title: str
    score: float
    max_grade: float
    percentage: float
    letter: str
    weight: float
    is_passing: bool
    date: str
    notes: str


@dataclass
class StudentReport:
    """Everything needed to render one student's report.

    Attributes:
        student_id: The student's identifier.
        student_name: Their display name.
        email: Their contact address.
        grades: Every live grade, most recent first.
        average_percentage: Weighted mean percentage, or ``None`` if ungraded.
        passed_count: Grades at or above the passing threshold.
        failed_count: Grades below it.
        courses_graded: Distinct courses with at least one grade.
    """

    student_id: str
    student_name: str
    email: str
    grades: list[GradeLine] = field(default_factory=list)
    average_percentage: float | None = None
    passed_count: int = 0
    failed_count: int = 0
    courses_graded: int = 0


@dataclass
class CourseReport:
    """Everything needed to render one course's report.

    Attributes:
        course_id: The course identifier.
        course_name: Its display name.
        max_grade: The course maximum.
        passing_grade: The passing threshold.
        grades: Every live grade, most recent first.
        average_score: Weighted mean score, or ``None`` if ungraded.
        pass_rate: Percentage of passing grades, or ``None`` if ungraded.
        graded_student_count: Distinct students holding a grade.
        distribution: Band label to count.
    """

    course_id: str
    course_name: str
    max_grade: float
    passing_grade: float
    grades: list[GradeLine] = field(default_factory=list)
    average_score: float | None = None
    pass_rate: float | None = None
    graded_student_count: int = 0
    distribution: dict[str, int] = field(default_factory=dict)


@dataclass
class SummaryReport:
    """Institution-wide statistics.

    Attributes:
        student_count: Total students on record.
        course_count: Total courses on record.
        grade_count: Total live grades.
        overall_average_percentage: Weighted mean across everything, or ``None``.
        distribution: Band label to count.
        top_students: ``(student_id, name, average)`` triples, best first.
        at_risk_students: ``(student_id, name, average)`` triples, worst first.
        at_risk_threshold: The percentage used to classify at-risk students.
    """

    student_count: int
    course_count: int
    grade_count: int
    overall_average_percentage: float | None
    distribution: dict[str, int] = field(default_factory=dict)
    top_students: list[tuple[str, str, float]] = field(default_factory=list)
    at_risk_students: list[tuple[str, str, float]] = field(default_factory=list)
    at_risk_threshold: float = 60.0


class ReportBuilder:
    """Turns a :class:`GradeBook` into the structured report dataclasses.

    Produces data only — no prose, no formatting, no locale.
    """

    def __init__(self, gradebook: GradeBook) -> None:
        """Bind the builder to a grade book.

        Args:
            gradebook: The source of students, courses and grades.
        """
        self._book = gradebook

    def _line(self, grade: Any) -> GradeLine:
        """Convert a :class:`~notenverwaltung.models.grade.Grade` into a report line."""
        return GradeLine(
            grade_id=grade.grade_id,
            course_id=grade.course.course_id,
            course_name=grade.course.name,
            student_id=grade.student.student_id,
            student_name=grade.student.full_name,
            title=grade.title,
            score=grade.score,
            max_grade=grade.course.max_grade,
            percentage=round(grade.percentage, 2),
            letter=grade.letter_for(self._book.scale),
            weight=grade.weight,
            is_passing=grade.is_passing,
            date=grade.date,
            notes=grade.notes,
        )

    def student_report(self, student_id: str) -> StudentReport:
        """Build a report for one student.

        Args:
            student_id: Whose report to build.

        Returns:
            The structured report.

        Raises:
            StudentNotFoundError: If the student does not exist.
        """
        student = self._book.store.get_student(student_id)
        grades = self._book.get_student_grades(student_id)
        lines = [self._line(g) for g in grades]
        return StudentReport(
            student_id=student.student_id,
            student_name=student.full_name,
            email=student.email,
            grades=lines,
            average_percentage=(
                round(
                    weighted_mean([(g.percentage, g.weight) for g in grades]),
                    2,
                )
                if grades
                else None
            ),
            passed_count=sum(1 for line in lines if line.is_passing),
            failed_count=sum(1 for line in lines if not line.is_passing),
            courses_graded=len({line.course_id for line in lines}),
        )

    def course_report(self, course_id: str) -> CourseReport:
        """Build a report for one course.

        Args:
            course_id: Whose report to build.

        Returns:
            The structured report.

        Raises:
            CourseNotFoundError: If the course does not exist.
        """
        course = self._book.store.get_course(course_id)
        grades = self._book.get_course_grades(course_id)
        lines = [self._line(g) for g in grades]
        return CourseReport(
            course_id=course.course_id,
            course_name=course.name,
            max_grade=course.max_grade,
            passing_grade=course.passing_grade,
            grades=lines,
            average_score=(
                round(
                    weighted_mean([(g.score, g.weight) for g in grades]),
                    2,
                )
                if grades
                else None
            ),
            pass_rate=(
                round(sum(1 for line in lines if line.is_passing) / len(lines) * 100, 2)
                if lines
                else None
            ),
            graded_student_count=len({line.student_id for line in lines}),
            distribution=self._book.grade_distribution(course_id),
        )

    def summary_report(self, at_risk_threshold: float = 60.0) -> SummaryReport:
        """Build the institution-wide summary.

        Args:
            at_risk_threshold: Percentage below which a student counts as at risk.

        Returns:
            The structured report.
        """
        stats = self._book.calculate_statistics()
        return SummaryReport(
            student_count=stats["student_count"],
            course_count=stats["course_count"],
            grade_count=stats["grade_count"],
            overall_average_percentage=(
                round(stats["overall_average_percentage"], 2)
                if stats["overall_average_percentage"] is not None
                else None
            ),
            distribution=stats["distribution"],
            top_students=[
                (s.student_id, s.full_name, round(avg, 2)) for s, avg in self._book.top_students()
            ],
            at_risk_students=[
                (s.student_id, s.full_name, round(avg, 2))
                for s, avg in self._book.students_at_risk(at_risk_threshold)
            ],
            at_risk_threshold=at_risk_threshold,
        )


class ReportGenerator(ABC):
    """Renders structured reports into a concrete output format.

    Subclasses implement one format each. Because they consume the dataclasses above
    rather than the grade book, a new format needs no knowledge of storage or statistics.
    """

    @abstractmethod
    def render_student(self, report: StudentReport) -> str:
        """Render a student report.

        Args:
            report: The structured report.

        Returns:
            The rendered document.
        """

    @abstractmethod
    def render_course(self, report: CourseReport) -> str:
        """Render a course report.

        Args:
            report: The structured report.

        Returns:
            The rendered document.
        """

    @abstractmethod
    def render_summary(self, report: SummaryReport) -> str:
        """Render a summary report.

        Args:
            report: The structured report.

        Returns:
            The rendered document.
        """

    def write(self, content: str, filepath: str) -> None:
        """Write rendered content to a file.

        Args:
            content: Output from one of the ``render_*`` methods.
            filepath: Destination path.
        """
        from pathlib import Path

        Path(filepath).write_text(content, encoding="utf-8")


class JsonReportGenerator(ReportGenerator):
    """Emits the structured report verbatim as JSON.

    This is what the API returns: the frontend receives numbers and identifiers and
    renders them in the user's language.
    """

    def _dump(self, report: object) -> str:
        """Serialise a report dataclass to indented JSON."""
        import json

        return json.dumps(asdict(report), indent=2, ensure_ascii=False)  # type: ignore[call-overload]

    def render_student(self, report: StudentReport) -> str:
        """Render a student report as JSON."""
        return self._dump(report)

    def render_course(self, report: CourseReport) -> str:
        """Render a course report as JSON."""
        return self._dump(report)

    def render_summary(self, report: SummaryReport) -> str:
        """Render a summary report as JSON."""
        return self._dump(report)
