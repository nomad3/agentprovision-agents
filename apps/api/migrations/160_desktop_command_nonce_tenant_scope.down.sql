-- 160_desktop_command_nonce_tenant_scope.down.sql

BEGIN;

DROP INDEX IF EXISTS idx_desktop_commands_tenant_nonce;

CREATE UNIQUE INDEX IF NOT EXISTS idx_desktop_commands_nonce
    ON desktop_commands(nonce) WHERE nonce IS NOT NULL;

DELETE FROM _migrations WHERE filename = '160_desktop_command_nonce_tenant_scope.sql';

COMMIT;
