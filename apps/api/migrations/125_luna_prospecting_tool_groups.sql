-- Migration 125 — give Luna agents the tool_groups required for sales /
-- market-intelligence work. Specifically:
--
--   * web_research — web_search, fetch_url, discover_companies
--     (lands with the same PR; powers the leads-list use case)
--   * knowledge    — create_entity, find_entities, record_observation,
--     etc. Needed to persist the leads Luna discovers as knowledge-
--     graph rows the user can browse later.
--   * sales        — qualify_lead, update_pipeline_stage, draft_outreach
--     etc. Lets Luna score + advance prospects without delegating to
--     the Sales Agent for every lead.
--   * competitor   — list/add/remove competitor + monitor controls.
--     Useful when the user asks Luna to compare prospects against a
--     known competitor set.
--
-- We do NOT add `email` or `bookings` here — outreach should remain
-- explicit (user-initiated) until the agent_policy gate is wired for
-- the workflow channel.
--
-- Idempotent: uses jsonb || semantics with a dedup pass to avoid
-- doubling up if the migration is re-applied.

UPDATE agents
SET tool_groups = (
    SELECT jsonb_agg(DISTINCT v ORDER BY v)
    FROM jsonb_array_elements_text(
        COALESCE(tool_groups, '[]'::jsonb)
        || '["web_research", "knowledge", "sales", "competitor"]'::jsonb
    ) AS t(v)
)
WHERE LOWER(name) LIKE '%luna%';
