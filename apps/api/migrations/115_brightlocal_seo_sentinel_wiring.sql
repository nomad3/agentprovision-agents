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
          "prompt": "Daily SEO sentinel summary for Dr. Castillo. Lead with losses, then competitor moves, then draft fixes. Cc Taylor on Monday weekly digest. Data: ${draft_cms_update.output}"
        }
      ]
    }'::jsonb,
    updated_at = NOW()
WHERE name = 'BrightLocal SEO Sentinel'
  AND definition::text ILIKE '%query_data_source%';
