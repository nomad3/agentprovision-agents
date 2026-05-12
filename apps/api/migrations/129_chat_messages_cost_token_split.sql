-- 129_chat_messages_cost_token_split.sql
-- Add per-message input/output token split + cost + model columns.
--
-- Why: PR #414 surfaced the existing `tokens_used` column (sum of
-- input+output) in the API + ap CLI render. The code-worker callback
-- already extracts `input_tokens`, `output_tokens`, `total_cost_usd`,
-- and `model` from CLI events (apps/code-worker/session_manager.py:140
-- and workflows.py:1402+) but the data was being stored only in the
-- `context` JSONB blob — no first-class columns, no efficient
-- aggregation, no per-tenant cost queries.
--
-- All four columns are nullable. NULL means "not measured": older
-- rows (pre-migration), agents that don't emit a usage struct, and
-- locally-run CLIs (OpenCode + gemma4) that don't compute a cost.
-- Callers MUST render absence as `—`, not 0 — they mean different
-- things (see chat.py::_extract_tokens_used docstring).
--
-- Index: per-session sum queries (ap session totals, web ChatPage
-- header). Per-tenant cost rollups go through the
-- agent_performance_snapshots table — no separate index needed.

ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS input_tokens  INTEGER,
    ADD COLUMN IF NOT EXISTS output_tokens INTEGER,
    -- cost_usd uses NUMERIC(12,6) so a $0.000001-per-token CLI run
    -- on a long conversation can accumulate without truncation, and
    -- the integer part has room for a $999999 hypothetical (the
    -- existing agent_performance_snapshots.total_cost_usd uses the
    -- same precision, keeps the math consistent across tables).
    ADD COLUMN IF NOT EXISTS cost_usd      NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS model         VARCHAR(64);

-- Backfill from the `context` JSONB blob where the code-worker
-- callback wrote these fields. Idempotent: only touches rows where
-- the new columns are still NULL (so a re-run after manual fixups
-- doesn't clobber later corrections). Skips rows whose JSONB values
-- aren't numeric — the `~ '^[0-9]+$'` filter on text-coerced values
-- avoids `invalid input syntax for integer` if a malformed event
-- ever wrote a string into one of these slots.
UPDATE chat_messages
SET input_tokens = (context ->> 'input_tokens')::int
WHERE input_tokens IS NULL
  AND context ? 'input_tokens'
  AND (context ->> 'input_tokens') ~ '^[0-9]+$';

UPDATE chat_messages
SET output_tokens = (context ->> 'output_tokens')::int
WHERE output_tokens IS NULL
  AND context ? 'output_tokens'
  AND (context ->> 'output_tokens') ~ '^[0-9]+$';

UPDATE chat_messages
SET cost_usd = (context ->> 'cost_usd')::numeric(12, 6)
WHERE cost_usd IS NULL
  AND context ? 'cost_usd'
  AND (context ->> 'cost_usd') ~ '^[0-9]+(\.[0-9]+)?$';

UPDATE chat_messages
SET model = LEFT((context ->> 'model'), 64)
WHERE model IS NULL
  AND context ? 'model'
  AND length(context ->> 'model') > 0;
