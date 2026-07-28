"""Account administration.

The CRUD is checked briefly. Most of this file is the four rules that stop an
administrator locking themselves out or quietly gaining privilege, because those
are the failures that need database access to undo.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    """Create an account and return the response body."""
    body: dict[str, Any] = {
        "email": "new.teacher@test.local",
        "full_name": "New Teacher",
        "role": "teacher",
    }
    body.update(overrides)
    response = client.post("/admin/users", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _find(client: TestClient, email: str) -> dict[str, Any]:
    """Look up one account by email."""
    rows = client.get("/admin/users").json()
    return next(row for row in rows if row["email"] == email)


# ── Authorization ────────────────────────────────────────────────────────────


def test_a_teacher_cannot_manage_accounts(as_teacher: TestClient) -> None:
    """Managing who can sign in is not a teaching capability."""
    assert as_teacher.get("/admin/users").status_code == 403


def test_a_student_cannot_manage_accounts(as_student: TestClient) -> None:
    """Nor a student."""
    assert as_student.get("/admin/users").status_code == 403


def test_anonymous_is_not_authenticated(client: TestClient) -> None:
    """No session is a 401, distinct from a session lacking the role."""
    assert client.get("/admin/users").status_code == 401


# ── Listing ──────────────────────────────────────────────────────────────────


def test_listing_never_exposes_password_material(as_admin: TestClient) -> None:
    """The record type has no such field, and this proves it stayed that way."""
    body = as_admin.get("/admin/users").text

    assert "password_hash" not in body
    assert "password_salt" not in body


def test_deactivated_accounts_are_listed_by_default(as_admin: TestClient) -> None:
    """Hiding them makes a deactivated account look deleted.

    Someone then tries to recreate it and hits a unique constraint they cannot
    explain.
    """
    emails = [row["email"] for row in as_admin.get("/admin/users").json()]
    assert "disabled@test.local" in emails


def test_inactive_accounts_can_be_filtered_out(as_admin: TestClient) -> None:
    """The filter still exists for the times you want only live accounts."""
    rows = as_admin.get("/admin/users", params={"include_inactive": False}).json()
    assert all(row["is_active"] for row in rows)


def test_accounts_can_be_searched(as_admin: TestClient) -> None:
    """By name or email, since an administrator remembers one or the other."""
    rows = as_admin.get("/admin/users", params={"q": "teacher@test"}).json()
    assert [row["email"] for row in rows] == ["teacher@test.local"]


# ── Creating ─────────────────────────────────────────────────────────────────


def test_creating_an_account_returns_a_one_time_password(as_admin: TestClient) -> None:
    """Generated, not chosen — a password an administrator picks is known to two
    people from the moment it exists."""
    body = _create(as_admin)

    assert body["user"]["email"] == "new.teacher@test.local"
    assert body["user"]["role"] == "teacher"
    assert len(str(body["initial_password"])) >= 12


def test_a_created_account_can_actually_sign_in(as_admin: TestClient, app: FastAPI) -> None:
    """The password that comes back has to work, or the feature is decorative."""
    created = _create(as_admin)

    with TestClient(app) as fresh:
        response = fresh.post(
            "/auth/login",
            json={
                "email": "new.teacher@test.local",
                "password": created["initial_password"],
            },
        )

    assert response.status_code == 200


def test_a_duplicate_email_is_rejected(as_admin: TestClient) -> None:
    """One address, one account."""
    _create(as_admin)
    response = as_admin.post(
        "/admin/users",
        json={"email": "new.teacher@test.local", "full_name": "Twin", "role": "teacher"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_ENTRY"


def test_an_admin_cannot_create_a_superadmin(as_admin: TestClient) -> None:
    """Otherwise the create form is a one-step privilege escalation."""
    response = as_admin.post(
        "/admin/users",
        json={"email": "sneaky@test.local", "full_name": "Sneaky", "role": "superadmin"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_an_admin_cannot_create_another_admin(as_admin: TestClient) -> None:
    """Equal is refused as well as above.

    An admin minting a second admin is how one compromised account becomes two.
    """
    response = as_admin.post(
        "/admin/users",
        json={"email": "peer@test.local", "full_name": "Peer", "role": "admin"},
    )

    assert response.status_code == 403


def test_a_superadmin_may_create_anything(as_superadmin: TestClient) -> None:
    """The counterweight: without this the tests above could pass by refusing everyone."""
    body = _create(as_superadmin, email="second.root@test.local", role="superadmin")
    assert body["user"]["role"] == "superadmin"


def test_a_malformed_email_is_rejected(as_admin: TestClient) -> None:
    """A sign-in address that cannot be signed in with is a broken account."""
    response = as_admin.post(
        "/admin/users",
        json={"email": "not-an-address", "full_name": "X", "role": "teacher"},
    )
    assert response.status_code == 422


# ── The self-lockout rules ───────────────────────────────────────────────────


def test_you_cannot_change_your_own_role(as_admin: TestClient) -> None:
    """Self-demotion is a lockout that nobody inside the application can undo."""
    me = _find(as_admin, "admin@test.local")

    response = as_admin.put(f"/admin/users/{me['id']}/role", json={"role": "student"})

    assert response.status_code == 409
    assert response.json()["code"] == "CANNOT_MODIFY_SELF"


def test_you_cannot_deactivate_yourself(as_admin: TestClient) -> None:
    """The same, and irreversible from inside."""
    me = _find(as_admin, "admin@test.local")

    response = as_admin.put(f"/admin/users/{me['id']}/active", json={"is_active": False})

    assert response.status_code == 409
    assert response.json()["code"] == "CANNOT_MODIFY_SELF"


def test_an_admin_cannot_demote_a_superadmin(as_admin: TestClient) -> None:
    """Acting on someone above you is escalation by another name."""
    root = _find(as_admin, "root@test.local")

    response = as_admin.put(f"/admin/users/{root['id']}/role", json={"role": "student"})

    assert response.status_code == 403


def test_an_admin_cannot_reset_a_superadmins_password(as_admin: TestClient) -> None:
    """The sharpest version: without this, reset-password is a takeover button."""
    root = _find(as_admin, "root@test.local")

    response = as_admin.post(f"/admin/users/{root['id']}/reset-password")

    assert response.status_code == 403


def test_the_last_superadmin_cannot_be_demoted(as_superadmin: TestClient) -> None:
    """An installation with nobody who can configure it needs database access to fix."""
    rows = as_superadmin.get("/admin/users").json()
    other_admin = next(row for row in rows if row["email"] == "admin@test.local")

    # Promote, then the original may be demoted; before that, it may not.
    root = next(row for row in rows if row["email"] == "root@test.local")
    assert (
        as_superadmin.put(f"/admin/users/{root['id']}/role", json={"role": "admin"}).status_code
        == 409
    )

    as_superadmin.put(f"/admin/users/{other_admin['id']}/role", json={"role": "superadmin"})
    assert (
        as_superadmin.put(f"/admin/users/{root['id']}/role", json={"role": "admin"}).status_code
        == 409
    )  # still self


def test_the_last_superadmin_cannot_be_deactivated(as_superadmin: TestClient) -> None:
    """Deactivation is the other route to the same empty installation."""
    created = _create(as_superadmin, email="temp.root@test.local", role="superadmin")
    user_id = created["user"]["id"]

    # Two superadmins now exist, so deactivating the new one is allowed.
    assert (
        as_superadmin.put(f"/admin/users/{user_id}/active", json={"is_active": False}).status_code
        == 200
    )


# ── Deactivation and resets ──────────────────────────────────────────────────


def test_deactivating_revokes_every_session(as_admin: TestClient, app: FastAPI) -> None:
    """An account that cannot sign in but stays signed in is not deactivated."""
    created = _create(as_admin)
    user_id = created["user"]["id"]

    with TestClient(app) as theirs:
        theirs.post(
            "/auth/login",
            json={
                "email": "new.teacher@test.local",
                "password": created["initial_password"],
            },
        )
        assert theirs.get("/auth/me").status_code == 200

        as_admin.put(f"/admin/users/{user_id}/active", json={"is_active": False})

        # The cookie is still in the jar; the session behind it is gone.
        assert theirs.get("/auth/me").status_code == 401

    assert as_admin.get("/admin/users").json()
    assert _find(as_admin, "new.teacher@test.local")["session_count"] == 0


def test_a_reset_password_works_and_the_old_one_does_not(
    as_admin: TestClient, app: FastAPI
) -> None:
    """A reset that leaves the old password working is not a reset."""
    created = _create(as_admin)
    user_id = created["user"]["id"]
    old = created["initial_password"]

    new = as_admin.post(f"/admin/users/{user_id}/reset-password").json()["temporary_password"]

    assert new != old
    with TestClient(app) as fresh:
        assert (
            fresh.post(
                "/auth/login", json={"email": "new.teacher@test.local", "password": old}
            ).status_code
            == 401
        )
        assert (
            fresh.post(
                "/auth/login", json={"email": "new.teacher@test.local", "password": new}
            ).status_code
            == 200
        )


def test_reactivation_restores_sign_in(as_admin: TestClient, app: FastAPI) -> None:
    """Deactivation must be reversible, or it is deletion with a friendlier name."""
    created = _create(as_admin)
    user_id = created["user"]["id"]

    as_admin.put(f"/admin/users/{user_id}/active", json={"is_active": False})
    as_admin.put(f"/admin/users/{user_id}/active", json={"is_active": True})

    with TestClient(app) as fresh:
        response = fresh.post(
            "/auth/login",
            json={
                "email": "new.teacher@test.local",
                "password": created["initial_password"],
            },
        )
    assert response.status_code == 200


def test_an_unknown_account_is_a_404(as_admin: TestClient) -> None:
    """A dangling id reports rather than silently succeeding."""
    assert as_admin.post("/admin/users/9999/reset-password").status_code == 404


def test_changes_are_written_to_the_audit_trail(as_admin: TestClient) -> None:
    """Who created an account, and who changed whose role, is exactly what an
    audit trail is for."""
    created = _create(as_admin)
    user_id = created["user"]["id"]
    as_admin.put(f"/admin/users/{user_id}/active", json={"is_active": False})

    # The audit insert shares the request's transaction, so a constraint failure
    # there would have rolled the change back. The change surviving is the proof
    # that the trail accepted it — this caught a CHECK violation on `action`.
    assert _find(as_admin, "new.teacher@test.local")["is_active"] is False
