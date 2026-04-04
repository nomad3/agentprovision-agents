-- Migration 082: Add agent-driven runtime fields
-- Supports: model tier routing, tool group scoping, memory domain filtering, escalation

ALTER TABLE agents ADD COLUMN IF NOT EXISTS tool_groups JSONB;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS default_model_tier VARCHAR(10) DEFAULT 'full';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS persona_prompt TEXT;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS memory_domains JSONB;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS escalation_agent_id UUID REFERENCES agents(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_agents_tool_groups ON agents USING GIN(tool_groups);
CREATE INDEX IF NOT EXISTS idx_agents_memory_domains ON agents USING GIN(memory_domains);
CREATE INDEX IF NOT EXISTS idx_agents_escalation_id ON agents(escalation_agent_id);
