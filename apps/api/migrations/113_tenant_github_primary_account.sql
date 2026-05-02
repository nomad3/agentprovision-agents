-- 113_tenant_github_primary_account.sql
--
-- Per-tenant primary GitHub account for repo operations.
--
-- Background: a tenant can connect more than one GitHub account
-- (e.g. personal + employer EMU). The MCP github tools previously
-- fetched whichever account the API returned first and silently used
-- only that account's repo access. PR #249 made the tools enumerate
-- both accounts and fan out, but for tenants where one account is
-- intentionally only used for the Copilot CLI runtime (e.g. Levi
-- Strauss EMU accounts that have a Copilot license but no repo
-- visibility under enterprise policy), fanning out is wasteful — the
-- non-repo account always returns 0 results and adds latency.
--
-- The new column lets a tenant pin "this is the GitHub account I want
-- for repo / issue / PR operations". MCP tools that don't get an
-- explicit `account_email` parameter use this as the default.
--
-- Code-worker's `_fetch_github_token` (apps/code-worker/workflows.py)
-- ALSO honors this pin so `git push` / `gh pr create` from the code
-- agent uses the same canonical account as MCP. Without that, the
-- runtime could pick the EMU token (no repo write access) and fail
-- PR creation even though MCP read tools succeeded with the pinned
-- personal token. Earlier revisions of this comment claimed code-worker
-- was "unaffected" — that was wrong; PR #249 actually wired the
-- code-worker honor, the comment is now consistent with the code.
--
-- Nullable on purpose: when null, the resolver falls back to the
-- multi-account fan-out / try-each behavior from PR #249.

ALTER TABLE tenant_features
ADD COLUMN IF NOT EXISTS github_primary_account VARCHAR(255);

COMMENT ON COLUMN tenant_features.github_primary_account IS
  'account_email of the connected github integration_config row to use as the default for MCP github tools (list_repos, get_repo, etc.). When null, all connected accounts are queried.';
