-- 043_add_skill_registry.sql
-- Skill registry table for file-based skills (native, custom, community tiers)
CREATE TABLE IF NOT EXISTS skill_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    slug VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    tier VARCHAR(20) NOT NULL DEFAULT 'native',
    category VARCHAR(50) NOT NULL DEFAULT 'general',
    tags JSONB DEFAULT '[]'::jsonb,
    auto_trigger_description TEXT,
    chain_to JSONB DEFAULT '[]'::jsonb,
    engine VARCHAR(20) NOT NULL DEFAULT 'python',
    is_published BOOLEAN DEFAULT FALSE,
    source_repo VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_skill_registry_slug_tenant UNIQUE (slug, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_skill_registry_tenant ON skill_registry(tenant_id);
CREATE INDEX IF NOT EXISTS idx_skill_registry_tier ON skill_registry(tier);
CREATE INDEX IF NOT EXISTS idx_skill_registry_category ON skill_registry(category);
