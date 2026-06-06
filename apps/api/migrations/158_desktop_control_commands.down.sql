-- 158_desktop_control_commands.down.sql
--
-- Rollback for the Luna desktop-control command queue + audit spine.
-- Drops audit rows and queued commands; run only when intentionally reverting
-- the development-phase desktop-control feature.

BEGIN;

DROP TABLE IF EXISTS desktop_command_events;
DROP TABLE IF EXISTS desktop_commands;

DELETE FROM _migrations WHERE filename = '158_desktop_control_commands.sql';

COMMIT;
