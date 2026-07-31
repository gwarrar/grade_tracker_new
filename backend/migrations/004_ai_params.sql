-- Per-provider generation parameters.
--
-- One JSON column rather than a column each for temperature, top_p and the rest.
-- Every vendor adds its own knobs -- NVIDIA NIM wants
-- `chat_template_kwargs: {thinking, reasoning_effort}`, others want `seed` or
-- `repetition_penalty` -- and a column per knob is a migration per vendor.
--
-- What goes in here is exactly "extra keys in this endpoint's request body". Note
-- that `extra_body` in the OpenAI SDK is an SDK affordance, not a wire concept: this
-- codebase posts raw JSON with httpx, so what the SDK spells
-- `extra_body={"chat_template_kwargs": {...}}` is simply top-level payload keys, and
-- there is nothing to wrap.
--
-- The value is applied at provider *construction*, never per call, which is what
-- keeps the agent loop and the four AI features from ever branching on a provider.
-- A denylist in the provider drops keys that would replace the conversation itself
-- (model, messages, tools, response_format, stream) -- a typo in an admin's JSON
-- must not be able to do that.

ALTER TABLE ai_providers ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}';
