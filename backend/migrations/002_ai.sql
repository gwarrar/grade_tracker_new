-- AI provider configuration, per-feature routing, usage accounting and the
-- insight cache.

-- A configured LLM endpoint.
--
-- `api_key_env` holds the NAME of an environment variable, never the key itself.
-- A database leak therefore exposes no credentials, and there is no encryption
-- scheme to design, rotate or get wrong. The trade-off is that adding a provider
-- means editing .env and restarting; that is the right trade for a self-hosted app.
CREATE TABLE ai_providers (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT NOT NULL,
    kind                 TEXT NOT NULL,   -- which LLMProvider subclass drives it
    base_url             TEXT,            -- NULL for the vendor default
    api_key_env          TEXT NOT NULL DEFAULT '',
    default_model        TEXT NOT NULL,
    is_enabled           INTEGER NOT NULL DEFAULT 1,

    -- Marks providers that route requests through third-party free pools whose data
    -- retention terms are unknown. This application holds student names, emails and
    -- grades. The admin UI shows a privacy warning wherever this is set.
    is_third_party_pool  INTEGER NOT NULL DEFAULT 0,

    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at           TEXT,

    CHECK (kind IN ('anthropic', 'openai_compatible'))
);

CREATE UNIQUE INDEX idx_ai_providers_name ON ai_providers (name);

-- Which provider and model serves each feature.
--
-- Separated from `ai_providers` because the features have genuinely different needs:
-- the command palette is latency-critical and wants a small fast model, while insight
-- narratives are quality-critical and want the strongest one. Pinning both to a single
-- provider default would make one of them wrong.
CREATE TABLE ai_feature_models (
    feature     TEXT PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES ai_providers (id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    effort      TEXT NOT NULL DEFAULT 'medium',
    updated_at  TEXT,

    CHECK (feature IN ('ask', 'insight', 'command', 'import')),
    CHECK (effort IN ('low', 'medium', 'high', 'xhigh', 'max'))
);

-- Per-call accounting, so /admin/ai can show what the AI features actually cost.
CREATE TABLE ai_usage (
    id             INTEGER PRIMARY KEY,
    feature        TEXT NOT NULL,
    provider_id    INTEGER REFERENCES ai_providers (id) ON DELETE SET NULL,
    model          TEXT NOT NULL,
    user_id        INTEGER REFERENCES users (id) ON DELETE SET NULL,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cached_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_estimate  REAL    NOT NULL DEFAULT 0.0,
    latency_ms     INTEGER NOT NULL DEFAULT 0,
    was_error      INTEGER NOT NULL DEFAULT 0,
    at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX idx_ai_usage_at      ON ai_usage (at);
CREATE INDEX idx_ai_usage_feature ON ai_usage (feature, at);

-- Generated narratives, keyed by a hash of the statistics they describe.
--
-- Regeneration is driven by the data changing, not by a clock: the same numbers always
-- produce the same insight, so re-billing for them is waste. Recording a new grade
-- changes the hash and the next request regenerates.
CREATE TABLE ai_insights (
    entity_type    TEXT NOT NULL,          -- 'student' | 'course' | 'summary'
    entity_id      TEXT NOT NULL,
    stats_sha256   TEXT NOT NULL,
    locale         TEXT NOT NULL DEFAULT 'en',
    payload_json   TEXT NOT NULL,
    model          TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),

    -- Locale is part of the key: the same numbers rendered in German are a different
    -- cached artefact, not a cache hit.
    PRIMARY KEY (entity_type, entity_id, locale),
    CHECK (entity_type IN ('student', 'course', 'summary'))
);
