"""Five defects that were live in shipped code, and invisible in every case.

Grouped because they share a shape rather than a subsystem: each one either failed
open or reported success, so nothing in the application, its logs or its test suite
was ever going to mention them. These tests are the only thing that will.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.config import Settings
from services.auth import AuthService, LoginThrottle, is_stale
from services.rate_limit import CallQuota, QuotaExceededError
from services.security import utc_now

PASSWORD = "test-password-2026"


class TestCookieSecurity:
    """`Secure` was decided by whether *any* configured origin mentioned localhost.

    Both of its failures pointed the same way -- toward a session cookie travelling
    in clear -- and neither produced a warning.
    """

    def test_a_purely_local_deployment_needs_no_secure(self) -> None:
        settings = Settings(cors_origins="http://localhost:3000,http://127.0.0.1:3000")

        assert settings.session_cookie_secure is False

    def test_one_production_origin_is_enough_to_require_it(self) -> None:
        """`any` rather than `all` was the bug. Leaving the dev entry in CORS_ORIGINS
        is the commonest misconfiguration there is, and it silently un-secured the
        real cookie."""
        settings = Settings(cors_origins="https://grades.school.de,http://localhost:3000")

        assert settings.session_cookie_secure is True

    def test_a_lookalike_host_does_not_count_as_local(self) -> None:
        """A substring test rather than a host parse: `mylocalhost.io` contains the
        word."""
        assert Settings(cors_origins="https://mylocalhost.io").session_cookie_secure is True

    def test_no_origins_is_unknown_rather_than_local(self) -> None:
        assert Settings(cors_origins="").session_cookie_secure is True

    def test_an_explicit_setting_wins(self) -> None:
        """For a deployment this cannot reason about: a tunnel, a local TLS proxy."""
        forced_off = Settings(cors_origins="https://x.test", cookie_secure=False)
        forced_on = Settings(cors_origins="http://localhost:3000", cookie_secure=True)

        assert forced_off.session_cookie_secure is False
        assert forced_on.session_cookie_secure is True

    def test_the_cookie_carries_the_verdict(self, client: TestClient) -> None:
        """Test settings are localhost-only, so the flag is off here. What matters is
        that the header follows the setting rather than a substring search."""
        response = client.post(
            "/auth/login", json={"email": "admin@test.local", "password": PASSWORD}
        )

        assert response.status_code == 200, response.text
        assert "Secure" not in response.headers.get("set-cookie", "")


class TestTrustedProxies:
    """Nothing may believe `X-Forwarded-For` unless told which hosts to believe."""

    def test_nothing_is_trusted_by_default(self) -> None:
        """Believing it from anyone lets a caller pick a new address per attempt and
        walk around the sign-in lockout entirely."""
        assert Settings().trusted_proxy_list == []

    def test_hosts_can_be_configured(self) -> None:
        assert Settings(trusted_proxies="10.0.0.1, 10.0.0.2").trusted_proxy_list == [
            "10.0.0.1",
            "10.0.0.2",
        ]

    def test_any_proxy_can_be_trusted_explicitly(self) -> None:
        assert Settings(trusted_proxies="*").trusted_proxy_list == "*"

    def test_a_forwarded_header_buys_nothing_when_nothing_is_trusted(
        self, client: TestClient
    ) -> None:
        """A different claimed address on every attempt, and still locked out."""
        wrong = {"email": "admin@test.local", "password": "wrong"}
        for index in range(6):
            client.post("/auth/login", json=wrong, headers={"x-forwarded-for": f"1.2.3.{index}"})

        blocked = client.post("/auth/login", json=wrong, headers={"x-forwarded-for": "9.9.9.9"})

        assert blocked.status_code == 429


class TestAiQuota:
    """Every AI request reaches a provider and is billed. The only gate was a session."""

    def test_calls_are_allowed_up_to_the_limit(self) -> None:
        quota = CallQuota(max_calls=3)

        for _ in range(3):
            quota.check("user-1")

    def test_the_limit_refuses_the_next_call(self) -> None:
        quota = CallQuota(max_calls=2)
        quota.check("user-1")
        quota.check("user-1")

        with pytest.raises(QuotaExceededError) as raised:
            quota.check("user-1")

        assert raised.value.http_status == 429
        assert int(str(raised.value.context["retry_after_seconds"])) > 0

    def test_callers_are_counted_separately(self) -> None:
        """Keyed by account, not address: the bill follows the account, and one
        router's address is shared by everyone behind it."""
        quota = CallQuota(max_calls=1)
        quota.check("user-1")

        quota.check("user-2")

    def test_a_window_expires(self) -> None:
        quota = CallQuota(max_calls=1, window_seconds=0)
        quota.check("user-1")

        quota.check("user-1")

    def test_a_zero_limit_turns_the_feature_off(self) -> None:
        """Clearer than an unbounded one is at leaving it on."""
        with pytest.raises(QuotaExceededError):
            CallQuota(max_calls=0).check("user-1")

    def test_a_student_is_refused_once_their_allowance_is_spent(
        self, app: FastAPI, as_student: TestClient
    ) -> None:
        """The case that made this urgent: any signed-in account could spend without
        limit, and the first sign of it was the vendor's invoice."""
        app.state.ai_quota = CallQuota(max_calls=0)

        response = as_student.post("/ai/ask", json={"question": "how am I doing?"})

        assert response.status_code == 429
        assert response.json()["code"] == "AI_QUOTA_EXCEEDED"


class TestUnhandledErrors:
    """A crash used to answer `text/plain`, the one shape the frontend cannot parse."""

    def test_a_crash_returns_a_problem_document(self, app: FastAPI) -> None:
        @app.get("/boom-for-tests")
        def _boom() -> None:  # pyright: ignore[reportUnusedFunction] - registered by the decorator
            raise RuntimeError("the database fell over")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom-for-tests")

        assert response.status_code == 500
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "INTERNAL_ERROR"

    def test_the_exception_message_is_not_echoed(self, app: FastAPI) -> None:
        """It carries paths, SQL and occasionally the value that broke, and this
        envelope is rendered to whoever made the request."""

        @app.get("/leaky-for-tests")
        def _leak() -> None:  # pyright: ignore[reportUnusedFunction] - registered by the decorator
            raise RuntimeError("SELECT password_hash FROM users WHERE id = 42")

        with TestClient(app, raise_server_exceptions=False) as client:
            body = client.get("/leaky-for-tests").text

        assert "password_hash" not in body


class TestSessionTouch:
    """`last_seen_at` was written on every authenticated request, GETs included."""

    def test_a_fresh_timestamp_is_not_rewritten(self) -> None:
        assert is_stale(utc_now(), seconds=60) is False

    def test_an_old_timestamp_is(self) -> None:
        assert is_stale("2020-01-01T00:00:00Z", seconds=60) is True

    def test_a_missing_one_is(self) -> None:
        assert is_stale(None, seconds=60) is True

    def test_an_unparseable_one_is(self) -> None:
        """Stale, so a bad row is repaired by the next request rather than frozen."""
        assert is_stale("not a timestamp", seconds=60) is True

    def test_resolving_a_fresh_session_writes_nothing(self, seeded_db: sqlite3.Connection) -> None:
        """Counted rather than compared. `utc_now()` has second resolution, so
        comparing the stored value before and after passes whether or not the write
        happened -- which is exactly how this went unnoticed. `total_changes` counts
        rows actually modified on this connection and cannot be fooled that way.

        On SQLite a write is a lock and an fsync, paid per page view to maintain a
        timestamp whose only reader displays a date.
        """
        auth = AuthService(seeded_db, LoginThrottle(5, 15), 168)
        token, _ = auth.login("admin@test.local", PASSWORD)
        # A new session has no `last_seen_at` at all, so the first resolve writes one
        # and should. The claim is about every request after that.
        auth.resolve(token)

        before = seeded_db.total_changes
        auth.resolve(token)
        auth.resolve(token)

        assert seeded_db.total_changes == before

    def test_resolving_a_stale_session_does_write(self, seeded_db: sqlite3.Connection) -> None:
        """The other half: skipping the write always would freeze the device list."""
        auth = AuthService(seeded_db, LoginThrottle(5, 15), 168)
        token, _ = auth.login("admin@test.local", PASSWORD)
        seeded_db.execute("UPDATE sessions SET last_seen_at = '2020-01-01T00:00:00Z'")

        before = seeded_db.total_changes
        auth.resolve(token)

        assert seeded_db.total_changes > before
        assert seeded_db.execute("SELECT last_seen_at FROM sessions").fetchone()[0] != (
            "2020-01-01T00:00:00Z"
        )
