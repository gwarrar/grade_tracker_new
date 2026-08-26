"""Configuring AI providers, routing and usage accounting.

Sits between the router and the database for the same reason every other service
does: the router parses HTTP and nothing else, and the transaction boundary lives
here where the audit write can share it.

Nothing in this module ever handles an API key. It records which environment
variable to read; reading it is :func:`llm.registry.build`'s job, at the moment of
use. A leak of everything this service writes exposes no credentials.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass

from llm.base import LLMError
from llm.registry import Feature, ProviderConfig, Registry, build
from notenverwaltung.exceptions import DuplicateEntryError, ValidationError
from notenverwaltung.storage import transaction
from services import audit

VALID_KINDS = frozenset({"anthropic", "openai_compatible"})
VALID_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})

# Rough per-million-token prices, used only to put an order of magnitude next to a
# token count. Deliberately not authoritative: providers change prices, free pools
# have none, and a wrong figure presented confidently is worse than an approximate
# one presented as approximate. The admin page labels it an estimate.
_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """A provider's configuration plus whether it could actually be used.

    Attributes:
        config: The stored row.
        key_present: Whether the named environment variable is set. Reported as a
            boolean and never as a value — the point of the design is that the
            application can see whether a key exists without the interface ever
            being able to show it.
    """

    config: ProviderConfig
    key_present: bool


@dataclass(frozen=True, slots=True)
class Routing:
    """Which provider and model serve one feature.

    Attributes:
        feature: The capability.
        provider_id: Which provider.
        provider_name: Its name, so the interface need not join.
        model: Pinned model, or empty for the provider's default.
        effort: Reasoning effort for providers that support it.
    """

    feature: str
    provider_id: int
    provider_name: str
    model: str
    effort: str


@dataclass(frozen=True, slots=True)
class UsageRow:
    """One day's usage of one feature.

    Attributes:
        day: ISO date.
        feature: Which capability.
        model: Which model answered.
        calls: Number of calls.
        input_tokens: Total input tokens.
        output_tokens: Total output tokens.
        cached_tokens: Input tokens served from a prompt cache.
        cost_estimate: Approximate cost in USD.
        errors: How many calls failed.
    """

    day: str
    feature: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_estimate: float
    errors: int


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Approximate the cost of one call.

    Args:
        model: The model that answered.
        input_tokens: Tokens sent.
        output_tokens: Tokens generated.

    Returns:
        Cost in USD, or 0.0 for a model with no listed price — a local model
        genuinely costs nothing, and inventing a figure for it would be worse than
        reporting none.
    """
    prices = _PRICES.get(model)
    if prices is None:
        return 0.0
    input_price, output_price = prices
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


class AiAdminService:
    """Provider configuration, feature routing and usage reporting."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialise the service.

        Args:
            conn: The request's database connection.
        """
        self._conn = conn
        self._registry = Registry(conn)

    def is_configured(self) -> bool:
        """Return whether an enabled provider and feature route both exist."""
        return any(provider.config.is_enabled for provider in self.list_providers()) and bool(
            self.routing()
        )

    # ── Providers ────────────────────────────────────────────────────────────

    def list_providers(self) -> list[ProviderStatus]:
        """List every configured provider and whether its key is available.

        Returns:
            One entry per provider, ordered by name.
        """
        return [
            ProviderStatus(
                config=config,
                key_present=bool(config.api_key_env and os.environ.get(config.api_key_env)),
            )
            for config in self._registry.providers()
        ]

    def create_provider(
        self,
        *,
        actor_id: int,
        name: str,
        kind: str,
        default_model: str,
        base_url: str | None = None,
        api_key_env: str = "",
        is_enabled: bool = True,
        is_third_party_pool: bool = False,
        params_json: str = "{}",
    ) -> ProviderConfig:
        """Add a provider.

        Args:
            actor_id: Who is making the change, for the audit log.
            name: Display name. Must be unique.
            kind: ``anthropic`` or ``openai_compatible``.
            default_model: Model used when a feature pins none.
            base_url: Endpoint override.
            api_key_env: **Name** of the environment variable holding the key.
            is_enabled: Whether it may serve traffic.
            is_third_party_pool: Whether it routes through third parties.
            params_json: Extra provider request settings as a JSON object.

        Returns:
            The stored configuration.

        Raises:
            ValidationError: If the kind is not one this application implements.
            DuplicateEntryError: If the name is taken.
        """
        self._check_kind(kind)
        params_json = _normalise_params_json(params_json)

        with transaction(self._conn):
            try:
                cursor = self._conn.execute(
                    "INSERT INTO ai_providers"
                    " (name, kind, base_url, api_key_env, default_model, is_enabled,"
                    "  is_third_party_pool, params_json)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        kind,
                        base_url or None,
                        api_key_env,
                        default_model,
                        int(is_enabled),
                        int(is_third_party_pool),
                        params_json,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise DuplicateEntryError(f"a provider named {name!r} already exists") from error

            provider_id = int(cursor.lastrowid or 0)
            config = self._registry.get(provider_id)
            audit.record(
                self._conn,
                actor_user_id=actor_id,
                entity="ai_provider",
                entity_id=str(provider_id),
                action="create",
                after={"name": name, "kind": kind, "api_key_env": api_key_env},
            )
            return config

    def update_provider(
        self,
        provider_id: int,
        *,
        actor_id: int,
        name: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        default_model: str | None = None,
        is_enabled: bool | None = None,
        is_third_party_pool: bool | None = None,
        params_json: str | None = None,
    ) -> ProviderConfig:
        """Change a provider's configuration.

        ``kind`` is deliberately not changeable: it selects the implementation, and
        switching it silently reinterprets every other field. Delete and recreate.

        Args:
            provider_id: Which provider.
            actor_id: Who is making the change.
            name: New display name.
            base_url: New endpoint.
            api_key_env: New environment variable name.
            default_model: New default model.
            is_enabled: Whether it may serve traffic.
            is_third_party_pool: Whether it routes through third parties.
            params_json: Extra provider request settings as a JSON object.

        Returns:
            The updated configuration.

        Raises:
            LLMError: If no such provider exists.
            DuplicateEntryError: If the new name is taken.
        """
        before = self._registry.get(provider_id)

        changes: dict[str, object] = {}
        if name is not None:
            changes["name"] = name
        if base_url is not None:
            changes["base_url"] = base_url or None
        if api_key_env is not None:
            changes["api_key_env"] = api_key_env
        if default_model is not None:
            changes["default_model"] = default_model
        if is_enabled is not None:
            changes["is_enabled"] = int(is_enabled)
        if is_third_party_pool is not None:
            changes["is_third_party_pool"] = int(is_third_party_pool)
        if params_json is not None:
            changes["params_json"] = _normalise_params_json(params_json)

        if not changes:
            return before

        assignments = ", ".join(f"{column} = ?" for column in changes)
        with transaction(self._conn):
            try:
                self._conn.execute(
                    f"UPDATE ai_providers SET {assignments}, updated_at = ?"  # noqa: S608
                    " WHERE id = ?",
                    (*changes.values(), _now(), provider_id),
                )
            except sqlite3.IntegrityError as error:
                raise DuplicateEntryError(f"a provider named {name!r} already exists") from error

            after = self._registry.get(provider_id)
            audit.record(
                self._conn,
                actor_user_id=actor_id,
                entity="ai_provider",
                entity_id=str(provider_id),
                action="update",
                before={"name": before.name, "is_enabled": before.is_enabled},
                after={"name": after.name, "is_enabled": after.is_enabled},
            )
            return after

    def delete_provider(self, provider_id: int, *, actor_id: int) -> None:
        """Remove a provider.

        Any feature routed to it loses its routing, by the schema's cascade. That
        is the honest outcome: the alternative is a route pointing at nothing,
        which fails at request time instead of at configuration time.

        Args:
            provider_id: Which provider.
            actor_id: Who is making the change.

        Raises:
            LLMError: If no such provider exists.
        """
        config = self._registry.get(provider_id)
        with transaction(self._conn):
            self._conn.execute("DELETE FROM ai_providers WHERE id = ?", (provider_id,))
            audit.record(
                self._conn,
                actor_user_id=actor_id,
                entity="ai_provider",
                entity_id=str(provider_id),
                action="delete",
                before={"name": config.name, "kind": config.kind},
            )

    def test_connection(self, provider_id: int) -> tuple[bool, str, str]:
        """Make the smallest possible real call, to prove the configuration works.

        A provider that only fails when someone asks a real question is a provider
        nobody notices is broken until it matters.

        Args:
            provider_id: Which provider.

        Returns:
            ``(ok, code, detail)``. ``code`` is a stable identifier the interface
            translates; ``detail`` is English and for the admin's eyes only.
        """
        config = self._registry.get(provider_id)
        try:
            model = build(config).check()
        except LLMError as error:
            return False, error.code, str(error)
        return True, "AI_OK", model

    def available_models(self, provider_id: int) -> list[str]:
        """List the models the endpoint offers, so nobody has to type one from memory.

        A local Ollama serves whatever that machine has pulled, which no default can
        know, and a hand-typed identifier fails at the first real question rather
        than at configuration time.

        Args:
            provider_id: Which provider.

        Returns:
            Model identifiers, or an empty list if the endpoint cannot enumerate
            them or is unreachable. Deliberately not an error: the field remains
            typeable, so an endpoint without a listing is inconvenient, not blocking.
        """
        config = self._registry.get(provider_id)
        try:
            return build(config).list_models()
        except LLMError:
            return []

    # ── Routing ──────────────────────────────────────────────────────────────

    def routing(self) -> list[Routing]:
        """List which provider serves each feature.

        Returns:
            One entry per configured feature.
        """
        rows = self._conn.execute(
            "SELECT m.feature, m.provider_id, p.name AS provider_name, m.model, m.effort"
            " FROM ai_feature_models m JOIN ai_providers p ON p.id = m.provider_id"
            " ORDER BY m.feature"
        ).fetchall()
        return [
            Routing(
                feature=row["feature"],
                provider_id=row["provider_id"],
                provider_name=row["provider_name"],
                model=row["model"],
                effort=row["effort"],
            )
            for row in rows
        ]

    def set_routing(
        self,
        feature: Feature,
        *,
        actor_id: int,
        provider_id: int,
        model: str = "",
        effort: str = "medium",
    ) -> Routing:
        """Point a feature at a provider.

        Args:
            feature: Which capability.
            actor_id: Who is making the change.
            provider_id: Which provider serves it.
            model: Pinned model, or empty for the provider's default.
            effort: Reasoning effort.

        Returns:
            The stored routing.

        Raises:
            ValidationError: If the effort is not a recognised level.
            LLMError: If no such provider exists.
        """
        if effort not in VALID_EFFORTS:
            raise ValidationError(
                f"effort must be one of {sorted(VALID_EFFORTS)}", field="effort", value=effort
            )

        # Checked rather than left to the foreign key, so the failure is a 404
        # naming the provider instead of an opaque integrity error.
        self._registry.get(provider_id)

        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO ai_feature_models (feature, provider_id, model, effort, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (feature) DO UPDATE SET"
                "   provider_id = excluded.provider_id,"
                "   model = excluded.model,"
                "   effort = excluded.effort,"
                "   updated_at = excluded.updated_at",
                (feature.value, provider_id, model, effort, _now()),
            )
            audit.record(
                self._conn,
                actor_user_id=actor_id,
                entity="ai_routing",
                entity_id=feature.value,
                action="update",
                after={"provider_id": provider_id, "model": model, "effort": effort},
            )

            stored = next(r for r in self.routing() if r.feature == feature.value)
            return stored

    # ── Usage ────────────────────────────────────────────────────────────────

    def record_usage(
        self,
        *,
        feature: Feature,
        provider_id: int | None,
        model: str,
        user_id: int | None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        latency_ms: int = 0,
        was_error: bool = False,
    ) -> None:
        """Log one call.

        Failures are logged too, with ``was_error``. A usage page that shows only
        successes hides exactly the pattern an administrator needs to see — a
        provider that started rejecting everything.

        Args:
            feature: Which capability made the call.
            provider_id: Which provider answered, if known.
            model: Which model answered.
            user_id: Who asked.
            input_tokens: Tokens sent.
            output_tokens: Tokens generated.
            cached_tokens: Input tokens served from cache.
            latency_ms: Round-trip time.
            was_error: Whether the call failed.
        """
        self._conn.execute(
            "INSERT INTO ai_usage"
            " (feature, provider_id, model, user_id, input_tokens, output_tokens,"
            "  cached_tokens, cost_estimate, latency_ms, was_error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                feature.value,
                provider_id,
                model,
                user_id,
                input_tokens,
                output_tokens,
                cached_tokens,
                estimate_cost(model, input_tokens, output_tokens),
                latency_ms,
                int(was_error),
            ),
        )

    def usage(self, *, days: int = 30) -> list[UsageRow]:
        """Summarise usage by day, feature and model.

        Args:
            days: How far back to look.

        Returns:
            One row per day/feature/model, most recent first.

        Raises:
            ValidationError: If `days` is not positive.
        """
        if days < 1:
            raise ValidationError("days must be positive", field="days", value=days)

        rows = self._conn.execute(
            "SELECT substr(at, 1, 10) AS day, feature, model,"
            "       COUNT(*) AS calls,"
            "       SUM(input_tokens) AS input_tokens,"
            "       SUM(output_tokens) AS output_tokens,"
            "       SUM(cached_tokens) AS cached_tokens,"
            "       SUM(cost_estimate) AS cost_estimate,"
            "       SUM(was_error) AS errors"
            " FROM ai_usage"
            " WHERE at >= ?"
            " GROUP BY day, feature, model"
            " ORDER BY day DESC, feature",
            (_days_ago(days),),
        ).fetchall()

        return [
            UsageRow(
                day=row["day"],
                feature=row["feature"],
                model=row["model"],
                calls=row["calls"],
                input_tokens=row["input_tokens"] or 0,
                output_tokens=row["output_tokens"] or 0,
                cached_tokens=row["cached_tokens"] or 0,
                cost_estimate=round(row["cost_estimate"] or 0.0, 4),
                errors=row["errors"] or 0,
            )
            for row in rows
        ]

    # ── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _check_kind(kind: str) -> None:
        """Reject a kind this application has no implementation for.

        Args:
            kind: The requested kind.

        Raises:
            ValidationError: If it is not implemented.
        """
        if kind not in VALID_KINDS:
            raise ValidationError(
                f"kind must be one of {sorted(VALID_KINDS)}", field="kind", value=kind
            )


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _days_ago(days: int) -> str:
    """Return an ISO-8601 timestamp `days` before now."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86_400))


def _normalise_params_json(value: str) -> str:
    """Validate and canonicalise provider request parameters.

    Args:
        value: A JSON object encoded as text.

    Returns:
        Compact, stable JSON for storage.

    Raises:
        ValidationError: If the value is invalid JSON or is not an object.
    """
    try:
        decoded = json.loads(value or "{}")
    except json.JSONDecodeError as error:
        raise ValidationError(
            f"params_json is not valid JSON: {error.msg}",
            field="params_json",
            value=value,
        ) from error
    if not isinstance(decoded, dict):
        raise ValidationError(
            "params_json must be a JSON object",
            field="params_json",
            value=value,
        )
    return json.dumps(decoded, sort_keys=True, separators=(",", ":"))
