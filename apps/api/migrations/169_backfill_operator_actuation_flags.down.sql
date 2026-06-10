-- Down for 169 — revert operator actuation flags to fail-closed OFF.
UPDATE tenant_features tf
SET pointer_control_enabled = false,
    keyboard_control_enabled = false
WHERE tf.tenant_id IN (
    SELECT DISTINCT dc.tenant_id
    FROM desktop_commands dc
    WHERE dc.capability IN ('pointer_control', 'keyboard_control')
);
