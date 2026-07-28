"""Build providers from configuration, and route features to them.

The database stores *which* provider serves each feature; the environment stores
the credentials. Keeping those apart is what makes a database leak harmless — a
dump of ``ai_providers`` contains endpoint names and model identifiers, and no
secrets at all.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

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
    IMPORT_MAP = "import_map"


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
    """

    id: int
    name: str
    kind: str
    base_url: str | None
    api_key_env: str
    default_model: str
    is_enabled: bool
    is_third_party_pool: bool

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
        )


def build(config: ProviderConfig, *, model: str | None = None) -> LLMProvider:
    """Construct the provider described by a configuration row.

    Args:
        config: The row.
        model: Model override, from the feature routing table.

    Returns:
        A ready provider.

    Raises:
        LLMError: If the named environment variable is unset. Reported here rather
            than at the first real request, so the admin page can say which
            variable is missing while someone is actually looking at it.
    """
    key = os.environ.get(config.api_key_env, "") if config.api_key_env else ""

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
            " is_enabled, is_third_party_pool FROM ai_providers ORDER BY name"
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
            " is_enabled, is_third_party_pool FROM ai_providers WHERE id = ?",
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
        row = self._conn.execute(
            "SELECT provider_id, model FROM ai_feature_models WHERE feature = ?",
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

        return build(config, model=row["model"])
