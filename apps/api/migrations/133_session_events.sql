-- 133_session_events.sql
-- Alpha Control Plane Tier 0-1 — PR 1 of 7
--
-- Persisted event log for the channel-agnostic Alpha Control Plane
-- protocol. Every event published via `publish_session_event` writes a
-- row here BEFORE Redis fan-out, so disconnected viewports can replay
-- via GET /api/v2/sessions/{id}/events?since=<seq_no>.
--
-- Design: docs/plans/2026-05-15-alpha-control-plane-design.md §5.1
-- Plan:   docs/plans/2026-05-15-alpha-control-plane-tier-0-1-plan.md §1
--
-- seq_no allocation: pg_advisory_xact_lock(hashtext(session_id)) +
-- COALESCE(MAX(seq_no), 0) + 1 inside the same transaction. The
-- UNIQUE(session_id, seq_no) constraint is the safety net if the
-- lock is ever bypassed.

BEGIN;

CREATE TABLE IF NOT EXISTS session_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    tenant_id   UUID NOT NULL,
    seq_no      BIGINT NOT NULL,
    event_type  VARCHAR(64) NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT session_events_session_seq_unique UNIQUE (session_id, seq_no)
);

-- Replay scans: WHERE session_id = ? AND seq_no > ? ORDER BY seq_no
-- The unique constraint already creates an index on (session_id, seq_no);
-- adding an explicit one would be redundant. Skipped intentionally.

-- Retention sweep: DELETE WHERE tenant_id = ? AND created_at < cutoff
-- The cron also filters out event_type='auto_quality_score' (retained
-- indefinitely for the RL store).
CREATE INDEX IF NOT EXISTS idx_session_events_tenant_created
    ON session_events(tenant_id, created_at);

-- Hot-path filter when subscribing to a single session by type
-- (used by channel-side filters in tier 4+ for auto_quality_score etc.).
-- Cheap because event_type cardinality is small (≤20 distinct values).
CREATE INDEX IF NOT EXISTS idx_session_events_session_type
    ON session_events(session_id, event_type);

COMMIT;
