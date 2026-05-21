-- Migration 144: value-layer kill-switch + value-set version uniqueness.
--
-- Per docs/plans/2026-05-21-luna-value-layer-design.md §4.3.
--
-- Two changes in one migration:
--
-- 1) tenant_features.value_layer_enabled — per-tenant gate for the
--    5 consultation points. Default OFF so adoption is opt-in.
--    Same shape as migration 142 (nightly_reflection_enabled).
--
-- 2) Unique partial index on (tenant_id, agent_id, version) for
--    memory_type='value_set' rows. The value-set substrate is
--    append-only with monotonic version (see design §4.1). A
--    concurrent writer collision is rare in Phase 1 (operator-only
--    writes) but the index makes it cleanly detectable so the
--    writer can retry with version+1 instead of silently winning.
--
-- Idempotent — safe to re-run.

ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS value_layer_enabled BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN tenant_features.value_layer_enabled IS
    'Gate for the value layer (consult engine, 5 consultation points). '
    'Default OFF; operators flip per tenant after seeding their value '
    'set. When FALSE, every consult() call returns allow/kill_switch_off. '
    'Locked design decision: design doc §6 + §10 PR 3.';

-- The value-set body is JSON-serialized text in agent_memories.content.
-- A monotonic version field lives inside that JSON; we pull it out
-- via the cast and uniqueness-constrain (tenant, agent, version) for
-- value_set rows only.
--
-- Concurrent writers that pick the same target version race here and
-- one of them gets a duplicate-key error — the writer retries with
-- version+1. Operator-only writes in Phase 1 means this is mostly
-- defensive; Phase 2 reflection-derived proposals make it real.
CREATE UNIQUE INDEX IF NOT EXISTS uq_value_set_version
    ON agent_memories (
        tenant_id,
        agent_id,
        ((content::jsonb ->> 'version')::int)
    )
    WHERE memory_type = 'value_set';
