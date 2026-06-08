-- 165_luna_add_commitments_tool_group.down.sql
--
-- Reverse: strip `commitments` from Luna-named agents' tool_groups.
-- jsonb `-` removes the element by value; no-op if absent.

BEGIN;

UPDATE agents
SET tool_groups = COALESCE(tool_groups, '[]'::jsonb) - 'commitments'
WHERE name ILIKE '%luna%'
  AND COALESCE(tool_groups, '[]'::jsonb) @> '["commitments"]'::jsonb;

DELETE FROM _migrations WHERE filename = '165_luna_add_commitments_tool_group.sql';

COMMIT;
