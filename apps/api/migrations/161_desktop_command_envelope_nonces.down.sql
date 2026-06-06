-- 161_desktop_command_envelope_nonces.down.sql

BEGIN;

DROP TABLE IF EXISTS desktop_command_envelope_nonces;
DELETE FROM _migrations WHERE filename = '161_desktop_command_envelope_nonces.sql';

COMMIT;
