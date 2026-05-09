-- Migration 116: rename competitor-agent references from "Harriet" to "Herriot".
--
-- Background: when we provisioned The Animal Doctor SOC tenant on
-- 2026-05-08 we seeded knowledge entities + persona prompts that referred
-- to Modern Animal's competitor AI agent as "Harriet" — the spelling used
-- in the discovery-call transcript. The 2026-05-09 research deep-dive
-- (docs/research/2026-05-09-modern-animal-harriet-sierra.md) verified
-- against Sierra's own customer page that the agent is actually named
-- **Herriot** (after James Herriot, the British vet author). Code review
-- of PR #320 independently confirmed the spelling.
--
-- This migration converges every persisted reference. It is:
--   - **idempotent** — uses simple text replacement, re-running is a no-op
--   - **tenant-agnostic** — applies to every tenant that has the seeded
--     entities, not just The Animal Doctor SOC, since the data model is
--     the same across any tenant we seed with the same vet-vertical
--     bootstrap.
--   - **safe** — only updates rows whose name/description literally
--     contains the spelling we want to fix; doesn't mass-edit content.
--
-- See PR #320 (Modern Animal research) for the original verification and
-- PR cleanup that surfaced the rename.

-- 1. The standalone competitor entity itself.
UPDATE knowledge_entities
SET
    name = 'Herriot (Modern Animal AI)',
    description = REPLACE(description, 'Harriet', 'Herriot'),
    updated_at = NOW()
WHERE name = 'Harriet (Modern Animal AI)';

-- 2. The Modern Animal entity description that mentions Harriet.
UPDATE knowledge_entities
SET
    description = REPLACE(description, '''Harriet''', '''Herriot'''),
    updated_at = NOW()
WHERE name = 'Modern Animal'
  AND description LIKE '%Harriet%';

-- 3. The Sierra AI entity description that mentions Harriet.
UPDATE knowledge_entities
SET
    description = REPLACE(description, 'Harriet', 'Herriot'),
    updated_at = NOW()
WHERE name = 'Sierra AI'
  AND description LIKE '%Harriet%';

-- 4. Any agent persona prompt that mentions Harriet — primarily the
--    Pet Health Concierge whose persona was authored before the
--    correction landed. Tenant-agnostic UPDATE because the persona is
--    structurally identical across tenants and the only legitimate
--    "Harriet" reference is the competitor name we're correcting.
--    NOTE: agents table has no updated_at column; the migration relies
--    on the row's natural mtime via persona-content change for audit.
UPDATE agents
SET persona_prompt = REPLACE(persona_prompt, 'Harriet', 'Herriot')
WHERE persona_prompt LIKE '%Harriet%';

-- Self-record this migration so re-apply on a fresh DB is a clean no-op.
INSERT INTO _migrations(filename) VALUES ('116_harriet_to_herriot_rename.sql')
ON CONFLICT DO NOTHING;
