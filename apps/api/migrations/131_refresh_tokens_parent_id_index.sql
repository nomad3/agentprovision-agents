-- 131_refresh_tokens_parent_id_index.sql
-- Index on `refresh_tokens.parent_id` to speed up rotation-chain
-- traversal in `revoke_chain_from` and to keep `users DELETE ... CASCADE`
-- O(log n) on the refresh_tokens children. Originally missing from
-- migration 130 — review finding I-3 on PR #442.
--
-- The partial index `idx_refresh_tokens_user_active` from migration 130
-- handles the listing hot-path. This one handles the walk-the-chain
-- hot-path (every replay-detection invocation).

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_parent_id
    ON refresh_tokens(parent_id)
    WHERE parent_id IS NOT NULL;
