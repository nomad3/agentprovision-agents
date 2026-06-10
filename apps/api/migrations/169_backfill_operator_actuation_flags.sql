-- 169_backfill_operator_actuation_flags.sql
-- PR4b: native-control actuation is now gated by per-tenant
-- pointer_control_enabled / keyboard_control_enabled (fail-closed, default OFF),
-- re-checked at enqueue AND claim. Backfill those flags for the operator/canary
-- tenant(s) so the already-live, validated desktop canary keeps working under the
-- new enforcement (design §6: "the enforcement deploy backfills the operator
-- tenant's flags" — preserve the canary in the SAME deploy as enforcement).
--
-- Data-derived (no hardcoded tenant UUID, drift-free): a tenant that has already
-- issued native-control commands IS, by definition, an actuating operator tenant.
-- Today that is exactly one tenant; every other tenant stays fail-closed OFF.
--
-- Each flag is set from its OWN class of evidence (Codex/Luna review): a tenant
-- that only ever issued pointer commands gets pointer enabled but NOT keyboard —
-- we grant exactly what each tenant actually exercised, never more. The global
-- bundle allowlist (env floor) is unchanged, so target scope is unaffected.

UPDATE tenant_features tf
SET pointer_control_enabled = EXISTS (
        SELECT 1 FROM desktop_commands dc
        WHERE dc.tenant_id = tf.tenant_id AND dc.capability = 'pointer_control'
    ),
    keyboard_control_enabled = EXISTS (
        SELECT 1 FROM desktop_commands dc
        WHERE dc.tenant_id = tf.tenant_id AND dc.capability = 'keyboard_control'
    )
WHERE tf.tenant_id IN (
    SELECT DISTINCT dc.tenant_id
    FROM desktop_commands dc
    WHERE dc.capability IN ('pointer_control', 'keyboard_control')
);
