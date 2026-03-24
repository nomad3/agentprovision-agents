-- Gap 02 Phase 2: agent identity profiles for self-model persistence

CREATE TABLE IF NOT EXISTS agent_identity_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_slug VARCHAR(100) NOT NULL,
    role VARCHAR(200) NOT NULL DEFAULT 'general assistant',
    mandate TEXT,
    domain_boundaries JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_tool_classes JSONB NOT NULL DEFAULT '[]'::jsonb,
    denied_tool_classes JSONB NOT NULL DEFAULT '[]'::jsonb,
    escalation_threshold VARCHAR(30) NOT NULL DEFAULT 'medium',
    planning_style VARCHAR(50) NOT NULL DEFAULT 'step_by_step',
    communication_style VARCHAR(50) NOT NULL DEFAULT 'professional',
    risk_posture VARCHAR(30) NOT NULL DEFAULT 'moderate',
    strengths JSONB NOT NULL DEFAULT '[]'::jsonb,
    weaknesses JSONB NOT NULL DEFAULT '[]'::jsonb,
    preferred_strategies JSONB NOT NULL DEFAULT '[]'::jsonb,
    avoided_strategies JSONB NOT NULL DEFAULT '[]'::jsonb,
    operating_principles JSONB NOT NULL DEFAULT '[]'::jsonb,
    success_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_identity_profile
ON agent_identity_profiles(tenant_id, agent_slug);
