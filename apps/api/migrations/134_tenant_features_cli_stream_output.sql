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
--
-- History:
--   2026-05-16  initial UPDATE-only seed
--   2026-05-16  PR #523: switched to INSERT…ON CONFLICT with
--               id=gen_random_uuid() to cover tenants with no
--               tenant_features row yet (review I4).
--   2026-05-16  PR #524: reverted to UPDATE-only. The INSERT path
--               hit `rl_settings NOT NULL no default` even though
--               ON CONFLICT (tenant_id) would have routed to UPDATE
--               — Postgres validates the candidate INSERT row's
--               column constraints BEFORE conflict resolution. The
--               saguilera test tenant always has a features row
--               (created lazily by `get_or_create_features` on
--               first auth), so UPDATE-only is sufficient. Tenants
--               without rows simply land on the default `FALSE`
--               until their next features access creates the row.

BEGIN;

ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS cli_stream_output BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE tenant_features SET cli_stream_output = TRUE
 WHERE tenant_id IN (SELECT tenant_id FROM users WHERE email = 'saguilera1608@gmail.com');

-- Record migration application.
INSERT INTO _migrations(filename) VALUES ('134_tenant_features_cli_stream_output.sql')
ON CONFLICT DO NOTHING;

COMMIT;
