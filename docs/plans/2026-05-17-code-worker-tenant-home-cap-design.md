# Cap per-tenant HOME size in code-worker

Date: 2026-05-17
Owner: Alpha platform
Status: Design (task #264)

## Problem

The code-worker writable layer grows continuously, reaching multi-GB
in hours, because each tenant gets a private HOME under
`/home/codeworker/st_sessions/<tenant_id>/` and sandboxed CLIs install
packages into it.

Observed snapshot (2026-05-17 ~01:10 UTC):

```
8.8 G   /home/codeworker/st_sessions/
  5.8 G   .../<one-tenant>/.local/lib
  216 K   .../<one-tenant>/.local/bin
  …       .gemini / .cache fragments per tenant
```

Growth rate ~12 MB/min steady-state. At this rate the writable layer
hits the 24 GiB recycle threshold (PR #517's gated sentinel) in
~30 hours of activity. That's the exact pattern that forced a
mid-incident `docker compose up -d --force-recreate code-worker` on
2026-05-04.

The persistent workspaces volume (mig + Helm shipped in #530 / task
#247) gave us a place for *workspace* content, but the per-tenant
HOME is still on the container's writable overlay.

## Why HOME exists per-tenant

Sandboxed CLIs (the bundled superpowers/skills code path, opencode in
sandbox mode, the npm/pip-install helpers some skill bundles use)
expect a writable `$HOME` so they can persist `.gemini`, `.cache`,
package installs, etc. Without per-tenant isolation, tenants share
package versions and credential state — unacceptable.

So the requirements are:

1. Each tenant keeps a writable, isolated HOME for CLI side effects.
2. The aggregate HOME footprint must not grow the writable layer.
3. Hot package installs (a tenant's `.local/lib`) should survive
   container recycles so the next chat turn doesn't reinstall.

## Approach — bind HOME onto the workspaces volume

The same workspaces volume already mounted at `/var/agentprovision/workspaces`
(per-tenant subdir model) gets a new sibling tree:

```
/var/agentprovision/workspaces/<tenant_id>/
   projects/                ← existing (cloned repos, chat session dirs)
   home/                    ← NEW — what was /home/codeworker/st_sessions/<tenant_id>
       .local/
       .cache/
       .gemini/
       ...
```

`apps/code-worker/workflows.py:1120` changes from:

```python
session_dir = os.path.join("/home/codeworker/st_sessions", task_input.tenant_id)
```

to use `cli_runtime.tenant_home_dir(task_input.tenant_id)` which
returns `<workspaces_root>/<tenant>/home/` — same helper that already
gates the workspace dir with the UUID regex. Make the directory at
first use (`os.makedirs(..., exist_ok=True)`), and set the CLI
subprocess `env["HOME"]` to that path so all the existing CLI startup
side effects (`.gemini/oauth_creds.json`, `pip install --user`, etc.)
land there.

This single change:

- Moves the growing dirs off the writable layer onto the persistent
  volume (which is on the host disk, not Docker VM overlay).
- Lets the next chat turn find the warm package cache.
- Removes the eventual need for a `--force-recreate` recycle.

## Quota — keep one noisy tenant from filling the volume

A tenant could now grow `home/` indefinitely. Add a soft cap:

- `_TENANT_HOME_BUDGET = 2 GiB` (constant alongside `_TENANT_WORKSPACE_BUDGET`).
- On each CLI invocation, after the subprocess returns, run a quick
  `du -sx --max-depth=0` (or `os.scandir`-based walker) on the
  tenant `home/` dir.
- If the dir > budget, prune the largest non-essential subtrees first
  in this order: `.cache/`, `.local/lib/python*/site-packages/*` not
  referenced by the lock file, `.gemini/logs/`, anything older than
  14 days under `.local/`.
- Never prune `.gemini/oauth_creds.json`, `.config/*`, lock files.

Quota check is best-effort; if it can't bring the dir under budget,
it logs an OPS_ALERT event but doesn't block the chat turn.

## Migration

1. **Build path** — compose + Helm: mount workspaces volume on
   code-worker is already done; no infra change.
2. **Code** — `cli_runtime.tenant_home_dir`, switch the workflows
   path, set `env["HOME"]`, add the quota walker. ~80 lines.
3. **Data** — for existing tenants whose stuff is currently in
   `/home/codeworker/st_sessions/`, one-shot copy into the new
   location on container start (init script). After first deploy this
   is a no-op on idle tenants and saves the warm caches for active
   ones.
4. **Backout** — flip a flag, fall back to `/home/codeworker/st_sessions`.
   No data loss because the old path stays untouched if the env var
   isn't honored.

## Risks

- **Volume IO performance.** Per-tenant `.local/lib` reads are
  random small files. Workspaces volume is a Docker named volume on
  the host disk — same medium as the writable layer, so no expected
  slowdown.
- **Quota walker on every turn.** ~80 ms on a 5 GB tree. Acceptable;
  amortize by only running once every 10 turns or above a
  watermark (e.g., skip walker if last walk was <10 min ago and
  delta-since-last is bounded by emitter counters).
- **Two HOMEs during migration.** The init copy could double the
  footprint briefly. Mitigate by using `rsync --remove-source-files`
  so the old tree shrinks as the new one fills.

## Rollout

| Phase | Change | Gate |
|------:|-------:|-----:|
| 1 | Add `tenant_home_dir` helper + quota walker behind feature flag `cw_home_on_volume` (default OFF) | unit tests + saguilera tenant smoke |
| 2 | Flip flag ON for `saguilera` only; observe writable layer for 24 h | flat or declining writable-layer growth |
| 3 | Flag ON for all tenants; keep old path untouched | 7-day soak |
| 4 | Delete old `/home/codeworker/st_sessions/` writes; one-shot init removes the stale tree | sentinel green for 14 days |

## Acceptance signals

- Code-worker writable layer stays under 2 GiB across a 7-day window
  with continuous chat traffic.
- A noisy tenant that previously hit 5.8 GB in `.local/lib` is now
  capped at 2 GB without breaking ongoing CLI invocations.
- Sentinel's `≥90 % + code-worker layer >5 GiB` recycle trigger does
  not fire under normal operation for a 14-day window.

## Non-goals

- Reducing the inventory of CLI binaries inside the code-worker
  image itself (~7.8 GB virtual size) — separate concern, slow churn.
- Cross-tenant package cache deduplication (every tenant still gets
  its own `.local/lib` because credential isolation is paramount).
