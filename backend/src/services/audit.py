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
    return [
        {
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
        for row in rows
    ]
