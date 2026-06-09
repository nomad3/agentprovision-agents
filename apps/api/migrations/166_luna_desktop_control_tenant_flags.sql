-- 166_luna_desktop_control_tenant_flags.sql
--
-- Per-tenant gating for Luna macOS computer-use (desktop control). PR4a of the
-- 2026-06-09 productionization plan. All default FALSE / empty, fail-closed —
-- native OS actuation is the highest-blast-radius capability on the platform
-- and must never enable on accident (same discipline as nightly_reflection_enabled
-- and red_flag_engine_enabled). NOTHING reads these columns yet; enforcement,
-- the governance tool-group split, and the operator-tenant backfill land in PR4b.
-- This migration is therefore zero-behavior-change.
--
--   desktop_control_enabled          master kill-switch (also gates observation)
--   pointer_control_enabled          Phase 3 pointer actuation
--   keyboard_control_enabled         Phase 4 keyboard actuation
--   native_control_target_allowlist  per-tenant bundle allowlist; effective list
--                                    = per-tenant ∩ global platform floor (PR4b)

BEGIN;

ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS desktop_control_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pointer_control_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS keyboard_control_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS native_control_target_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb;

INSERT INTO _migrations(filename) VALUES ('166_luna_desktop_control_tenant_flags.sql')
ON CONFLICT DO NOTHING;

COMMIT;
