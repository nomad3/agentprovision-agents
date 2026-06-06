-- 162_desktop_command_approval_grants.sql
--
-- Explicit approval grants for Luna desktop command claims. Grants are
-- consumed with a compare-and-swap update before command claim leases are
-- issued, keeping native invoke paths fail-closed until approval trust is
-- proven end to end.

BEGIN;

CREATE TABLE IF NOT EXISTS desktop_command_approval_grants (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id              UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    session_id           UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    shell_id             VARCHAR(96) NOT NULL,
    device_id            UUID NULL REFERENCES device_registry(id) ON DELETE SET NULL,
    desktop_command_id   UUID NULL REFERENCES desktop_commands(id) ON DELETE CASCADE,
    risk_tier            VARCHAR(32) NOT NULL,
    capability           VARCHAR(64) NOT NULL,
    status               VARCHAR(32) NOT NULL DEFAULT 'active',
    target_binding       JSONB NOT NULL DEFAULT '{}'::jsonb,
    max_actions          INTEGER NOT NULL DEFAULT 1,
    remaining_actions    INTEGER NOT NULL DEFAULT 1,
    approved_by_user_id  UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    approved_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at           TIMESTAMPTZ NOT NULL,
    consumed_at          TIMESTAMPTZ NULL,
    revoked_at           TIMESTAMPTZ NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT desktop_command_approval_grants_shell_check CHECK (shell_id LIKE 'desktop-%'),
    CONSTRAINT desktop_command_approval_grants_status_check CHECK (
        status IN ('active', 'consumed', 'revoked', 'expired')
    ),
    CONSTRAINT desktop_command_approval_grants_risk_check CHECK (
        risk_tier IN ('observe', 'native_control')
    ),
    CONSTRAINT desktop_command_approval_grants_actions_check CHECK (
        max_actions > 0 AND remaining_actions >= 0 AND remaining_actions <= max_actions
    )
);

ALTER TABLE desktop_commands
    ADD COLUMN IF NOT EXISTS approval_id UUID NULL;

CREATE INDEX IF NOT EXISTS idx_desktop_command_approval_grants_tenant_status
    ON desktop_command_approval_grants(tenant_id, status, expires_at);
CREATE INDEX IF NOT EXISTS idx_desktop_command_approval_grants_session_shell
    ON desktop_command_approval_grants(session_id, shell_id, created_at);
CREATE INDEX IF NOT EXISTS idx_desktop_command_approval_grants_command
    ON desktop_command_approval_grants(desktop_command_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_desktop_command_approval_grants_active_command
    ON desktop_command_approval_grants(tenant_id, desktop_command_id)
    WHERE desktop_command_id IS NOT NULL AND status = 'active';
CREATE INDEX IF NOT EXISTS idx_desktop_commands_approval
    ON desktop_commands(approval_id) WHERE approval_id IS NOT NULL;

INSERT INTO _migrations(filename) VALUES ('162_desktop_command_approval_grants.sql')
ON CONFLICT DO NOTHING;

COMMIT;
