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


def grade_point_average(weighted: list[tuple[float | None, float]]) -> float | None:
    """Average grade points, weighting each by its course's credits.

    Args:
        weighted: ``(points, credits)`` per course. A course whose band carries no
            points is dropped rather than counted as zero — an unpriced band is an
            unanswered question, and zero is an answer that would drag the average
            down for an institution that simply never configured a GPA.

    Returns:
        The average to three decimals, or ``None`` when no course carries points.
        ``None`` rather than ``0.0`` for the same reason: the caller must be able to
        tell "no GPA to show" from "a GPA of zero", and only one of those is worth
        printing.
    """
    priced = [(points, credits) for points, credits in weighted if points is not None]
    if not priced:
        return None
    return round(weighted_mean(priced), 3)


@dataclass
class CourseResult:
    """One student's standing in one course.

    This is a new concept rather than a rearrangement of existing data. Until a GPA
    needed it, the product had no per-course grade for a student anywhere on the
    server — a report was a flat list of individual marks, and the only per-course
    average was computed in the browser. A credit-weighted GPA cannot be built from
    individual marks, because credits attach to the course and not to the mark.

    Attributes:
        course_id: The course.
        course_name: Its display name.
        credits: What the course is worth, and the weight of this result in the GPA.
        grade_count: How many marks the average covers.
        average_percentage: Weighted mean of this course's marks.
        letter: The band that average falls in.
        points: What that band is worth, or ``None`` if the scale prices no points.
    """

    course_id: str
    course_name: str
    credits: float
    grade_count: int
    average_percentage: float
    letter: str
    points: float | None


@dataclass
class StudentReport:
    """Everything needed to render one student's report.

    Attributes:
        student_id: The student's identifier.
        student_name: Their display name.
        email: Their contact address.
        grades: Every live grade, most recent first.
        courses: One standing per course, the basis of the GPA.
        average_percentage: Weighted mean percentage, or ``None`` if ungraded.
        gpa: Credit-weighted grade point average, or ``None`` when the grading
            scale prices no bands. Distinct from ``average_percentage``, which
            weights each *mark* by its own weight; this weights each *course* by
            its credits, so a six-credit course counts six times a one-credit one.
        passed_count: Grades at or above the passing threshold.
        failed_count: Grades below it.
        courses_graded: Distinct courses with at least one grade.
    """

    student_id: str
    student_name: str
    email: str
    grades: list[GradeLine] = field(default_factory=list)
    courses: list[CourseResult] = field(default_factory=list)
    average_percentage: float | None = None
    gpa: float | None = None
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
        courses = self._course_results(grades)
        return StudentReport(
            student_id=student.student_id,
            student_name=student.full_name,
            email=student.email,
            grades=lines,
            courses=courses,
            average_percentage=(
                round(
                    weighted_mean([(g.percentage, g.weight) for g in grades]),
                    2,
                )
                if grades
                else None
            ),
            gpa=grade_point_average([(c.points, c.credits) for c in courses]),
            passed_count=sum(1 for line in lines if line.is_passing),
            failed_count=sum(1 for line in lines if not line.is_passing),
            courses_graded=len({line.course_id for line in lines}),
        )

    def _course_results(self, grades: list[Any]) -> list[CourseResult]:
        """Collapse a student's marks into one standing per course.

        Ordered by course name rather than by whatever order the grades arrived in,
        so the same student produces the same report twice.

        Args:
            grades: The student's live grades.

        Returns:
            One result per course holding at least one mark.
        """
        by_course: dict[str, list[Any]] = {}
        for grade in grades:
            by_course.setdefault(grade.course.course_id, []).append(grade)

        scale = self._book.scale
        results: list[CourseResult] = []
        for course_grades in by_course.values():
            course = course_grades[0].course
            average = weighted_mean([(g.percentage, g.weight) for g in course_grades])
            results.append(
                CourseResult(
                    course_id=course.course_id,
                    course_name=course.name,
                    credits=course.credits,
                    grade_count=len(course_grades),
                    average_percentage=round(average, 2),
                    letter=scale.label_for(average),
                    points=scale.points_for(average),
                )
            )
        return sorted(results, key=lambda result: result.course_name)

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
