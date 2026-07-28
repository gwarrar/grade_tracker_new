"""The :class:`Course` domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from notenverwaltung.exceptions import ValidationError


@dataclass
class Course:
    """A course students can enrol in and be graded against.

    Attributes:
        course_id: Institution-assigned code, e.g. ``"CS101"``.
        name: Human-readable title.
        max_grade: The highest achievable score. Defaults to 100.
        passing_grade: The lowest passing score. Must be within ``(0, max_grade]``.
        max_students: Enrolment capacity.
        teacher_id: Optional owning teacher's user id. Drives row-level access:
            a teacher sees only the courses they own.
        term: Optional academic term, e.g. ``"2026-SS"``. Lets averages be scoped
            to a period instead of spanning all time.
        credits: Weight of this course in a GPA calculation.
    """

    course_id: str
    name: str
    max_grade: float = 100.0
    passing_grade: float = 50.0
    max_students: int = 30
    teacher_id: int | None = field(default=None)
    term: str | None = field(default=None)
    credits: float = 1.0

    def __post_init__(self) -> None:
        """Normalise whitespace and validate every field.

        Raises:
            ValidationError: If an identifier or name is blank, or a numeric bound
                is outside its permitted range.
        """
        self.course_id = self.course_id.strip()
        self.name = self.name.strip()
        if self.term is not None:
            self.term = self.term.strip() or None

        if not self.course_id:
            raise ValidationError("Course ID cannot be empty.", field="course_id")
        if not self.name:
            raise ValidationError("Course name cannot be empty.", field="name")
        if self.max_grade <= 0:
            raise ValidationError(
                "Maximum grade must be greater than 0.",
                field="max_grade",
                value=self.max_grade,
            )
        if not 0 < self.passing_grade <= self.max_grade:
            raise ValidationError(
                "Passing grade must be greater than 0 and at most the maximum grade.",
                field="passing_grade",
                value=self.passing_grade,
                max_grade=self.max_grade,
            )
        if self.max_students <= 0:
            raise ValidationError(
                "Capacity must be greater than 0.",
                field="max_students",
                value=self.max_students,
            )
        if self.credits <= 0:
            raise ValidationError(
                "Credits must be greater than 0.", field="credits", value=self.credits
            )

    def __str__(self) -> str:
        """Return a readable representation for logs and reports."""
        return f"{self.name} (ID: {self.course_id})"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "course_id": self.course_id,
            "name": self.name,
            "max_grade": self.max_grade,
            "passing_grade": self.passing_grade,
            "max_students": self.max_students,
            "teacher_id": self.teacher_id,
            "term": self.term,
            "credits": self.credits,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Course:
        """Rebuild a course from :meth:`to_dict` output.

        Optional fields fall back to the dataclass defaults, so payloads written by
        the coursework version still load.

        Args:
            data: Mapping with at least ``course_id`` and ``name``.

        Returns:
            The reconstructed course.

        Raises:
            ValidationError: If a required key is missing or a value is invalid.
        """
        try:
            return cls(
                course_id=data["course_id"],
                name=data["name"],
                max_grade=float(data.get("max_grade", 100.0)),
                passing_grade=float(data.get("passing_grade", 50.0)),
                max_students=int(data.get("max_students", 30)),
                teacher_id=data.get("teacher_id"),
                term=data.get("term"),
                credits=float(data.get("credits", 1.0)),
            )
        except KeyError as exc:
            raise ValidationError(
                f"Missing course field: {exc.args[0]}", field=exc.args[0]
            ) from exc
