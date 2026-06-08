-- 165_luna_add_commitments_tool_group.sql
--
-- Grant Luna the new `commitments` tool_group so she can DRIVE the
-- Accountable Learning & Commitment System (plan 2026-06-08) rather than
-- only seeing open commitments pre-loaded in recalled context. The group
-- exposes the 5 MCP tools registered in
-- apps/mcp-server/src/mcp_tools/commitments.py:
--   commitment_create, commitment_complete, commitment_list_open,
--   commitment_scan_red_flags, learning_artifact_write
--
-- Why this migration exists: PRs A–D shipped the schema, proof-gated
-- service, red-flag engine, internal endpoints, MCP tools, and the web
-- operator surface — but the tools were not mapped to any tool_group, so
-- resolve_tool_names(agent.tool_groups) excluded them from every agent's
-- CLI --allowedTools and the code-worker hook hard-blocked them. Net
-- effect: "Luna is the lead / drives it" (plan north star) did not hold.
-- This migration + the registry entry (services/tool_groups.py) +
-- the bundled luna/skill.md frontmatter close that gap together.
--
-- Idempotent append (jsonb `||` guarded by `NOT @>`), unlike migration
-- 156's exact-shape WHERE — existing Luna rows have drifted (some carry
-- `luna_learn`, etc.), so an exact match would silently skip them. The
-- containment guard makes re-runs a no-op and tolerates any prior shape.
-- Scoped to Luna-named agents (the assistant + supervisor) across tenants;
-- new agents pick the group up from the bundled skill.md frontmatter.
--
-- tool_groups_review_required is NOT touched (operator-curated expansion,
-- same posture as migrations 154/156).

BEGIN;

UPDATE agents
SET tool_groups = COALESCE(tool_groups, '[]'::jsonb) || '["commitments"]'::jsonb
WHERE name ILIKE '%luna%'
  AND NOT (COALESCE(tool_groups, '[]'::jsonb) @> '["commitments"]'::jsonb);

INSERT INTO _migrations(filename) VALUES ('165_luna_add_commitments_tool_group.sql')
ON CONFLICT DO NOTHING;

COMMIT;
