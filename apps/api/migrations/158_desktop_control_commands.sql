-- 158_desktop_control_commands.sql
--
-- Luna desktop-control command queue + authoritative audit spine.
-- This migration intentionally creates the schema before pointer/keyboard
-- control exists. The first wired endpoint only ingests metadata-only local
-- observation audit events and mirrors display-safe rows to session_events.

BEGIN;

CREATE TABLE IF NOT EXISTS desktop_commands (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id              UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    session_id           UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    shell_id             VARCHAR(96) NOT NULL,
    device_id            UUID NULL REFERENCES device_registry(id) ON DELETE SET NULL,
    correlation_id       UUID NOT NULL DEFAULT gen_random_uuid(),
    capability           VARCHAR(64) NOT NULL,
    status               VARCHAR(32) NOT NULL DEFAULT 'pending',
    source               VARCHAR(32) NOT NULL DEFAULT 'api',
    nonce                VARCHAR(96) NULL,
    payload              JSONB NOT NULL DEFAULT '{}'::jsonb,
    lease_owner_shell_id VARCHAR(96) NULL,
    lease_expires_at     TIMESTAMPTZ NULL,
    claimed_at           TIMESTAMPTZ NULL,
    completed_at         TIMESTAMPTZ NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT desktop_commands_shell_id_check CHECK (shell_id LIKE 'desktop-%'),
    CONSTRAINT desktop_commands_status_check CHECK (
        status IN ('pending', 'claimed', 'running', 'succeeded', 'failed', 'denied', 'preempted', 'expired')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_desktop_commands_nonce
    ON desktop_commands(nonce) WHERE nonce IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_desktop_commands_tenant_status
    ON desktop_commands(tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_desktop_commands_session_shell
    ON desktop_commands(session_id, shell_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_desktop_commands_correlation
    ON desktop_commands(correlation_id);

CREATE TABLE IF NOT EXISTS desktop_command_events (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id              UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    session_id           UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    desktop_command_id   UUID NULL REFERENCES desktop_commands(id) ON DELETE SET NULL,
    approval_id          UUID NULL,
    correlation_id       UUID NULL,
    event_type           VARCHAR(64) NOT NULL,
    source               VARCHAR(32) NOT NULL,
    action               VARCHAR(64) NOT NULL,
    capability           VARCHAR(64) NOT NULL,
    outcome              VARCHAR(32) NOT NULL,
    reason               VARCHAR(512) NULL,
    mode                 VARCHAR(32) NULL,
    shell_id             VARCHAR(96) NOT NULL,
    device_id            UUID NULL REFERENCES device_registry(id) ON DELETE SET NULL,
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT desktop_command_events_shell_id_check CHECK (shell_id LIKE 'desktop-%'),
    CONSTRAINT desktop_command_events_source_check CHECK (
        source IN ('mcp', 'local_user', 'api', 'tauri', 'tauri_local')
    ),
    CONSTRAINT desktop_command_events_outcome_check CHECK (
        outcome IN ('requested', 'approved', 'started', 'succeeded', 'failed', 'denied', 'stopped', 'preempted', 'expired')
    )
);

CREATE INDEX IF NOT EXISTS idx_desktop_events_tenant_created
    ON desktop_command_events(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_desktop_events_session_created
    ON desktop_command_events(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_desktop_events_session_type
    ON desktop_command_events(session_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_desktop_events_shell_created
    ON desktop_command_events(shell_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_desktop_events_command
    ON desktop_command_events(desktop_command_id);
CREATE INDEX IF NOT EXISTS idx_desktop_events_correlation
    ON desktop_command_events(correlation_id) WHERE correlation_id IS NOT NULL;

INSERT INTO _migrations(filename) VALUES ('158_desktop_control_commands.sql')
ON CONFLICT DO NOTHING;

COMMIT;
