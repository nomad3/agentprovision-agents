-- Gap 01 Phase 2: conflict detection and freshness decay

-- Add dispute reason to assertions
ALTER TABLE world_state_assertions
ADD COLUMN IF NOT EXISTS dispute_reason VARCHAR(500);

-- Add dispute tracking to snapshots
ALTER TABLE world_state_snapshots
ADD COLUMN IF NOT EXISTS disputed_attributes JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE world_state_snapshots
ADD COLUMN IF NOT EXISTS disputed_count INTEGER NOT NULL DEFAULT 0;

-- Index for efficient dispute queries
CREATE INDEX IF NOT EXISTS idx_wsa_tenant_disputed
ON world_state_assertions(tenant_id, subject_slug)
WHERE status = 'disputed';
