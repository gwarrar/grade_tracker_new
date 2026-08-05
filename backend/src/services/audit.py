"""The audit trail.

A grade system must be able to answer "who changed this mark, when, and from what".
That question arrives months later, during a dispute, when the current row alone
cannot answer it.

Every write goes through here, inside the same transaction as the change itself, so
a committed change always has its audit entry and a rolled-back one leaves none.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from notenverwaltung.exceptions import ValidationError
from notenverwaltung.storage.queries import Page, SortSpec, paginate
from notenverwaltung.storage.scope import ALLOW_ALL, Scope

_ACTIONS = ("create", "update", "delete")
"""The only verbs the table's CHECK permits.

Deliberately not widened to login/export/view verbs: SQLite cannot alter a CHECK, so
adding one means a table rebuild, and sign-ins are already recorded structurally in
``sessions``.
"""

_REDACTED_KEYS = {"password", "password_hash", "password_salt", "token", "api_key", "secret"}
"""Never written to the audit log.

The trail records *that* a credential changed, never its value. An append-only table
nobody prunes is the worst possible place for a secret to land.
"""


def _clean(payload: dict[str, Any] | None) -> str | None:
    """Serialise a snapshot, dropping anything sensitive.

    Args:
        payload: The entity state, or ``None``.

    Returns:
        Compact JSON with sensitive keys replaced, or ``None``.
    """
    if payload is None:
        return None
    safe = {
        key: ("<redacted>" if key.lower() in _REDACTED_KEYS else value)
        for key, value in payload.items()
    }
    return json.dumps(safe, ensure_ascii=False, sort_keys=True, default=str)


def record(
    conn: sqlite3.Connection,
    *,
    actor_user_id: int | None,
    entity: str,
    entity_id: str,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Append one entry to the audit trail.

    Call inside the same transaction as the change being recorded.

    Args:
        conn: The connection running the change.
        actor_user_id: Who made the change, or ``None`` for a system action.
        entity: What kind of thing changed, e.g. ``"grade"``.
        entity_id: Which one.
        action: ``"create"``, ``"update"`` or ``"delete"``.
        before: State prior to the change, for updates and deletes.
        after: State after the change, for creates and updates.
    """
    conn.execute(
        "INSERT INTO audit_log (actor_user_id, entity, entity_id, action, before_json, after_json)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (actor_user_id, entity, entity_id, action, _clean(before), _clean(after)),
    )


def _shape(row: sqlite3.Row) -> dict[str, Any]:
    """Shape one audit row, parsing the JSON snapshots.

    The single place the snapshots are parsed, shared by :func:`history` and
    :func:`feed`.

    Args:
        row: A row carrying ``id``, ``action``, ``at``, ``actor_user_id``,
            ``actor_name``, ``before_json`` and ``after_json``.

    Returns:
        One entry, with ``before`` and ``after`` already parsed.
    """
    return {
        "id": row["id"],
        "action": row["action"],
        "at": row["at"],
        "actor_user_id": row["actor_user_id"],
        # The account may have been deleted since; the entry survives it, which
        # is the point of an append-only trail.
        "actor_name": row["actor_name"],
        "before": json.loads(row["before_json"]) if row["before_json"] else None,
        "after": json.loads(row["after_json"]) if row["after_json"] else None,
    }


def history(
    conn: sqlite3.Connection, entity: str, entity_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    """Return an entity's change history, most recent first.

    Args:
        conn: The connection to query.
        entity: What kind of thing to look up.
        entity_id: Which one.
        limit: How many entries to return.

    Returns:
        One dictionary per change, with ``before`` and ``after`` already parsed.
    """
    rows = conn.execute(
        "SELECT a.id, a.action, a.before_json, a.after_json, a.at,"
        "       a.actor_user_id, u.full_name AS actor_name"
        "  FROM audit_log a LEFT JOIN users u ON u.id = a.actor_user_id"
        " WHERE a.entity = ? AND a.entity_id = ?"
        " ORDER BY a.at DESC, a.id DESC LIMIT ?",
        (entity, entity_id, limit),
    )
    return [_shape(row) for row in rows]


def feed(
    conn: sqlite3.Connection,
    *,
    actor_user_id: int | None = None,
    entity: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    size: int = 25,
) -> Page[dict[str, Any]]:
    """Return the institution-wide activity feed, most recent first.

    Unlike every other list query this one takes no principal: the whole table is
    admin-only, so there is no row dimension for a scope to express. The gate is the
    role check on the route, not a filter in the query.

    Args:
        conn: The connection to query.
        actor_user_id: Only changes made by this account.
        entity: Only this kind of thing, e.g. ``"grade"``.
        action: Only ``"create"``, ``"update"`` or ``"delete"``.
        date_from: Earliest day, ISO ``YYYY-MM-DD``, inclusive.
        date_to: Latest day, ISO ``YYYY-MM-DD``, inclusive.
        page: 1-based page number.
        size: Rows per page.

    Returns:
        One page of entry dictionaries, each additionally carrying ``entity`` and
        ``entity_id``.

    Raises:
        ValidationError: If ``action`` is not one of the three recorded verbs.
    """
    if action is not None and action not in _ACTIONS:
        raise ValidationError(
            f"Unknown audit action {action!r}.", field="action", allowed=list(_ACTIONS)
        )

    extra = ALLOW_ALL
    if actor_user_id is not None:
        extra = extra & Scope("a.actor_user_id = ?", (actor_user_id,))
    if entity is not None:
        extra = extra & Scope("a.entity = ?", (entity,))
    if action is not None:
        extra = extra & Scope("a.action = ?", (action,))
    # ISO-8601 timestamps compare correctly as text. The end date is a day, while
    # ``at`` carries a time, so it is extended to the last second of that day —
    # an entry made at 15:00 on the final day is still within it.
    if date_from:
        extra = extra & Scope("a.at >= ?", (date_from,))
    if date_to:
        extra = extra & Scope("a.at <= ? || 'T23:59:59Z'", (date_to,))

    rows, total = paginate(
        conn,
        select=(
            "a.id, a.entity, a.entity_id, a.action, a.before_json, a.after_json, a.at,"
            " a.actor_user_id, u.full_name AS actor_name"
        ),
        from_clause="audit_log a LEFT JOIN users u ON u.id = a.actor_user_id",
        # The whole table is admin-only — see the docstring. ALLOW_ALL is deliberate
        # here; in any other list query it would be the bug DENY_ALL exists to prevent.
        scope=ALLOW_ALL,
        # The id tie-break keeps rows sharing a second in a stable order, so a page
        # boundary can never split them.
        sort=SortSpec(column="a.at DESC, a.id", descending=True),
        page=page,
        size=size,
        extra=extra,
    )
    items = [
        {**_shape(row), "entity": row["entity"], "entity_id": row["entity_id"]} for row in rows
    ]
    return Page(items=items, total=total, page=page, size=size)
