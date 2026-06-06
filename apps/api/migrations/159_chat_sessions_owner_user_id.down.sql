-- 159_chat_sessions_owner_user_id.down.sql

BEGIN;

DROP INDEX IF EXISTS idx_chat_sessions_owner_user_id;

ALTER TABLE chat_sessions
    DROP COLUMN IF EXISTS owner_user_id;

DELETE FROM _migrations WHERE filename = '159_chat_sessions_owner_user_id.sql';

COMMIT;
