-- 132_workflow_runs_timestamptz.sql
-- Convert `workflow_runs.started_at` / `completed_at` from
-- TIMESTAMP WITHOUT TIME ZONE to TIMESTAMPTZ (TIMESTAMP WITH TIME ZONE).
--
-- Background: the columns were created naive and populated by
-- `datetime.utcnow()` (naive). Serialising naive datetimes through
-- Pydantic produces strings without a `Z` suffix, which the Rust CLI's
-- `chrono::DateTime<Utc>` rejects at parse time (PR #454 review B1).
-- We patched it temporarily with a `_utc_aware` shim that stamps UTC
-- on the way out, and a `datetime.utcnow()` workaround for query
-- bounds (PR #454 review I-new-1).
--
-- This migration is the real fix. Both columns store the same wall-
-- clock UTC moments they always did, but the type is now explicit, so:
--   - Pydantic v2 emits `Z` / `+00:00` automatically on serialisation.
--   - tz-aware Python datetimes compare cleanly in WHERE clauses
--     against psycopg2 AND psycopg3 (no more DatatypeMismatch under
--     driver upgrade).
--   - The `_utc_aware` shim + `now_naive` workaround in
--     `apps/api/app/api/v1/dashboard_tasks.py` can be removed in the
--     same PR.
--
-- Existing rows: every datetime currently in the columns was produced
-- by `datetime.utcnow()`, so treating them as UTC during conversion
-- preserves their semantic meaning. The `USING ... AT TIME ZONE 'UTC'`
-- clause does the right thing here — Postgres reads the naive value
-- as "UTC wall clock" and produces the equivalent TIMESTAMPTZ.
--
-- Lock cost: ALTER COLUMN ... TYPE rewrites the column. For a typical
-- tenant workflow_runs table this is small enough (<100k rows) that
-- the brief ACCESS EXCLUSIVE is acceptable. If a tenant ends up with
-- millions of rows, switch to the "add new column / backfill /
-- swap / drop" dance — but that's not the situation today.

ALTER TABLE workflow_runs
    ALTER COLUMN started_at TYPE TIMESTAMPTZ USING started_at AT TIME ZONE 'UTC';

ALTER TABLE workflow_runs
    ALTER COLUMN completed_at TYPE TIMESTAMPTZ USING completed_at AT TIME ZONE 'UTC';
