"""Row-level access control.

**This module is the security boundary.** Everything a signed-in user is allowed to
read is decided here, once, and expressed as a :class:`~notenverwaltung.storage.scope.Scope`
that every list and detail query composes into its ``WHERE`` clause.

The alternative — a role check inside each route handler — fails in a specific and
dangerous way: the handler someone adds next month forgets the check, and the bug is
invisible because the endpoint returns data exactly as expected. Filtering in the
query instead means a forgotten scope produces an **empty result**. Empty results get
reported. Over-broad results do not.

Routes therefore assert only *action* permission ("may this user record a grade at
all"). They never assert *row* permission ("may this user record a grade for this
student") — that is answered here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from notenverwaltung.models import Role, Theme
from notenverwaltung.storage.scope import ALLOW_ALL, DENY_ALL, Scope

_SAFE_COLUMN = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")


def _column(name: str) -> str:
    """Validate a column name before it is interpolated into SQL.

    Every caller in this codebase passes a literal, so this never fires today. It
    exists because the alternative is a module where "the column name is always
    trusted" is an unwritten rule -- and this module is the security boundary, which
    is the worst possible place to rely on one. The values these scopes compare
    against always travel as ``?`` parameters; only the column name is interpolated,
    and only after passing this.

    Args:
        name: A column, optionally table-qualified, e.g. ``"g.course_id"``.

    Returns:
        The name unchanged.

    Raises:
        ValueError: If the name is not a plain identifier.
    """
    if not _SAFE_COLUMN.match(name):
        raise ValueError(f"Unsafe column name in scope: {name!r}")
    return name


@dataclass(frozen=True)
class Principal:
    """The authenticated caller.

    Frozen: a request handler must not be able to adjust its own permissions
    part-way through, and an accidental ``principal.role = Role.ADMIN`` should be an
    error rather than a privilege escalation.

    Attributes:
        user_id: The signed-in account.
        role: What they may do.
        email: Their sign-in address.
        full_name: Display name.
        student_id: The student record linked to this account, if any. Only set for
            student users, and the basis of their entire visibility.
        locale: Resolved language, after falling back through the organisation default.
        theme: Resolved colour scheme.
        must_change_password: Whether the password still is the generated one an
            administrator handed over, and so is known to two people.
    """

    user_id: int
    role: Role
    email: str
    full_name: str
    student_id: str | None = None
    locale: str = "en"
    theme: Theme = Theme.SYSTEM
    must_change_password: bool = False

    @property
    def is_admin(self) -> bool:
        """Whether the caller may see and change everything."""
        return self.role.can_act_as(Role.ADMIN)

    @property
    def is_superadmin(self) -> bool:
        """Whether the caller may configure AI providers and other system settings."""
        return self.role is Role.SUPERADMIN

    def can(self, required: Role) -> bool:
        """Whether the caller meets a minimum role.

        Args:
            required: The least privileged role permitted.

        Returns:
            ``True`` if the caller qualifies.
        """
        return self.role.can_act_as(required)


def course_scope(principal: Principal, column: str = "course_id") -> Scope:
    """Restrict a query to the courses a principal may see.

    Args:
        principal: The authenticated caller.
        column: The column holding a course id, qualified if the query joins
            (e.g. ``"g.course_id"``).

    Returns:
        Administrators get every course; a teacher gets the courses they own; a
        student gets the courses they are enrolled on. Anyone else gets nothing.
    """
    if principal.is_admin:
        return ALLOW_ALL

    if principal.role is Role.TEACHER:
        return Scope(
            f"{_column(column)} IN (SELECT course_id FROM courses WHERE teacher_id = ?)",  # noqa: S608
            (principal.user_id,),
        )

    if principal.role is Role.STUDENT and principal.student_id:
        return Scope(
            f"{_column(column)} IN (SELECT course_id FROM enrollments WHERE student_id = ?)",  # noqa: S608
            (principal.student_id,),
        )

    # A student user with no linked student record can see nothing, which is correct:
    # the account exists but has no academic identity to scope by.
    return DENY_ALL


def student_scope(principal: Principal, column: str = "student_id") -> Scope:
    """Restrict a query to the students a principal may see.

    Args:
        principal: The authenticated caller.
        column: The column holding a student id, qualified if the query joins.

    Returns:
        Administrators get every student; a teacher gets students enrolled on a
        course they own; a student gets only themselves.
    """
    if principal.is_admin:
        return ALLOW_ALL

    if principal.role is Role.TEACHER:
        return Scope(
            f"{_column(column)} IN ("  # noqa: S608
            "  SELECT e.student_id FROM enrollments e"
            "  JOIN courses c ON c.course_id = e.course_id"
            "  WHERE c.teacher_id = ?)",
            (principal.user_id,),
        )

    if principal.role is Role.STUDENT and principal.student_id:
        return Scope(f"{_column(column)} = ?", (principal.student_id,))

    return DENY_ALL


def grade_scope(
    principal: Principal, student_column: str = "student_id", course_column: str = "course_id"
) -> Scope:
    """Restrict a query to the grades a principal may see.

    A grade is visible when **both** its student and its course are. Requiring both is
    what stops a teacher reading a student's marks from a colleague's course simply
    because that student also sits in one of theirs.

    Args:
        principal: The authenticated caller.
        student_column: Column holding the student id.
        course_column: Column holding the course id.

    Returns:
        The intersection of the student and course scopes.
    """
    if principal.is_admin:
        return ALLOW_ALL

    if principal.role is Role.STUDENT:
        # A student sees all of their own grades, including those from a course whose
        # enrolment has since been withdrawn -- the marks are still theirs.
        return student_scope(principal, student_column)

    return student_scope(principal, student_column) & course_scope(principal, course_column)


def user_scope(principal: Principal, column: str = "id") -> Scope:
    """Restrict a query to the user accounts a principal may see.

    Args:
        principal: The authenticated caller.
        column: The column holding a user id.

    Returns:
        Administrators get every account; everyone else gets only their own.
    """
    if principal.is_admin:
        return ALLOW_ALL
    return Scope(f"{_column(column)} = ?", (principal.user_id,))


def note_scope(principal: Principal, column: str = "visibility") -> Scope:
    """Restrict a query to the notes a principal may see.

    Covers the **visibility** dimension only. Whether the note's entity is visible is
    proven beforehand by the caller fetching the student or course — the pattern
    :meth:`services.directory.DirectoryService.list_enrollments` already uses.

    Args:
        principal: The authenticated caller.
        column: The column holding the visibility, qualified if the query joins.

    Returns:
        Administrators get every note; a teacher gets ``staff``, ``shared`` and
        ``course`` notes plus their own; a student gets ``shared`` and ``course``
        notes plus their own. The ``author_id`` clause is load-bearing: without it a
        student could not see a note they had just written.
    """
    if principal.is_admin:
        return ALLOW_ALL

    if principal.role is Role.TEACHER:
        return Scope(
            f"{_column(column)} IN ('staff', 'shared', 'course') OR author_id = ?",
            (principal.user_id,),
        )

    if principal.role is Role.STUDENT:
        return Scope(
            f"{_column(column)} IN ('shared', 'course') OR author_id = ?",
            (principal.user_id,),
        )

    return DENY_ALL


def can_write_course(principal: Principal, teacher_id: int | None) -> bool:
    """Whether a principal may modify a course.

    Read access is broader than write access: a student can see a course they are
    enrolled on, and must not be able to rename it.

    Args:
        principal: The authenticated caller.
        teacher_id: The course's owning teacher.

    Returns:
        ``True`` for administrators, and for the teacher who owns the course.
    """
    if principal.is_admin:
        return True
    return principal.role is Role.TEACHER and teacher_id == principal.user_id
