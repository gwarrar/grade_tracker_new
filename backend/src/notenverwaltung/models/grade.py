"""The :class:`Grade` domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from notenverwaltung.exceptions import ValidationError
from notenverwaltung.grading_scale import DEFAULT_SCALE, GradingScale
from notenverwaltung.models.course import Course
from notenverwaltung.models.student import Student

_ACCEPTED_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y")
"""Input formats accepted, in priority order. Everything is stored as ISO ``%Y-%m-%d``.

The coursework version stored ``DD-MM-YYYY`` while the specification called for ISO.
Rather than pick a side and break existing files, parsing accepts both (plus the two
separators German and French users type by habit) and normalises on the way in.
There is no ambiguity: the four-digit year identifies the format by position.
"""


def normalise_date(value: str) -> str:
    """Parse a date in any accepted format and return it as ISO ``YYYY-MM-DD``.

    Args:
        value: A date string in one of :data:`_ACCEPTED_DATE_FORMATS`.

    Returns:
        The equivalent ISO-8601 date string.

    Raises:
        ValidationError: If the string matches no accepted format, or encodes a
            date that does not exist such as ``2026-02-30``.
    """
    text = value.strip()
    for fmt in _ACCEPTED_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValidationError("Date must be ISO (YYYY-MM-DD) or DD-MM-YYYY.", field="date", value=value)


@dataclass
class Grade:
    """A score awarded to a student for a course.

    A student may hold several grades for one course — use :attr:`title` to name them
    (``"Midterm"``, ``"Final"``) and :attr:`weight` to say how much each counts.

    Attributes:
        student: The graded student.
        course: The course graded against.
        score: Points awarded, within ``[0, course.max_grade]``.
        date: Award date, always stored as ISO ``YYYY-MM-DD``.
        notes: Free-text remark.
        title: What this grade is for, e.g. ``"Midterm"``. Empty for a course's
            single overall grade.
        weight: Relative weight in the course average. Equal weighting by default.
        grade_id: Database identifier. ``None`` until persisted — which is how the
            store distinguishes an insert from an update.
        graded_by: User id of whoever recorded it, for the audit trail.
    """

    student: Student
    course: Course
    score: float
    date: str
    notes: str = ""
    title: str = ""
    weight: float = 1.0
    grade_id: int | None = field(default=None)
    graded_by: int | None = field(default=None)

    def __post_init__(self) -> None:
        """Normalise the date and validate the score and weight.

        Raises:
            ValidationError: If the score is outside ``[0, course.max_grade]``, the
                weight is not positive, or the date cannot be parsed.
        """
        self.date = normalise_date(self.date)
        self.title = self.title.strip()
        self.notes = self.notes.strip()

        if not 0 <= self.score <= self.course.max_grade:
            raise ValidationError(
                f"Score {self.score} is outside the range [0, {self.course.max_grade}].",
                field="score",
                value=self.score,
                max_grade=self.course.max_grade,
            )
        if self.weight <= 0:
            raise ValidationError(
                "Weight must be greater than 0.", field="weight", value=self.weight
            )

    @property
    def is_passing(self) -> bool:
        """Whether the score reaches the course's passing threshold."""
        return self.score >= self.course.passing_grade

    @property
    def percentage(self) -> float:
        """The score as a percentage of the course maximum."""
        return (self.score / self.course.max_grade) * 100

    @property
    def letter_grade(self) -> str:
        """The letter under the default A-F scale.

        Use :meth:`letter_for` to apply an organisation's configured scale instead.
        """
        return DEFAULT_SCALE.label_for(self.percentage)

    @property
    def date_obj(self) -> date:
        """The award date as a :class:`datetime.date`, for sorting and arithmetic."""
        return date.fromisoformat(self.date)

    def letter_for(self, scale: GradingScale) -> str:
        """Return the label for this grade under a specific scale.

        Args:
            scale: The organisation's configured grading scale.

        Returns:
            The band label, e.g. ``"A"`` or ``"2"``.
        """
        return scale.label_for(self.percentage)

    def __str__(self) -> str:
        """Return a readable representation for logs and reports."""
        status = "Passed" if self.is_passing else "Failed"
        label = f" [{self.title}]" if self.title else ""
        return (
            f"Grade: {self.student.full_name} - {self.course.name}{label}: "
            f"{self.score}/{self.course.max_grade} ({self.letter_grade}) - {status}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation.

        Students and courses are referenced by id rather than nested, so a grade book
        round-trips through JSON without duplicating every student on every grade.
        """
        return {
            "grade_id": self.grade_id,
            "student_id": self.student.student_id,
            "course_id": self.course.course_id,
            "score": self.score,
            "date": self.date,
            "notes": self.notes,
            "title": self.title,
            "weight": self.weight,
            "graded_by": self.graded_by,
        }
