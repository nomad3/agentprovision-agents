# Revert deploy prunes to end-of-pipeline orphan cleanup only

**Date:** 2026-05-14
**Branch:** `fix/deploy-prune-only-orphans-at-end`
**Status:** Implementing

## TL;DR

Strip out the pre-build prune step (PR #463) and the post-up aggressive prune (PR #465). They've caused successive deploy wedges. Replace with a single `docker image prune -f` (dangling/orphan only) at the very end of the pipeline, after `Apply pending DB migrations`.

User directive: *"only prune after the pipeline finishes entirely to remove orphan images."*

## Why the in-flight prunes broke deploys

- **PR #463 pre-build prune.** Removed the just-stopped api/orchestration-worker/code-worker containers, forcing `compose up -d` to recreate them from scratch instead of restarting. Wedged for 14+ min in PR #467's deploy. Partially fixed in #468 by removing the container prune; but image+builder prunes at this point still consumed minutes and risked hitting BuildKit's stuck-cache state mid-build.
- **PR #465 post-up aggressive prune.** Triggered the BuildKit stuck-cache wedge mid-pipeline. `Build and update services` step hung silently after building the first cached service in 2 seconds, then sat doing nothing for 2 hours until the timeout killed it.

The pattern: BuildKit's internal ref-counting goes wedged when prune runs while builds or compose operations are in flight. The on-host auto-prune sentinel hits the same wedge during normal operation — recovery is a Docker Desktop restart.

## What we're keeping

- **End-of-pipeline `docker image prune -f`** — dangling only, no `-a`, no builder prune, no buildx prune. Removes only the just-replaced previous-version images whose tags got reassigned by the new build. That's the only cleanup the deploy itself is responsible for.

## What's leaving the deploy

- The pre-build "Free disk before build" step (entire step removed).
- The post-up aggressive prune (image -a + builder + buildx). The step is renamed from "Up and prune" to just "Up" and contains only `docker compose up -d`.

## What handles disk maintenance instead

The on-host auto-prune sentinel (running independently as a background process, threshold `<50 GiB free or >92% used`). It can be paused during deploys if BuildKit wedge becomes a recurring problem; that's separate work.

## Step order after this PR

```
Pre-checkout — release bind-mounts
Checkout code
Reset working tree
Symlink env files
Detect changed services
Build and update services
Up
Apply pending DB migrations
Prune orphan images     ← new, only prune in the whole pipeline
```

## Verification

After merge, this PR's own deploy runs the new logic. No `apps/**` paths changed, so:
- `Build and update services` is a no-op (skip-build path from #466)
- `Up` does `compose up -d` (no-op against unchanged images)
- `Apply pending DB migrations` is idempotent
- `Prune orphan images` runs `image prune -f` — should report 0 reclaimed (no orphans from this fast-path)

Then the user can workflow_dispatch a full rebuild-all that goes through the same clean pipeline without prunes interfering mid-flight.

## References

- PR #463 (pre-build prune — removed by this PR)
- PR #465 (post-up aggressive prune — removed by this PR)
- PR #466 (skip-build path + 120 min timeout — KEPT)
- PR #467 (repo-path refs — KEPT)
- PR #468 (drop container prune from pre-build — superseded; this PR removes the whole step)
