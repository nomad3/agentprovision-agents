-- Down for 168_enable_desktop_perception.sql — revert to fail-closed default OFF.
ALTER TABLE tenant_features ALTER COLUMN desktop_control_enabled SET DEFAULT false;
UPDATE tenant_features SET desktop_control_enabled = false;
