-- 164_red_flag_engine_killswitch.down.sql
BEGIN;
ALTER TABLE tenant_features DROP COLUMN IF EXISTS red_flag_engine_enabled;
DELETE FROM _migrations WHERE filename = '164_red_flag_engine_killswitch.sql';
COMMIT;
