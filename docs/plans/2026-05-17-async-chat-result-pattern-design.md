# Async chat-result pattern — beat Cloudflare 524 on long CLI turns

Date: 2026-05-17
Owner: Alpha platform
Status: Design (task #161)

## Why now

Current flow: `POST /chat/sessions/{id}/messages/stream` runs the CLI
turn in a worker thread and streams chunks back over SSE. A 3-second
heartbeat comment is interleaved (`apps/api/app/api/v1/chat.py:223`),
which prevents the common idle-origin 524 case.

Residual failure modes:

1. **Worker crash mid-generation.** The `done_event.wait()` loop keeps
   waiting and the heartbeats stop — CF eventually 524s. Client can't
   tell crash from a slow turn.
2. **Client disconnect (mobile sleep, tab close, network blip).** The
   generation finishes but the result is lost — there's no replay.
   User reloads the chat and sees nothing.
3. **Very long turns (multi-CLI plans, code-worker iterations).** Even
   with heartbeats, the CF Tunnel happily holds the SSE open, but
   intermediate proxies (corporate, mobile carriers) cut connections
   after 60–120 s of "anomalous" SSE.

We want a model where the **CLI turn is owned by the server**, not by
the request lifecycle. The client subscribes; if the subscription
drops, the work continues, and any client (same browser, second tab,
Luna mobile, watch face) can re-attach.

## Approach — job + replayable event stream

```
POST   /chat/sessions/{id}/messages/start          → {job_id}
GET    /chat/jobs/{job_id}/events?from=<seq>       SSE, replays seq+1..N, tails live
POST   /chat/jobs/{job_id}/cancel                  best-effort
GET    /chat/jobs/{job_id}                         { status, result, error, last_seq }
```

Server-side:

- `chat_jobs` table — `id`, `session_id`, `status` (queued/running/done/failed/cancelled),
  `result_message_id` nullable, `error` nullable, `created_at`, `finished_at`.
  Single source of truth for whether a job is alive.
- `chat_job_events` table — `(job_id, seq) PK`, `kind` (chunk/tool_use/tool_result/lifecycle),
  `payload jsonb`, `created_at`. Append-only ring; we keep the last
  N=2000 events per job, dropped on `finished_at + 24h` via a janitor.
- Workers write events through the existing `SessionEventEmitter` —
  bind a `job_id` alongside the `chat_session_id` so the same
  150 ms/32-chunk/16 KB batching applies. Add a Postgres LISTEN/NOTIFY
  channel `chat_job_evt:{job_id}` so the SSE endpoint wakes
  immediately on new events without polling.
- SSE endpoint:
  1. Fetch all events with `seq > from` (catch-up, replay).
  2. Subscribe to LISTEN channel, push new events as they land.
  3. When the job row flips to a terminal status, emit a final
     `result` event and close the stream.
  4. Heartbeat comment every 3 s if no event in that window.

Client-side:

- `chat.postMessageStart(sessionId, content)` returns `{job_id}` — fire
  in `<200 ms` even on huge turns.
- `chat.subscribeJob(job_id, fromSeq, onEvent, onDone, onError)` wraps
  `fetch(..., body reader)` like today's `postMessageStream`, but
  every event carries `seq`; the client remembers the highest seq it
  rendered so it can reconnect with `?from=<seq>` and replay nothing
  it's already seen.
- Reconnect strategy: on `fetch` reject or stream end without
  terminal event, retry with exponential backoff capped at 8 s,
  `from=<last_seq>`. Stop retrying when the job row says terminal.

## Migration path

1. **Migration N** — new tables `chat_jobs`, `chat_job_events`.
   Backfill: not needed; only new turns get a job_id.
2. **API additions** — `/messages/start`, `/jobs/{id}/events`,
   `/jobs/{id}/cancel`. Old `/messages/stream` stays untouched.
3. **`SessionEventEmitter`** — add optional `job_id` field; when set,
   events are persisted to `chat_job_events` in addition to the
   existing in-memory broadcast.
4. **Web client** — new `postMessageStart` + `subscribeJob`. Keep
   `postMessageStream` as a fallback path behind a feature flag
   (`chat_async_jobs`, default OFF for prod, ON for `saguilera` test
   tenant first).
5. **Cutover** — once the flag is ON tenant-wide and no
   regressions surface for a week, delete the old endpoint.

## Open questions (decide before code)

- **Cancel semantics.** Cooperative only (set `cancel_requested=true`,
  the CLI executor polls)? Or hard kill the subprocess? Lean
  cooperative + 30 s grace then SIGTERM.
- **Backpressure on `chat_job_events`.** A noisy CLI can emit
  thousands of chunks. Either compact at the emitter (already does
  16 KB batching) or compact at write time (merge adjacent same-kind
  rows). Lean: rely on emitter batching, observe in prod.
- **Multi-tenant fairness.** A single tenant can saturate the
  worker pool with long jobs. Out of scope for this design;
  separate workstream — covered by the existing CLI tier routing.

## Risks

- **DB write amplification.** Every chunk becomes a row. Mitigated
  by emitter batching (150 ms/32-chunk/16 KB) — expected ≤ 4–6
  rows/sec/turn at peak.
- **LISTEN/NOTIFY scaling.** Postgres caps total LISTEN channels per
  backend. Use a single channel `chat_job_evt` with the job_id in the
  payload; SSE subscribers filter in user-space.
- **Event ordering across replicas.** `(job_id, seq)` PK forces
  monotonic per-job ordering; emitter assigns seq via a sequence per
  job. No reorder risk.

## Non-goals

- Tool-result streaming protocol changes (already handled by
  `chunk_kind` taxonomy).
- Multi-CLI fan-out / coalition pattern (covered separately).
- Mobile push when a long job finishes — future work; the job table
  is the durable signal a push handler can read.

## Rollout phases

| Phase | Scope | Gate |
|------:|------:|-----:|
| 1 | Tables + write path (jobs created on every new turn, events persisted, old SSE endpoint unchanged) | Migration green, no read traffic yet |
| 2 | Read path (`/jobs/{id}/events`) + feature-flag-gated client switch on `saguilera` | 24 h soak, p95 chunk latency within 200 ms of legacy |
| 3 | Flag ON for all tenants | 7-day error-rate parity |
| 4 | Delete `/messages/stream` endpoint + the legacy client path | After Phase 3 has run 14 days |

## Acceptance signals

- A turn that takes 5 minutes (e.g. multi-CLI plan + code-worker
  build) reaches the user with zero 524s on the production Cloudflare
  Tunnel.
- Closing and reopening the tab during a long turn restores all the
  text that was generated while disconnected.
- Cancel button observably halts the CLI within 30 s.
