-- Down-migration for 117_tenant_features_cpa_export_format.sql.
-- Rolls back the `cpa_export_format` column on `tenant_features`.

ALTER TABLE tenant_features
    DROP COLUMN IF EXISTS cpa_export_format;

DELETE FROM _migrations WHERE filename = '117_tenant_features_cpa_export_format.sql';
