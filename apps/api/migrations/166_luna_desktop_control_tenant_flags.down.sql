-- 166_luna_desktop_control_tenant_flags.down.sql
BEGIN;

ALTER TABLE tenant_features
    DROP COLUMN IF EXISTS native_control_target_allowlist,
    DROP COLUMN IF EXISTS keyboard_control_enabled,
    DROP COLUMN IF EXISTS pointer_control_enabled,
    DROP COLUMN IF EXISTS desktop_control_enabled;

DELETE FROM _migrations WHERE filename = '166_luna_desktop_control_tenant_flags.sql';

COMMIT;
