-- 176_desktop_approval_requests.sql
--
-- Luna P5.4b — agent-facing pending desktop approval requests.
--
-- A REQUEST is "Luna asked to run a native desktop action and is waiting for a
-- human to approve it" — distinct from a GRANT (already approved). It lives in
-- its own table and is invisible to the command claim path (which only consumes
-- desktop_command_approval_grants WHERE status = 'active'), so a pending request
-- can never authorize a native action. The P5.5 approval surface flips
-- pending -> approved and mints the real grant (grant_id then set).

BEGIN;

CREATE TABLE IF NOT EXISTS desktop_approval_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    shell_id VARCHAR(96) NOT NULL,
    device_id UUID REFERENCES device_registry(id) ON DELETE SET NULL,
    action VARCHAR(48) NOT NULL,
    capability VARCHAR(64) NOT NULL,
    target_binding JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    requested_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    decided_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    grant_id UUID REFERENCES desktop_command_approval_grants(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ,
    CONSTRAINT desktop_approval_requests_status_check CHECK (
        status IN ('pending', 'approved', 'denied', 'expired', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_desktop_approval_requests_tenant_status
    ON desktop_approval_requests (tenant_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_desktop_approval_requests_session
    ON desktop_approval_requests (session_id);

INSERT INTO _migrations(filename) VALUES ('176_desktop_approval_requests.sql')
ON CONFLICT DO NOTHING;

COMMIT;
