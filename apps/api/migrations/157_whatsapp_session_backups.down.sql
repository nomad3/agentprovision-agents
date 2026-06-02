-- 157_whatsapp_session_backups.down.sql
--
-- Manual rollback for 157_whatsapp_session_backups.sql. Drops the rolling
-- session-backup table. The current session lives in
-- channel_accounts.session_blob and is untouched, so dropping this table
-- only removes the recovery tier (a corrupt current blob would then fall
-- back to a QR re-pair again). Run only if you are intentionally reverting
-- the durability feature.
--
-- Remember to also delete the _migrations row so the up-migration can
-- re-apply: DELETE FROM _migrations WHERE filename = '157_whatsapp_session_backups.sql';

BEGIN;

DROP TABLE IF EXISTS whatsapp_session_backups;

DELETE FROM _migrations WHERE filename = '157_whatsapp_session_backups.sql';

COMMIT;
