-- Down migration for 114_user_preferences_value_json.sql
-- Backfill any NULL `value` rows (from gesture_bindings) before restoring NOT NULL.

UPDATE user_preferences SET value = '' WHERE value IS NULL;

ALTER TABLE user_preferences
  ALTER COLUMN value SET NOT NULL;

ALTER TABLE user_preferences
  DROP CONSTRAINT IF EXISTS user_preferences_value_json_size_cap;

ALTER TABLE user_preferences
  DROP COLUMN IF EXISTS value_json;

DELETE FROM _migrations WHERE filename = '114_user_preferences_value_json.sql';
