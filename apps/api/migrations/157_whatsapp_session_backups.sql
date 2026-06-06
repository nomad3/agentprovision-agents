-- 157_whatsapp_session_backups.sql
--
-- WhatsApp session durability — rolling known-good backups.
-- Design: docs/plans/2026-06-02-whatsapp-session-durability-design.md
--
-- The neonize device session is an on-disk SQLite file persisted to
-- channel_accounts.session_blob (a single gzip blob). That single field
-- is the corruption trap: today _save_session_to_db overwrites it even
-- when the pre-save checkpoint failed (the "corruption amplifier"), and
-- _restore_session_from_db rehydrates whatever bytes are there with no
-- validation — so one bad write round-trips straight back to a forced
-- QR re-pair (terrible UX for customer tenants who must physically
-- re-link their phone).
--
-- This table holds N rolling *validated* snapshots so a corrupt or
-- mid-write current blob can always fall back to the last known-good
-- copy. Contract (see design §2/§3):
--
--   * Only a blob that passed PRAGMA integrity_check + the device-key
--     assertion is written here with validation_status = 'ok'.
--   * Restore order is current → newest 'ok' backup → next → … . A QR is
--     reached only if EVERY copy fails (effectively never) or the device
--     was genuinely revoked by WhatsApp.
--   * channel_accounts.session_blob stays the "current" pointer; this
--     table is the recovery tier.
--
-- Pruning to the last N 'ok' rows per (tenant_id, account_id) is owned
-- by the writer (_save_session_to_db), not a DB trigger — same janitor
-- discipline as migration 137.
--
-- Wrapped in BEGIN/COMMIT (same pattern as migrations 133/136/137) so a
-- failure on the index/comment after a successful CREATE TABLE doesn't
-- leave a half-applied state when run via `docker exec psql` per
-- ~/.claude/.../migration_apply_pattern.md.

BEGIN;

CREATE TABLE IF NOT EXISTS whatsapp_session_backups (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- ON DELETE CASCADE: tearing down a tenant rips its session backups
    -- too (same precedent as chat_jobs / session_events).
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_id          VARCHAR(64) NOT NULL DEFAULT 'default',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- gzip-compressed neonize SQLite snapshot, validated before insert.
    blob                BYTEA NOT NULL,
    -- sha256 of the *raw* (decompressed) SQLite bytes — lets the writer
    -- skip inserting a duplicate snapshot when nothing changed.
    sha256              VARCHAR(64) NOT NULL,
    size_bytes          INTEGER NOT NULL,
    -- Only 'ok' rows are restore candidates. 'pending'/'corrupt' are
    -- reserved for future diagnostics; the writer only ever inserts 'ok'.
    validation_status   VARCHAR(16) NOT NULL DEFAULT 'ok',
    -- What triggered the snapshot: 'shutdown' / 'connected' /
    -- 'disconnected' / 'pair' / 'heartbeat' / 'runtime'.
    source_event        VARCHAR(32) NULL,
    CONSTRAINT whatsapp_session_backups_validation_check
        CHECK (validation_status IN ('ok', 'pending', 'corrupt'))
);

-- Newest-first restore + prune scan: WHERE tenant_id = ? AND account_id = ?
-- AND validation_status = 'ok' ORDER BY created_at DESC.
CREATE INDEX IF NOT EXISTS idx_wa_session_backups_acct_created
    ON whatsapp_session_backups(tenant_id, account_id, created_at DESC);

INSERT INTO _migrations(filename) VALUES ('157_whatsapp_session_backups.sql')
ON CONFLICT DO NOTHING;

COMMIT;
