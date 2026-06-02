# API restart hang — bound uvicorn's request-drain so SSE can't block the WhatsApp shutdown drain

**Date:** 2026-06-02 · **Status:** Fix (follow-up to PR #765 WhatsApp session durability)
**Files:** `apps/api/Dockerfile` (uvicorn CMD). Mirrors: none — both docker-compose (`build:`) and helm (no `container.command` override) inherit the image CMD, so the Dockerfile is the single source.
**Related:** `docs/plans/2026-06-02-whatsapp-session-durability-design.md` (§8 deferred this); `helm/values/agentprovision-api.yaml` + `docker-compose.yml` (`stop_grace_period: 180s`, unchanged).

## The problem (the other half of "api hangs ~180s on restart")
On SIGTERM uvicorn (0.47.0, default `timeout_graceful_shutdown = None`) **waits indefinitely for in-flight requests to finish before running the lifespan/shutdown hooks.** The api serves several never-ending streams as `while True` loops:
- `apps/api/app/api/v2/session_events.py` — v2 session SSE (`while True: pubsub.get_message(timeout=5)`),
- `apps/api/app/api/v1/chat.py` — chat-job events SSE,
- `apps/api/app/api/v1/collaborations.py` and others.

These never complete on their own, so uvicorn sits in *"Waiting for connections to close"* until docker's `stop_grace_period: 180s` SIGKILLs the process.

**Why it nullifies the WhatsApp drain:** the clean-shutdown drain (`shutdown_whatsapp` → `whatsapp_service.drain_and_shutdown`, PR #765) is a FastAPI `@app.on_event("shutdown")` hook. Lifespan shutdown runs **after** uvicorn's request-drain. So while the SSE keeps uvicorn waiting, the drain never runs — no bounded wait, no per-account disconnect, no validated session save. Confirmed live 2026-06-02: a restart logged "Waiting for connections to close" with **zero** `WhatsApp drain:` lines, and a SIGKILL landed at the grace ceiling. (The PR #765 corruption fix still made that SIGKILL recoverable — restore validated the current blob and reconnected with no QR — but the hang itself remained.)

## Root cause
uvicorn's request-drain is unbounded, and the only long-lived requests are infinite SSE/WebSocket streams. The shutdown ordering (request-drain → lifespan shutdown) means an unbounded request-drain starves the lifespan drain.

## Fix
Make uvicorn wait ≤10s for in-flight requests on SIGTERM, then **cancel** the lingering SSE/WebSocket streams and proceed to the lifespan shutdown (the WhatsApp drain).

### Delivery mechanism — ENV var, not just the image CMD (post-deploy correction)
The first cut added `--timeout-graceful-shutdown 10` to the uvicorn CMD in `apps/api/Dockerfile`. **That change is inert in this deployment** and was verified so on 2026-06-02: the Docker-Desktop deploy **bind-mounts `apps/api` and does not rebuild the api image** (the running image `agentprovision-agents-api:latest` is days old; the "Building api" step hits `#6 CACHED` and produces no new image). A CMD-only change therefore never reaches the running container — `docker inspect` showed the live container still on the old CMD after a successful deploy.

The operative fix is to set the value as an **environment variable**, which the deploy applies on every container recreate (no rebuild needed):
```
UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=10
```
uvicorn's CLI is a click command with `context_settings={"auto_envvar_prefix": "UVICORN"}`, so every option is settable via `UVICORN_<OPTION>`; `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN` == `--timeout-graceful-shutdown`. Verified empirically in-container (`RESOLVED=33` for a 33 env value). Set in `docker-compose.yml` (api `environment:`) and `helm/values/agentprovision-api.yaml` (api `env:`), kept in sync per the no-drift rule. The Dockerfile CMD flag is retained as a consistent default for a plain `docker run` / a future real image rebuild, but the **env var is what takes effect** in the live deploy.

### What gets cut, and why a 10s cap is an acceptable trade (corrected — Luna + superpowers review)
An earlier draft claimed "no long-blocking HTTP request exists / chat is job-based." **That is false for the live path** and is corrected here:
- The job-based path (`POST /messages/start` → `{job_id}` + `GET /jobs/{job_id}/events`) exists in `chat.js`, but the actual chat UIs (`apps/web/src/dashboard/tabs/ChatTab.js`, `apps/web/src/pages/ChatPage.js`, the Luna client) call the **blocking** `POST /sessions/{id}/messages/stream` (and `/messages`, `/messages/upload`, `/messages/enhanced`) — a single long-lived POST that runs the **full** turn inline, with **no replay**.
- So a 10s graceful-shutdown **does cut an in-flight chat turn that has run >10s** when a restart lands mid-turn. The web client surfaces this as a stream timeout; the user retries. This is a **deliberate, accepted, deploy-time degradation** — it is the only thing that regresses the 180s grace's chat-turn protection.
- Why it's acceptable: deploys are **merge-triggered** (operator-controlled, infrequent), chat p50 is ~5.5s so most turns finish under the cap, and the alternative is strictly worse — a **guaranteed** 180s hang on every restart in which the WhatsApp drain **never runs** (no validated shutdown save). The flag trades one rare, retryable, in-flight turn for the drain actually running + ~13s restarts.
- The genuinely long-lived requests — v2 session SSE (`?since=<seq_no>`), chat-job SSE (`?from_seq=`), collaborations (pure Redis subscriber, events persist in the blackboard), review/task/MCP SSE — are all **reconnect+replay safe**; cutting them is a no-op the clients already handle (Cloudflare's 100s idle drop). There are **no WebSocket routes** (`@app.websocket` / `@router.websocket` count = 0), so no mid-frame WS concern.

A single uvicorn timeout **cannot** distinguish an infinite SSE stream from a finite 90s chat POST (it caps both); the surgical alternative that would protect chat turns is in *Considered + rejected* below. One global flag covers all SSE/WS endpoints uniformly — minimal blast radius.

## Budget (must fit the container stop grace) — corrected per Luna review
`stop_grace_period` / `terminationGracePeriodSeconds` = **180s** (kept). uvicorn's request-drain runs BEFORE the lifespan shutdown, so the WhatsApp drain **and its fallback** share the remaining budget:
- uvicorn request-drain ≤ **10s** (`--timeout-graceful-shutdown`).
- lifespan shutdown = `shutdown_whatsapp` → `drain_and_shutdown`, capped at **`_DRAIN_CAP_S = 140`** (`main.py` `asyncio.wait_for`); realistic ≈ in-flight wait 90s + concurrent disconnect ~8s + fast saves ≈ ~100s.
- on drain-timeout/exception, a **bounded** fallback `shutdown()` capped at **`_FALLBACK_CAP_S = 8`**.
- **Worst case = 10 + 140 + 8 = 158s < 180s**, ~22s teardown margin. (The prior 10 + 165 + 10 = **185s overflowed** — docker could SIGKILL the fallback mid-run; Luna caught it. The non-timeout `except` fallback is now `wait_for`-bounded too, so the handler can never itself hang.)
- **Invariant for future edits:** `uvicorn_graceful + _DRAIN_CAP_S + _FALLBACK_CAP_S` must stay **≤ ~160s** (≤180 with margin). Bumping `WHATSAPP_DRAIN_DEADLINE_SECONDS` or the caps without revisiting the 180s grace re-introduces the SIGKILL-mid-write window.

Idle restart (no in-flight chat turn): uvicorn waits ~≤10s to cut the ever-present dashboard SSE, drain completes in seconds → **~13s restart** (down from ~180s), and the validated shutdown save runs.

## Acceptance criteria
- `docker restart api` with a dashboard SSE connected → restart completes in ~10–15s (not ~180s).
- Shutdown logs show `WhatsApp drain: starting` → per-account `Saved validated WhatsApp session … (shutdown …)` → `WhatsApp drain: complete` (the drain actually runs).
- WhatsApp reconnects on startup with no QR; SSE clients reconnect and replay from `since=<seq>`.
- Worst-case shutdown (uvicorn 10 + drain 140 + fallback 8 = 158s) stays under the 180s grace.
- **Known, accepted:** an in-flight blocking chat turn (`/messages/stream` et al.) that has run >10s when a deploy lands is cut and the user retries — the deliberate trade for the drain running (see "What gets cut").

## Considered + rejected
- **Surgical per-SSE shutdown `asyncio.Event` (protect chat turns):** close the infinite SSE streams promptly on shutdown while letting finite chat POSTs finish naturally — protects chat turns AND fixes the hang. Rejected for now (operator chose the simple flag, 2026-06-02): it must be threaded through every streaming endpoint and needs a shutdown signal set *before* the lifespan phase, which fights uvicorn's own SIGTERM handler (one `add_signal_handler` slot per signal). Tracked as the follow-up if the deploy-time chat-turn cut proves annoying.
- **Drop `stop_grace_period` to 30s:** rejected in PR #765 (Codex-5.5) — the drain needs headroom; the hang is fixed by bounding the request-drain, not the grace.
