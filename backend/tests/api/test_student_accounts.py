"""Student sign-in accounts: provisioning, linking, and the forced first change.

The bug these guard against is quiet rather than loud. An account created without
being attached to a student record signs in perfectly well and then shows an empty
application — with no `student_id` on the principal, `student_scope` matches zero
rows, so every list is legitimately empty and nothing looks broken. It is only
visible end to end, which is why most of this file signs the new account in.
"""

from __future__ import annotations

import io
import json
from typing import Any

from fastapi.testclient import TestClient

STUDENTS_MAPPING = {
    "student_id": "student_id",
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
}


def _new_student(client: TestClient, **overrides: Any) -> dict[str, Any]:
    """Create a student and return the response body."""
    body: dict[str, Any] = {
        "student_id": "S900",
        "first_name": "Nadia",
        "last_name": "Haddad",
        "email": "nadia.haddad@students.test",
    }
    body.update(overrides)
    response = client.post("/students", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _sign_in(app: Any, email: str, password: str) -> TestClient:
    """Open a session for one set of credentials."""
    client = TestClient(app)
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return client


# ── Provisioning ─────────────────────────────────────────────────────────────


def test_a_new_student_gets_an_account_by_default(as_admin: TestClient) -> None:
    """The register and the login are created together, or the second never happens."""
    created = _new_student(as_admin)

    assert created["initial_password"]
    assert created["user_id"] is not None


def test_the_account_is_attached_to_the_record(as_admin: TestClient) -> None:
    """The link is the whole point: without it the account sees nothing."""
    created = _new_student(as_admin)

    account = next(
        row for row in as_admin.get("/admin/users").json() if row["id"] == created["user_id"]
    )
    assert account["student_id"] == "S900"
    assert account["role"] == "student"


def test_the_new_account_can_sign_in_and_sees_its_own_record(
    app: Any, as_admin: TestClient
) -> None:
    """End to end, because every layer of this passed while the feature did not."""
    created = _new_student(as_admin)

    student = _sign_in(app, "nadia.haddad@students.test", created["initial_password"])
    me = student.get("/auth/me").json()
    assert me["student_id"] == "S900"
    # The generated password reaches the account and no further: everything except
    # reading your own identity, changing it and leaving is refused until it is
    # replaced. Provisioning hands out a credential with two owners, and this is
    # the window in which that is true.
    assert me["must_change_password"] is True
    assert student.get("/students").status_code == 403

    student.post(
        "/profile/password",
        json={"current_password": created["initial_password"], "new_password": "her-own-2026"},
    )
    # Changing it closes every session, so the record is read through a new one.
    student = _sign_in(app, "nadia.haddad@students.test", "her-own-2026")

    visible = student.get("/students").json()
    assert [row["student_id"] for row in visible["items"]] == ["S900"]


def test_a_record_can_be_created_without_an_account(as_admin: TestClient) -> None:
    """An archive of past cohorts should not become live credentials."""
    created = _new_student(as_admin, create_account=False)

    assert created["initial_password"] is None
    assert created["user_id"] is None


def test_the_password_is_never_retrievable_afterwards(as_admin: TestClient) -> None:
    """Shown once. Anything else means it is stored somewhere readable."""
    created = _new_student(as_admin)
    password = created["initial_password"]

    assert password not in as_admin.get("/students/S900").text
    assert password not in as_admin.get("/admin/users").text
    assert password not in as_admin.get("/admin/audit").text


# ── The forced first change ──────────────────────────────────────────────────


def test_a_generated_password_must_be_changed(app: Any, as_admin: TestClient) -> None:
    """Until it is replaced, two people know it, so the account is shared."""
    created = _new_student(as_admin)

    student = _sign_in(app, "nadia.haddad@students.test", created["initial_password"])
    assert student.get("/auth/me").json()["must_change_password"] is True


def test_changing_the_password_clears_the_flag(app: Any, as_admin: TestClient) -> None:
    """The one path by which a password becomes known to one person again."""
    created = _new_student(as_admin)
    initial = created["initial_password"]

    student = _sign_in(app, "nadia.haddad@students.test", initial)
    changed = student.post(
        "/profile/password",
        json={"current_password": initial, "new_password": "a-much-better-secret"},
    )
    assert changed.status_code == 200, changed.text

    # The change closes every session, so this proves the flag against a fresh one.
    again = _sign_in(app, "nadia.haddad@students.test", "a-much-better-secret")
    assert again.get("/auth/me").json()["must_change_password"] is False


def test_an_administrative_reset_raises_the_flag_again(app: Any, as_admin: TestClient) -> None:
    """A reset hands the password to a second person, exactly as creation did."""
    created = _new_student(as_admin)
    initial = created["initial_password"]

    student = _sign_in(app, "nadia.haddad@students.test", initial)
    student.post(
        "/profile/password",
        json={"current_password": initial, "new_password": "a-much-better-secret"},
    )

    reset = as_admin.post(f"/admin/users/{created['user_id']}/reset-password")
    assert reset.status_code == 200, reset.text

    after = _sign_in(app, "nadia.haddad@students.test", reset.json()["temporary_password"])
    assert after.get("/auth/me").json()["must_change_password"] is True


# ── Accounts made the other way round ────────────────────────────────────────


def test_an_account_created_by_hand_claims_its_student_record(as_admin: TestClient) -> None:
    """The path that produced the original report: a record already existed, an
    administrator created the account from the accounts page, and nothing joined
    them. The address is the join."""
    _new_student(as_admin, create_account=False)

    response = as_admin.post(
        "/admin/users",
        json={
            "email": "nadia.haddad@students.test",
            "full_name": "Nadia Haddad",
            "role": "student",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["user"]["student_id"] == "S900"


def test_an_account_never_steals_an_existing_link(as_admin: TestClient) -> None:
    """Only unlinked records are claimed, so a second account at the same address
    cannot take another account's visibility."""
    created = _new_student(as_admin)

    second = as_admin.post(
        "/admin/users",
        json={
            "email": "nadia.haddad@students.test",
            "full_name": "Impostor",
            "role": "student",
        },
    )
    # The address is unique, so this is refused outright — and even if the address
    # were reused, the record is already linked and would not be reassigned.
    assert second.status_code == 409
    account = next(
        row for row in as_admin.get("/admin/users").json() if row["id"] == created["user_id"]
    )
    assert account["student_id"] == "S900"


# ── Finding them again ───────────────────────────────────────────────────────


def test_accounts_can_be_filtered_to_one_role(as_admin: TestClient) -> None:
    """A cohort import mints hundreds of student accounts; without this the staff
    accounts an administrator came to manage are buried."""
    _new_student(as_admin)

    students = as_admin.get("/admin/users", params={"role": "student"}).json()
    assert students
    assert {row["role"] for row in students} == {"student"}

    everyone = as_admin.get("/admin/users").json()
    assert len(everyone) > len(students)


# ── Import ───────────────────────────────────────────────────────────────────


def test_an_import_returns_one_credential_per_student(as_admin: TestClient) -> None:
    """Four hundred students imported with no way in is four hundred accounts
    somebody makes by hand."""
    content = (
        b"student_id,first_name,last_name,email\n"
        b"S901,Ines,Rossi,ines.rossi@students.test\n"
        b"S902,Omar,Nasri,omar.nasri@students.test\n"
    )
    response = as_admin.post(
        "/import/students",
        files={"file": ("students.csv", io.BytesIO(content), "text/csv")},
        data={"mapping": json.dumps(STUDENTS_MAPPING)},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["imported"] == 2
    assert [row["student_id"] for row in body["credentials"]] == ["S901", "S902"]
    assert all(row["initial_password"] for row in body["credentials"])

    linked = as_admin.get("/admin/users", params={"role": "student"}).json()
    assert {"S901", "S902"} <= {row["student_id"] for row in linked}


def test_an_import_can_decline_to_create_accounts(as_admin: TestClient) -> None:
    """Same opt-out as the form, for the same reason."""
    content = b"student_id,first_name,last_name,email\nS903,Pia,Berg,pia.berg@students.test\n"
    response = as_admin.post(
        "/import/students",
        files={"file": ("students.csv", io.BytesIO(content), "text/csv")},
        data={"mapping": json.dumps(STUDENTS_MAPPING), "create_accounts": "false"},
    )
    assert response.status_code == 200, response.text

    assert response.json()["credentials"] == []
    assert as_admin.get("/students/S903").json()["user_id"] is None
