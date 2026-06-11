-- 173_luna_background_control_flag.down.sql

ALTER TABLE tenant_features
    DROP COLUMN IF EXISTS background_control_enabled;
