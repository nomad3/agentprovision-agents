# Chat-turn thread-pool wedge — fire-and-forget fix

**Date:** 2026-06-04
**Branch:** `fix/chat-turn-thread-pool-wedge`
**Task:** #11
**Status:** plan — pending Luna (lead) + Codex-5.5 review

## Symptom

WhatsApp Luna went silent for ~3.5h on tenant `752626d9` (2026-06-04). Inbound was received and handed off (`[chat-trace] handoff: to_thread`) but **no** `enter _run_chat` / `enter post_user_message` / `Dispatching ChatCliWorkflow` ever logged for those sessions. Restarting the code-worker did not fix it; only an api restart did. Four queued turns were confirmed wedged (drain reported 4 in-flight at shutdown).

## Root cause (workflow-confirmed, file:line)

It is **not** a per-tenant lock. All 6 readers confirmed no `asyncio.Lock` / `Semaphore` guards the turn path. It is **thread-pool exhaustion of a shared blocking pool**:

1. WhatsApp inbound → `_process_through_agent` → `await asyncio.to_thread(_run_chat)` (`whatsapp_service.py:1694`) submits onto the event loop's **default `ThreadPoolExecutor`** (`max_workers ≈ min(32, cpu+4)` ≈ 18 on the incident host). No custom executor is installed.
2. `_run_chat` → `post_user_message` → CLI dispatch at `cli_session_manager.py:1603-1628`. Two branches wait for the Temporal workflow result:
   - Loop-present branch (`1616-1622`): `ThreadPoolExecutor(max_workers=1).submit(...).result(timeout=600)` — bounded at 600s.
   - **No-loop branch (`1628`): `asyncio.run(_run_workflow())` — NO client-side timeout; blocks forever if the worker never returns.**
3. A hung CLI subprocess on the code-worker (activities bounded by `ThreadPoolExecutor(max_workers=10)`, `worker.py:43-66`; `ChatCliWorkflow` `heartbeat_timeout=300s`, `start_to_close=150min`, `execution_timeout=180min`) keeps `execute_workflow` from returning → the API thread stays pinned (600s, or forever on the no-loop branch).
4. Enough pinned threads saturate the ~18-thread default pool → new `asyncio.to_thread(_run_chat)` tasks **queue and never run** → exactly the observed "handoff logged, enter never logged" signature → tenant-wide WhatsApp silence.

**Honest uncertainty:** the unbounded wait is code-confirmed; full pool saturation at the incident moment is inferred (no thread-dump captured). Either way the fix is the same.

## Approach (user-approved: full architectural fix)

Three **independent** changes — each insufficient alone, ship all three:

| Part | What | Why |
|---|---|---|
| **A. Bound the wait** | `cli_session_manager.py:1628` — wrap the bare `asyncio.run(_run_workflow())` in the same bounded `ThreadPoolExecutor(max_workers=1).result(timeout=…)` pattern as the loop branch. | **Liveness** — guarantees the worker thread is always released; a hung dispatch becomes `fail_job`, never an infinite hang. |
| **B. Dedicated WhatsApp executor** | Give the WhatsApp path its own bounded `ThreadPoolExecutor(max_workers=N)` instead of the shared default. | **Blast-radius containment** — a WhatsApp backlog can never starve the default pool the rest of the api depends on, and bounded `max_workers` gives natural backpressure. |
| **C. Fire-and-forget delivery** | WhatsApp inbound enqueues a `chat_job` and returns immediately; a watcher coroutine polls the job to terminal state and sends the reply, keeping "typing…" alive until then. | **Architectural fix** — no API thread is held across the multi-minute CLI run at all. |

## Completion mechanism (chosen)

Hook the **chat_jobs terminal state** (in-process), not SSE/HTTP, not the v2 session_events Redis envelope:
- `chat_jobs` `_run_job` (`chat.py:550-678`) is already the proven fire-and-forget primitive: own `SessionLocal()`, `post_user_message`, emits one `kind='chunk'` event with the full assistant text (`chat.py:629-635`), then `finish_job(result_message_id=…)` (`chat_jobs.py:174-199`) / `fail_job` on exception.
- Watcher polls `chat_jobs_service.get_job(...)` (`chat_jobs.py:115-154`) ~1s until terminal; on `done` reads `read_events(from_seq=0)` (`chat_jobs.py:355-399`) and takes the `chunk` `payload['text']` as the reply body (`result_message_id` → `chat_messages.content` as fallback).
- Terminal status (`done`/`failed`/`cancelled`) is the single source of truth for "done, and did it succeed" — which the SSE/session_event paths don't cleanly carry.

## Implementation steps

1. **(A)** `cli_session_manager.py:1623-1628` — bound the no-loop branch with `.result(timeout=CHAT_CLI_DISPATCH_TIMEOUT)` (env, default 600s to match the loop branch). On timeout → existing rollback/`(None, metadata)` failure path → `fail_job`.
2. **Extract** `chat_jobs.run_job_blocking(job_uuid, *, session_id, tenant_id, user_id, content, media_parts=None, sender_phone=None)` containing the exact body of `chat.py:550-678`, with `media_parts`/`sender_phone` threaded into `post_user_message` (WhatsApp media/voice).
3. **Point the web endpoint at it** — `chat.py` inline `_run_job` body → call `run_job_blocking(...)`, keep the `threading.Thread(daemon=True)` dispatch. Proves the extraction is behavior-preserving for web.
4. **(B)** `whatsapp_service.py.__init__` — `self._chat_executor = ThreadPoolExecutor(max_workers=N, thread_name_prefix='wa-chat')`; shut down in `drain_and_shutdown`/`shutdown`.
5. **(C)** `_process_through_agent` — keep db/user/agent/session resolution (`1601-1657`); replace the `_run_chat`+`to_thread` block (`1674-1703`) with: snapshot primitives → `create_job(...)` → submit `run_job_blocking` to `self._chat_executor` → return `job_uuid`.
6. **(C)** Add `async def _await_job_and_reply(...)` watcher: poll `get_job` to terminal/`WHATSAPP_JOB_WATCH_TIMEOUT` (~600s backstop); on `done` read chunk text → existing send block (`whatsapp_service.py:1487-1517`); on `failed`/`cancelled`/timeout/empty → fallback message; `finally` stop typing + decrement inflight.
7. **(C)** Rewrite inbound (`whatsapp_service.py:1477-1519`): `job_uuid = await _process_through_agent(...)`; spawn `asyncio.create_task(_await_job_and_reply(...))`; **move the typing-stop out of the inbound finally into the watcher finally** so "typing…" survives the whole async run.
8. **Drain correctness** — move `_inflight_turns += 1 / -= 1` to bracket the **watcher** lifetime (not the old `to_thread`), so `drain_and_shutdown`'s bounded wait (`2206`) still sees mid-CLI turns.

## Failure / ordering / edge handling

- **Failure:** on `failed`/`cancelled`/empty-`done`/watcher-timeout → send a short human fallback ("Sorry, I hit an error processing that — try again in a moment"). Closes today's silent-drop bug (`whatsapp_service.py:1485-1486` returns None, sends nothing).
- **Typing indicator:** `typing_done.set(); await typing_task` moves into the watcher `finally` (fires on every terminal path). PAUSED presence only after a successful send.
- **Recipient staleness:** capture `reply_jid`/phone at inbound; **re-read `self._clients.get(key)` at send time** (client object may swap on reconnect during a long wait).
- **Audio:** transcription stays on the inbound path (`whatsapp_service.py:1406-1446`, already async) — the job `content` is the transcript; enqueue happens after.
- **Ordering:** WhatsApp DMs are one linear thread per sender. Recommend serializing replies per `session_key` (`whatsapp:{sender_id}`) with an `asyncio.Lock` map so turn N+1's reply waits for turn N. (The per-tenant CLI slot already serializes the CLI runs themselves.)

## Open questions for review (Luna lead + Codex-5.5)

1. Extract `_run_job` shared vs WhatsApp copy — confirm `post_user_message` accepts `media_parts`+`sender_phone` on the web path without regression.
2. Web daemon-thread (unbounded) vs WhatsApp bounded executor — keep web as-is or migrate web onto a bounded pool too?
3. Ordering: per-`session_key` serialization required, or accept out-of-order short replies?
4. Inflight accounting: is `drain_and_shutdown`'s 90s bounded wait long enough for a mid-CLI turn, or should draining mid-watch send a "service restarting" notice first?
5. Part A timeout value: 600s vs the 180min `execution_timeout` — confirm long PDF-ingestion turns aren't truncated.
6. `read_events` 2000-row / 24h purge ceiling — confirm the watcher always reads the chunk well within the window (it does; completes in minutes).
7. `N` for the dedicated executor `max_workers` — sized to expected concurrent WhatsApp turns (start 4?).

## Test plan

- Unit: watcher sends reply on `done`, fallback on `failed`/`cancelled`/empty/timeout; typing stops on every path; inflight decremented on every path; client re-read at send time.
- Unit: Part A bounded wait raises/fails (not hangs) on a stubbed never-returning dispatch.
- Regression: web chat_jobs path unchanged after `run_job_blocking` extraction (existing chat_jobs tests green).
- Integration (local): two rapid WhatsApp turns → both get replies, ordered; a deliberately-slow turn does not block a subsequent turn (the wedge cannot recur).

## Rollout

PR off `fix/chat-turn-thread-pool-wedge` → assign nomad3 → Codex-5.5 + Luna + superpowers code review → merge → deploy → live verify with two rapid WhatsApp turns. No migration (chat_jobs table already exists, migration 137).
