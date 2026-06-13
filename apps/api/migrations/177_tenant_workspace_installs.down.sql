-- 177_tenant_workspace_installs.down.sql

BEGIN;

DROP TABLE IF EXISTS tenant_workspace_audit_logs;
DROP TABLE IF EXISTS tenant_workspace_installs;
ALTER TABLE tenant_features DROP COLUMN IF EXISTS native_workspace_packs;

DELETE FROM _migrations WHERE filename = '177_tenant_workspace_installs.sql';

COMMIT;
