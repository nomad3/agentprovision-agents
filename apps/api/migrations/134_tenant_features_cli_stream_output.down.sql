-- Down-migration for 134_tenant_features_cli_stream_output.sql.

ALTER TABLE tenant_features
    DROP COLUMN IF EXISTS cli_stream_output;

DELETE FROM _migrations WHERE filename = '134_tenant_features_cli_stream_output.sql';
