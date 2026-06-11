-- 173_luna_background_control_flag.sql
-- Phase 5 background app-control gets its own per-tenant actuation gate.
-- Default FALSE / fail-closed for every tenant. Operator/canary tenants that
-- have already claimed native-control commands are backfilled so the first
-- background-control dry-run can use the same tenant lane as pointer/keyboard.

BEGIN;

ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS background_control_enabled BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE tenant_features tf
SET background_control_enabled = TRUE
WHERE tf.tenant_id IN (
    SELECT DISTINCT dc.tenant_id
    FROM desktop_commands dc
    WHERE dc.capability IN ('pointer_control', 'keyboard_control')
      AND dc.claimed_at IS NOT NULL
);

INSERT INTO _migrations(filename) VALUES ('173_luna_background_control_flag.sql')
ON CONFLICT DO NOTHING;

COMMIT;
