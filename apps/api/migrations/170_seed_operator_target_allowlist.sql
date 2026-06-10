-- 170_seed_operator_target_allowlist.sql
-- PR4c: the desktop target allowlist is now PER-TENANT (effective = per-tenant
-- tenant_features.native_control_target_allowlist ∩ global env floor), and an
-- EMPTY per-tenant list DENIES all targets (fail-closed). Every tenant currently
-- has [] (the default), so once PR4c enforcement lands the operator/canary tenant
-- would be denied unless its allowlist is seeded — in the SAME deploy as the
-- enforcement (mirrors migration 169's operator-flag backfill).
--
-- Data-derived (drift-free, no hardcoded UUID, no hardcoded bundle list): seed
-- each actuating tenant's allowlist with the DISTINCT target bundle_ids it has
-- actually issued native-control (pointer/keyboard) commands against. Today that
-- is exactly one tenant targeting com.agentprovision.luna + com.apple.TextEdit.
-- Every other tenant stays at [] = deny-all. The effective list is still capped by
-- the global env floor at enforcement time, so this can never widen beyond it.

UPDATE tenant_features tf
SET native_control_target_allowlist = COALESCE((
        SELECT to_jsonb(array_agg(DISTINCT bundle ORDER BY bundle))
        FROM (
            SELECT dc.payload->'target'->>'bundle_id' AS bundle
            FROM desktop_commands dc
            WHERE dc.tenant_id = tf.tenant_id
              AND dc.capability IN ('pointer_control', 'keyboard_control')
              AND dc.payload->'target'->>'bundle_id' IS NOT NULL
        ) b
    ), '[]'::jsonb)
WHERE tf.tenant_id IN (
    SELECT DISTINCT dc.tenant_id
    FROM desktop_commands dc
    WHERE dc.capability IN ('pointer_control', 'keyboard_control')
);
