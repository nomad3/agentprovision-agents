-- Gap 06 Phase 2: structured collaboration sessions

CREATE TABLE IF NOT EXISTS collaboration_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    blackboard_id UUID NOT NULL REFERENCES blackboards(id) ON DELETE CASCADE,
    pattern VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    current_phase VARCHAR(50) NOT NULL DEFAULT 'propose',
    phase_index INTEGER NOT NULL DEFAULT 0,
    role_assignments JSONB NOT NULL DEFAULT '{}'::jsonb,
    pattern_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome TEXT,
    consensus_reached VARCHAR(10),
    rounds_completed INTEGER NOT NULL DEFAULT 0,
    max_rounds INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_collab_sessions_tenant_status
ON collaboration_sessions(tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_collab_sessions_blackboard
ON collaboration_sessions(blackboard_id);
