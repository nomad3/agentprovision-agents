-- Gap 01 Phase 3: causal graph linking actions to outcomes

CREATE TABLE IF NOT EXISTS causal_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cause_type VARCHAR(50) NOT NULL,
    cause_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    cause_summary VARCHAR(500) NOT NULL,
    effect_type VARCHAR(50) NOT NULL,
    effect_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    effect_summary VARCHAR(500) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    mechanism TEXT,
    observation_count INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(30) NOT NULL DEFAULT 'hypothesis',
    source_assertion_id UUID REFERENCES world_state_assertions(id),
    agent_slug VARCHAR(100),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_causal_edges_tenant_cause
ON causal_edges(tenant_id, cause_type, cause_summary);

CREATE INDEX IF NOT EXISTS idx_causal_edges_tenant_effect
ON causal_edges(tenant_id, effect_type, effect_summary);

CREATE INDEX IF NOT EXISTS idx_causal_edges_tenant_status
ON causal_edges(tenant_id, status)
WHERE status IN ('hypothesis', 'corroborated', 'confirmed');
