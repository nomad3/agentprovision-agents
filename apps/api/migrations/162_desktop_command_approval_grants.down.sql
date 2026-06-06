-- 162_desktop_command_approval_grants.down.sql

BEGIN;

DROP INDEX IF EXISTS idx_desktop_commands_approval;
DROP INDEX IF EXISTS idx_desktop_command_approval_grants_active_command;
ALTER TABLE desktop_commands
    DROP COLUMN IF EXISTS approval_id;

DROP TABLE IF EXISTS desktop_command_approval_grants;

DELETE FROM _migrations WHERE filename = '162_desktop_command_approval_grants.sql';

COMMIT;
