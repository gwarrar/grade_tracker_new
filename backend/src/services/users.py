"""Managing the people who can sign in.

The CRUD here is ordinary. What is not ordinary, and what most of this module is
about, are four rules that stop an administrator destroying their own access or
quietly acquiring more:

1. **Nobody may raise anyone above themselves.** An admin creating a superadmin
   would be a one-step privilege escalation dressed as a normal form submission.
2. **Nobody may change their own role or deactivate themselves.** Both are
   self-lockout, and the second is irreversible from inside the application.
3. **The last active superadmin cannot be removed.** Not by demotion, not by
   deactivation. An installation with nobody who can configure it is a support
   ticket that requires database access to close.
4. **An administrator never sees or sets a password directly.** They trigger a
   reset that returns a one-time value; the user changes it themselves.

Each of these is enforced here rather than in the router, so a second caller
cannot arrive later and skip them.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from typing import Any

from notenverwaltung.exceptions import (
    DuplicateEntryError,
    ForbiddenError,
    GradeBookError,
    ValidationError,
)
from notenverwaltung.models.user import Role
from notenverwaltung.storage import transaction
from notenverwaltung.storage.queries import escape_like
from services import audit
from services.scoping import Principal
from services.security import MIN_PASSWORD_LENGTH, hash_password, utc_now

#: Length of a generated temporary password, in bytes before encoding.
_TEMPORARY_PASSWORD_BYTES = 12


class UserNotFoundError(GradeBookError):
    """Raised when no account matches the requested id."""

    code = "USER_NOT_FOUND"
    http_status = 404


class LastSuperadminError(GradeBookError):
    """Raised when an action would leave the installation with no superadmin."""

    code = "LAST_SUPERADMIN"
    http_status = 409


class SelfModificationError(GradeBookError):
    """Raised when someone tries to change their own role or active state."""

    code = "CANNOT_MODIFY_SELF"
    http_status = 409


@dataclass(frozen=True, slots=True)
class UserRecord:
    """One account, without anything secret.

    The password hash and salt are not fields here at all, rather than being
    fields that callers are trusted to skip. A shape that cannot carry a secret
    cannot leak one.
    """

    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    locale: str | None
    created_at: str
    updated_at: str | None
    student_id: str | None
    session_count: int
    must_change_password: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> UserRecord:
        """Build a record from a database row.

        Args:
            row: A row of the listing query.

        Returns:
            The typed record.
        """
        return cls(
            id=row["id"],
            email=row["email"],
            full_name=row["full_name"],
            role=row["role"],
            is_active=bool(row["is_active"]),
            locale=row["locale"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            student_id=row["student_id"],
            session_count=row["session_count"],
            must_change_password=bool(row["must_change_password"]),
        )


# Every field the API exposes, and no others. Selecting * here would mean a new
# secret column added later is published by default.
_SELECT = (
    "SELECT u.id, u.email, u.full_name, u.role, u.is_active, u.locale,"
    "       u.created_at, u.updated_at, u.must_change_password,"
    "       (SELECT s.student_id FROM students s WHERE s.user_id = u.id) AS student_id,"
    "       (SELECT COUNT(*) FROM sessions ss"
    "         WHERE ss.user_id = u.id AND ss.expires_at > ?) AS session_count"
    "  FROM users u"
)


class UserService:
    """Account administration."""

    def __init__(self, conn: sqlite3.Connection, actor: Principal) -> None:
        """Initialise the service.

        Args:
            conn: The request's database connection.
            actor: Who is making the changes. Held rather than passed per call, so
                the self-modification rules cannot be bypassed by omitting it.
        """
        self._conn = conn
        self._actor = actor

    # ── Reading ──────────────────────────────────────────────────────────────

    def list(
        self, *, query: str = "", include_inactive: bool = True, role: Role | None = None
    ) -> list[UserRecord]:
        """List accounts.

        Args:
            query: Substring of name or email. Empty matches everything.
            include_inactive: Whether deactivated accounts appear. They do by
                default — hiding them makes a deactivated account look deleted,
                and someone then tries to recreate it and hits a unique
                constraint they cannot explain.
            role: Restrict to one role. A cohort import mints hundreds of student
                accounts, which would otherwise bury the handful of staff accounts
                an administrator actually came here to manage.

        Returns:
            Accounts, ordered by name.
        """
        where: list[str] = []
        params: list[Any] = [utc_now()]

        if query:
            where.append("(u.full_name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\')")
            pattern = f"%{escape_like(query)}%"
            params.extend([pattern, pattern])
        if not include_inactive:
            where.append("u.is_active = 1")
        if role is not None:
            where.append("u.role = ?")
            params.append(role.value)

        clause = f" WHERE {' AND '.join(where)}" if where else ""
        rows = self._conn.execute(
            f"{_SELECT}{clause} ORDER BY u.full_name",
            tuple(params),
        ).fetchall()
        return [UserRecord.from_row(row) for row in rows]

    def get(self, user_id: int) -> UserRecord:
        """Fetch one account.

        Args:
            user_id: Primary key.

        Returns:
            The account.

        Raises:
            UserNotFoundError: If no such account exists.
        """
        row = self._conn.execute(
            f"{_SELECT} WHERE u.id = ?",
            (utc_now(), user_id),
        ).fetchone()
        if row is None:
            raise UserNotFoundError(f"no account with id {user_id}", user_id=user_id)
        return UserRecord.from_row(row)

    # ── Writing ──────────────────────────────────────────────────────────────

    def create(
        self, *, email: str, full_name: str, role: Role, password: str | None = None
    ) -> tuple[UserRecord, str]:
        """Create an account.

        Args:
            email: Sign-in address. Must be unique.
            full_name: Display name.
            role: What the account may do.
            password: Initial password. Generated when omitted, which is the
                normal path — an administrator choosing a password means the
                password is known to two people from the moment it exists.

        Returns:
            The account and its initial password, the only time that value is
            ever available. The account is flagged to require a change, because
            until the person replaces it the password has two owners.

        Raises:
            ForbiddenError: If the actor may not grant this role.
            ValidationError: If the email or password is unusable.
            DuplicateEntryError: If the email is taken.
        """
        self._assert_may_grant(role)

        address = email.strip().lower()
        if "@" not in address or len(address) < 3:
            raise ValidationError("that is not an email address", field="email", value=email)

        initial = password or secrets.token_urlsafe(_TEMPORARY_PASSWORD_BYTES)
        if len(initial) < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"password must be at least {MIN_PASSWORD_LENGTH} characters",
                field="password",
            )

        digest, salt = hash_password(initial)
        # The account, its link to a student record and the audit entry are one unit.
        # `transaction` nests through savepoints, so the callers that already opened
        # one -- provisioning a student, importing a cohort -- are unaffected; this
        # covers the `POST /users` path, which had none.
        with transaction(self._conn):
            try:
                cursor = self._conn.execute(
                    "INSERT INTO users"
                    " (email, password_hash, password_salt, role, full_name,"
                    " must_change_password)"
                    " VALUES (?, ?, ?, ?, ?, 1)",
                    (address, digest, salt, role.value, full_name.strip()),
                )
            except sqlite3.IntegrityError as error:
                raise DuplicateEntryError(f"{address} already has an account") from error

            user_id = int(cursor.lastrowid or 0)
            if role is Role.STUDENT:
                self._link_student_record(user_id, address)
            self._record(user_id, "create", after={"email": address, "role": role.value})
        return self.get(user_id), initial

    def _link_student_record(self, user_id: int, address: str) -> None:
        """Attach a new student account to the record that shares its address.

        Creating the account and attaching it were two acts, and nothing performed
        the second. The account signed in and then saw nothing at all: with no
        ``student_id`` on the principal, ``student_scope`` matches zero rows, so
        the application is empty rather than broken-looking.

        Only unlinked records are claimed, so this cannot move an existing link,
        and only an exact address match, so it cannot guess.

        Args:
            user_id: The freshly created account.
            address: Its sign-in address, already normalised.
        """
        self._conn.execute(
            "UPDATE students SET user_id = ?, updated_at = ?"
            " WHERE user_id IS NULL AND lower(email) = ?",
            (user_id, utc_now(), address),
        )

    def set_role(self, user_id: int, role: Role) -> UserRecord:
        """Change what an account may do.

        Args:
            user_id: Which account.
            role: The new role.

        Returns:
            The updated account.

        Raises:
            SelfModificationError: If the actor is changing their own role.
            ForbiddenError: If the actor may not grant this role, or may not act
                on this account.
            LastSuperadminError: If this would demote the last superadmin.
            UserNotFoundError: If no such account exists.
        """
        before = self.get(user_id)
        self._assert_not_self(user_id)
        self._assert_may_grant(role)
        self._assert_may_act_on(before)

        with transaction(self._conn):
            # The "last superadmin" count is inside the transaction with the update
            # it guards. Outside, two administrators demoting the last two
            # superadmins at the same moment both counted one remaining and both
            # succeeded, leaving an installation nobody can administer.
            if before.role == Role.SUPERADMIN.value and role is not Role.SUPERADMIN:
                self._assert_not_last_superadmin(user_id)

            self._conn.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
                (role.value, utc_now(), user_id),
            )
            self._record(
                user_id, "update", before={"role": before.role}, after={"role": role.value}
            )
        return self.get(user_id)

    def set_active(self, user_id: int, *, active: bool) -> UserRecord:
        """Activate or deactivate an account.

        Deactivating also revokes every session, because an account that cannot
        sign in but stays signed in is not deactivated in any sense the word
        normally carries.

        Args:
            user_id: Which account.
            active: Whether it may sign in.

        Returns:
            The updated account.

        Raises:
            SelfModificationError: If the actor is deactivating themselves.
            ForbiddenError: If the actor may not act on this account.
            LastSuperadminError: If this would disable the last superadmin.
            UserNotFoundError: If no such account exists.
        """
        target = self.get(user_id)
        self._assert_not_self(user_id)
        self._assert_may_act_on(target)

        with transaction(self._conn):
            if not active and target.role == Role.SUPERADMIN.value:
                self._assert_not_last_superadmin(user_id)

            self._conn.execute(
                "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
                (int(active), utc_now(), user_id),
            )
            if not active:
                # In the same unit of work as the flag. Apart, a lock timeout on
                # this statement left the account marked inactive with every
                # session still live and nothing in the audit trail saying so.
                self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

            self._record(
                user_id,
                "update",
                before={"is_active": target.is_active},
                after={"is_active": active},
            )
        return self.get(user_id)

    def reset_password(self, user_id: int) -> str:
        """Issue a new temporary password and sign the account out everywhere.

        The administrator never chooses or sees an existing password — they mint a
        replacement, hand it over once, and the user changes it. Sessions are
        revoked because a reset is what someone does when they suspect the account
        is compromised, and leaving the intruder's session alive defeats it.

        Args:
            user_id: Which account.

        Returns:
            The temporary password. The only time it is available in plain text.

        Raises:
            ForbiddenError: If the actor may not act on this account.
            UserNotFoundError: If no such account exists.
        """
        target = self.get(user_id)
        self._assert_may_act_on(target)

        temporary = secrets.token_urlsafe(_TEMPORARY_PASSWORD_BYTES)
        digest, salt = hash_password(temporary)
        # All three together, or none. A reset that changed the password and then
        # failed to close the sessions would leave the holder of the old one signed
        # in -- which is the exact thing a reset is performed to stop -- and no
        # audit entry to say a reset had happened at all.
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = 1,"
                " updated_at = ? WHERE id = ?",
                (digest, salt, utc_now(), user_id),
            )
            self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

            # The password itself is never written to the audit trail — the trail is
            # readable by anyone who can read the database, which is the population a
            # reset is meant to protect against. Only the fact of the reset is recorded.
            self._record(user_id, "update", after={"password_reset": True})
        return temporary

    # ── Rules ────────────────────────────────────────────────────────────────

    def _assert_not_self(self, user_id: int) -> None:
        """Refuse an action the actor is aiming at their own account.

        Args:
            user_id: The target account.

        Raises:
            SelfModificationError: If it is the actor's own.
        """
        if user_id == self._actor.user_id:
            raise SelfModificationError(
                "you cannot change your own role or deactivate yourself", user_id=user_id
            )

    def _assert_may_grant(self, role: Role) -> None:
        """Refuse granting a role at or above the actor's own.

        Equal is refused as well as above: an admin minting a second admin is how
        a compromised account becomes two compromised accounts, and a superadmin
        remains able to do it.

        Args:
            role: The role being granted.

        Raises:
            ForbiddenError: If the actor may not grant it.
        """
        if self._actor.role is Role.SUPERADMIN:
            return
        if not self._actor.role.outranks(role):
            raise ForbiddenError(f"you cannot grant the {role.value} role", role=role.value)

    def _assert_may_act_on(self, target: UserRecord) -> None:
        """Refuse acting on an account at or above the actor's own rank.

        Without this, an admin could reset a superadmin's password and take the
        installation over — the reset endpoint would be a privilege escalation.

        Args:
            target: The account being acted on.

        Raises:
            ForbiddenError: If the target outranks or matches the actor.
        """
        if self._actor.role is Role.SUPERADMIN:
            return
        if not self._actor.role.outranks(Role(target.role)):
            raise ForbiddenError(
                "you cannot act on an account at or above your own level",
                user_id=target.id,
            )

    def _assert_not_last_superadmin(self, user_id: int) -> None:
        """Refuse removing the only remaining superadmin.

        Args:
            user_id: The account being demoted or deactivated.

        Raises:
            LastSuperadminError: If no other active superadmin exists.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) AS remaining FROM users"
            " WHERE role = 'superadmin' AND is_active = 1 AND id != ?",
            (user_id,),
        ).fetchone()
        if row["remaining"] == 0:
            raise LastSuperadminError(
                "this is the last superadmin; promote someone else first",
                user_id=user_id,
            )

    def _record(
        self,
        user_id: int,
        action: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        """Append one entry to the audit trail.

        Args:
            user_id: The account acted on.
            action: What happened.
            before: Prior values, where relevant.
            after: New values, where relevant.
        """
        audit.record(
            self._conn,
            actor_user_id=self._actor.user_id,
            entity="user",
            entity_id=str(user_id),
            action=action,
            before=before,
            after=after,
        )
