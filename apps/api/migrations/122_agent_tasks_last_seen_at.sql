-- Migration 122: agent_tasks.last_seen_at for Phase 4 leaf-side
-- heartbeat endpoint.
--
-- The Claude Code PostToolUse hook on a leaf agent fires
-- POST /api/v1/agents/internal/heartbeat after every tool call. The
-- handler updates the agent_tasks row's last_seen_at column. The
-- existing heartbeat-missed event emitter (Phase 3 commit 8) reads this
-- to decide when to fire ``execution.heartbeat_missed`` if a leaf goes
-- silent for >2x heartbeat_interval.
--
-- The column is nullable (legacy rows have no leaf-side hook history)
-- and timezone-aware (matches the project convention for new
-- TIMESTAMPTZ columns). The fall-through if the column is absent is
-- a hard 500 from the heartbeat endpoint — not a quiet downgrade —
-- because the auth-tier rejection step (Phase 4 §10.3(c)) MUST be
-- explicit, never silent.

ALTER TABLE agent_tasks
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;

-- Index for the heartbeat-missed scan path (find rows where
-- last_seen_at is older than threshold). Partial index on non-null
-- values keeps it small.
CREATE INDEX IF NOT EXISTS idx_agent_tasks_last_seen_at
    ON agent_tasks (last_seen_at)
    WHERE last_seen_at IS NOT NULL;

-- Self-record so re-applying this migration on a fresh DB is a clean no-op.
INSERT INTO _migrations(filename) VALUES ('122_agent_tasks_last_seen_at.sql')
ON CONFLICT DO NOTHING;
