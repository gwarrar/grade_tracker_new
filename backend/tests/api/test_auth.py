"""Sign-in, sessions and the profile endpoints."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from api.deps import SESSION_COOKIE
from tests.api.conftest import ACCOUNTS, PASSWORD, sign_in


class TestLogin:
    def test_valid_credentials_open_a_session(self, client: TestClient) -> None:
        response = client.post(
            "/auth/login", json={"email": "admin@test.local", "password": PASSWORD}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "admin@test.local"
        assert body["role"] == "admin"
        assert SESSION_COOKIE in response.cookies

    def test_the_cookie_is_httponly_and_samesite(self, client: TestClient) -> None:
        """HttpOnly turns an XSS from 'session stolen' into 'session not stolen';
        SameSite blocks the cookie on cross-site POSTs, which is CSRF protection
        without a token dance."""
        response = client.post(
            "/auth/login", json={"email": "admin@test.local", "password": PASSWORD}
        )
        header = response.headers["set-cookie"].lower()
        assert "httponly" in header
        assert "samesite=lax" in header

    def test_wrong_password_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/auth/login", json={"email": "admin@test.local", "password": "wrong"}
        )
        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_CREDENTIALS"

    def test_unknown_email_gives_the_identical_response(self, client: TestClient) -> None:
        """Distinguishing the two tells an attacker which addresses are worth attacking."""
        unknown = client.post(
            "/auth/login", json={"email": "nobody@test.local", "password": PASSWORD}
        )
        wrong = client.post("/auth/login", json={"email": "admin@test.local", "password": "wrong"})
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["code"] == wrong.json()["code"] == "INVALID_CREDENTIALS"

    def test_a_deactivated_account_cannot_sign_in(self, client: TestClient) -> None:
        response = client.post(
            "/auth/login", json={"email": "disabled@test.local", "password": PASSWORD}
        )
        assert response.status_code == 403
        assert response.json()["code"] == "ACCOUNT_DISABLED"

    def test_repeated_failures_are_locked_out(self, client: TestClient) -> None:
        for _ in range(5):
            client.post("/auth/login", json={"email": "admin@test.local", "password": "wrong"})

        response = client.post(
            "/auth/login", json={"email": "admin@test.local", "password": "wrong"}
        )
        assert response.status_code == 429
        assert response.json()["code"] == "TOO_MANY_ATTEMPTS"
        assert "retry_after_seconds" in response.json()["context"]

    def test_email_case_does_not_matter(self, client: TestClient) -> None:
        response = client.post(
            "/auth/login", json={"email": "ADMIN@TEST.LOCAL", "password": PASSWORD}
        )
        assert response.status_code == 200

    def test_the_response_never_contains_a_password_hash(self, client: TestClient) -> None:
        response = client.post(
            "/auth/login", json={"email": "admin@test.local", "password": PASSWORD}
        )
        # Names the secrets rather than banning the word: the principal legitimately
        # carries `must_change_password`, and a substring check would have made that
        # field impossible to add for a reason unrelated to what it guards.
        body = response.text.lower()
        assert PASSWORD.lower() not in body
        assert "password_hash" not in body
        assert "password_salt" not in body
        assert set(response.json()) == {
            "user_id",
            "email",
            "full_name",
            "role",
            "student_id",
            "locale",
            "theme",
            "must_change_password",
        }


class TestSession:
    def test_me_requires_a_session(self, client: TestClient) -> None:
        response = client.get("/auth/me")
        assert response.status_code == 401
        assert response.json()["code"] == "NOT_AUTHENTICATED"

    def test_me_returns_the_signed_in_user(self, as_teacher: TestClient) -> None:
        body = as_teacher.get("/auth/me").json()
        assert body["email"] == "teacher@test.local"
        assert body["role"] == "teacher"

    def test_a_student_carries_their_linked_record(self, as_student: TestClient) -> None:
        """A student's entire visibility is scoped by this id."""
        assert as_student.get("/auth/me").json()["student_id"] == "S001"

    def test_an_account_with_no_student_record_has_none(self, client: TestClient) -> None:
        sign_in(client, "orphan")
        assert client.get("/auth/me").json()["student_id"] is None

    def test_logout_ends_the_session(self, as_admin: TestClient) -> None:
        assert as_admin.post("/auth/logout").json()["code"] == "SIGNED_OUT"
        assert as_admin.get("/auth/me").status_code == 401

    def test_logout_without_a_session_still_succeeds(self, client: TestClient) -> None:
        """A client clearing a session it already lost should not get an error."""
        assert client.post("/auth/logout").status_code == 200

    def test_a_forged_token_is_rejected(self, client: TestClient) -> None:
        client.cookies.set(SESSION_COOKIE, "not-a-real-token")
        assert client.get("/auth/me").status_code == 401

    def test_deactivating_an_account_kills_its_live_session(
        self, as_teacher: TestClient, seeded_db: sqlite3.Connection
    ) -> None:
        """Effective on the next request, not at the next sign-in. This is the whole
        reason sessions are database rows rather than signed tokens."""
        assert as_teacher.get("/auth/me").status_code == 200

        seeded_db.execute("UPDATE users SET is_active = 0 WHERE email = 'teacher@test.local'")
        seeded_db.commit()

        assert as_teacher.get("/auth/me").status_code == 401


class TestProfile:
    def test_preferences_persist_to_the_account(self, as_student: TestClient) -> None:
        """Stored on the account, not only in the browser, so they follow the user
        to another device."""
        response = as_student.patch("/profile", json={"locale": "de", "theme": "dark"})
        assert response.status_code == 200
        assert response.json()["locale"] == "de"
        assert response.json()["theme"] == "dark"
        assert as_student.get("/auth/me").json()["locale"] == "de"

    def test_an_omitted_field_is_left_alone(self, as_student: TestClient) -> None:
        as_student.patch("/profile", json={"locale": "de", "theme": "dark"})
        as_student.patch("/profile", json={"theme": "light"})
        body = as_student.get("/auth/me").json()
        assert body["locale"] == "de"
        assert body["theme"] == "light"

    def test_an_unshipped_locale_is_rejected(self, as_student: TestClient) -> None:
        response = as_student.patch("/profile", json={"locale": "ja"})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    def test_an_unknown_theme_is_rejected(self, as_student: TestClient) -> None:
        assert as_student.patch("/profile", json={"theme": "neon"}).status_code == 422

    def test_sessions_are_listed_with_the_current_one_flagged(self, as_admin: TestClient) -> None:
        sessions = as_admin.get("/profile/sessions").json()
        assert len(sessions) == 1
        assert sessions[0]["is_current"] is True

    def test_revoking_others_leaves_the_caller_signed_in(
        self, app: object, as_admin: TestClient
    ) -> None:
        """Otherwise 'sign out my other devices' would sign you out too."""
        with TestClient(app) as second:  # type: ignore[arg-type]
            sign_in(second, "admin")
            assert len(as_admin.get("/profile/sessions").json()) == 2

            response = as_admin.post("/profile/sessions/revoke-others")
            assert response.json()["count"] == 1

            assert as_admin.get("/auth/me").status_code == 200
            assert second.get("/auth/me").status_code == 401

    def test_a_session_belonging_to_someone_else_cannot_be_revoked(
        self, app: object, as_admin: TestClient
    ) -> None:
        """The revoke query is scoped by user id, so guessing a hash achieves nothing."""
        with TestClient(app) as victim:  # type: ignore[arg-type]
            sign_in(victim, "teacher")
            victim_hash = victim.get("/profile/sessions").json()[0]["token_sha256"]

            response = as_admin.delete(f"/profile/sessions/{victim_hash}")
            assert response.status_code == 404
            assert victim.get("/auth/me").status_code == 200


class TestPasswordChange:
    def test_requires_the_current_password(self, as_student: TestClient) -> None:
        """An unattended browser must not be enough to take an account over."""
        response = as_student.post(
            "/profile/password",
            json={"current_password": "wrong", "new_password": "a-new-long-password"},
        )
        assert response.status_code == 401

    def test_rejects_a_short_replacement(self, as_student: TestClient) -> None:
        response = as_student.post(
            "/profile/password", json={"current_password": PASSWORD, "new_password": "short"}
        )
        assert response.status_code == 422

    def test_succeeds_and_closes_every_session(self, app: object, as_student: TestClient) -> None:
        """A password change is how someone responds to a suspected compromise;
        leaving the attacker's session alive would defeat the point."""
        with TestClient(app) as attacker:  # type: ignore[arg-type]
            sign_in(attacker, "student")

            response = as_student.post(
                "/profile/password",
                json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
            )
            assert response.json()["code"] == "PASSWORD_CHANGED"

            assert attacker.get("/auth/me").status_code == 401
            assert as_student.get("/auth/me").status_code == 401

    def test_the_new_password_works(self, client: TestClient) -> None:
        sign_in(client, "student")
        client.post(
            "/profile/password",
            json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
        )
        email, _ = ACCOUNTS["student"]
        assert (
            client.post(
                "/auth/login", json={"email": email, "password": "a-brand-new-password"}
            ).status_code
            == 200
        )


class TestProblemResponses:
    def test_errors_use_problem_json(self, client: TestClient) -> None:
        response = client.get("/auth/me")
        assert response.headers["content-type"].startswith("application/problem+json")

    def test_errors_carry_a_machine_code(self, client: TestClient) -> None:
        """The frontend renders the code, not the detail -- which is what keeps a
        message catalogue out of the backend."""
        body = client.get("/auth/me").json()
        assert body["code"] == "NOT_AUTHENTICATED"
        assert body["status"] == 401

    def test_routing_errors_use_the_same_envelope(self, client: TestClient) -> None:
        """Otherwise a client would need two error parsers."""
        body = client.get("/no-such-endpoint").json()
        assert body["code"] == "NOT_FOUND"

    def test_schema_failures_name_the_field(self, client: TestClient) -> None:
        body = client.post("/auth/login", json={}).json()
        assert body["code"] == "VALIDATION_ERROR"
        assert {f["field"] for f in body["context"]["fields"]} == {"email", "password"}

    def test_a_malformed_address_is_a_failed_login_not_a_validation_error(
        self, client: TestClient
    ) -> None:
        """Rejecting it earlier would only tell an attacker that the address is
        malformed rather than unknown."""
        response = client.post("/auth/login", json={"email": "nonsense", "password": "x"})
        assert response.status_code == 401


class TestHealth:
    def test_reports_up_without_a_session(self, client: TestClient) -> None:
        assert client.get("/health").json()["status"] == "ok"
