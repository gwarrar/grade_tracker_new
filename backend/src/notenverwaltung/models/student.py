"""The :class:`Student` domain model."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from notenverwaltung.exceptions import ValidationError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
"""Deliberately permissive.

Fully validating an address per RFC 5322 is famously not worth it — the only real
proof an address works is sending mail to it. This rejects the typos that matter
(missing ``@``, missing domain, whitespace) and accepts everything else.
"""


@dataclass
class Student:
    """A student enrolled at the institution.

    Attributes:
        student_id: Institution-assigned identifier, e.g. ``"S001"``. Immutable in practice.
        first_name: Given name.
        last_name: Family name.
        email: Contact address, unique per student by convention.
        user_id: Optional link to a login account. ``None`` for students who have
            records but never sign in — a common case for younger cohorts.
    """

    student_id: str
    first_name: str
    last_name: str
    email: str
    user_id: int | None = field(default=None)

    def __post_init__(self) -> None:
        """Normalise whitespace and validate every field.

        Raises:
            ValidationError: If an identifier or name is blank, or the email is malformed.
        """
        self.student_id = self.student_id.strip()
        self.first_name = self.first_name.strip()
        self.last_name = self.last_name.strip()
        self.email = self.email.strip().lower()

        if not self.student_id:
            raise ValidationError("Student ID cannot be empty.", field="student_id")
        if not self.first_name:
            raise ValidationError("First name cannot be empty.", field="first_name")
        if not self.last_name:
            raise ValidationError("Last name cannot be empty.", field="last_name")
        if not _EMAIL_RE.match(self.email):
            raise ValidationError("Invalid email address.", field="email", value=self.email)

    @property
    def full_name(self) -> str:
        """The student's display name, ``"first last"``."""
        return f"{self.first_name} {self.last_name}"

    def __str__(self) -> str:
        """Return a readable representation for logs and reports."""
        return f"Student: {self.full_name} ({self.student_id})"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "student_id": self.student_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Student:
        """Rebuild a student from :meth:`to_dict` output.

        Args:
            data: Mapping with at least ``student_id``, ``first_name``, ``last_name``
                and ``email``. ``user_id`` is optional.

        Returns:
            The reconstructed student.

        Raises:
            ValidationError: If a required key is missing or a value is invalid.
        """
        try:
            return cls(
                student_id=data["student_id"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                email=data["email"],
                user_id=data.get("user_id"),
            )
        except KeyError as exc:
            raise ValidationError(
                f"Missing student field: {exc.args[0]}", field=exc.args[0]
            ) from exc
