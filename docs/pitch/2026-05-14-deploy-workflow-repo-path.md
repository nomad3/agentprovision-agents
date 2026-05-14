# Deploy workflow: update stale repo-name references

**Date:** 2026-05-14
**Branch:** `fix/deploy-workflow-repo-path`
**Status:** Implementing

## TL;DR

The deploy workflow has three references to the pre-rename `servicetsunami-agents` slug. The repo was renamed `servicetsunami-agents → agentprovision-agents` on 2026-05-13 (PR #451). PR #466's fast-pathed deploy just failed at `Up and prune` because the env-symlink step looked for the source files under the old path and didn't find them.

## What's broken

`.github/workflows/docker-desktop-deploy.yaml`:

1. **Line 47** — `Pre-checkout — release bind-mounts` step uses `SRC="$HOME/Documents/GitHub/servicetsunami-agents"`. Wrong dir → can't stop containers cleanly → not fatal, but noisy.

2. **Line 93** — `Symlink env files` step uses the same SRC. The `.env` files live ONLY at `$HOME/Documents/GitHub/agentprovision-agents/{apps/api/.env, .env}` on this host. The symlinks never get created. Then `docker compose up -d` fails with: `env file ... apps/api/.env not found`. **This is what killed PR #466's deploy** and would kill every future deploy until fixed.

3. **Line 255** — `Apply pending DB migrations` step uses `DB_CONTAINER: servicetsunami-agents-db-1`. The container is now `agentprovision-agents-db-1`. Migration step would silently fail to find the container and skip migrations.

## Fix

Sed-replace all three. Single-line trivial change but blocking everything downstream.

## Why this wasn't caught earlier

PR #451 (repo rename) updated in-source refs but missed the deploy workflow because the workflow only fires on push-to-main and runs on a self-hosted runner whose env hasn't actually executed since the rename. The cli-v0.7.4 cycle's deploys all wedged on the timeout bug (#466) before reaching the env-symlink step in a way that would have surfaced this. With #466's skip-build fast-path, the workflow actually completes its earlier steps and surfaces the env-path bug.

## After this PR merges

1. **This PR's own deploy** runs the new logic — no apps/** changed → skip build → fast-path through to `Up and prune` → symlinks find their source → `docker compose up -d` succeeds → migrations run.
2. **Then** trigger `gh workflow run docker-desktop-deploy.yaml --ref main -f action=rebuild-all` to actually deploy the accumulated api/migration code from #456/#459/#460/#461 with 120-min headroom.

## Verification

- Symlink source paths point at the correct dir (`agentprovision-agents/`).
- DB container name matches `docker compose ps` output: `agentprovision-agents-db-1`.
- No other workflow files reference the old name.
