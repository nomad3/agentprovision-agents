-- 160_desktop_command_nonce_tenant_scope.sql
--
-- Scope Luna desktop command idempotency nonces by tenant. The previous
-- partial unique index on nonce alone could let one tenant collide with
-- another tenant's retry key.

BEGIN;

DROP INDEX IF EXISTS idx_desktop_commands_nonce;

CREATE UNIQUE INDEX IF NOT EXISTS idx_desktop_commands_tenant_nonce
    ON desktop_commands(tenant_id, nonce) WHERE nonce IS NOT NULL;

INSERT INTO _migrations(filename) VALUES ('160_desktop_command_nonce_tenant_scope.sql')
ON CONFLICT DO NOTHING;

COMMIT;
