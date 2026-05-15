# Fix docker-desktop-deploy change-detection + recreate semantics

**Date:** 2026-05-14
**Branch:** `fix/deploy-change-detection`
**Status:** Implementing

## TL;DR

The deploy workflow had three compounding bugs that left containers running stale images even when their apps/** code changed:

1. `actions/checkout@v4` used default `fetch-depth: 1` (shallow). `git diff HEAD~1 HEAD` failed because HEAD~1 didn't exist on the runner.
2. The fallback string `echo "apps/api"` (no trailing slash) didn't match the grep pattern `"apps/api/"` (trailing slash). Net: SERVICES came out empty whenever the diff failed.
3. The Up step ran plain `docker compose up -d` with no service args and no `--force-recreate`. That only starts *stopped* containers — it does NOT recreate already-running containers whose images were just rebuilt. Even when build succeeded, the swap didn't happen.

## How it surfaced

After merging PR #471 (`feat(claude-auth): stdin-forward`), the squash-merge commit `f28ea6d4` correctly touched apps/api + apps/web + tests. The deploy workflow fired automatically:

- Detect changed services step: SERVICES=`""` (empty, because the diff returned nothing and the fallback string didn't match)
- Build step: no-op (empty SERVICES loop)
- Up step: `docker compose up -d` → no recreation
- Result: api container had the new code (apps/api/ is bind-mounted so picks up file changes), but web container kept its old nginx image from 2026-05-14 13:54 — pre-merge.

The user reported the broken UI flow ("aparently hasn't landed") because the paste-code input and cancellable-flag UI changes weren't visible.

## Fix

```yaml
- name: Checkout code
  uses: actions/checkout@v4
  with:
    clean: false
    fetch-depth: 0   # so HEAD~1 resolves for the diff below
```

Fallback string now ends in slash:

```bash
CHANGED=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || echo "apps/api/")
```

Up step explicitly recreates rebuilt services:

```bash
SERVICES="${{ steps.changes.outputs.services }}"
if [ -n "$SERVICES" ]; then
  docker compose up -d --force-recreate --no-deps $SERVICES
fi
docker compose up -d
```

The two-step approach: first force-recreate the rebuilt services (so their new images go live), then bring up anything stopped (db, cloudflared, etc.) without disturbing live containers.

## Why three fixes instead of one

Any one of these would have masked the others:

- Just fetch-depth: 0 → diff works, but if a future workflow change re-introduces a diff failure, the empty-fallback bug reappears.
- Just the fallback slash → catches the diff-failure case, but workflows that depend on accurate change detection still drift.
- Just the recreate fix → moot when SERVICES is empty (nothing to recreate).

Defense in depth — each layer catches a different failure mode.

## Recovery for the current cycle

PR #471 already merged but its web changes aren't deployed. A rebuild-all workflow_dispatch run (`25894134538`) is in flight to bring web onto the new bundle. After this PR merges, the next normal push will deploy correctly without manual intervention.

## Files

- `.github/workflows/docker-desktop-deploy.yaml` — checkout depth + fallback string + Up recreation
- `docs/pitch/2026-05-14-deploy-change-detection-fix.md`
