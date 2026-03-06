-- Migration 037: Memory activities - Luna's audit log
-- Tracks all memory-related events: entity extraction, memory creation,
-- action triggers, recalls, etc.

CREATE TABLE IF NOT EXISTS memory_activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    source VARCHAR(50),
    metadata JSONB,
    entity_id UUID REFERENCES knowledge_entities(id) ON DELETE SET NULL,
    memory_id UUID REFERENCES agent_memories(id) ON DELETE SET NULL,
    workflow_run_id VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_activities_tenant ON memory_activities(tenant_id);
CREATE INDEX IF NOT EXISTS idx_memory_activities_type ON memory_activities(event_type);
CREATE INDEX IF NOT EXISTS idx_memory_activities_created ON memory_activities(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_activities_tenant_created ON memory_activities(tenant_id, created_at DESC);
