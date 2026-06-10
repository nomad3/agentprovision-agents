-- Down for 170 — revert seeded operator allowlist(s) to the fail-closed empty default.
UPDATE tenant_features tf
SET native_control_target_allowlist = '[]'::jsonb
WHERE tf.tenant_id IN (
    SELECT DISTINCT dc.tenant_id
    FROM desktop_commands dc
    WHERE dc.capability IN ('pointer_control', 'keyboard_control')
);
