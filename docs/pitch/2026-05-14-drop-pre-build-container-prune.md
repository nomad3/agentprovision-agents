# Drop container prune from pre-build deploy step

**Date:** 2026-05-14
**Branch:** `fix/deploy-no-pre-build-container-prune`
**Status:** Implementing

## TL;DR

PR #463 added `docker container prune -f` to the pre-build "Free disk before build" step. That removes the just-stopped api/orchestration-worker/code-worker containers (which the Pre-checkout step intentionally leaves in EXITED state so it can release their bind-mounts), forcing `docker compose up -d` later to recreate them from scratch instead of just restarting them. PR #467's deploy wedged for 14+ min on that recreation.

Drop the container prune. Images + builder are where the real disk-freeing happens; containers are tiny metadata.

## Sequence of events that surfaced the bug

PR #467's deploy on 2026-05-14:

1. **Pre-checkout** stops `api`, `orchestration-worker`, `code-worker` → EXITED state, bind-mounts released.
2. **Free disk before build** (the new step from #463) runs `docker container prune -f` → **removes those three exited containers**.
3. **Build and update services** (no-op via the skip-build path from #466).
4. **Up and prune** runs `docker compose up -d` → has to **recreate three containers from scratch** instead of restarting → wedged for 14+ min without producing output → I killed it manually → step recorded as failure → migrations skipped.

The fix is removing one line (and its comment block). Image prune + builder prune still free real disk; container prune was reclaiming KB of metadata at the cost of breaking the compose restart fast path.

## Why container prune in pre-build seemed reasonable in #463

The #463 comment said "catches any zombie exited containers from killed deploys" — referring to the cli-v0.7.4 wedge where cancelled deploys left process state behind. But:

- Those "zombies" were never containers in EXITED state — they were buildx subprocesses inside the runner, which container prune doesn't touch.
- The post-up aggressive prune in #465 already catches genuine stale containers (anything `compose up -d` didn't claim).
- The pre-checkout step's deliberate stop is the FAR more common case at deploy-time, and the prune is actively hostile to it.

## After this PR

1. **This PR's own deploy** uses the skip-build fast-path (no apps changed). Now ALSO uses the no-container-prune fast-restart path. Should finish in <1 min.
2. **Then trigger:** `gh workflow run docker-desktop-deploy.yaml --ref main -f action=rebuild-all` — with 120-min timeout (PR #466) + correct paths (PR #467) + no-container-prune restart (this PR) all in place, the full rebuild should land cleanly.

## What's safe to leave in pre-build

`docker image prune -a -f` — only removes images not referenced by a running container. The three deliberately-stopped containers' previous EXITED instances reference no images (they're stopped, not images). Image prune is fine.

`docker builder prune --filter "until=2h"` — touches BuildKit cache, not containers. Fine.

## References

- PR #463 (pre-build prune — introduced this bug)
- PR #465 (post-up aggressive prune — the right place for thorough cleanup)
- PR #466 (timeout + change-detector — the prior unblock)
- PR #467 (repo-path refs — the prior-prior unblock)
