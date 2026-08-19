"""The :class:`GradeBook` façade: statistics, search and file interchange.

Wraps a :class:`~notenverwaltung.storage.sqlite_store.GradeStore` and adds the analysis the
application actually asks for. Deliberately contains no SQL and no HTTP concepts, so
it can be exercised directly from a test or a REPL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from notenverwaltung.grading_scale import DEFAULT_SCALE, GradingScale
from notenverwaltung.models.course import Course
from notenverwaltung.models.grade import Grade
from notenverwaltung.models.student import Student
from notenverwaltung.storage.sqlite_store import GradeStore

_CSV_GRADE_FIELDS = ("student_id", "course_id", "score", "date")
"""Required columns for grade import. ``notes``, ``title`` and ``weight`` are optional."""


def weighted_mean(values: list[tuple[float, float]]) -> float:
    """Return the weighted mean of ``(value, weight)`` pairs.

    Module-level rather than a method: the report builder needs it too, and reaching
    into another class's private helper is how a "just this once" import becomes a
    dependency nobody can safely change.

    Args:
        values: Pairs to average. Must not be empty.

    Returns:
        The weighted mean.
    """
    total_weight = sum(w for _, w in values)
    return sum(v * w for v, w in values) / total_weight


@dataclass
class ImportReport:
    """Outcome of a bulk import.

    A malformed row must not abort the whole file — a teacher pasting 300 rows wants
    the 297 good ones recorded and a precise list of the 3 that failed.

    Attributes:
        imported: Rows successfully recorded.
        skipped: Rows rejected.
        errors: ``(line_number, reason_code)`` for each rejected row. The reason is a
            machine code so the frontend can translate it.
    """

    imported: int = 0
    skipped: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "imported": self.imported,
            "skipped": self.skipped,
            "errors": [{"line": line, "code": code} for line, code in self.errors],
        }


class GradeBook:
    """Statistics and rankings over a :class:`GradeStore`.

    Attributes:
        store: The backing persistence layer.
        scale: The grading scale used for letter grades and distributions.
    """

    def __init__(self, store: GradeStore, scale: GradingScale | None = None) -> None:
        """Create a grade book.

        Args:
            store: Where to read from. Required: every caller has a connection
                already, and a default would only ever have served tests.
            scale: The grading scale. Defaults to the specification's A-F bands.
        """
        self.store = store
        self.scale: GradingScale = scale if scale is not None else DEFAULT_SCALE

    # ── Collection views ─────────────────────────────────────────────────────
    @property
    def students(self) -> dict[str, Student]:
        """Every student, keyed by id."""
        return {s.student_id: s for s in self.store.get_all_students()}

    @property
    def courses(self) -> dict[str, Course]:
        """Every course, keyed by id."""
        return {c.course_id: c for c in self.store.get_all_courses()}

    @property
    def grades(self) -> list[Grade]:
        """Every live grade."""
        return self.store.get_all_grades()

    # ── Writes ───────────────────────────────────────────────────────────────
    def add_student(self, student: Student) -> None:
        """Add a student.

        Args:
            student: The student to add.

        Raises:
            DuplicateEntryError: If the id or email is already taken.
        """
        self.store.add_student(student)

    def add_course(self, course: Course) -> None:
        """Add a course.

        Args:
            course: The course to add.

        Raises:
            DuplicateEntryError: If the id is already taken.
        """
        self.store.add_course(course)

    def record_grade(
        self,
        student_id: str,
        course_id: str,
        score: float,
        date: str,
        notes: str = "",
        title: str = "",
        weight: float = 1.0,
        graded_by: int | None = None,
    ) -> Grade:
        """Record a grade for a student in a course.

        Args:
            student_id: Who is being graded.
            course_id: What they are being graded on.
            score: Points awarded, within the course's range.
            date: Award date, ISO or ``DD-MM-YYYY``.
            notes: Optional remark.
            title: Optional name, e.g. ``"Midterm"``.
            weight: Relative weight in the course average.
            graded_by: User id of the grader, for the audit trail.

        Returns:
            The stored grade, with its assigned ``grade_id``.

        Raises:
            StudentNotFoundError: If the student does not exist.
            CourseNotFoundError: If the course does not exist.
            ValidationError: If the score, weight or date is invalid.
        """
        student = self.store.get_student(student_id)
        course = self.store.get_course(course_id)
        grade = Grade(
            student=student,
            course=course,
            score=score,
            date=date,
            notes=notes,
            title=title,
            weight=weight,
            graded_by=graded_by,
        )
        return self.store.record_grade(grade)

    def get_student_grades(self, student_id: str) -> list[Grade]:
        """Return every live grade for a student.

        Args:
            student_id: Whose grades to fetch.

        Returns:
            The student's grades, most recent first.

        Raises:
            StudentNotFoundError: If the student does not exist.
        """
        self.store.get_student(student_id)  # existence check: absent ≠ "has no grades"
        return self.store.get_student_grades(student_id)

    def get_course_grades(self, course_id: str) -> list[Grade]:
        """Return every live grade for a course.

        Args:
            course_id: Whose grades to fetch.

        Returns:
            The course's grades, most recent first.

        Raises:
            CourseNotFoundError: If the course does not exist.
        """
        self.store.get_course(course_id)
        return self.store.get_course_grades(course_id)

    # ── Statistics ───────────────────────────────────────────────────────────

    def grade_distribution(self, course_id: str | None = None) -> dict[str, int]:
        """Count grades per band label.

        Args:
            course_id: Restrict to one course, or ``None`` for the whole book.

        Returns:
            Band label to count, including bands with a count of zero so a chart
            renders a complete axis rather than skipping empty categories.

        Raises:
            CourseNotFoundError: If ``course_id`` is given but does not exist.
        """
        grades = self.get_course_grades(course_id) if course_id is not None else self.grades
        distribution = {band.label: 0 for band in self.scale.bands}
        for grade in grades:
            distribution[grade.letter_for(self.scale)] += 1
        return distribution

    def top_students(self, n: int = 5) -> list[tuple[Student, float]]:
        """Return the highest-averaging students.

        Students with no grades are excluded rather than ranked as zero.

        Args:
            n: How many to return.

        Returns:
            ``(student, average_percentage)`` pairs, highest first.
        """
        ranked = self._student_averages()
        ranked.sort(key=lambda pair: pair[1], reverse=True)
        return ranked[:n]

    def students_at_risk(self, threshold: float = 60.0) -> list[tuple[Student, float]]:
        """Return students averaging below a threshold.

        Args:
            threshold: The percentage below which a student counts as at risk.

        Returns:
            ``(student, average_percentage)`` pairs, lowest first — worst case first
            is what an intervention list is read for.
        """
        at_risk = [pair for pair in self._student_averages() if pair[1] < threshold]
        at_risk.sort(key=lambda pair: pair[1])
        return at_risk

    def _student_averages(self) -> list[tuple[Student, float]]:
        """Every graded student's weighted average, in one pass.

        Both rankings used to walk `self.students` and call `get_student_grades` per
        student, which is a query each. A summary report calls both, so one request
        issued 2*(2N+1) queries for N students -- and neither pass reused the other's
        work, on top of `calculate_statistics` having already loaded every grade.

        Grouping one `get_all_grades()` here makes it a single read. Students with no
        grades never appear, which is what both callers already wanted: no data is
        not the same as poor performance, and ranking an unassessed student as zero
        would put them at the top of an intervention list.

        Returns:
            ``(student, average_percentage)`` for every student holding a grade,
            unordered -- each caller sorts for its own purpose.
        """
        by_student: dict[str, list[tuple[float, float]]] = {}
        for grade in self.grades:
            by_student.setdefault(grade.student.student_id, []).append(
                (grade.percentage, grade.weight)
            )

        students = self.students
        return [
            (students[student_id], weighted_mean(values))
            for student_id, values in by_student.items()
            if student_id in students and values
        ]

    # ── Search ───────────────────────────────────────────────────────────────

    # ── JSON interchange ─────────────────────────────────────────────────────

    # ── CSV interchange ──────────────────────────────────────────────────────

    def calculate_statistics(self) -> dict[str, Any]:
        """Return a summary of the whole grade book, for a dashboard.

        Returns:
            Totals, the overall average percentage, and the grade distribution. The
            average is ``None`` when nothing has been graded yet — distinct from 0.0,
            which would wrongly suggest everyone failed.
        """
        grades = self.grades
        overall = weighted_mean([(g.percentage, g.weight) for g in grades]) if grades else None
        return {
            "student_count": len(self.store.get_all_students()),
            "course_count": len(self.store.get_all_courses()),
            "grade_count": len(grades),
            "overall_average_percentage": overall,
            "distribution": self.grade_distribution(),
        }
