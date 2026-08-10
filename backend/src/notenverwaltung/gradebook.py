"""The :class:`GradeBook` façade: statistics, search and file interchange.

Wraps a :class:`~notenverwaltung.storage.base.GradeStore` and adds the analysis the
application actually asks for. Deliberately contains no SQL and no HTTP concepts, so
it can be exercised directly from a test or a REPL.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from notenverwaltung.exceptions import (
    NoGradesRecordedError,
    ValidationError,
)
from notenverwaltung.grading_scale import DEFAULT_SCALE, GradingScale
from notenverwaltung.models.course import Course
from notenverwaltung.models.grade import Grade
from notenverwaltung.models.student import Student
from notenverwaltung.storage.base import GradeStore
from notenverwaltung.storage.memory_store import InMemoryGradeStore

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
    """Statistics, search and interchange over a :class:`GradeStore`.

    Attributes:
        store: The backing persistence layer.
        scale: The grading scale used for letter grades and distributions.
    """

    def __init__(self, store: GradeStore | None = None, scale: GradingScale | None = None) -> None:
        """Create a grade book.

        Args:
            store: Where to persist. Defaults to a fresh in-memory store.
            scale: The grading scale. Defaults to the specification's A-F bands.
        """
        self.store: GradeStore = store if store is not None else InMemoryGradeStore()
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

    def student_average(self, student_id: str) -> float:
        """Return a student's weighted average **percentage** across all their courses.

        Percentages, not raw scores: a course marked out of 10 and one marked out of
        100 are not comparable as raw numbers. Averaging 80/100 with 8/10 as raw
        scores gives 44, which describes nothing. As percentages both are 80%.

        Args:
            student_id: Whose average to compute.

        Returns:
            The weighted mean percentage, 0-100.

        Raises:
            StudentNotFoundError: If the student does not exist.
            NoGradesRecordedError: If the student has no grades.
        """
        grades = self.get_student_grades(student_id)
        if not grades:
            raise NoGradesRecordedError(
                f"Student {student_id!r} has no grades.", student_id=student_id
            )
        return weighted_mean([(g.percentage, g.weight) for g in grades])

    def course_average(self, course_id: str) -> float:
        """Return a course's weighted average score.

        Raw scores are correct here — every grade shares one course maximum.

        Args:
            course_id: Whose average to compute.

        Returns:
            The weighted mean score.

        Raises:
            CourseNotFoundError: If the course does not exist.
            NoGradesRecordedError: If the course has no grades.
        """
        grades = self.get_course_grades(course_id)
        if not grades:
            raise NoGradesRecordedError(f"Course {course_id!r} has no grades.", course_id=course_id)
        return weighted_mean([(g.score, g.weight) for g in grades])

    def course_pass_rate(self, course_id: str) -> float:
        """Return the percentage of a course's grades that are passing.

        Args:
            course_id: Whose pass rate to compute.

        Returns:
            The pass rate, 0-100.

        Raises:
            CourseNotFoundError: If the course does not exist.
            NoGradesRecordedError: If the course has no grades.
        """
        grades = self.get_course_grades(course_id)
        if not grades:
            raise NoGradesRecordedError(f"Course {course_id!r} has no grades.", course_id=course_id)
        return sum(1 for g in grades if g.is_passing) / len(grades) * 100

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

    def graded_student_count(self, course_id: str) -> int:
        """Return how many **distinct students** hold a grade in a course.

        Named for what it measures. The coursework version called this
        ``course_enrollment_count`` and returned ``len(grades)``, which double-counts
        anyone with more than one grade and says nothing about enrolment — a student
        can be enrolled and ungraded. True enrolment lives in the ``enrollments``
        table and is served by the enrolment service.

        Args:
            course_id: Which course to count.

        Returns:
            The number of distinct graded students.

        Raises:
            CourseNotFoundError: If the course does not exist.
        """
        return len({g.student.student_id for g in self.get_course_grades(course_id)})

    # ── Search ───────────────────────────────────────────────────────────────
    @staticmethod
    def _compile(query: str) -> re.Pattern[str]:
        """Compile a user-supplied search pattern.

        Args:
            query: The raw search string.

        Returns:
            A case-insensitive compiled pattern.

        Raises:
            ValidationError: If the pattern is not valid regex. The coursework
                version passed the raw string to :func:`re.search`, so a query of
                ``"["`` raised :class:`re.error` and surfaced as a server error.
        """
        try:
            return re.compile(query, re.IGNORECASE)
        except re.error as exc:
            raise ValidationError(
                f"Invalid search pattern: {exc}", field="query", value=query
            ) from exc

    def search_students(self, query: str) -> list[Student]:
        """Find students whose name or email matches a pattern.

        Args:
            query: A regular expression, matched case-insensitively.

        Returns:
            Matching students, ordered by id.

        Raises:
            ValidationError: If the pattern is invalid regex.
        """
        pattern = self._compile(query)
        return [
            s
            for s in self.store.get_all_students()
            if pattern.search(s.first_name)
            or pattern.search(s.last_name)
            or pattern.search(s.email)
        ]

    def search_courses(self, query: str) -> list[Course]:
        """Find courses whose name or id matches a pattern.

        Args:
            query: A regular expression, matched case-insensitively.

        Returns:
            Matching courses, ordered by id.

        Raises:
            ValidationError: If the pattern is invalid regex.
        """
        pattern = self._compile(query)
        return [
            c
            for c in self.store.get_all_courses()
            if pattern.search(c.name) or pattern.search(c.course_id)
        ]

    # ── JSON interchange ─────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        """Return the whole grade book as a JSON-serialisable structure."""
        return {
            "version": 2,
            "students": [s.to_dict() for s in self.store.get_all_students()],
            "courses": [c.to_dict() for c in self.store.get_all_courses()],
            "grades": [g.to_dict() for g in self.store.get_all_grades()],
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        """Populate the store from :meth:`to_dict` output.

        Students and courses are loaded before grades, since grades reference them.

        Args:
            data: A structure produced by :meth:`to_dict`.

        Raises:
            ValidationError: If the structure is malformed or a grade references an
                unknown student or course.
        """
        for raw in data.get("students", []):
            self.store.add_student(Student.from_dict(raw))
        for raw in data.get("courses", []):
            self.store.add_course(Course.from_dict(raw))
        for raw in data.get("grades", []):
            try:
                self.record_grade(
                    student_id=raw["student_id"],
                    course_id=raw["course_id"],
                    score=raw["score"],
                    date=raw["date"],
                    notes=raw.get("notes", ""),
                    title=raw.get("title", ""),
                    weight=raw.get("weight", 1.0),
                )
            except KeyError as exc:
                raise ValidationError(
                    f"Missing grade field: {exc.args[0]}", field=exc.args[0]
                ) from exc

    def save_json(self, filepath: str | Path) -> None:
        """Write the whole grade book to a JSON file.

        Args:
            filepath: Destination path. Parent directories must exist.
        """
        Path(filepath).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def load_json(self, filepath: str | Path) -> None:
        """Read a grade book from a JSON file written by :meth:`save_json`.

        Args:
            filepath: Source path.

        Raises:
            ValidationError: If the file is not valid JSON or has the wrong shape.
            FileNotFoundError: If the file does not exist.
        """
        try:
            data = json.loads(Path(filepath).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{filepath} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValidationError(f"{filepath} does not contain a grade book object.")
        self.load_dict(data)

    # ── CSV interchange ──────────────────────────────────────────────────────
    def export_csv(self, filepath: str | Path) -> None:
        """Write every grade to a spreadsheet-friendly CSV file.

        Args:
            filepath: Destination path.
        """
        with Path(filepath).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "student_id",
                    "student_name",
                    "course_id",
                    "course_name",
                    "title",
                    "score",
                    "max_grade",
                    "percentage",
                    "letter",
                    "weight",
                    "date",
                    "notes",
                ]
            )
            for grade in self.store.get_all_grades():
                writer.writerow(
                    [
                        grade.student.student_id,
                        grade.student.full_name,
                        grade.course.course_id,
                        grade.course.name,
                        grade.title,
                        grade.score,
                        grade.course.max_grade,
                        f"{grade.percentage:.1f}",
                        grade.letter_for(self.scale),
                        grade.weight,
                        grade.date,
                        grade.notes,
                    ]
                )

    def import_csv(self, filepath: str | Path) -> ImportReport:
        """Bulk-import grades from a CSV file.

        Requires ``student_id``, ``course_id``, ``score`` and ``date`` columns;
        ``title``, ``weight`` and ``notes`` are optional. Invalid rows are collected
        and reported rather than aborting the run, so one typo in row 4 does not cost
        the other 299 rows.

        Args:
            filepath: Source path.

        Returns:
            Counts and per-row failures.

        Raises:
            ValidationError: If the file has no header or is missing a required column.
            FileNotFoundError: If the file does not exist.
        """
        report = ImportReport()
        with Path(filepath).open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValidationError("CSV file is empty or has no header row.")

            missing = [c for c in _CSV_GRADE_FIELDS if c not in reader.fieldnames]
            if missing:
                raise ValidationError(
                    f"CSV is missing required columns: {', '.join(missing)}",
                    missing_columns=missing,
                )

            for line_number, row in enumerate(reader, start=2):  # line 1 is the header
                try:
                    self.record_grade(
                        student_id=(row["student_id"] or "").strip(),
                        course_id=(row["course_id"] or "").strip(),
                        score=float((row["score"] or "").strip()),
                        date=(row["date"] or "").strip(),
                        notes=(row.get("notes") or "").strip(),
                        title=(row.get("title") or "").strip(),
                        weight=float((row.get("weight") or "1").strip() or 1),
                    )
                    report.imported += 1
                except ValueError as exc:
                    # Covers ValidationError, the *NotFoundError family, and the
                    # plain ValueError float() raises on unparseable numbers.
                    code = getattr(exc, "code", "INVALID_NUMBER")
                    report.skipped += 1
                    report.errors.append((line_number, code))
        return report

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
