"""Build providers from configuration, and route features to them.

The database stores *which* provider serves each feature; the environment stores
the credentials. Keeping those apart is what makes a database leak harmless — a
dump of ``ai_providers`` contains endpoint names and model identifiers, and no
secrets at all.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from llm.anthropic_provider import AnthropicProvider
from llm.base import LLMError, LLMProvider
from llm.openai_compatible_provider import OpenAICompatibleProvider


class Feature(StrEnum):
    """An AI-backed capability that can be routed independently.

    Separate routing exists because the features have genuinely different needs:
    the command palette is latency-critical and wants a small fast model, while
    insight narratives are quality-critical and want the strongest one. Pinning
    both to one default would make one of them wrong.
    """

    ASK = "ask"
    INSIGHT = "insight"
    COMMAND = "command"
    IMPORT_MAP = "import"  # matches the CHECK constraint on ai_feature_models


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """One row of ``ai_providers``.

    Attributes:
        id: Primary key.
        name: Display name, unique.
        kind: Which implementation drives it.
        base_url: Endpoint override, or None for the vendor default.
        api_key_env: The **name** of the environment variable holding the key.
            Never the key.
        default_model: Model used when a feature does not pin one.
        is_enabled: Disabled providers are configuration kept for later, not
            candidates.
        is_third_party_pool: Routes through third parties with unknown retention.
        params_json: Extra request-body keys for this endpoint, as JSON. Vendor knobs
            such as ``temperature`` or NVIDIA's ``chat_template_kwargs`` live here so
            that adding one is configuration rather than a migration.
    """

    id: int
    name: str
    kind: str
    base_url: str | None
    api_key_env: str
    default_model: str
    is_enabled: bool
    is_third_party_pool: bool
    params_json: str = "{}"

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ProviderConfig:
        """Build a config from a database row.

        Args:
            row: A row of ``ai_providers``.

        Returns:
            The typed configuration.
        """
        return cls(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            base_url=row["base_url"],
            api_key_env=row["api_key_env"],
            default_model=row["default_model"],
            is_enabled=bool(row["is_enabled"]),
            is_third_party_pool=bool(row["is_third_party_pool"]),
            params_json=row["params_json"],
        )


def parse_params(config: ProviderConfig) -> dict[str, Any]:
    """Decode a provider's configured request-body parameters.

    Args:
        config: The row.

    Returns:
        The decoded object, empty when unset.

    Raises:
        LLMError: If the stored value is not a JSON **object**. Raised at construction
            so the admin page's Test connection reports it while someone is looking,
            rather than at whatever hour the first real request happens.
    """
    if not config.params_json.strip():
        return {}
    try:
        value = json.loads(config.params_json)
    except json.JSONDecodeError as error:
        raise LLMError(
            f"params_json is not valid JSON: {error}",
            code="AI_BAD_PARAMS",
            provider=config.name,
        ) from error
    if not isinstance(value, dict):
        raise LLMError(
            f"params_json must be a JSON object, got {type(value).__name__}",
            code="AI_BAD_PARAMS",
            provider=config.name,
        )
    return value


def build(
    config: ProviderConfig, *, model: str | None = None, effort: str = "medium"
) -> LLMProvider:
    """Construct the provider described by a configuration row.

    Args:
        config: The row.
        model: Model override, from the feature routing table.
        effort: Reasoning effort, also from the routing table. Applied here rather
            than passed to :meth:`~llm.base.LLMProvider.chat`, because no caller has
            a reason to vary it per call — the routing row is where that decision is
            configured, and a parameter nobody would use is a parameter to maintain
            for nothing.

    Returns:
        A ready provider.

    Raises:
        LLMError: If the named environment variable is unset, or the configured
            parameters are not a JSON object. Reported here rather than at the first
            real request, so the admin page can say what is wrong while someone is
            actually looking at it.
    """
    key = os.environ.get(config.api_key_env, "") if config.api_key_env else ""
    params = parse_params(config)

    match config.kind:
        case "anthropic":
            if not key:
                raise LLMError(
                    f"environment variable {config.api_key_env} is not set",
                    code="AI_KEY_MISSING",
                    provider=config.name,
                )
            return AnthropicProvider(
                name=config.name,
                model=model or config.default_model,
                api_key=key,
                base_url=config.base_url,
                params=params,
                effort=effort,
            )

        case "openai_compatible":
            # No key requirement: a local endpoint such as Ollama authenticates
            # nothing, and demanding a credential would make the most private
            # option the hardest to configure.
            return OpenAICompatibleProvider(
                name=config.name,
                model=model or config.default_model,
                api_key=key,
                base_url=config.base_url,
                params=params,
                effort=effort,
            )

        case _:
            raise LLMError(
                f"unknown provider kind {config.kind!r}",
                code="AI_UNKNOWN_KIND",
                provider=config.name,
            )


class Registry:
    """Resolves a feature to the provider configured to serve it."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialise the registry.

        Args:
            conn: The database connection to read configuration from.
        """
        self._conn = conn

    def providers(self) -> list[ProviderConfig]:
        """List every configured provider, enabled or not.

        Returns:
            All rows of ``ai_providers``, ordered by name.
        """
        rows = self._conn.execute(
            "SELECT id, name, kind, base_url, api_key_env, default_model,"
            " is_enabled, is_third_party_pool, params_json FROM ai_providers ORDER BY name"
        ).fetchall()
        return [ProviderConfig.from_row(row) for row in rows]

    def get(self, provider_id: int) -> ProviderConfig:
        """Fetch one provider's configuration.

        Args:
            provider_id: Primary key.

        Returns:
            The configuration.

        Raises:
            LLMError: If no such provider exists.
        """
        row = self._conn.execute(
            "SELECT id, name, kind, base_url, api_key_env, default_model,"
            " is_enabled, is_third_party_pool, params_json FROM ai_providers WHERE id = ?",
            (provider_id,),
        ).fetchone()
        if row is None:
            raise LLMError(f"no provider with id {provider_id}", code="AI_PROVIDER_NOT_FOUND")
        return ProviderConfig.from_row(row)

    def resolve(self, feature: Feature) -> LLMProvider:
        """Build the provider that serves a feature.

        Args:
            feature: Which capability is asking.

        Returns:
            A ready provider.

        Raises:
            LLMError: If the feature has no routing, or its provider is disabled.
        """
        # `effort` is selected here, which it was not before: the column was written
        # by the admin page, validated, displayed, and then never read — so the
        # setting had no effect on anything. It reaches the provider below.
        row = self._conn.execute(
            "SELECT provider_id, model, effort FROM ai_feature_models WHERE feature = ?",
            (feature.value,),
        ).fetchone()

        if row is None:
            raise LLMError(
                f"no provider configured for {feature.value}",
                code="AI_NOT_CONFIGURED",
            )

        config = self.get(row["provider_id"])
        if not config.is_enabled:
            # Fails rather than silently falling back. A disabled provider still
            # routing traffic is the kind of surprise that makes an admin page
            # untrustworthy.
            raise LLMError(
                f"provider {config.name} is disabled",
                code="AI_PROVIDER_DISABLED",
                provider=config.name,
            )

        return build(config, model=row["model"], effort=row["effort"] or "medium")
