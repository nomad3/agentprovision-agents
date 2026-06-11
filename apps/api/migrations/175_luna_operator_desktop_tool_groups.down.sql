-- 175_luna_operator_desktop_tool_groups.down.sql

BEGIN;

UPDATE agents AS a
SET tool_groups = COALESCE(
    (
        SELECT jsonb_agg(to_jsonb(value) ORDER BY ord)
        FROM jsonb_array_elements_text(COALESCE(a.tool_groups, '[]'::jsonb))
             WITH ORDINALITY AS elems(value, ord)
        WHERE value NOT IN ('desktop_observe', 'desktop_control')
    ),
    '[]'::jsonb
)
WHERE a.tenant_id = '752626d9-8b2c-4aa2-87ef-c458d48bd38a'
  AND a.name IN ('Luna', 'Luna Supervisor')
  AND COALESCE(a.tool_groups, '[]'::jsonb) ?| ARRAY['desktop_observe', 'desktop_control'];

DELETE FROM _migrations WHERE filename = '175_luna_operator_desktop_tool_groups.sql';

COMMIT;
