-- Migration 117: Wire the Multi-Site Revenue Sync workflow to the real
-- pulse_query_invoices MCP tool, AND update the Pet Health Concierge
-- persona to call pulse_get_patient when the client is authenticated.
--
-- Originally the workflow was created with a placeholder
-- query_data_source step against the legacy 'covetrus_pulse' data source
-- (pre-Pulse-Connect-partner-program), and the persona had a "Pulse hooks
-- marked TODO" line. Now that pulse_get_patient + pulse_list_appointments
-- + pulse_query_invoices exist, swap the placeholder and the persona TODO.
--
-- Idempotent: each UPDATE has a guard ensuring it only fires when the
-- old text is still present. Safe to re-run.
--
-- Tenant-scoped (Animal Doctor SOC) per the PR #324 review pattern — never
-- match by `name` alone, since template installs may seed identically-named
-- workflows on other tenants.

-- ── 1) Multi-Site Revenue Sync workflow → use pulse_query_invoices ─────────
UPDATE dynamic_workflows
SET
    definition = '{
      "trigger": {"type": "cron", "config": {"schedule": "0 7 * * *", "timezone": "America/Los_Angeles"}},
      "steps": [
        {
          "id": "pull_pulse_daily",
          "type": "mcp_tool",
          "tool": "pulse_query_invoices",
          "params": {
            "date_range": "1d",
            "limit": 500
          }
        },
        {
          "id": "consolidate",
          "type": "mcp_tool",
          "tool": "generate_insights",
          "params": {
            "datasets": ["${pull_pulse_daily.output.totals_by_location}"],
            "kind": "daily_multi_site_revenue_summary",
            "context": "Three veterinary hospitals on a single Covetrus Pulse instance. The input is pre-rolled per-location revenue + appointment counts + per-service-type splits from pulse_query_invoices. Surface per-location revenue, appointment count, top services, and notable deltas vs trailing-7-day average. Cc the practice COO on Monday weekly digest."
          }
        },
        {
          "id": "deliver_to_owner",
          "type": "agent",
          "agent": "luna",
          "prompt": "Deliver this morning''s consolidated multi-site revenue summary to the practice owner via WhatsApp in your warm-COO style. Lead with totals, then per-location, then anomalies. Cc the practice COO on Monday weekly digest. Data: ${consolidate.output}"
        }
      ]
    }'::jsonb,
    updated_at = NOW()
WHERE id = '6cbeff40-cd77-4955-bc19-c5a27a7b0e82'
  AND tenant_id = '7f632730-1a38-41f1-9f99-508d696dbcf1'
  AND definition::text ILIKE '%query_data_source%';


-- ── 2) Pet Health Concierge persona → real Pulse hooks ────────────────────
-- Replace the TODO trailer with the actual tool list + a
-- when-authenticated instruction. Idempotent via the ILIKE guard.
UPDATE agents
SET
    persona_prompt = REPLACE(
        persona_prompt,
        '- (Pulse hooks marked TODO — wired when API research lands)',
        '- pulse_get_patient — Covetrus Pulse chart (vaccines, current Rx, allergies, weight history, diagnoses, last visit). When the client is authenticated, call this FIRST and surface allergies + current Rx in your reply. If Pulse is unreachable (error response), fall back to the unauthenticated triage flow without exposing the failure to the client.
- pulse_list_appointments — schedule lookup for booking conflicts and recent-visit context
- pulse_query_invoices — recent billing line items (used sparingly; never quote prices in chat)'
    )
WHERE tenant_id = '7f632730-1a38-41f1-9f99-508d696dbcf1'
  AND id = 'f2455598-374a-4e76-a3b7-7894aed1e10f'
  AND persona_prompt ILIKE '%Pulse hooks marked TODO%';

-- Also drop the stale "research-blocked; for now reference Pulse via a single
-- data source named 'covetrus_pulse'" line — those data-source semantics are
-- replaced by the partner API. Idempotent.
UPDATE agents
SET
    persona_prompt = REPLACE(
        persona_prompt,
        'location_id = anaheim | buena_park | mission_viejo. (Pulse API access is
research-blocked; for now reference Pulse via a single data source named
''covetrus_pulse'', not 3 separate PMS sources.)',
        'location_id = anaheim | buena_park | mission_viejo. The Covetrus
Pulse Connect partner API is wired (pulse_get_patient, pulse_list_appointments,
pulse_query_invoices). Each tool accepts a location_id filter and the
tenant credential carries an optional location_ids allowlist that scopes
queries to the practice''s real locations.'
    )
WHERE tenant_id = '7f632730-1a38-41f1-9f99-508d696dbcf1'
  AND id = 'f2455598-374a-4e76-a3b7-7894aed1e10f'
  AND persona_prompt LIKE '%research-blocked%';


-- ── Self-record migration ─────────────────────────────────────────────────
-- Per the convention followed by 110/111/112/113/114/115/116 and the
-- migration_apply_pattern memory note.
INSERT INTO _migrations(filename) VALUES ('118_pulse_revenue_sync_wiring.sql')
ON CONFLICT DO NOTHING;
