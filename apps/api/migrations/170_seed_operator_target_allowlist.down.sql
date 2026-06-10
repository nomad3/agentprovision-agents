-- Down for 170 — revert seeded operator allowlist(s) to the fail-closed empty
-- default. Scoped to the same actuation-evidence tenant set the up migration
-- touched (claimed_at IS NOT NULL), so it cannot clobber a future tenant that was
-- never seeded by 170.
UPDATE tenant_features tf
SET native_control_target_allowlist = '[]'::jsonb
WHERE tf.tenant_id IN (
    SELECT DISTINCT dc.tenant_id
    FROM desktop_commands dc
    WHERE dc.capability IN ('pointer_control', 'keyboard_control')
      AND dc.claimed_at IS NOT NULL
);
