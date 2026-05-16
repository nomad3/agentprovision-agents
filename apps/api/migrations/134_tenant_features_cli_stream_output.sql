-- Migration 134: cli_stream_output feature flag.
--
-- Gates the Claude Code `--output-format stream-json --verbose` rollout
-- per plan docs/plans/2026-05-16-terminal-full-cli-output.md §9. When
-- TRUE, the code-worker streams every Claude event (reasoning, tool_use,
-- tool_result, result.*) live into the terminal card. When FALSE
-- (default), the worker keeps using `--output-format json` and only
-- the existing lifecycle echoes appear.
--
-- Default OFF in prod. Seeded ON for the saguilera1608@gmail.com test
-- tenant so the new path can soak with a real user before fleet-wide
-- ramp.
--
-- Idempotent — safe to re-run.

BEGIN;

ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS cli_stream_output BOOLEAN NOT NULL DEFAULT FALSE;

-- Seed the saguilera test tenant ON. The user table is keyed on email;
-- the tenant_features row is per-tenant. Cascade through users to
-- find the right tenant_id, then upsert the flag. NO-OP if the user
-- doesn't exist (fresh DB / different env).
--
-- INSERT…ON CONFLICT instead of UPDATE-only (review I4) so tenants
-- whose tenant_features row hasn't been provisioned yet still get
-- the flag flipped on. DISTINCT guards against multi-row email
-- duplicates surfacing the same tenant_id twice.
INSERT INTO tenant_features (tenant_id, cli_stream_output)
SELECT DISTINCT tenant_id, TRUE
  FROM users
 WHERE email = 'saguilera1608@gmail.com'
ON CONFLICT (tenant_id) DO UPDATE
   SET cli_stream_output = TRUE;

-- Record migration application.
INSERT INTO _migrations(filename) VALUES ('134_tenant_features_cli_stream_output.sql')
ON CONFLICT DO NOTHING;

COMMIT;
