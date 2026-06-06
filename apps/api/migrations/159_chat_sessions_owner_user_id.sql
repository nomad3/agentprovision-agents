-- 159_chat_sessions_owner_user_id.sql
--
-- Add an explicit owner for user-visible chat sessions. Desktop-control
-- command requests use this as a prerequisite before any live macOS content
-- can be returned to an MCP/tool caller.

BEGIN;

ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS owner_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner_user_id
    ON chat_sessions(owner_user_id)
    WHERE owner_user_id IS NOT NULL;

-- Preserve existing single-user tenants without guessing in multi-user tenants.
WITH tenant_users AS (
    SELECT
        tenant_id,
        id AS user_id,
        COUNT(*) OVER (PARTITION BY tenant_id) AS user_count
    FROM users
),
single_tenant_users AS (
    SELECT tenant_id, user_id
    FROM tenant_users
    WHERE user_count = 1
)
UPDATE chat_sessions AS session
SET owner_user_id = single_user.user_id
FROM single_tenant_users AS single_user
WHERE session.tenant_id = single_user.tenant_id
  AND session.owner_user_id IS NULL;

INSERT INTO _migrations(filename) VALUES ('159_chat_sessions_owner_user_id.sql')
ON CONFLICT DO NOTHING;

COMMIT;
