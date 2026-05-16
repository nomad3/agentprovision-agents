-- 135_revoke_stale_claude_session_tokens.sql
--
-- One-shot: revoke every active `claude_code.session_token` row in
-- the vault. The rows currently in the DB were stored by the broken
-- `claude auth login --claudeai` path (commit `c54f91b3`, 2026-04-05)
-- and contain interactive subscription-session credentials in
-- whatever shape `_persist_credentials`' salvage glob picked up
-- first — NOT the long-lived `sk-ant-oat01-…` shape that
-- `CLAUDE_CODE_OAUTH_TOKEN` requires.
--
-- Anthropic rejects these tokens with `401 Invalid bearer token` on
-- every executor call. PR #531 (drop inherited `ANTHROPIC_API_KEY`)
-- removed the fallback that was silently masking the bug — now every
-- Claude Code user hits the 401 directly.
--
-- Forcing a revoke flips the Integrations UI to "Disconnected" so
-- every affected tenant is prompted to re-auth via the new
-- `claude setup-token`-based flow shipped in this PR. The new flow
-- captures the token straight from stdout, validates the
-- `sk-ant-oat01-` prefix, and probes the token before persisting —
-- so any row created after this migration is structurally correct
-- by construction.
--
-- Schema note: `integration_credentials` uses a `status` column
-- (active/expired/revoked) for lifecycle, NOT a `revoked_at`
-- timestamp like `refresh_tokens` does. We mirror that convention
-- here. `updated_at` is bumped automatically by the SQLAlchemy
-- `onupdate` hook on the next write; for raw-SQL revokes we touch
-- it explicitly so audit queries see the migration timestamp.
--
-- Idempotent: `WHERE status = 'active'` only matches still-active
-- rows. Re-running the migration is a no-op (subsequent invocations
-- match zero rows because the first run set status='revoked'). No
-- new rows are created.
--
-- Design: docs/plans/2026-05-16-oauth-reconnect-token-format-mismatch.md

BEGIN;

UPDATE integration_credentials
   SET status = 'revoked',
       updated_at = NOW()
 WHERE credential_key = 'session_token'
   AND status = 'active'
   AND integration_config_id IN (
        SELECT id
          FROM integration_configs
         WHERE integration_name = 'claude_code'
   );

COMMIT;
