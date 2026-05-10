-- Down-migration for 121_tenant_features_resilient_executor.sql.
-- Drops the two flag columns added by the up-migration.

ALTER TABLE tenant_features
    DROP COLUMN IF EXISTS use_resilient_executor;

ALTER TABLE tenant_features
    DROP COLUMN IF EXISTS shadow_mode_real_dispatch;

DELETE FROM _migrations WHERE filename = '121_tenant_features_resilient_executor.sql';
