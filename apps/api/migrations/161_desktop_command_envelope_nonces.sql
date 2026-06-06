-- 161_desktop_command_envelope_nonces.sql
--
-- Single-use nonce store for signed Luna desktop command envelopes.
-- Envelopes are issued during command claim and consumed during completion so
-- replay attempts become terminal denial audit events before native actuation
-- can ever use a stale lease.

BEGIN;

CREATE TABLE IF NOT EXISTS desktop_command_envelope_nonces (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    desktop_command_id UUID NOT NULL REFERENCES desktop_commands(id) ON DELETE CASCADE,
    session_id         UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    shell_id           VARCHAR(96) NOT NULL,
    device_id          UUID NULL REFERENCES device_registry(id) ON DELETE SET NULL,
    nonce              VARCHAR(96) NOT NULL,
    envelope_hash      CHAR(64) NOT NULL,
    status             VARCHAR(32) NOT NULL DEFAULT 'issued',
    issued_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at         TIMESTAMPTZ NOT NULL,
    consumed_at        TIMESTAMPTZ NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT desktop_command_envelope_nonces_shell_check CHECK (shell_id LIKE 'desktop-%'),
    CONSTRAINT desktop_command_envelope_nonces_status_check CHECK (
        status IN ('issued', 'consumed', 'replayed', 'expired')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_desktop_command_envelope_nonces_tenant_nonce
    ON desktop_command_envelope_nonces(tenant_id, nonce);
CREATE INDEX IF NOT EXISTS idx_desktop_command_envelope_nonces_command
    ON desktop_command_envelope_nonces(desktop_command_id);
CREATE INDEX IF NOT EXISTS idx_desktop_command_envelope_nonces_session
    ON desktop_command_envelope_nonces(session_id);
CREATE INDEX IF NOT EXISTS idx_desktop_command_envelope_nonces_shell
    ON desktop_command_envelope_nonces(shell_id);
CREATE INDEX IF NOT EXISTS idx_desktop_command_envelope_nonces_status
    ON desktop_command_envelope_nonces(status);

INSERT INTO _migrations(filename) VALUES ('161_desktop_command_envelope_nonces.sql')
ON CONFLICT DO NOTHING;

COMMIT;
