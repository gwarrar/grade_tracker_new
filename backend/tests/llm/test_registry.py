"""Provider construction and feature routing.

The registry is where the "keys live in the environment, routing lives in the
database" split is actually enforced. These tests hold that line: a configuration
row must never be sufficient to make a request, and a missing variable must be
reported by name rather than surfacing as a 401 later.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from llm.anthropic_provider import AnthropicProvider
from llm.base import LLMError, Message, Role
from llm.openai_compatible_provider import OpenAICompatibleProvider
from llm.registry import Feature, ProviderConfig, Registry, build
from notenverwaltung.storage.db import apply_migrations, connect


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A migrated in-memory database."""
    connection = connect(":memory:")
    apply_migrations(connection)
    yield connection
    connection.close()


def _add_provider(
    conn: sqlite3.Connection,
    *,
    name: str = "anthropic",
    kind: str = "anthropic",
    api_key_env: str = "ANTHROPIC_API_KEY",
    base_url: str | None = None,
    model: str = "claude-opus-5",
    enabled: bool = True,
    params_json: str = "{}",
) -> int:
    """Insert a provider row and return its id."""
    cursor = conn.execute(
        "INSERT INTO ai_providers"
        " (name, kind, base_url, api_key_env, default_model, is_enabled, params_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, kind, base_url, api_key_env, model, int(enabled), params_json),
    )
    return int(cursor.lastrowid or 0)


def _route(
    conn: sqlite3.Connection,
    feature: Feature,
    provider_id: int,
    model: str = "",
    effort: str = "medium",
) -> None:
    """Point a feature at a provider."""
    conn.execute(
        "INSERT INTO ai_feature_models (feature, provider_id, model, effort) VALUES (?, ?, ?, ?)",
        (feature.value, provider_id, model, effort),
    )


# ── build ────────────────────────────────────────────────────────────────────


def test_builds_an_anthropic_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured Anthropic row plus its environment variable yields a provider."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    config = ProviderConfig(
        id=1,
        name="anthropic",
        kind="anthropic",
        base_url=None,
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-opus-5",
        is_enabled=True,
        is_third_party_pool=False,
    )

    provider = build(config)

    assert isinstance(provider, AnthropicProvider)
    assert provider.model == "claude-opus-5"


def test_a_missing_key_is_reported_by_variable_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reported here, not as a 401 on the first real question.

    A configuration that only fails when someone asks a question is a
    configuration nobody notices until it matters.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = ProviderConfig(
        id=1,
        name="anthropic",
        kind="anthropic",
        base_url=None,
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-opus-5",
        is_enabled=True,
        is_third_party_pool=False,
    )

    with pytest.raises(LLMError) as caught:
        build(config)

    assert caught.value.code == "AI_KEY_MISSING"
    assert "ANTHROPIC_API_KEY" in str(caught.value)


def test_a_local_endpoint_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama authenticates nothing.

    Demanding a credential would make the most private option — a model that never
    leaves the machine — the only one that could not be configured.
    """
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    config = ProviderConfig(
        id=2,
        name="ollama",
        kind="openai_compatible",
        base_url="http://localhost:11434/v1",
        api_key_env="OLLAMA_API_KEY",
        default_model="llama3",
        is_enabled=True,
        is_third_party_pool=False,
    )

    provider = build(config)

    assert isinstance(provider, OpenAICompatibleProvider)


def test_an_unknown_kind_is_rejected() -> None:
    """A kind the code cannot serve fails loudly rather than returning None."""
    config = ProviderConfig(
        id=3,
        name="mystery",
        kind="telepathy",
        base_url=None,
        api_key_env="",
        default_model="m",
        is_enabled=True,
        is_third_party_pool=False,
    )

    with pytest.raises(LLMError) as caught:
        build(config)

    assert caught.value.code == "AI_UNKNOWN_KIND"


@pytest.mark.parametrize("params_json", ["{broken", "[1, 2, 3]"])
def test_generation_parameters_must_be_a_json_object(params_json: str) -> None:
    """Malformed or non-object settings fail before the first real request."""
    config = ProviderConfig(
        id=4,
        name="nvidia",
        kind="openai_compatible",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="",
        default_model="deepseek-ai/deepseek-v4-flash",
        is_enabled=True,
        is_third_party_pool=False,
        params_json=params_json,
    )

    with pytest.raises(LLMError) as caught:
        build(config)

    assert caught.value.code == "AI_BAD_PARAMS"


# ── routing ──────────────────────────────────────────────────────────────────


def test_resolve_uses_the_model_pinned_to_the_feature(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-feature model overrides the provider default.

    This is the whole reason routing is a separate table: the command palette is
    latency-critical and the insight narrative is quality-critical, and one default
    cannot be right for both.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider_id = _add_provider(conn, model="claude-opus-5")
    _route(conn, Feature.COMMAND, provider_id, model="claude-haiku-4-5")

    provider = Registry(conn).resolve(Feature.COMMAND)

    assert provider.model == "claude-haiku-4-5"


def test_resolve_falls_back_to_the_provider_default(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty pin means "whatever the provider defaults to"."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider_id = _add_provider(conn, model="claude-opus-5")
    _route(conn, Feature.ASK, provider_id, model="")

    assert Registry(conn).resolve(Feature.ASK).model == "claude-opus-5"


def test_resolve_applies_the_route_effort_and_provider_parameters(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configuration stored in both tables reaches the actual wire payload."""
    provider_id = _add_provider(
        conn,
        name="nvidia",
        kind="openai_compatible",
        api_key_env="",
        base_url="https://integrate.api.nvidia.com/v1",
        model="deepseek-ai/deepseek-v4-flash",
        # "auto" is how a provider opts in and defers to the routing table for the
        # level. Absent, no reasoning parameter is sent at all.
        params_json='{"temperature": 0.6, "reasoning_effort": "auto"}',
    )
    _route(conn, Feature.ASK, provider_id, effort="max")
    captured: dict[str, Any] = {}

    def respond(*_: Any, **kwargs: Any) -> httpx.Response:
        captured.update(kwargs["json"])
        return httpx.Response(
            200,
            json={
                "model": "deepseek-ai/deepseek-v4-flash",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {},
            },
        )

    monkeypatch.setattr(httpx, "post", respond)

    Registry(conn).resolve(Feature.ASK).chat([Message(role=Role.USER, content="hi")])

    assert captured["reasoning_effort"] == "high"
    assert captured["temperature"] == 0.6


def test_a_provider_that_never_asked_for_effort_is_sent_none(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain model must not receive a reasoning parameter it cannot accept.

    The routing column is NOT NULL DEFAULT 'medium', so deriving the parameter from
    it sent one to every provider — and Ollama answers 400 ``"llama3.2:1b" does not
    support thinking``. A reasoning model is fine without it; a plain one is broken
    by it, so it is opt-in.
    """
    provider_id = _add_provider(
        conn,
        name="ollama",
        kind="openai_compatible",
        api_key_env="",
        base_url="http://127.0.0.1:11434/v1",
        model="llama3.2:1b",
        params_json="{}",
    )
    _route(conn, Feature.ASK, provider_id, effort="high")
    captured: dict[str, Any] = {}

    def respond(*_: Any, **kwargs: Any) -> httpx.Response:
        captured.update(kwargs["json"])
        return httpx.Response(
            200,
            json={
                "model": "llama3.2:1b",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {},
            },
        )

    monkeypatch.setattr(httpx, "post", respond)

    Registry(conn).resolve(Feature.ASK).chat([Message(role=Role.USER, content="hi")])

    assert "reasoning_effort" not in captured


def test_an_unrouted_feature_is_reported(conn: sqlite3.Connection) -> None:
    """A feature nobody configured is a configuration gap, not a crash."""
    with pytest.raises(LLMError) as caught:
        Registry(conn).resolve(Feature.INSIGHT)

    assert caught.value.code == "AI_NOT_CONFIGURED"


def test_a_disabled_provider_does_not_serve(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disabling must actually stop traffic.

    Silently falling back to another provider is the kind of surprise that makes
    an admin page untrustworthy — the switch would appear to do nothing.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider_id = _add_provider(conn, enabled=False)
    _route(conn, Feature.ASK, provider_id)

    with pytest.raises(LLMError) as caught:
        Registry(conn).resolve(Feature.ASK)

    assert caught.value.code == "AI_PROVIDER_DISABLED"


def test_listing_providers_never_exposes_a_key(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row carries the variable's name, never its value.

    This is the property that makes a database leak harmless, so it is asserted
    rather than assumed.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    _add_provider(conn)

    listed = Registry(conn).providers()

    assert len(listed) == 1
    assert listed[0].api_key_env == "ANTHROPIC_API_KEY"
    assert "sk-secret-value" not in repr(listed[0])


def test_fetching_an_unknown_provider_is_reported(conn: sqlite3.Connection) -> None:
    """A dangling id reports rather than returning None for the caller to deref."""
    with pytest.raises(LLMError) as caught:
        Registry(conn).get(999)

    assert caught.value.code == "AI_PROVIDER_NOT_FOUND"
