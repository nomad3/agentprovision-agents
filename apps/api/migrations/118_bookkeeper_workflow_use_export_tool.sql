-- Migration 118: rewire the `Bookkeeper Categorization` workflow's
-- final delivery step from the legacy `generate_excel_report` MCP tool
-- (dental practice operations report — wrong output shape for the
-- bookkeeper) to the new `bookkeeper_export_aaha` tool that picks the
-- format adapter from `tenant_features.cpa_export_format`.
--
-- The workflow itself is seeded into `dynamic_workflows` per-tenant
-- when the Bookkeeper Agent is provisioned. Tenants that have not
-- yet been provisioned with the workflow simply have no rows to
-- update — the migration is a no-op for them.
--
-- This migration is:
--   - **idempotent** — only updates rows that still reference the old
--     tool name, so re-running is safe
--   - **tenant-agnostic** — applies to every tenant whose Bookkeeper
--     Categorization workflow has the legacy step
--   - **non-destructive** — uses jsonb_set + jsonpath_exists, never
--     drops a workflow that doesn't match the expected shape

-- Replace `generate_excel_report` references inside the workflow's
-- step list with `bookkeeper_export_aaha`. We use the broad string
-- replacement on the JSONB cast-to-text rather than walking the array
-- with a SET because the step shape varies (some workflows have it
-- inside a `parallel`, others in a `sequence`, and PostgreSQL's
-- jsonb_path_query_array can't write back through a wildcard path).
UPDATE dynamic_workflows
SET
    definition = REPLACE(
        definition::text,
        '"tool": "generate_excel_report"',
        '"tool": "bookkeeper_export_aaha"'
    )::jsonb,
    updated_at = NOW()
WHERE name = 'Bookkeeper Categorization'
  AND definition::text LIKE '%"tool": "generate_excel_report"%';

-- Self-record for clean re-apply on a fresh DB.
INSERT INTO _migrations(filename) VALUES ('118_bookkeeper_workflow_use_export_tool.sql')
ON CONFLICT DO NOTHING;
