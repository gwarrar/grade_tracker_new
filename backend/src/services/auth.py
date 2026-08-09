"""Authentication: sign in, sign out, session lookup, password change.

Sessions are database rows rather than signed tokens. That makes revocation a
``DELETE`` which takes effect on the next request — the only implementation under
which "log out my other devices" and "deactivate this account" mean what a user
expects them to mean. A JWT would need a revocation list to achieve the same thing,
which is a database row with extra steps.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from notenverwaltung.exceptions import GradeBookError, NotAuthenticatedError, ValidationError
from notenverwaltung.models import Role, Theme
from services.scoping import Principal
from services.security import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    hash_token,
    new_session_token,
    session_expiry,
    utc_now,
    verify_password,
)


class AuthenticationError(GradeBookError):
    """Raised when credentials are rejected."""

    code = "INVALID_CREDENTIALS"
    http_status = 401


class AccountDisabledError(GradeBookError):
    """Raised when a deactivated account attempts to sign in."""

    code = "ACCOUNT_DISABLED"
    http_status = 403


#: How stale a session's ``last_seen_at`` may get before it is written again.
#: Its only reader is the device list on the profile page, which shows a date.
SESSION_TOUCH_SECONDS = 60


def is_stale(last_seen: str | None, seconds: int) -> bool:
    """Whether a stored timestamp is older than a cutoff.

    Args:
        last_seen: An ISO-8601 UTC timestamp as :func:`utc_now` writes them, or None
            for a session that has never been touched.
        seconds: How old is too old.

    Returns:
        True when the value is missing, unparseable, or older than the cutoff.
        Unparseable counts as stale so a bad row is repaired by the next request
        rather than freezing forever.
    """
    if not last_seen:
        return True
    try:
        seen = datetime.strptime(last_seen, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return True
    return (datetime.now(UTC) - seen).total_seconds() >= seconds


class RateLimitedError(GradeBookError):
    """Raised when sign-in attempts are temporarily locked out."""

    code = "TOO_MANY_ATTEMPTS"
    http_status = 429


@dataclass
class _Attempts:
    """Failed sign-in attempts for one identity."""

    count: int = 0
    locked_until: float = 0.0


class LoginThrottle:
    """In-memory lockout for repeated failed sign-ins.

    Keyed by email **and** client address together. Keying on email alone would let
    anyone lock a known user out of their own account by failing five times on their
    behalf; keying on address alone would let one shared NAT lock out a whole school.

    In-memory because this is a single-process, self-hosted application. It resets on
    restart, which is an acceptable trade against introducing Redis. If the deployment
    ever grows a second process, this becomes the thing to move — see
    ``docs/DECISIONS.md``.
    """

    def __init__(self, max_attempts: int, lockout_minutes: int) -> None:
        """Configure the throttle.

        Args:
            max_attempts: Failures tolerated before lockout.
            lockout_minutes: How long a lockout lasts.
        """
        self._max = max_attempts
        self._lockout_seconds = lockout_minutes * 60
        self._attempts: dict[tuple[str, str], _Attempts] = {}

    def check(self, email: str, address: str) -> None:
        """Raise if this identity is currently locked out.

        Args:
            email: The email being attempted.
            address: The client address.

        Raises:
            RateLimitedError: If the lockout window has not elapsed.
        """
        record = self._attempts.get((email.lower(), address))
        if record and record.locked_until > time.monotonic():
            raise RateLimitedError(
                "Too many failed sign-in attempts.",
                retry_after_seconds=int(record.locked_until - time.monotonic()),
            )

    def record_failure(self, email: str, address: str) -> None:
        """Count a failed attempt and lock out once the limit is reached.

        Args:
            email: The email that was attempted.
            address: The client address.
        """
        key = (email.lower(), address)
        record = self._attempts.setdefault(key, _Attempts())
        record.count += 1
        if record.count >= self._max:
            record.locked_until = time.monotonic() + self._lockout_seconds
            record.count = 0

    def record_success(self, email: str, address: str) -> None:
        """Clear the failure count after a successful sign-in.

        Args:
            email: The email that signed in.
            address: The client address.
        """
        self._attempts.pop((email.lower(), address), None)


class AuthService:
    """Sign-in, sign-out and session resolution."""

    def __init__(
        self, conn: sqlite3.Connection, throttle: LoginThrottle, session_ttl_hours: int
    ) -> None:
        """Bind the service to a connection.

        Args:
            conn: An open, migrated connection.
            throttle: The shared sign-in throttle.
            session_ttl_hours: How long a new session stays valid.
        """
        self._conn = conn
        self._throttle = throttle
        self._ttl = session_ttl_hours

    def login(
        self, email: str, password: str, *, address: str = "", user_agent: str = ""
    ) -> tuple[str, Principal]:
        """Verify credentials and open a session.

        Args:
            email: The account's sign-in address.
            password: The plaintext password.
            address: Client address, for throttling and the session record.
            user_agent: Client user agent, so the profile page can label sessions.

        Returns:
            ``(raw_token, principal)``. The raw token goes into a cookie and is never
            stored server-side.

        Raises:
            RateLimitedError: If this email and address are locked out.
            AuthenticationError: If the email is unknown or the password is wrong.
            AccountDisabledError: If the account has been deactivated.
        """
        self._throttle.check(email, address)

        row = self._conn.execute(
            "SELECT id, email, password_hash, password_salt, role, full_name, is_active,"
            " locale, theme_preference, must_change_password"
            " FROM users WHERE lower(email) = lower(?)",
            (email.strip(),),
        ).fetchone()

        # Hash even when the user does not exist, so a missing account and a wrong
        # password take the same time. Skipping the work on a miss makes account
        # existence measurable with a stopwatch.
        stored_hash = row["password_hash"] if row else "0" * 128
        stored_salt = row["password_salt"] if row else "00" * 16
        password_ok = verify_password(password, stored_hash, stored_salt)

        if row is None or not password_ok:
            self._throttle.record_failure(email, address)
            # One message for both cases: "no such account" tells an attacker which
            # addresses are worth attacking.
            raise AuthenticationError("Email or password is incorrect.")

        if not row["is_active"]:
            raise AccountDisabledError("This account has been deactivated.")

        self._throttle.record_success(email, address)

        raw_token, token_hash = new_session_token()
        self._conn.execute(
            "INSERT INTO sessions (token_sha256, user_id, expires_at, user_agent, ip_address)"
            " VALUES (?, ?, ?, ?, ?)",
            (token_hash, row["id"], session_expiry(self._ttl), user_agent[:255], address[:64]),
        )
        return raw_token, self._principal_from_row(row)

    def logout(self, raw_token: str) -> None:
        """Close one session.

        Args:
            raw_token: The token from the client's cookie.
        """
        self._conn.execute("DELETE FROM sessions WHERE token_sha256 = ?", (hash_token(raw_token),))

    def logout_everywhere(self, user_id: int, *, keep_token: str | None = None) -> int:
        """Close every session for a user.

        Args:
            user_id: Whose sessions to close.
            keep_token: A session to preserve, normally the caller's own — otherwise
                "sign out my other devices" signs you out too.

        Returns:
            How many sessions were closed.
        """
        if keep_token:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_sha256 != ?",
                (user_id, hash_token(keep_token)),
            )
        else:
            cursor = self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return cursor.rowcount

    def resolve(self, raw_token: str) -> Principal | None:
        """Look up the principal behind a session token.

        Args:
            raw_token: The token from the client's cookie.

        Returns:
            The principal, or ``None`` if the token is unknown, expired, or belongs
            to a deactivated account.
        """
        token_hash = hash_token(raw_token)
        row = self._conn.execute(
            "SELECT u.id, u.email, u.role, u.full_name, u.is_active, u.locale,"
            "       u.theme_preference, u.must_change_password, s.last_seen_at"
            "  FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_sha256 = ? AND s.expires_at > ?",
            (token_hash, utc_now()),
        ).fetchone()

        if row is None or not row["is_active"]:
            # Deactivation takes effect on the next request rather than at the next
            # sign-in, which is the point of storing sessions rather than signing them.
            return None

        # Only when it has gone stale. This ran on every authenticated request,
        # including every GET, and on SQLite a write is a lock and an fsync -- paid
        # per page view to keep a timestamp nobody reads to the second. The device
        # list on the profile page is the only reader, and a minute's resolution is
        # more than it shows.
        if is_stale(row["last_seen_at"], SESSION_TOUCH_SECONDS):
            self._conn.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE token_sha256 = ?",
                (utc_now(), token_hash),
            )
        return self._principal_from_row(row)

    def list_sessions(self, user_id: int) -> list[dict[str, object]]:
        """Return a user's live sessions, most recent first.

        Args:
            user_id: Whose sessions to list.

        Returns:
            One dictionary per session. The token hash is included so the client can
            identify a session to revoke; the raw token is not recoverable from it.
        """
        rows = self._conn.execute(
            "SELECT token_sha256, created_at, last_seen_at, user_agent, ip_address"
            "  FROM sessions WHERE user_id = ? AND expires_at > ?"
            " ORDER BY COALESCE(last_seen_at, created_at) DESC",
            (user_id, utc_now()),
        )
        return [dict(row) for row in rows]

    def revoke_session(self, user_id: int, token_sha256: str) -> bool:
        """Close one specific session belonging to a user.

        Scoped by ``user_id`` so a caller cannot revoke somebody else's session by
        guessing a hash.

        Args:
            user_id: The session's owner.
            token_sha256: Which session to close.

        Returns:
            ``True`` if a session was closed.
        """
        cursor = self._conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_sha256 = ?",
            (user_id, token_sha256),
        )
        return cursor.rowcount > 0

    def change_password(self, user_id: int, current: str, replacement: str) -> None:
        """Change a user's password and close their other sessions.

        Args:
            user_id: Whose password to change.
            current: The existing password, re-verified even though the caller is
                already signed in — an unattended browser must not be enough to take
                an account over permanently.
            replacement: The new password.

        Raises:
            AuthenticationError: If ``current`` is wrong.
            ValidationError: If ``replacement`` is too short or unchanged.
        """
        row = self._conn.execute(
            "SELECT password_hash, password_salt FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None or not verify_password(current, row["password_hash"], row["password_salt"]):
            raise AuthenticationError("Current password is incorrect.")

        if len(replacement) < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
                field="password",
                min_length=MIN_PASSWORD_LENGTH,
            )
        if replacement == current:
            raise ValidationError(
                "New password must differ from the current one.", field="password"
            )

        digest, salt = hash_password(replacement)
        # Clearing the flag here rather than anywhere else: this is the only path
        # by which a password becomes known to one person again.
        self._conn.execute(
            "UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = 0,"
            " updated_at = ? WHERE id = ?",
            (digest, salt, utc_now(), user_id),
        )
        # A password change is how someone responds to a suspected compromise. Leaving
        # the attacker's existing sessions alive would defeat the point.
        self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def update_preferences(
        self,
        user_id: int,
        *,
        locale: str | None = None,
        theme: str | None = None,
        full_name: str | None = None,
        touched: frozenset[str] = frozenset(),
    ) -> None:
        """Update a user's own display preferences.

        Args:
            user_id: Whose preferences to change.
            locale: New language, or ``None`` to follow the organisation default.
            theme: New colour scheme, or ``None`` to follow the default.
            full_name: New display name.
            touched: Which fields the caller actually sent. Only these are written —
                otherwise an omitted field would be indistinguishable from an explicit
                null and silently clear the stored value.
        """
        columns = {"locale": locale, "theme_preference": theme, "full_name": full_name}
        sent = {"locale": "locale", "theme_preference": "theme", "full_name": "full_name"}
        updates = {col: val for col, val in columns.items() if sent[col] in touched}
        if not updates:
            return

        clause = ", ".join(f"{col} = ?" for col in updates)
        self._conn.execute(
            f"UPDATE users SET {clause}, updated_at = ? WHERE id = ?",  # noqa: S608
            (*updates.values(), utc_now(), user_id),
        )

    def reload_principal(self, user_id: int) -> Principal:
        """Re-read a principal after their account changed.

        Args:
            user_id: Whose principal to rebuild.

        Returns:
            The refreshed principal.

        Raises:
            NotAuthenticatedError: If the account has since disappeared.
        """
        row = self._conn.execute(
            "SELECT id, email, role, full_name, is_active, locale, theme_preference,"
            "       must_change_password FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise NotAuthenticatedError("Account no longer exists.")
        return self._principal_from_row(row)

    def purge_expired(self) -> int:
        """Delete expired session rows.

        Returns:
            How many rows were removed.
        """
        return self._conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ?", (utc_now(),)
        ).rowcount

    def _principal_from_row(self, row: sqlite3.Row) -> Principal:
        """Build a principal, resolving the linked student record and preferences.

        Args:
            row: A joined users row.

        Returns:
            The principal for this request.
        """
        role = Role(row["role"])

        student_id: str | None = None
        if role is Role.STUDENT:
            linked = self._conn.execute(
                "SELECT student_id FROM students WHERE user_id = ?", (row["id"],)
            ).fetchone()
            student_id = linked["student_id"] if linked else None

        org = self._conn.execute(
            "SELECT default_locale, default_theme FROM organization WHERE id = 1"
        ).fetchone()

        return Principal(
            user_id=row["id"],
            role=role,
            email=row["email"],
            full_name=row["full_name"],
            student_id=student_id,
            locale=row["locale"] or (org["default_locale"] if org else "en"),
            theme=Theme(row["theme_preference"] or (org["default_theme"] if org else "system")),
            must_change_password=bool(row["must_change_password"]),
        )
