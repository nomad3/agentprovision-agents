-- Migration 124 — strip stray `null` entries from agents.tool_groups,
-- agents.memory_domains, agents.capabilities.
--
-- Why: PR #368 (Luna meta tool_group) + earlier seeds wrote rows shaped
-- like `[null, "meta"]` into tool_groups via different code paths that
-- preserved the source list's null sentinel. The Pydantic
-- `List[str]` schema on agent.py rejects nulls, which made
-- `GET /api/v1/agents` 500 with ResponseValidationError. The schema now
-- has a `field_validator` that strips nulls at read time, but cleaning
-- the persisted data avoids every read paying the validator cost and
-- makes downstream queries (LIKE / GIN index lookups for "meta")
-- behave intuitively.
--
-- Applied manually on the production DB 2026-05-11 against the
-- Animal Doctor SOC tenant's Luna General Assistant agent — this
-- migration is the durable backfill so the cleanup survives pipeline
-- redeploys.

UPDATE agents
SET tool_groups = (
    SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
    FROM jsonb_array_elements(tool_groups) elem
    WHERE elem != 'null'::jsonb
)
WHERE tool_groups IS NOT NULL
  AND jsonb_typeof(tool_groups) = 'array'
  AND tool_groups @> '[null]'::jsonb;

UPDATE agents
SET memory_domains = (
    SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
    FROM jsonb_array_elements(memory_domains) elem
    WHERE elem != 'null'::jsonb
)
WHERE memory_domains IS NOT NULL
  AND jsonb_typeof(memory_domains) = 'array'
  AND memory_domains @> '[null]'::jsonb;

UPDATE agents
SET capabilities = (
    SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
    FROM jsonb_array_elements(capabilities) elem
    WHERE elem != 'null'::jsonb
)
WHERE capabilities IS NOT NULL
  AND jsonb_typeof(capabilities) = 'array'
  AND capabilities @> '[null]'::jsonb;
