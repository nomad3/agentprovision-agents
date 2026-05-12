-- Migration 047: Add CLI orchestrator feature flags
ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS cli_orchestrator_enabled BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS default_cli_platform VARCHAR(50) DEFAULT 'claude_code';
