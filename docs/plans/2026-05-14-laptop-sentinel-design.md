# Laptop Sentinel — Design

**Date:** 2026-05-14
**Status:** Approved (brainstorming complete)
**Owner:** nomade
**Implementation:** to follow as `2026-05-14-laptop-sentinel-implementation.md` (writing-plans next)

## Goal

A continuously-running monitor for this MacBook (M4) that keeps the `agentprovision-agents` docker-compose stack healthy and the host out of disk-pressure trouble. It runs as a Claude Code `/loop` session, ticks every 5 minutes, auto-recovers known-safe failure modes, and notifies on critical events only.

The motivating failure history is documented in memory:
- `docker_disk_full_recovery` — Docker VM disk full → db FATAL on `postmaster.pid` write; recovery is image+builder+container prune (never `volume prune`).
- `whatsapp_silent_disconnect_recovery` / `whatsapp_auto_restore_handler` — silent socket staleness fixed by `docker compose restart api`; auto-handler exists but is in-process to the api container, so it can't help when the api itself is down.
- `ci_deploy_secret_hydration_race` — concurrent self-hosted runs clobber each other's workdir; cloudflared comes up creds-less.

The sentinel is the always-on safety net layered above those in-process handlers.

## Non-goals

- Not a replacement for the WhatsApp auto-restore handler (in-process, faster) — sentinel is the fallback when the api is down.
- Not a Kubernetes/production observability stack — local laptop only.
- Not a metrics/timeseries tool — append-only JSON log is enough for trending; no Prometheus.
- Not in scope for the `management-platform-db-1` container (separate stack, separate concern).

## Design choices (decided in brainstorming)

| Choice | Decision | Rationale |
|---|---|---|
| Behavior on detection | Auto-recover + notify | Matches `full_autonomy_grant`; failure modes are well-understood and have documented playbooks. |
| Notification sinks | macOS notification + log file + push to phone | Triage locally; only escalate to phone for critical. |
| Runtime | `/loop` in a long-running Claude Code session | User preference. Re-arm with one command after Claude Code restart. |
| Cadence | Every 5 minutes | Catches db/api flaps quickly; ~288 ticks/day. |
| Service roster | Pinned list of 12 services | Simpler; sentinel surfaces "I expected service X and didn't find it" clearly. Manual update when stack changes is acceptable. |
| Push policy | Critical only | 5-min cadence × any-degraded-pushes would be noisy. macOS notification + log still fire on every degraded tick. |

## Components

```
scripts/sentinel/
├── sentinel.md          # the runbook the loop reads each tick (the actual logic)
├── state.json           # last_status, consecutive_failures, last_action_at per action key
├── sentinel.log         # append-only JSONL, one line per tick
└── README.md            # how to start / stop / re-arm the loop
```

The `/loop` prompt is intentionally short — it just says "run scripts/sentinel/sentinel.md". All evolving logic lives in the markdown runbook so we can iterate without restarting the loop session.

## Tick logic (single pass, fail-fast on first action)

Order matters: disk pressure must clear before container recovery, because most container failures during disk-full cascade.

1. **Host disk** — `df -h /`
   - free <10GB → `warn`
   - free <5GB → `critical` (push)
2. **Docker disk** — `docker system df` + `docker info` (for VM disk if surfaced)
   - reclaimable >10GB AND VM free <20GB → `docker image prune -f` then `docker builder prune -f`
   - VM free <5GB → `critical` (push)
   - **Never** `volume prune`, **never** `docker system prune -a`.
3. **Container roster** — `docker ps --format '{{.Names}}\t{{.Status}}'` filtered to the pinned list:
   ```
   agentprovision-agents-orchestration-worker-1
   agentprovision-agents-luna-client-1          (expect healthy)
   agentprovision-agents-web-1                  (expect healthy)
   agentprovision-agents-api-1                  (expect healthy)
   agentprovision-agents-memory-core-1
   agentprovision-agents-code-worker-1
   agentprovision-agents-mcp-tools-1            (expect healthy)
   agentprovision-agents-db-1
   agentprovision-agents-embedding-service-1
   agentprovision-agents-cloudflared-1
   agentprovision-agents-temporal-1
   agentprovision-agents-redis-1
   ```
   Missing or not `Up` → `docker compose up -d <service>` from the resolved compose workdir (see "Workdir resolution").
   Healthcheck-expected service in `Up` but not `(healthy)` after 2 ticks → `docker compose restart <service>`.
4. **DB liveness** — `docker exec agentprovision-agents-db-1 pg_isready -U postgres`. Not ready → restart db; if disk also flagged in step 2, re-check after disk action ran first.
5. **API liveness** — `curl -fsS http://localhost:8000/health` (sentinel verifies the path on first run; falls back to `/` if `/health` 404s, then locks in the working path in `state.json`). Down >2 ticks → `docker compose restart api`. Per memory `whatsapp_silent_disconnect_recovery`, this is also the documented recovery for stale neonize sockets.
6. **Cloudflared** — `docker logs --tail 50 agentprovision-agents-cloudflared-1` greps for `Unable to find tunnel credentials` (the `ci_deploy_secret_hydration_race` symptom). If matched → push only; tell the user to run the documented recovery (copy creds + `.env` from dev workdir). Sentinel does NOT auto-recover this — credential hydration is a human decision.

## Workdir resolution

Sentinel does not hardcode the compose path. On the first tick (and cached in `state.json`), it inspects a running container:

```
docker inspect agentprovision-agents-db-1 \
  --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}'
```

The result (e.g. `/Users/nomade/actions-runner/_work/agentprovision-agents/agentprovision-agents`) is the canonical workdir for any `docker compose up -d` / `restart` the sentinel issues. This avoids the workdir-drift hazard called out in `ci_deploy_secret_hydration_race`.

## State, cooldowns, escalation

`state.json`:
```json
{
  "compose_workdir": "/Users/nomade/...",
  "api_health_path": "/health",
  "last_status": "healthy",
  "consecutive_failures_by_key": { "api_down": 0, "db_down": 0, "disk_warn": 0 },
  "last_action_at": { "image_prune": "2026-05-14T...", "api_restart": "..." }
}
```

Rules:
- **Cooldown**: any specific recovery action runs at most once per 15 minutes. The cooldown key is the action verb (`image_prune`, `db_restart`, `api_restart`, `compose_up_<service>`).
- **Escalation**: if the same problem persists across 3 consecutive ticks despite recovery attempts, the sentinel stops auto-acting on that problem and pushes a critical notification with the diagnostic trail. Resets when the problem clears for a tick.
- **Docker engine unreachable**: `docker info` failure → push only, no further action. That's a Rancher Desktop / human problem.

## Notifications

Per real event:

| Sink | When |
|---|---|
| `sentinel.log` (JSONL append) | Every tick, healthy or not — needed for trending. |
| `osascript -e 'display notification ...'` | Every degraded or critical tick. |
| `PushNotification` tool | Critical only (host <5GB, Docker VM <5GB, escalation, docker engine unreachable, cloudflared creds missing, api down >3 ticks). Re-push every 30min if the critical persists. |

Push payload format:
```
[sentinel:critical] <one-line summary> — <recovery attempted yes/no> — see scripts/sentinel/sentinel.log
```

## Bootstrap & operator UX

`scripts/sentinel/README.md` documents:

- **Start**: open Claude Code in `agentprovision-agents/`, run `/loop 5m run the sentinel runbook at scripts/sentinel/sentinel.md`.
- **Stop**: end the Claude Code session.
- **Re-arm after reboot**: same start command. State persists; cooldowns resume from `state.json`.
- **Tail**: `tail -f scripts/sentinel/sentinel.log | jq .`
- **Manual run** (verify changes to runbook): `claude -p "run scripts/sentinel/sentinel.md"`.

## Safety properties (invariants)

1. Never executes `docker volume prune`, `docker system prune -a`, `docker compose down -v`, or any command that removes volumes / data.
2. Never deletes files outside `scripts/sentinel/`.
3. Never runs more than one mutating action per tick (fail-fast ordering).
4. Cooldown table makes restart loops structurally impossible inside a 15-min window.
5. Escalation makes infinite recovery loops structurally impossible across windows.
6. If `docker` is unreachable, sentinel becomes read-only.

## Out of scope (deferred, can revisit)

- Live-derived service roster (rejected for v1; revisit if we add services often).
- Push on every degraded tick (rejected as too noisy).
- Sidecar container variant (rejected — can't help when Docker engine itself is the problem).
- `/schedule` remote routine (rejected — can't see local Docker).
- Integration with the `management-platform-db-1` stack.
- Alerting on temporal workflow backlog or redis memory pressure (add later if those become real).

## Open questions for implementation

1. Confirm api healthcheck path on first sentinel run; cache in `state.json`.
2. Confirm Rancher Desktop's docker VM disk reporting surface (`docker info` field name) on this machine — `sentinel.md` will probe in v0.
3. Decide whether `cloudflared` log-grep belongs in v1 or v2; leaning v1 because it's the cheapest of the three "human problem" detectors.

## Next step

Invoke `superpowers:writing-plans` to produce `2026-05-14-laptop-sentinel-implementation.md`.
