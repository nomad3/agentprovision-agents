-- Down for 171 — drop the perception-redaction columns + index.
DROP INDEX IF EXISTS ix_perception_artifacts_redaction_pickup;
ALTER TABLE perception_artifacts
    DROP COLUMN IF EXISTS redacted_storage_path,
    DROP COLUMN IF EXISTS redacted_at,
    DROP COLUMN IF EXISTS raw_deleted_at,
    DROP COLUMN IF EXISTS redaction_meta,
    DROP COLUMN IF EXISTS redact_claimed_at,
    DROP COLUMN IF EXISTS redact_claimed_by,
    DROP COLUMN IF EXISTS redact_attempts;
