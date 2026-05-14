# Aggressive image + build cache prune post-deploy

**Date:** 2026-05-14
**Author:** Claude (opus) at user request
**Status:** Implementing
**Branch:** `chore/deploy-post-prune-aggressive`
**Task:** #203

## TL;DR

PR #463 added a pre-build prune to free space before the heavy Rust builds. This PR closes the loop with a post-up prune that removes:

1. The just-replaced previous tagged image versions
2. All BuildKit / buildx cache from this build

For a single-dev self-hosted runner where each deploy can add 5-15 GB of Rust build cache, the post-deploy survivors are the most important thing to clean up — they're the disk-growth driver.

## Problem

The existing `Up and prune` step ran `docker image prune -f` (no `-a`). That only removes **dangling** images (no tag at all). After `docker compose up -d`:

- New `agentprovision-agents-api:latest` is pinned → previous version becomes untagged → cleaned ✅
- Old tagged images from earlier deploys not referenced by the current compose set → **not cleaned** ❌
- BuildKit cache from this build (5-15 GB for Rust services) → **not cleaned** ❌

Run 5-10 deploys and the disk fills with stale layers. The 2026-05-13 cli-v0.7.4 cycle hit 95% disk at the first cancelled deploy — most of the bytes were stale TAGGED images from cli-v0.7.0..0.7.3 deploys earlier in the week.

## Why "save cache for next incremental rebuild" doesn't apply here

The classic argument against aggressive post-deploy cache prune is "the cache seeds the next incremental rebuild." That assumes:

1. Consecutive deploys touch the same services. **False here** — `apps/web` changes don't help `apps/embedding-service` rebuilds, and vice versa.
2. The cache stays useful long enough to matter. **False here** — the pre-build prune in PR #463 already drops cache older than 2 h. A deploy 3 h later starts cold-cache regardless.
3. The host has cheap disk. **False here** — single Mac VM, shared with everything else, dropped to 95% used during the cli-v0.7.4 cycle.

For this setup, aggressive post-deploy prune is the right call.

## Implementation

`.github/workflows/docker-desktop-deploy.yaml`, the `Up and prune` step. Three layers after `docker compose up -d`:

```yaml
docker image prune -a -f       # any image not used by a running container
docker builder prune -af       # all BuildKit cache
docker buildx prune -af        # buildx-managed cache pool (overlaps with builder)
```

`df -h` + `docker system df` echoes before and after so deploy logs surface the reclaim numbers.

## Why not `docker system prune -a -f`

That includes `network prune`, which would tear down the compose network the running services depend on. Single nuclear option is wrong — three targeted calls are the right granularity.

## Risk

The aggressive image prune targets images **not currently referenced**. The compose services are all running by this point in the workflow, so their images are pinned. The only thing prune touches is genuinely stale (no container references it).

Rollback concern: an aggressive prune removes the previous version's image, so a manual rollback can't `docker compose up` against the prior tag without pulling. Acceptable for this setup — rollback goes through `git revert` + a fresh deploy, not local image reuse.

## Verification

Will be observable on the next deploy after merge:
- Logs show "Disk before post-up prune" and "Disk after post-up prune" lines
- `docker system df` block shows TOTAL + RECLAIMABLE shrink

## References

- PR #463 — pre-build prune (this PR's predecessor)
- `feedback_docker_disk_full_recovery` memory — 2026-05-04 recovery freed 55 GB
