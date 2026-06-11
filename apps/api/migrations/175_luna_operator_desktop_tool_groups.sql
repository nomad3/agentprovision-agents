-- 175_luna_operator_desktop_tool_groups.sql
--
-- Grant Simon's operator Luna agents the already-registered desktop-control
-- tool groups. This does not enable native actuation by itself: the API tenant
-- gates, bundle allowlist, Luna Tauri shell claim path, and approval/envelope
-- boundaries still apply. It only makes the governed MCP tools visible to the
-- operator Luna agent runtime so prompts can reach the proven dry-run loop.

BEGIN;

UPDATE agents
SET tool_groups =
        COALESCE(tool_groups, '[]'::jsonb)
        || CASE
            WHEN COALESCE(tool_groups, '[]'::jsonb) ? 'desktop_observe'
                THEN '[]'::jsonb
            ELSE '["desktop_observe"]'::jsonb
        END
        || CASE
            WHEN COALESCE(tool_groups, '[]'::jsonb) ? 'desktop_control'
                THEN '[]'::jsonb
            ELSE '["desktop_control"]'::jsonb
        END,
    tool_groups_review_required = FALSE
WHERE tenant_id = '752626d9-8b2c-4aa2-87ef-c458d48bd38a'
  AND name IN ('Luna', 'Luna Supervisor');

INSERT INTO _migrations(filename) VALUES ('175_luna_operator_desktop_tool_groups.sql')
ON CONFLICT DO NOTHING;

COMMIT;
