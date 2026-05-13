-- 131_refresh_tokens_parent_id_index.sql
-- Index on `refresh_tokens.parent_id` to speed up rotation-chain
-- traversal in `revoke_chain_from` and to keep `users DELETE ... CASCADE`
-- O(log n) on the refresh_tokens children. Originally missing from
-- migration 130 — review finding I-3 on PR #442.
--
-- The partial index `idx_refresh_tokens_user_active` from migration 130
-- handles the listing hot-path. This one handles the walk-the-chain
-- hot-path (every replay-detection invocation).
--
-- `CONCURRENTLY` avoids ACCESS EXCLUSIVE on a potentially-hot table.
-- Reviewer NIT-1 on PR #445.
--
-- IMPORTANT: `CREATE INDEX CONCURRENTLY` cannot run inside a transaction.
-- The local-dev migration runner (per memory `migration_apply_pattern.md`)
-- uses `docker exec psql` with autocommit, which is fine. The CI/helm
-- path applies migrations via `psql -f`, also fine — each statement is
-- its own transaction.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_refresh_tokens_parent_id
    ON refresh_tokens(parent_id)
    WHERE parent_id IS NOT NULL;
