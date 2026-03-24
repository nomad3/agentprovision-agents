-- 053: Safety governance phase 2
-- Persist evidence packs for sensitive governed actions.

CREATE TABLE IF NOT EXISTS safety_evidence_packs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    action_type VARCHAR(50) NOT NULL,
    action_name VARCHAR(150) NOT NULL,
    channel VARCHAR(50) NOT NULL,
    decision VARCHAR(30) NOT NULL,
    decision_source VARCHAR(50) NOT NULL,
    risk_class VARCHAR(50) NOT NULL,
    risk_level VARCHAR(20) NOT NULL,
    evidence_required BOOLEAN NOT NULL DEFAULT false,
    evidence_sufficient BOOLEAN NOT NULL DEFAULT false,
    world_state_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    recent_observations JSONB NOT NULL DEFAULT '[]'::jsonb,
    assumptions JSONB NOT NULL DEFAULT '[]'::jsonb,
    uncertainty_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    proposed_action JSONB NOT NULL DEFAULT '{}'::jsonb,
    expected_downside TEXT,
    context_summary TEXT,
    context_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    agent_slug VARCHAR(100),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_safety_evidence_packs_tenant
    ON safety_evidence_packs(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_safety_evidence_packs_action
    ON safety_evidence_packs(tenant_id, action_type, action_name, channel);
