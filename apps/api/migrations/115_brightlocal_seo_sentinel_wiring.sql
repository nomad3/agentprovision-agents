-- Migration 115: Wire the BrightLocal SEO Sentinel workflow to the real
-- MCP tool. The workflow was originally created with a placeholder
-- `query_data_source brightlocal` step (PR seeding the vet vertical).
-- Now that `brightlocal_rank_changes` and `brightlocal_competitor_check`
-- exist as real MCP tools we replace the placeholder.
--
-- Idempotent: only updates rows whose first step still points at the
-- placeholder. Safe to re-run.

UPDATE dynamic_workflows
SET
    definition = '{
      "trigger": {"type": "cron", "config": {"schedule": "0 8 * * *", "timezone": "America/Los_Angeles"}},
      "steps": [
        {
          "id": "poll_brightlocal",
          "type": "mcp_tool",
          "tool": "brightlocal_rank_changes",
          "params": {"since_days": 1, "min_delta": 1}
        },
        {
          "id": "check_competitors",
          "type": "mcp_tool",
          "tool": "brightlocal_competitor_check",
          "params": {}
        },
        {
          "id": "analyze_gaps",
          "type": "agent",
          "agent": "seo_optimizer_agent",
          "prompt": "Analyze this 24h BrightLocal pull. For any tracked keyword that dropped >2 positions OR where a competitor surged into top-3, surface the gap and draft a content/keyword adjustment. Tag each finding with target location and service. Return JSON list. Rank changes: ${poll_brightlocal.output}. Competitor positions: ${check_competitors.output}"
        },
        {
          "id": "draft_cms_update",
          "type": "agent",
          "agent": "seo_optimizer_agent",
          "prompt": "For each gap from ${analyze_gaps.output}, draft the exact CMS edit (page URL, before/after copy, image alt-tag changes). Return as a human-reviewable change list — DO NOT push to CMS. Owner/COO approves before push."
        },
        {
          "id": "summary",
          "type": "agent",
          "agent": "luna",
          "prompt": "Daily SEO sentinel summary. Lead with losses, then competitor moves, then draft fixes. Cc the practice COO on Monday weekly digest. Data: ${draft_cms_update.output}"
        }
      ]
    }'::jsonb,
    updated_at = NOW()
-- IMPORTANT (PR #324 review fix): scope by explicit (tenant_id, id) instead
-- of `name = 'BrightLocal SEO Sentinel'`. The previous filter would have
-- matched the row across all tenants if any other tenant ever installed a
-- workflow with that exact name (e.g. via template install). The
-- personalized prompt content was tenant-specific and would have leaked.
-- The personalized strings are now generic ("the practice COO") so even if
-- this fires elsewhere it doesn't carry Animal Doctor SOC details, but the
-- scoping itself is the real fix.
WHERE id = 'aba6a728-c711-41de-9921-d35c5423349c'
  AND tenant_id = '7f632730-1a38-41f1-9f99-508d696dbcf1'
  AND definition::text ILIKE '%query_data_source%';

-- Self-record this migration so re-apply on a fresh DB is a clean no-op.
-- Per the convention followed by 110/111/112/113/114 and the
-- migration_apply_pattern memory note.
INSERT INTO _migrations(filename) VALUES ('115_brightlocal_seo_sentinel_wiring.sql')
ON CONFLICT DO NOTHING;
