-- 109 — `vw_fabrication_candidates` view.
--
-- Joins assistant chat_messages with tool_calls in a +/-90s tenant-scoped
-- time window. A row qualifies as a "fabrication candidate" when:
--   - the response is substantive (>= 200 chars)
--   - zero tool_calls fired in the surrounding window
--   - no failed tool calls captured stderr-side either
--   (i.e. Luna produced specific output without grounding it in any tool result)
--
-- The view is purely diagnostic — read-only joins over existing tables.
-- Drop and recreate with CREATE OR REPLACE to make the migration replayable.
--
-- Pair with scripts/fabrication_report.py for a tenant-grouped summary.

CREATE OR REPLACE VIEW vw_fabrication_candidates AS
SELECT
    cs.tenant_id,
    cm.id AS message_id,
    cm.session_id,
    cm.created_at,
    LENGTH(cm.content) AS resp_chars,
    cm.context->>'platform' AS platform,
    cm.context->>'agent_slug' AS agent_slug,
    LEFT(cm.content, 240) AS response_preview,
    -- failures observed via stderr (PR #175 capture)
    jsonb_array_length(COALESCE((cm.context->>'tools_called')::jsonb, '[]'::jsonb))
        AS stderr_tool_errors,
    -- successes + failures observed server-side (PR #178/#180 audit)
    (SELECT COUNT(*) FROM tool_calls tc
        WHERE tc.tenant_id = cs.tenant_id
          AND tc.started_at BETWEEN cm.created_at - INTERVAL '90 seconds'
                                AND cm.created_at + INTERVAL '5 seconds')
        AS audit_tool_calls
FROM chat_messages cm
JOIN chat_sessions cs ON cs.id = cm.session_id
WHERE cm.role = 'assistant'
  AND LENGTH(cm.content) >= 200;

COMMENT ON VIEW vw_fabrication_candidates IS
    'Diagnostic — assistant turns with their tool-grounding signals. Filter where audit_tool_calls=0 AND stderr_tool_errors=0 to get fabrication candidates. Time-window join is approximate; precise per-turn correlation needs session_id threading through MCP.';
