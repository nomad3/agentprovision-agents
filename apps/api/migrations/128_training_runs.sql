-- 128_training_runs.sql
--
-- Tracks the initial-training pass that `alpha quickstart` + the web
-- /onboarding/* flow run when a new tenant connects a wedge channel.
-- Each row represents one bulk ingestion (Local AI CLI / Gmail+Calendar /
-- Slack / WhatsApp / etc.) of raw items into the knowledge graph.
--
-- Lifecycle:
--   pending   → row inserted at POST /memory/training/bulk-ingest
--   running   → TrainingIngestionWorkflow has picked up the work
--   complete  → all items processed successfully
--   failed    → workflow surfaced an unrecoverable error (see `error`)
--
-- Idempotency: (tenant_id, snapshot_id) is unique. Re-POSTing the same
-- snapshot returns the existing row instead of creating a duplicate
-- workflow run.
--
-- See: docs/plans/2026-05-11-ap-quickstart-design.md §7.1-7.2.

CREATE TABLE IF NOT EXISTS training_runs (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source          VARCHAR(32) NOT NULL,
    snapshot_id     UUID NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    items_total     INTEGER NOT NULL DEFAULT 0,
    items_processed INTEGER NOT NULL DEFAULT 0,
    error           TEXT NULL,
    workflow_id     VARCHAR(128) NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    started_at      TIMESTAMP NULL,
    completed_at    TIMESTAMP NULL
);

-- The deduplication key for `POST /bulk-ingest` — same snapshot
-- re-posted by a CLI/web retry should reuse the existing run, not
-- spawn a parallel workflow. Tenant scoping ensures snapshot_id
-- collisions across tenants don't conflict.
CREATE UNIQUE INDEX IF NOT EXISTS uq_training_runs_tenant_snapshot
    ON training_runs (tenant_id, snapshot_id);

-- The status-lookup index for `GET /memory/training/{id}` and for
-- the workflow's progress queries. Active runs cluster at the top.
CREATE INDEX IF NOT EXISTS idx_training_runs_tenant_status
    ON training_runs (tenant_id, status, created_at DESC);

COMMENT ON COLUMN training_runs.source IS
    'Wedge channel: local_ai_cli | github_cli | gmail | calendar | slack | whatsapp.';
COMMENT ON COLUMN training_runs.snapshot_id IS
    'Client-generated idempotency key. Same (tenant_id, snapshot_id) → same row, never a parallel workflow.';
COMMENT ON COLUMN training_runs.workflow_id IS
    'Temporal workflow_id for forensic queries — `TrainingIngestionWorkflow-<run_id>`.';

INSERT INTO _migrations(filename) VALUES ('128_training_runs.sql')
ON CONFLICT DO NOTHING;
