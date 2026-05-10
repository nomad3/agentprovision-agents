-- Migration 121: resilient CLI orchestrator feature flags.
--
-- Adds two boolean columns to `tenant_features` to gate the Phase 2
-- cutover for the resilient CLI orchestrator (the new ResilientExecutor +
-- ProviderAdapter chain walker — design doc
-- docs/plans/2026-05-09-resilient-cli-orchestrator-design.md).
--
-- Why two flags, not one:
--
--   1. `use_resilient_executor` (default FALSE)
--      The hard gate. When TRUE, `agent_router` builds an
--      ExecutionRequest and calls ResilientExecutor.execute(req)
--      instead of the legacy chain-walk loop. When FALSE, the
--      legacy path runs (zero behavior change). Cutover plan:
--      flip TRUE on internal tenants, observe ≥99.5% shadow-mode
--      agreement for 48h, ramp pilot tenants, then ramp fleet-wide.
--
--   2. `shadow_mode_real_dispatch` (default FALSE)
--      Fine-grained sub-flag for the flag-OFF shadow path. When
--      FALSE (default), the cli_session_manager flag-off shadow
--      runs against a stubbed adapter that REPLAYS the legacy
--      outcome — no real Temporal dispatch, no real LLM call.
--      That's the cheap, mass-deployable path used to estimate
--      classifier agreement at production scale without burning
--      2x cost. When TRUE (used for ~48h on a single internal
--      tenant during validation), the shadow runs the REAL
--      ResilientExecutor against the same Temporal/LLM backend so
--      we can measure end-to-end behavior delta.
--
-- Migration is:
--   - **idempotent** — uses ADD COLUMN IF NOT EXISTS, safe to re-run
--   - **tenant-agnostic** — applies to every tenant
--   - **non-breaking** — defaults FALSE preserve legacy behavior

ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS use_resilient_executor BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS shadow_mode_real_dispatch BOOLEAN NOT NULL DEFAULT FALSE;

-- Self-record so re-applying this migration on a fresh DB is a clean no-op.
INSERT INTO _migrations(filename) VALUES ('121_tenant_features_resilient_executor.sql')
ON CONFLICT DO NOTHING;
