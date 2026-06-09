-- 167_perception_artifacts.sql
-- Luna Phase 5.2 — Governed Perception Transport, PR2 of 4
--
-- Quarantine registry for governed screenshot "observation" artifacts. The
-- bytes themselves live on an API-ONLY volume (OBSERVATION_QUARANTINE_ROOT,
-- never the agent-shared workspaces volume); this row is the metadata + cleanup
-- handle. P5.2 is TRANSPORT ONLY: nothing reads the bytes (no retrieval route of
-- any kind) until the P5.3 validator + redactor land. `redaction_status` is
-- always 'not_planner_safe' in P5.2.
--
-- Design: docs/plans/2026-06-09-luna-phase5.2-governed-perception-design.md

CREATE TABLE IF NOT EXISTS perception_artifacts (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id              UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    shell_id                VARCHAR(96) NOT NULL,
    device_id               UUID REFERENCES device_registry(id) ON DELETE SET NULL,
    artifact_type           VARCHAR(32) NOT NULL DEFAULT 'screenshot',
    storage_path            TEXT NOT NULL,
    sha256                  VARCHAR(64) NOT NULL,
    size_bytes              BIGINT NOT NULL,
    redaction_status        VARCHAR(32) NOT NULL DEFAULT 'not_planner_safe',
    source_window_bundle_id VARCHAR(255),
    expires_at              TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_perception_artifacts_tenant ON perception_artifacts (tenant_id);
CREATE INDEX IF NOT EXISTS ix_perception_artifacts_session ON perception_artifacts (session_id);
-- Cleanup scan: live (not-yet-deleted) artifacts past their TTL.
CREATE INDEX IF NOT EXISTS ix_perception_artifacts_expiry
    ON perception_artifacts (expires_at)
    WHERE deleted_at IS NULL;
