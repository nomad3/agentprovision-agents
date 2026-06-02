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
Add `--timeout-graceful-shutdown 10` to the uvicorn CMD (`apps/api/Dockerfile`). uvicorn then waits ≤10s for in-flight requests, **cancels** the lingering SSE/WebSocket streams, and proceeds to the lifespan shutdown (the WhatsApp drain).

Why this is safe — there is **no long-blocking HTTP request** to cut:
- The chat turn is **job-based**: `POST /sessions/{sid}/messages/start` returns `{job_id}` in <200ms (`chat.py`), generation runs in the worker, results stream over `GET /jobs/{job_id}/events` SSE with `from=<seq>` replay.
- Every long-lived request is a **reconnect+replay-safe SSE/WS stream** (`since=<seq_no>` / `from=<seq>`). Cutting one on shutdown just makes the client reconnect after restart — exactly what those endpoints already handle for Cloudflare's 100s idle drop.

One global flag covers **all** SSE/WS endpoints uniformly — no per-endpoint shutdown-event plumbing, minimal blast radius.

## Budget (must fit the container stop grace)
`stop_grace_period` / `terminationGracePeriodSeconds` = **180s** (kept; protects the drain, not chat turns which are now job-based).
- uvicorn request-drain ≤ **10s** (T).
- then lifespan shutdown = WhatsApp drain: in-flight wait deadline 90s + concurrent disconnect ~8s + fast validated saves ≈ **~100s realistic worst**, **165s hard cap** (`main.py` `asyncio.wait_for`).
- Total ≤ T + drain ≈ 10 + ~100 = ~110s typical; ≤ 10 + 165 = 175s absolute < 180s. ✓

Idle restart (no in-flight turns): uvicorn waits ~≤10s to cut the ever-present dashboard SSE, drain completes in seconds → **~13s restart** (down from ~180s), and the validated shutdown save runs.

## Acceptance criteria
- `docker restart api` with a dashboard SSE connected → restart completes in ~10–15s (not ~180s).
- Shutdown logs show `WhatsApp drain: starting` → per-account `Saved validated WhatsApp session … (shutdown …)` → `WhatsApp drain: complete` (the drain actually runs).
- WhatsApp reconnects on startup with no QR; SSE clients reconnect and replay from `since=<seq>`.
- No long-blocking HTTP request is truncated (none exist — chat is job-based).

## Considered + rejected
- **Per-SSE shutdown `asyncio.Event` + SIGTERM handler:** would cut SSE in ~1s (vs ~10s) but must be threaded through every streaming endpoint and fights uvicorn's own SIGTERM handler (one `add_signal_handler` slot per signal). Higher blast radius for a ~9s gain. Possible future optimization, not needed now.
- **Drop `stop_grace_period` to 30s:** rejected in PR #765 (Codex-5.5) — the drain needs headroom; the hang is fixed by bounding the request-drain, not the grace.
