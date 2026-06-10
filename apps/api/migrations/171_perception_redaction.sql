-- 171_perception_redaction.sql
-- Luna Phase 5.3a — perception redactor: the first CONTROLLED reader of the P5.2
-- quarantine produces a planner-safe (redacted) artifact. Adds the redacted-bytes
-- pointer, the atomic-transition bookkeeping (raw_deleted_at is a PREREQUISITE of
-- planner_safe — raw + redacted never coexist), the byte-free redaction audit, and
-- the worker lease/recovery fields. `redaction_status` is a plain String column
-- (no enum/check) so the new values 'redacting' + 'planner_safe' need no DDL.

ALTER TABLE perception_artifacts
    ADD COLUMN IF NOT EXISTS redacted_storage_path TEXT,
    ADD COLUMN IF NOT EXISTS redacted_at           TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS raw_deleted_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS redaction_meta         JSONB,
    ADD COLUMN IF NOT EXISTS redact_claimed_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS redact_claimed_by      TEXT,
    ADD COLUMN IF NOT EXISTS redact_attempts        INTEGER NOT NULL DEFAULT 0;

-- The redactor worker claims fresh artifacts ordered by created_at; this partial
-- index keeps that scan cheap as the table grows.
CREATE INDEX IF NOT EXISTS ix_perception_artifacts_redaction_pickup
    ON perception_artifacts (created_at)
    WHERE deleted_at IS NULL AND redaction_status IN ('not_planner_safe', 'redacting');
