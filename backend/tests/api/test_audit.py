"""Reading the audit trail over HTTP, and the guards that keep it append-only.

The feed is admin-only; the grade-scoped history endpoint tested elsewhere stays
available to teachers. The trigger tests at the bottom prove the table cannot be
rewritten even by someone with database access.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import ACCOUNTS


def _user_id(conn: sqlite3.Connection, key: str) -> int:
    """Look up a fixture account's id."""
    row = conn.execute("SELECT id FROM users WHERE email = ?", (ACCOUNTS[key][0],)).fetchone()
    return row["id"]


def seed_entry(
    conn: sqlite3.Connection,
    *,
    actor: str | None,
    entity: str,
    entity_id: str,
    action: str,
    at: str,
    before_json: str | None = None,
    after_json: str | None = None,
) -> int:
    """Insert one entry directly, so each test controls the actor and the timestamp."""
    cursor = conn.execute(
        "INSERT INTO audit_log"
        " (actor_user_id, entity, entity_id, action, before_json, after_json, at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            _user_id(conn, actor) if actor else None,
            entity,
            entity_id,
            action,
            before_json,
            after_json,
            at,
        ),
    )
    return cursor.lastrowid or 0


def seed_variety(conn: sqlite3.Connection) -> None:
    """Entries spanning two actors, three entities, all three verbs and two months."""
    seed_entry(
        conn,
        actor="teacher",
        entity="grade",
        entity_id="1",
        action="create",
        at="2026-01-10T09:00:00Z",
        after_json='{"score": 78}',
    )
    seed_entry(
        conn,
        actor="teacher",
        entity="grade",
        entity_id="1",
        action="update",
        at="2026-01-12T10:30:00Z",
        before_json='{"score": 78}',
        after_json='{"score": 82}',
    )
    seed_entry(
        conn,
        actor="admin",
        entity="student",
        entity_id="S001",
        action="update",
        at="2026-02-01T15:00:00Z",
        before_json='{"cohort": null}',
        after_json='{"cohort": "2026"}',
    )
    seed_entry(
        conn,
        actor="admin",
        entity="course",
        entity_id="CS101",
        action="delete",
        at="2026-02-20T08:00:00Z",
        before_json='{"name": "Intro"}',
    )


# ── Authorization ────────────────────────────────────────────────────────────


def test_a_teacher_cannot_read_either_route(as_teacher: TestClient) -> None:
    """The trail beyond one's own grades is an admin matter."""
    assert as_teacher.get("/audit").status_code == 403
    assert as_teacher.get("/audit/grade/1").status_code == 403


def test_a_student_cannot_read_either_route(as_student: TestClient) -> None:
    """Nor a student."""
    assert as_student.get("/audit").status_code == 403
    assert as_student.get("/audit/grade/1").status_code == 403


# ── The feed ─────────────────────────────────────────────────────────────────


def test_an_admin_gets_a_page(as_admin: TestClient, seeded_db: sqlite3.Connection) -> None:
    """One page envelope, most recent first, with the snapshots already parsed."""
    seed_variety(seeded_db)

    response = as_admin.get("/audit")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 4
    assert body["page"] == 1
    assert body["size"] == 25
    assert body["pages"] == 1

    items = body["items"]
    assert [item["id"] for item in items] == sorted((item["id"] for item in items), reverse=True)
    newest = items[0]
    assert newest["entity"] == "course"
    assert newest["entity_id"] == "CS101"
    assert newest["action"] == "delete"
    assert newest["at"] == "2026-02-20T08:00:00Z"
    assert newest["actor_name"] == "Admin"
    assert newest["before"] == {"name": "Intro"}
    assert newest["after"] is None


def test_the_actor_filter_narrows_to_one_account(
    as_admin: TestClient, seeded_db: sqlite3.Connection
) -> None:
    seed_variety(seeded_db)
    admin_id = _user_id(seeded_db, "admin")

    body = as_admin.get("/audit", params={"actor_user_id": admin_id}).json()
    assert body["total"] == 2
    assert {item["entity"] for item in body["items"]} == {"student", "course"}


def test_the_entity_filter_narrows_to_one_kind(
    as_admin: TestClient, seeded_db: sqlite3.Connection
) -> None:
    seed_variety(seeded_db)

    body = as_admin.get("/audit", params={"entity": "grade"}).json()
    assert body["total"] == 2
    assert {item["action"] for item in body["items"]} == {"create", "update"}


def test_the_action_filter_narrows_to_one_verb(
    as_admin: TestClient, seeded_db: sqlite3.Connection
) -> None:
    seed_variety(seeded_db)

    body = as_admin.get("/audit", params={"action": "update"}).json()
    assert body["total"] == 2
    assert {item["entity"] for item in body["items"]} == {"grade", "student"}


def test_an_unknown_action_is_a_validation_error(as_admin: TestClient) -> None:
    """The table's CHECK only permits the three verbs; ask for anything else and fail."""
    response = as_admin.get("/audit", params={"action": "export"})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_the_date_range_filter_is_inclusive_at_both_ends(
    as_admin: TestClient, seeded_db: sqlite3.Connection
) -> None:
    """The end date is a day, not an instant: an entry at 15:00 still falls within it."""
    seed_variety(seeded_db)

    body = as_admin.get(
        "/audit", params={"date_from": "2026-01-11", "date_to": "2026-02-01"}
    ).json()
    assert body["total"] == 2
    assert {item["at"] for item in body["items"]} == {
        "2026-01-12T10:30:00Z",
        "2026-02-01T15:00:00Z",
    }


def test_paging_is_correct_at_a_page_boundary(
    as_admin: TestClient, seeded_db: sqlite3.Connection
) -> None:
    """Adjacent pages join into the full ordered list, with nothing lost or repeated."""
    for index in range(5):
        seed_entry(
            seeded_db,
            actor="admin",
            entity="grade",
            entity_id=str(index + 1),
            action="create",
            at=f"2026-03-0{index + 1}T12:00:00Z",
            after_json='{"score": 50}',
        )

    first = as_admin.get("/audit", params={"size": 2, "page": 1}).json()
    second = as_admin.get("/audit", params={"size": 2, "page": 2}).json()
    third = as_admin.get("/audit", params={"size": 2, "page": 3}).json()

    assert first["total"] == 5
    assert first["pages"] == 3
    assert [len(first["items"]), len(second["items"]), len(third["items"])] == [2, 2, 1]

    ids = [item["id"] for page in (first, second, third) for item in page["items"]]
    assert len(ids) == len(set(ids)) == 5
    assert ids == sorted(ids, reverse=True)
    # The boundary itself: page two picks up exactly where page one left off.
    assert first["items"][-1]["at"] == "2026-03-04T12:00:00Z"
    assert second["items"][0]["at"] == "2026-03-03T12:00:00Z"


# ── The entity door ──────────────────────────────────────────────────────────


def test_the_entity_route_returns_only_that_entitys_trail(
    as_admin: TestClient, seeded_db: sqlite3.Connection
) -> None:
    """The admin door to one entity's trail — the grade-scoped door serves teachers."""
    seed_variety(seeded_db)

    response = as_admin.get("/audit/grade/1")
    assert response.status_code == 200, response.text
    items = response.json()
    assert [item["action"] for item in items] == ["update", "create"]
    assert items[0]["before"] == {"score": 78}
    assert items[0]["after"] == {"score": 82}


# ── The append-only guarantee ────────────────────────────────────────────────


def test_the_triggers_abort_an_update_and_a_delete(seeded_db: sqlite3.Connection) -> None:
    """The immutability is a database property, not a convention in the code."""
    entry_id = seed_entry(
        seeded_db,
        actor="teacher",
        entity="grade",
        entity_id="1",
        action="create",
        at="2026-01-10T09:00:00Z",
        after_json='{"score": 78}',
    )

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        seeded_db.execute("UPDATE audit_log SET action = 'delete' WHERE id = ?", (entry_id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        seeded_db.execute("DELETE FROM audit_log WHERE id = ?", (entry_id,))

    row = seeded_db.execute("SELECT action FROM audit_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["action"] == "create"
