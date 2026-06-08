-- 164_red_flag_engine_killswitch.sql
--
-- Per-tenant opt-in for the red-flag engine (plan 2026-06-08 §9, PR3).
-- Default FALSE, fail-closed — an autonomous scheduled loop must never run on
-- accident (same discipline as nightly_reflection_enabled).

BEGIN;

ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS red_flag_engine_enabled BOOLEAN NOT NULL DEFAULT FALSE;

INSERT INTO _migrations(filename) VALUES ('164_red_flag_engine_killswitch.sql')
ON CONFLICT DO NOTHING;

COMMIT;
