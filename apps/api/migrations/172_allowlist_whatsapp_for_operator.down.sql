-- Down for 172 — remove net.whatsapp.WhatsApp from the operator allowlist(s).
UPDATE tenant_features tf
SET native_control_target_allowlist = (
    SELECT COALESCE(to_jsonb(array_agg(b ORDER BY b)), '[]'::jsonb)
    FROM jsonb_array_elements_text(tf.native_control_target_allowlist) AS s(b)
    WHERE b <> 'net.whatsapp.WhatsApp'
)
WHERE tf.tenant_id IN (
    SELECT DISTINCT dc.tenant_id
    FROM desktop_commands dc
    WHERE dc.capability IN ('pointer_control', 'keyboard_control')
      AND dc.claimed_at IS NOT NULL
);
