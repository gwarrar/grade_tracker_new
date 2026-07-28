"""Admin-editable UI translations.

The shipped translations live in ``web/messages/*.json`` — the frontend owns the
wording, which is why the backend has no message catalogue. This module handles the
one thing the frontend cannot: **per-organisation overrides**.

The need is real rather than decorative. Institutions rename *Student* to *Pupil*,
*Trainee* or *Auszubildende*, and *Course* to *Module* or *Modul*. Shipping a code
change for each one is absurd; so is forking the translation files.

An override is stored by key and merged over the shipped value at read time. The
frontend still renders every string — it just fetches the merged map instead of
importing the file directly.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from notenverwaltung.exceptions import ForbiddenError, ValidationError
from notenverwaltung.models import SUPPORTED_LOCALES
from services.audit import record
from services.scoping import Principal
from services.security import utc_now

_KEY_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)*$")
"""Dotted lower-case path, e.g. ``nav.students``.

Constrained so the key space stays a namespace rather than free text. Without it the
override table accumulates typos that look like real keys and never match anything.
"""

MAX_VALUE_LENGTH = 500
"""A UI label, not an essay. Also caps what one row can cost the public endpoint."""


def _check_locale(locale: str) -> str:
    """Validate a locale tag.

    Args:
        locale: The requested language.

    Returns:
        The locale unchanged.

    Raises:
        ValidationError: If no translation file ships for it.
    """
    if locale not in SUPPORTED_LOCALES:
        raise ValidationError(
            f"No translation ships for {locale!r}.",
            field="locale",
            supported=list(SUPPORTED_LOCALES),
        )
    return locale


class LocalizationService:
    """Reads and edits per-organisation string overrides."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Bind the service to a connection.

        Args:
            conn: The request's connection.
        """
        self._conn = conn

    def overrides(self, locale: str) -> dict[str, str]:
        """Return every override for a locale.

        Public: the sign-in page needs its labels before anyone has signed in.

        Args:
            locale: Which language.

        Returns:
            Dotted key to replacement text. Empty when nothing is overridden, which
            is the normal case — the frontend then uses its shipped values unchanged.

        Raises:
            ValidationError: If the locale is not supported.
        """
        _check_locale(locale)
        rows = self._conn.execute(
            "SELECT key, value FROM i18n_overrides WHERE locale = ? ORDER BY key", (locale,)
        )
        return {row["key"]: row["value"] for row in rows}

    def all_overrides(self) -> dict[str, dict[str, str]]:
        """Return overrides for every supported locale.

        Returns:
            Locale to its override map, including locales with none, so the admin
            page can render a complete grid rather than inferring absence.
        """
        result: dict[str, dict[str, str]] = {locale: {} for locale in SUPPORTED_LOCALES}
        for row in self._conn.execute("SELECT locale, key, value FROM i18n_overrides"):
            if row["locale"] in result:
                result[row["locale"]][row["key"]] = row["value"]
        return result

    def set_override(
        self, principal: Principal, locale: str, key: str, value: str
    ) -> dict[str, Any]:
        """Create or replace one override.

        Args:
            principal: The authenticated caller.
            locale: Which language.
            key: Dotted message key, e.g. ``nav.students``.
            value: The replacement text.

        Returns:
            The stored override.

        Raises:
            ForbiddenError: If the caller is not an administrator.
            ValidationError: If the locale, key or value is invalid.
        """
        self._assert_admin(principal)
        _check_locale(locale)

        key = key.strip()
        value = value.strip()

        if not _KEY_RE.match(key):
            raise ValidationError(
                "A message key must be a dotted lower-case path, e.g. 'nav.students'.",
                field="key",
                value=key,
            )
        if not value:
            # Deleting is a separate, explicit operation. An empty override would
            # render as a blank label and read as a broken page.
            raise ValidationError(
                "An override cannot be empty. Delete it to restore the shipped text.",
                field="value",
            )
        if len(value) > MAX_VALUE_LENGTH:
            raise ValidationError(
                f"An override may be at most {MAX_VALUE_LENGTH} characters.",
                field="value",
                max_length=MAX_VALUE_LENGTH,
            )

        before = self._conn.execute(
            "SELECT value FROM i18n_overrides WHERE locale = ? AND key = ?", (locale, key)
        ).fetchone()

        # Two statements rather than INSERT OR REPLACE, which is SQLite-specific and
        # banned by the portability rules in docs/DECISIONS.md.
        if before is None:
            self._conn.execute(
                "INSERT INTO i18n_overrides (locale, key, value, updated_by, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (locale, key, value, principal.user_id, utc_now()),
            )
        else:
            self._conn.execute(
                "UPDATE i18n_overrides SET value = ?, updated_by = ?, updated_at = ?"
                " WHERE locale = ? AND key = ?",
                (value, principal.user_id, utc_now(), locale, key),
            )

        record(
            self._conn,
            actor_user_id=principal.user_id,
            entity="i18n_override",
            entity_id=f"{locale}:{key}",
            action="create" if before is None else "update",
            before={"value": before["value"]} if before else None,
            after={"value": value},
        )
        return {"locale": locale, "key": key, "value": value}

    def delete_override(self, principal: Principal, locale: str, key: str) -> None:
        """Remove an override, restoring the shipped text.

        Args:
            principal: The authenticated caller.
            locale: Which language.
            key: Which message key.

        Raises:
            ForbiddenError: If the caller is not an administrator.
            ValidationError: If the locale is unsupported or no such override exists.
        """
        self._assert_admin(principal)
        _check_locale(locale)

        before = self._conn.execute(
            "SELECT value FROM i18n_overrides WHERE locale = ? AND key = ?", (locale, key)
        ).fetchone()
        if before is None:
            error = ValidationError(f"No override for {key!r} in {locale!r}.", field="key")
            error.code = "OVERRIDE_NOT_FOUND"
            error.http_status = 404
            raise error

        self._conn.execute("DELETE FROM i18n_overrides WHERE locale = ? AND key = ?", (locale, key))
        record(
            self._conn,
            actor_user_id=principal.user_id,
            entity="i18n_override",
            entity_id=f"{locale}:{key}",
            action="delete",
            before={"value": before["value"]},
        )

    @staticmethod
    def _assert_admin(principal: Principal) -> None:
        """Raise unless the caller may edit translations.

        Args:
            principal: The authenticated caller.

        Raises:
            ForbiddenError: If they are not an administrator.
        """
        if not principal.is_admin:
            raise ForbiddenError(
                "Editing translations requires an administrator.",
                actual_role=str(principal.role),
            )
