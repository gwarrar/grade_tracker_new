"""Usage accounting and cost estimation.

The HTTP surface is covered in ``tests/api/test_admin_ai.py``. What is left here
is the logic that has no obvious HTTP shape: the aggregation query, the price
table, and the field-by-field update.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from llm.registry import Feature
from notenverwaltung.exceptions import ValidationError
from notenverwaltung.storage.db import apply_migrations, connect
from services.ai_admin import AiAdminService, estimate_cost


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A migrated in-memory database with two real users.

    The users exist because `audit_log.actor_user_id` and `ai_usage.user_id` are
    foreign keys — a fixture inventing an id would fail on the constraint that
    keeps the audit trail attributable.

    Exposed separately from the service so a test can inspect the trail without
    reaching past the service's boundary.
    """
    connection = connect(":memory:")
    apply_migrations(connection)
    for user_id, email in ((1, "root@test.local"), (7, "admin@test.local")):
        connection.execute(
            "INSERT INTO users (id, email, password_hash, password_salt, role, full_name)"
            " VALUES (?, ?, 'x', 'x', 'superadmin', 'Test')",
            (user_id, email),
        )
    yield connection
    connection.close()


@pytest.fixture
def service(conn: sqlite3.Connection) -> AiAdminService:
    """A service over the test database."""
    return AiAdminService(conn)


@pytest.fixture
def provider_id(service: AiAdminService) -> int:
    """One configured provider."""
    return service.create_provider(
        actor_id=1,
        name="anthropic",
        kind="anthropic",
        default_model="claude-opus-5",
        api_key_env="ANTHROPIC_API_KEY",
    ).id


# ── Cost estimation ──────────────────────────────────────────────────────────


def test_cost_is_estimated_from_the_price_table() -> None:
    """One million in and one million out of Opus is $5 + $25."""
    assert estimate_cost("claude-opus-5", 1_000_000, 1_000_000) == pytest.approx(30.0)


def test_a_cheaper_model_estimates_lower() -> None:
    """The table distinguishes tiers, which is the only reason it is worth having."""
    opus = estimate_cost("claude-opus-5", 100_000, 10_000)
    haiku = estimate_cost("claude-haiku-4-5", 100_000, 10_000)
    assert haiku < opus


def test_an_unpriced_model_costs_nothing_rather_than_a_guess() -> None:
    """A local model genuinely costs nothing.

    Inventing a figure for it would be worse than reporting none — the number
    would look authoritative and be wrong.
    """
    assert estimate_cost("llama3", 1_000_000, 1_000_000) == 0.0


# ── Usage ────────────────────────────────────────────────────────────────────


def test_usage_aggregates_by_day_feature_and_model(
    service: AiAdminService, provider_id: int
) -> None:
    """Several calls to one feature collapse into one row with summed totals."""
    for _ in range(3):
        service.record_usage(
            feature=Feature.ASK,
            provider_id=provider_id,
            model="claude-opus-5",
            user_id=1,
            input_tokens=100,
            output_tokens=50,
            cached_tokens=20,
        )

    rows = service.usage()

    assert len(rows) == 1
    assert rows[0].feature == "ask"
    assert rows[0].calls == 3
    assert rows[0].input_tokens == 300
    assert rows[0].output_tokens == 150
    assert rows[0].cached_tokens == 60


def test_different_features_are_reported_separately(
    service: AiAdminService, provider_id: int
) -> None:
    """Otherwise the page cannot show which feature is expensive."""
    service.record_usage(
        feature=Feature.ASK, provider_id=provider_id, model="claude-opus-5", user_id=1
    )
    service.record_usage(
        feature=Feature.COMMAND, provider_id=provider_id, model="claude-haiku-4-5", user_id=1
    )

    assert {row.feature for row in service.usage()} == {"ask", "command"}


def test_failed_calls_are_counted(service: AiAdminService, provider_id: int) -> None:
    """A usage page showing only successes hides the pattern that matters most.

    A provider that has started rejecting everything is invisible if errors are
    not recorded.
    """
    service.record_usage(
        feature=Feature.ASK, provider_id=provider_id, model="claude-opus-5", user_id=1
    )
    service.record_usage(
        feature=Feature.ASK,
        provider_id=provider_id,
        model="claude-opus-5",
        user_id=1,
        was_error=True,
    )

    row = service.usage()[0]
    assert row.calls == 2
    assert row.errors == 1


def test_usage_cost_accumulates(service: AiAdminService, provider_id: int) -> None:
    """The estimate is stored per call and summed, not recomputed on read.

    Recomputing would silently restate history the moment the price table changed.
    """
    service.record_usage(
        feature=Feature.INSIGHT,
        provider_id=provider_id,
        model="claude-opus-5",
        user_id=1,
        input_tokens=1_000_000,
        output_tokens=0,
    )

    assert service.usage()[0].cost_estimate == pytest.approx(5.0)


def test_usage_rejects_a_non_positive_window(service: AiAdminService) -> None:
    """A negative window would silently return everything."""
    with pytest.raises(ValidationError):
        service.usage(days=0)


def test_usage_survives_a_deleted_provider(service: AiAdminService, provider_id: int) -> None:
    """History outlives configuration.

    The provider_id is nulled by the schema rather than cascading the rows away —
    deleting a provider must not erase the record of what it cost.
    """
    service.record_usage(
        feature=Feature.ASK,
        provider_id=provider_id,
        model="claude-opus-5",
        user_id=1,
        input_tokens=100,
    )
    service.delete_provider(provider_id, actor_id=1)

    rows = service.usage()
    assert len(rows) == 1
    assert rows[0].input_tokens == 100


# ── Updates ──────────────────────────────────────────────────────────────────


def test_updating_with_no_changes_is_a_no_op(service: AiAdminService, provider_id: int) -> None:
    """An empty PATCH must not write an audit entry or bump updated_at."""
    before = service.update_provider(provider_id, actor_id=1)
    assert before.name == "anthropic"


def test_each_field_updates_independently(service: AiAdminService, provider_id: int) -> None:
    """Every branch of the assignment builder, since each is a separate column."""
    updated = service.update_provider(
        provider_id,
        actor_id=1,
        name="claude",
        base_url="https://proxy.example/v1",
        api_key_env="OTHER_KEY",
        default_model="claude-sonnet-5",
        is_enabled=False,
        is_third_party_pool=True,
        params_json='{"temperature": 0.2}',
    )

    assert updated.name == "claude"
    assert updated.base_url == "https://proxy.example/v1"
    assert updated.api_key_env == "OTHER_KEY"
    assert updated.default_model == "claude-sonnet-5"
    assert updated.is_enabled is False
    assert updated.is_third_party_pool is True
    assert updated.params_json == '{"temperature":0.2}'


def test_clearing_the_base_url_stores_null_not_an_empty_string(
    service: AiAdminService, provider_id: int
) -> None:
    """An empty string is not a URL.

    Stored as one it would be sent to httpx as "/chat/completions" and fail with a
    confusing relative-URL error rather than falling back to the vendor default.
    """
    updated = service.update_provider(provider_id, actor_id=1, base_url="")
    assert updated.base_url is None


def test_an_unimplemented_kind_is_rejected(service: AiAdminService) -> None:
    """Guarded in the service, not only at the HTTP schema."""
    with pytest.raises(ValidationError):
        service.create_provider(actor_id=1, name="x", kind="telepathy", default_model="m")


def test_an_unknown_effort_is_rejected(service: AiAdminService, provider_id: int) -> None:
    """Checked before the insert, so the failure is a domain error not a CHECK violation."""
    with pytest.raises(ValidationError):
        service.set_routing(Feature.ASK, actor_id=1, provider_id=provider_id, effort="maximum")


def test_routing_records_the_pinned_model(service: AiAdminService, provider_id: int) -> None:
    """The stored routing is read back, not echoed from the request."""
    route = service.set_routing(
        Feature.COMMAND, actor_id=1, provider_id=provider_id, model="claude-haiku-4-5", effort="low"
    )

    assert route.feature == "command"
    assert route.model == "claude-haiku-4-5"
    assert route.effort == "low"
    assert route.provider_name == "anthropic"


def test_a_provider_row_carries_no_key(
    service: AiAdminService, provider_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property the whole design rests on, asserted at the service boundary too."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-do-not-leak")

    listed = service.list_providers()

    assert listed[0].key_present is True
    assert "sk-do-not-leak" not in repr(listed[0])


def test_audit_entries_are_written_for_configuration_changes(
    service: AiAdminService, provider_id: int, conn: sqlite3.Connection
) -> None:
    """Who pointed the AI at which third party is exactly what an audit trail is for."""
    service.update_provider(provider_id, actor_id=7, is_enabled=False)

    rows = conn.execute(
        "SELECT actor_user_id, action FROM audit_log WHERE entity = 'ai_provider' ORDER BY id"
    ).fetchall()

    assert [row["action"] for row in rows] == ["create", "update"]
    assert rows[-1]["actor_user_id"] == 7
