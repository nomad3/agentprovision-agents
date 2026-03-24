-- Phase 3: trust-aware autonomy for governed execution

CREATE TABLE IF NOT EXISTS agent_trust_profiles (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_slug VARCHAR(100) NOT NULL,
    trust_score DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    autonomy_tier VARCHAR(40) NOT NULL DEFAULT 'recommend_only',
    reward_signal DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    provider_signal DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    rated_experience_count INTEGER NOT NULL DEFAULT 0,
    provider_review_count INTEGER NOT NULL DEFAULT 0,
    rationale TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_trust_profile
ON agent_trust_profiles(tenant_id, agent_slug);

CREATE INDEX IF NOT EXISTS idx_agent_trust_profiles_tenant_score
ON agent_trust_profiles(tenant_id, trust_score DESC);
