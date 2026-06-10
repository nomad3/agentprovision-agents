-- 172_allowlist_whatsapp_for_operator.sql
-- Goal: let Luna operate the WhatsApp desktop app (net.whatsapp.WhatsApp) via the
-- computer-use stack — "type a message + Enter to send" — the first REAL app beyond
-- the fixed canary. Adds the WhatsApp bundle to the operator/canary tenant's
-- per-tenant native_control_target_allowlist.
--
-- The effective target allowlist is per-tenant ∩ global floor, so the floor env
-- DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST must ALSO include net.whatsapp.WhatsApp
-- (operational change in PRODUCTION.env) for the actuation to be authorized.
--
-- Data-derived to the actuating operator tenant(s) (same evidence as migrations
-- 169/170: a claimed native-control command). Idempotent — the UNION dedups.

UPDATE tenant_features tf
SET native_control_target_allowlist = (
    SELECT to_jsonb(array_agg(DISTINCT b ORDER BY b))
    FROM (
        SELECT jsonb_array_elements_text(tf.native_control_target_allowlist) AS b
        UNION
        SELECT 'net.whatsapp.WhatsApp' AS b
    ) s
)
WHERE tf.tenant_id IN (
    SELECT DISTINCT dc.tenant_id
    FROM desktop_commands dc
    WHERE dc.capability IN ('pointer_control', 'keyboard_control')
      AND dc.claimed_at IS NOT NULL
);
