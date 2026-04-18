-- Add password reset token columns to users table

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR,
  ADD COLUMN IF NOT EXISTS password_reset_expires TIMESTAMP;

INSERT INTO _migrations (name) VALUES ('092_add_password_reset_to_users')
ON CONFLICT DO NOTHING;
