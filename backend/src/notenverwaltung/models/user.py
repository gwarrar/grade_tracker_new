"""The :class:`User` domain model and the role hierarchy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from notenverwaltung.exceptions import ValidationError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Role(StrEnum):
    """What a user may do.

    Ordered by authority, which :meth:`outranks` relies on. A ``StrEnum`` so the value
    stored in the database is the readable name rather than an integer nobody can
    interpret while reading a row by hand.
    """

    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"

    @property
    def rank(self) -> int:
        """Position in the hierarchy. Higher is more privileged."""
        return _RANKS[self]

    def outranks(self, other: Role) -> bool:
        """Whether this role is strictly more privileged than another.

        Args:
            other: The role to compare against.

        Returns:
            ``True`` if this role sits higher in the hierarchy.
        """
        return self.rank > other.rank

    def can_act_as(self, required: Role) -> bool:
        """Whether this role satisfies a minimum requirement.

        Args:
            required: The least privileged role permitted.

        Returns:
            ``True`` if this role is at least as privileged as ``required``.
        """
        return self.rank >= required.rank


_RANKS: dict[Role, int] = {
    Role.STUDENT: 0,
    Role.TEACHER: 1,
    Role.ADMIN: 2,
    Role.SUPERADMIN: 3,
}


class Theme(StrEnum):
    """A user's colour-scheme preference.

    ``SYSTEM`` follows the operating system and is the default: it is the only value
    that is correct both at midday and at midnight without the user intervening.
    """

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


@dataclass
class User:
    """An account that can sign in.

    Distinct from :class:`~notenverwaltung.models.student.Student`: a student is an
    academic record, a user is a login. Most students have both, some have only a
    record, and teachers and administrators have only an account.

    Attributes:
        id: Database identifier. ``None`` until persisted.
        email: Sign-in address, unique case-insensitively.
        full_name: Display name.
        role: What the user may do.
        password_hash: scrypt digest, hex-encoded. Never leaves the backend.
        password_salt: Per-user salt, hex-encoded.
        avatar_path: Optional uploaded avatar.
        locale: Preferred language, or ``None`` to follow the organisation default.
        theme_preference: Preferred colour scheme, or ``None`` to follow the default.
        is_active: Deactivated users cannot sign in but keep their records — which is
            why deactivation exists instead of deletion.
        created_at: ISO timestamp.
    """

    email: str
    full_name: str
    role: Role
    password_hash: str = ""
    password_salt: str = ""
    id: int | None = field(default=None)
    avatar_path: str | None = field(default=None)
    locale: str | None = field(default=None)
    theme_preference: Theme | None = field(default=None)
    is_active: bool = True
    created_at: str | None = field(default=None)

    def __post_init__(self) -> None:
        """Normalise and validate the account fields.

        Raises:
            ValidationError: If the email is malformed, the name is blank, or the
                role is not a recognised value.
        """
        self.email = self.email.strip().lower()
        self.full_name = self.full_name.strip()

        if not _EMAIL_RE.match(self.email):
            raise ValidationError("Invalid email address.", field="email", value=self.email)
        if not self.full_name:
            raise ValidationError("Full name cannot be empty.", field="full_name")

    @classmethod
    def from_row(cls, row: Any) -> User:
        """Build a user from a ``users`` table row.

        The model declares `role` as a :class:`Role` and means it. Coercing the
        database's plain strings happens here, at the boundary, rather than inside
        ``__post_init__`` where it would be unreachable to a type checker and would
        quietly widen the model's contract for every caller.

        Args:
            row: A mapping with the table's column names.

        Returns:
            The reconstructed user.

        Raises:
            ValidationError: If the stored role or theme is not a recognised value.
        """
        try:
            role = Role(row["role"])
            theme = Theme(row["theme_preference"]) if row["theme_preference"] else None
        except ValueError as exc:
            raise ValidationError(f"Unrecognised value in users row: {exc}") from exc

        return cls(
            email=row["email"],
            full_name=row["full_name"],
            role=role,
            password_hash=row["password_hash"],
            password_salt=row["password_salt"],
            id=row["id"],
            avatar_path=row["avatar_path"],
            locale=row["locale"],
            theme_preference=theme,
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
        )

    @property
    def is_staff(self) -> bool:
        """Whether the user is a teacher or above."""
        return self.role.can_act_as(Role.TEACHER)

    def __str__(self) -> str:
        """Return a readable representation for logs."""
        return f"{self.full_name} <{self.email}> ({self.role})"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation.

        The password hash and salt are **deliberately excluded**. A model whose
        serialiser cannot emit a credential is one that cannot leak it by accident
        through a new endpoint, a log line, or a debug dump.
        """
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": str(self.role),
            "avatar_path": self.avatar_path,
            "locale": self.locale,
            "theme_preference": str(self.theme_preference) if self.theme_preference else None,
            "is_active": self.is_active,
            "created_at": self.created_at,
        }
