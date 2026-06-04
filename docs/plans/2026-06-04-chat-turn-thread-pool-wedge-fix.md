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
| **A. Bound the wait (correctly)** | `cli_session_manager.py` — bound the **Temporal await itself** with `asyncio.wait_for(execute_workflow(...), timeout=…)` inside `_run_workflow`, so the coroutine completes (raises `TimeoutError`) and both branches (`asyncio.run` and the `submit().result()`) return promptly with **no thread left to join**. Do **not** rely on `with ThreadPoolExecutor(...).result(timeout=…)` (see Review 1, C1). | **Liveness** — a timeout actually releases the caller thread and fails the chat_job; never an infinite hang or a `shutdown(wait=True)` re-wedge. |
| **B. Dedicated WhatsApp executor + bounded admission** | Give the WhatsApp path its own `ThreadPoolExecutor(max_workers=N)` **and** an `asyncio.Semaphore(QUEUE_CAP)` gating submission (the executor's internal submit queue is unbounded). Over-cap → immediate "I'm a bit overloaded, try again" fallback, not unbounded queueing. | **Blast-radius containment + backpressure** — a WhatsApp burst can never starve the default pool *or* pile up watchers that time out before starting. |
| **C. Fire-and-forget delivery, ordered per sender** | WhatsApp inbound enqueues a `chat_job` and returns immediately; a watcher polls the job to terminal state and sends the reply, keeping "typing…" alive. **Full job execution is serialized per `session_key`** (a per-sender single-consumer queue), so turn N completes before N+1 starts — replies and history can't invert. | **Architectural fix** — no API thread is held across the multi-minute CLI run, and a linear DM thread stays linear. |

## Completion mechanism (chosen)

Hook the **chat_jobs terminal state** (in-process), not SSE/HTTP, not the v2 session_events Redis envelope:
- `chat_jobs` `_run_job` (`chat.py:550-678`) is already the proven fire-and-forget primitive: own `SessionLocal()`, `post_user_message`, emits one `kind='chunk'` event with the full assistant text (`chat.py:629-635`), then `finish_job(result_message_id=…)` (`chat_jobs.py:174-199`) / `fail_job` on exception.
- Watcher polls `chat_jobs_service.get_job(...)` (`chat_jobs.py:115-154`) ~1s until terminal; on `done` reads `read_events(from_seq=0)` (`chat_jobs.py:355-399`) and takes the `chunk` `payload['text']` as the reply body (`result_message_id` → `chat_messages.content` as fallback).
- Terminal status (`done`/`failed`/`cancelled`) is the single source of truth for "done, and did it succeed" — which the SSE/session_event paths don't cleanly carry.

## Implementation steps (revised after Review 1)

1. **(A) — real timeout.** In `cli_session_manager.py`, wrap the Temporal wait inside `_run_workflow` with `await asyncio.wait_for(client.execute_workflow(...), timeout=CHAT_CLI_DISPATCH_TIMEOUT)` (env, default 600s — the chat-wait SLA, **never** the 180min `execution_timeout`). Because the coroutine now self-terminates on timeout, **both** call sites resolve cleanly: the no-loop branch (`asyncio.run(_run_workflow())`, line 1628) returns on `TimeoutError`; the loop branch's `submit(...).result()` (1616-1622) gets a result/exception so its worker thread finishes — no `shutdown(wait=True)` join on a hung thread. `TimeoutError` → existing rollback/`(None, metadata)` failure path → `fail_job`. (The orphaned Temporal workflow keeps running server-side; acceptable — no consumer, and it self-expires. Optionally fire `handle.cancel()` on timeout.)
2. **Extract** `chat_jobs.run_job_blocking(job_uuid, *, session_id, tenant_id, user_id, content, media_parts=None, sender_phone=None)` from `chat.py:550-678`. **Ownership guard:** only run the body if `start_job(...)` transitions `queued→running` (it owns the job); otherwise return. Thread `media_parts`/`sender_phone` into `post_user_message`. **Concatenate all `chunk` events in seq order** for the reply text (don't assume a single chunk).
3. **Point the web endpoint at it** — `chat.py` inline `_run_job` body → `run_job_blocking(...)`, keep the `threading.Thread(daemon=True)` dispatch (web stays unbounded-daemon this PR; the helper makes a later migration trivial). Proves the extraction is behavior-preserving for web.
4. **(B)** `whatsapp_service.py.__init__` — `self._chat_executor = ThreadPoolExecutor(max_workers=N=4, thread_name_prefix='wa-chat')` **+** `self._chat_admit = asyncio.Semaphore(QUEUE_CAP)` (bounded admission). Shut the executor down in `drain_and_shutdown`/`shutdown`.
5. **(C) ordered per-sender dispatch.** `_process_through_agent` keeps db/user/agent/session resolution (`1601-1657`); replace the `_run_chat`+`to_thread` block (`1674-1703`) with: snapshot primitives → `create_job(...)` → return `job_uuid`. Submission goes through a **per-`session_key` single-consumer task** (an `asyncio.Queue` per `whatsapp:{sender_id}`) that runs jobs strictly sequentially: acquire `_chat_admit` (non-blocking; over-cap → terminalize job + overloaded-fallback), submit `run_job_blocking` to `self._chat_executor`, await its completion, send the reply, then take the next queued turn. This serializes **execution and send** per sender.
6. **(C) watcher / completion.** The per-sender consumer awaits the job to terminal state (poll `get_job` ~1s up to `WHATSAPP_JOB_WATCH_TIMEOUT`≈600s). On `done` → concatenated chunk text → existing send block (`whatsapp_service.py:1487-1517`), **re-reading `self._clients.get(key)` at send time**; on `failed`/`cancelled`/timeout/empty → fallback message; `finally` stop typing + release `_chat_admit` + decrement inflight.
7. **(C) inbound rewrite + typing ownership.** `whatsapp_service.py:1477-1519`: enqueue onto the per-sender consumer; **move typing-stop into the consumer's per-turn finally** so "typing…" survives the async run. **If enqueue/`_process_through_agent` fails *before* a consumer turn starts, the inbound handler itself stops typing + sends a fallback** (covers the pre-watcher failure path).
8. **Submit-failure terminalization.** Wrap `executor.submit(...)` in try/except (e.g. `RuntimeError` during shutdown) → immediate `fail_job(job_uuid)` → consumer sends fallback. Never leave a `queued` job to rot until the watch timeout.
9. **Drain correctness + mid-turn policy.** Track per-sender consumer + in-flight tasks in a set; bracket `_inflight_turns` around the **consumer turn** lifetime. On `drain_and_shutdown` deadline (`2206`): cancel pending consumer tasks and send each affected sender a best-effort "I'm restarting — please resend that in a moment" before disconnect (or document the deliberate no-send).

## Failure / ordering / edge handling

- **Failure:** on `failed`/`cancelled`/empty-`done`/watcher-timeout → send a short human fallback ("Sorry, I hit an error processing that — try again in a moment"). Closes today's silent-drop bug (`whatsapp_service.py:1485-1486` returns None, sends nothing).
- **Typing indicator:** `typing_done.set(); await typing_task` moves into the watcher `finally` (fires on every terminal path). PAUSED presence only after a successful send.
- **Recipient staleness:** capture `reply_jid`/phone at inbound; **re-read `self._clients.get(key)` at send time** (client object may swap on reconnect during a long wait).
- **Audio:** transcription stays on the inbound path (`whatsapp_service.py:1406-1446`, already async) — the job `content` is the transcript; enqueue happens after.
- **Ordering:** WhatsApp DMs are one linear thread per sender. Recommend serializing replies per `session_key` (`whatsapp:{sender_id}`) with an `asyncio.Lock` map so turn N+1's reply waits for turn N. (The per-tenant CLI slot already serializes the CLI runs themselves.)

## Review 1 — Luna (lead, Codex-5.5), 2026-06-04 — BLOCK → addressed

**Verdict:** block as written. Critical bug + 6 required changes, all now folded into the Approach + Implementation steps above.

- **C1 (critical):** the `with ThreadPoolExecutor(...).result(timeout=600)` pattern doesn't bound the wait — on timeout the context manager's `shutdown(wait=True)` joins the still-running `asyncio.run()` thread and re-wedges. The existing loop-branch has the same latent bug. → **Step 1 rewritten** to bound the Temporal await with `asyncio.wait_for` so the coroutine self-terminates and no thread is left to join.
- **R2:** dedicated executor needs **bounded admission** (the submit queue is unbounded) → **Step 4** adds `asyncio.Semaphore(QUEUE_CAP)` + overloaded-fallback.
- **R3:** ordering is **required**, covering execution + send, per `session_key` → **Step 5** uses a per-sender single-consumer queue.
- **R4:** `run_job_blocking` must check `start_job` **ownership** and **concatenate all chunks** → **Step 2**.
- **R5:** **submit failure must terminalize** the job immediately → **Step 8**.
- **R6:** **drain mid-turn policy** — track tasks, cancel + best-effort notice on deadline → **Step 9**.
- **R7:** **typing ownership** on the pre-watcher failure path → **Step 7**.

**Open questions resolved by Luna:**
1. Extract `_run_job` shared — **yes**; `post_user_message` already accepts `sender_phone`+`media_parts`.
2. Web bounded pool — **not mandatory** this PR; keep web daemon-thread, make the helper migration-ready.
3. Ordering — **required** per `session_key`, execution + send.
4. Inflight/drain — watcher-bracketed accounting correct; **add deadline fallback/cancel**.
5. Timeout — **never 180min on the API wait**; 600s only as the env-configured chat SLA, and it must be a **real** (cancellable) timeout.
6. `read_events` ceiling — fine for one chunk; **concatenate** to future-proof.
7. Executor `N` — **start 4**, paired with the bounded semaphore + metrics.

**Status:** revised plan pending Luna re-confirm (→ approve-with-changes), then implement.

## Test plan

- Unit: watcher sends reply on `done`, fallback on `failed`/`cancelled`/empty/timeout; typing stops on every path; inflight decremented on every path; client re-read at send time.
- Unit: Part A bounded wait raises/fails (not hangs) on a stubbed never-returning dispatch.
- Regression: web chat_jobs path unchanged after `run_job_blocking` extraction (existing chat_jobs tests green).
- Integration (local): two rapid WhatsApp turns → both get replies, ordered; a deliberately-slow turn does not block a subsequent turn (the wedge cannot recur).

## Rollout

PR off `fix/chat-turn-thread-pool-wedge` → assign nomad3 → Codex-5.5 + Luna + superpowers code review → merge → deploy → live verify with two rapid WhatsApp turns. No migration (chat_jobs table already exists, migration 137).
