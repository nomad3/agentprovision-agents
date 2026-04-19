-- Migration: 101_chat_sessions_agent_id
-- Refactor: AgentKit → Agent consolidation (pivoted from ADK).
-- Steps:
--   1. Add chat_sessions.agent_id column (FK to agents)
--   2. For each AgentKit without a matching Agent (same tenant + name),
--      synthesize an Agent row from the kit's config
--   3. Backfill chat_sessions.agent_id via name match
--   4. Leave agent_kit_id column and agent_kits table in place as deprecated
--      (drop deferred to a later migration once no code references them)

ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS agent_id UUID REFERENCES agents(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_chat_sessions_agent_id ON chat_sessions(agent_id);

INSERT INTO agents (
    id, tenant_id, name, description, config,
    persona_prompt, capabilities, tool_groups, default_model_tier,
    status, version, role, autonomy_level, max_delegation_depth
)
SELECT
    gen_random_uuid(),
    ak.tenant_id,
    ak.name,
    ak.description,
    ((COALESCE(ak.config::jsonb, '{}'::jsonb)) - 'model' - 'base_model' - 'primary_objective' - 'skill_slug')::json,
    COALESCE(ak.config::jsonb ->> 'system_prompt', ak.config::jsonb ->> 'primary_objective', ''),
    CASE
        WHEN ak.config::jsonb ? 'tools' AND jsonb_typeof(ak.config::jsonb -> 'tools') = 'array'
            THEN (ak.config::jsonb -> 'tools')::json
        ELSE '[]'::json
    END,
    '[]'::jsonb,
    'full',
    'production',
    1,
    CASE WHEN ak.kit_type = 'hierarchy' THEN 'supervisor' ELSE NULL END,
    'supervised',
    2
FROM agent_kits ak
WHERE NOT EXISTS (
    SELECT 1 FROM agents a
    WHERE a.tenant_id = ak.tenant_id
      AND LOWER(a.name) = LOWER(ak.name)
);

UPDATE chat_sessions cs
SET agent_id = a.id
FROM agent_kits ak
JOIN agents a ON a.tenant_id = ak.tenant_id AND LOWER(a.name) = LOWER(ak.name)
WHERE cs.agent_kit_id = ak.id
  AND cs.agent_id IS NULL;

INSERT INTO _migrations(filename) VALUES ('101_chat_sessions_agent_id') ON CONFLICT DO NOTHING;
