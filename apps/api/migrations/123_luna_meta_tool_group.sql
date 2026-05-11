-- Migration 123: Add `meta` tool group to every existing Luna agent.
--
-- Why: Luna replies "I couldn't access the live MCP registry" when asked
-- questions like "list my agents" because her tool_groups
-- (typically ["knowledge", "email"]) do not include the platform
-- introspection MCP tools (find_agent, list_dynamic_workflows,
-- list_skills, list_mcp_servers, discover_mcp_tools, read_library_skill).
--
-- The new `meta` group is defined in apps/api/app/services/tool_groups.py
-- and is now added to new Luna agents on tenant register (services/users.py).
-- This migration backfills the same change to every existing Luna across
-- every tenant.
--
-- Idempotent:
--   * NULL tool_groups → set to ["meta"]
--   * already contains "meta" → no-op
--   * else → append "meta"

UPDATE agents
SET tool_groups = (
    CASE
        WHEN tool_groups IS NULL THEN '["meta"]'::jsonb
        WHEN tool_groups @> '["meta"]'::jsonb THEN tool_groups
        ELSE tool_groups || '["meta"]'::jsonb
    END
)
WHERE name = 'Luna' OR name ILIKE 'luna%';

-- Self-record so re-applying this migration on a fresh DB is a clean no-op.
INSERT INTO _migrations(filename) VALUES ('123_luna_meta_tool_group.sql')
ON CONFLICT DO NOTHING;
