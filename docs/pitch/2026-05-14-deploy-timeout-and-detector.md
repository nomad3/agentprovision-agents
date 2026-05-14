# Deploy: bump timeout 60→120 + skip-build on infra-only changes

**Date:** 2026-05-14
**Branch:** `fix/deploy-timeout-and-detector`
**Status:** Implementing

## TL;DR

The cli-v0.7.4 deploy queue wedged tonight because two issues compounded:

1. `timeout-minutes: 60` is shorter than a cold rebuild-all (~70-90 min)
2. The change-detector treats "no service files in diff" the same as "rebuild everything," making workflow-file-only PRs trigger a useless full rebuild

This PR fixes both. Skip-build is the more important of the two — it means **this PR's own deploy finishes in <2 min** without rebuilding anything (no `apps/**/` paths changed), unblocking the queue.

## What we observed

- PR #463 (deploy-prune step) merged at 22:33 local
- Its deploy started immediately on the runner, ran the new "Free disk before build" step successfully
- Hit the `Build and update services` step, started cold-cache rebuilding all 8 services (because change-detector hit the empty-SERVICES → fallback rebuild-all branch)
- Killed at 23:34 local — exactly 60 min — by the workflow `timeout-minutes` ceiling
- Queue behind it: #464 (web-only, would have been fast), #465 (workflow-file only, would have hit the same wedge)

API code that's been sitting on main since #456/#459/#460/#461 never deployed because every workflow file change runs its own rebuild-all and times out.

## The fix

`.github/workflows/docker-desktop-deploy.yaml`:

**1. Job-level timeout:** `60 → 120`. Empirically a cold rebuild-all needs ~70-90 min; 120 leaves enough headroom that an actual hang (HF xet, runner partial-state) still surfaces within a reasonable window rather than silently consuming the slot.

**2. Detector logic:** split the rebuild-all branch.

```diff
- if [ -z "$SERVICES" ] || [ "${{ github.event.inputs.action }}" = "rebuild-all" ]; then
+ if [ "${{ github.event.inputs.action }}" = "rebuild-all" ]; then
    SERVICES="api web code-worker orchestration-worker embedding-service memory-core mcp-tools luna-client"
  fi
```

Empty `$SERVICES` now means *exactly that* — no services to build. The for-loop in `Build and update services` is a no-op when SERVICES is empty, and the deploy fast-paths through `compose up -d` (re-applies current images) + `Apply pending DB migrations` (idempotent, picks up any unapplied migrations against the existing image's code).

The first-deploy "rebuild everything" case is now handled by the explicit `workflow_dispatch action=rebuild-all` input.

## Why this is safe

- Workflow-file-only deploys still RUN — they exercise the `compose up -d` + migrations path and surface any drift between the running stack and what main expects. They just don't pointlessly rebuild.
- Service-file deploys are unaffected — `apps/api/` change still triggers `api + orchestration-worker` build, etc.
- Manual `gh workflow run docker-desktop-deploy.yaml -f action=rebuild-all` still works for the legitimate "I want everything rebuilt" case.

## Rollout

After merge:
1. **This PR's deploy** runs the new logic → no apps/** match → SKIP build → fast deploy completes
2. **Queued deploy for #464** picks up → web-only build → fast → DeviceLoginPage page lives
3. **Queued #465 deploy** → no apps/** match → SKIP build → fast — and the post-up aggressive prune that landed in #465 is now LIVE for all future deploys
4. **Final step**: `gh workflow run docker-desktop-deploy.yaml -f action=rebuild-all` to force a full rebuild that picks up the accumulated #456/#459/#460/#461 main code

## References

- PR #463 — pre-build prune (works correctly; the bug above is independent)
- PR #465 — post-up aggressive prune (also correct; waiting for this fix to land before it can actually deploy)
- `feedback_no_local_builds` — keep deploys on the CI path; this is exactly the kind of issue local rebuilds mask
