-- 130_refresh_tokens.sql
-- Long-lived refresh tokens for CLI sessions ("log in once" UX).
--
-- Why: today the CLI gets a 24h access token via /auth/login + can call
-- /auth/refresh while it's still valid, but the refresh chain hard-caps
-- at 7 days (MAX_TOKEN_CHAIN_AGE_SECONDS in apps/api/app/api/v1/auth.py).
-- After 7 days the user has to re-enter password. Claude Code / Codex /
-- GitHub CLI all hand out long-lived refresh credentials (30–90 days)
-- bound to the device so users authenticate once per laptop.
--
-- This migration creates the server-side store. The CLI gets two
-- credentials at login:
--   1. access_token  — short-ish JWT (24h)   — used on every request
--   2. refresh_token — opaque random secret  — exchanged via /auth/token/refresh
--                                              when the access token expires
--
-- Rotation: every successful /auth/token/refresh issues a NEW refresh
-- token and marks the old one revoked (with parent_id linking the chain).
-- This catches stolen refresh tokens: if both the attacker and the
-- legitimate user try to refresh the same token, the second exchange
-- 401s and we can mass-revoke the chain via the parent_id link.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE refresh_tokens (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- sha256(secret). The raw secret is only returned to the client at
    -- creation time; we store the hash so a DB leak doesn't yield live
    -- refresh credentials.
    token_hash    CHAR(64) NOT NULL UNIQUE,
    -- Rotation chain pointer. If this token was issued by exchanging an
    -- older one, parent_id references that older token. Null on the
    -- first link (i.e. the token minted at /auth/login).
    parent_id     UUID REFERENCES refresh_tokens(id),
    -- Human-readable origin. Default "alpha CLI" until the CLI starts
    -- shipping a richer device-label (hostname + OS) in the login
    -- payload. Web UI sessions will use "web".
    device_label  TEXT,
    -- Diagnostic only; populated from the request at login + each
    -- rotation. Not used for auth decisions (no IP pinning — laptops
    -- roam networks).
    user_agent    TEXT,
    ip_inet       INET,
    expires_at    TIMESTAMP NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMP,
    -- Set on rotation (replaced by a child), explicit revoke via
    -- DELETE /auth/sessions/{id}, or detected reuse.
    revoked_at    TIMESTAMP,
    -- One of: 'rotated', 'user_revoked', 'reuse_detected', 'logout',
    -- 'admin_revoked'. Plain text to keep migration cheap; codify as
    -- an enum later if the surface justifies it.
    revoked_reason TEXT
);

-- Lookup hot-paths:
--   1. by user_id + revoked_at IS NULL for /auth/sessions listing
--   2. by token_hash for /auth/token/refresh (already unique-indexed)
CREATE INDEX idx_refresh_tokens_user_active
    ON refresh_tokens(user_id)
    WHERE revoked_at IS NULL;
