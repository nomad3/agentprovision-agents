# Implementation Plan: Terminal Card — Full CLI Output

**Date:** 2026-05-16
**Goal:** Replace the generic `start/end/duration/cost` terminal output with the **full CLI transcript** — reasoning, tool calls, file edits, real stdout — same as users see when running Claude Code / Codex / Gemini directly in their own terminal.

---

## 1. Diagnosis — Current state of `cli_subprocess_stream`

### Verified facts from the codebase

| Question | Answer |
|---|---|
| Is `cli_subprocess_stream` defined as an event type? | **Yes** — consumed by `apps/api/app/api/v2/session_events.py:87` (coalescer) and rendered by both `TerminalCard.js:49-51` and `AgentActivityPanel.js:59-60`. |
| Is `cli_subprocess_stream` ever **emitted**? | **No.** Repo-wide grep returns **zero producer sites**. |
| Where does the actual CLI subprocess run? | **`apps/code-worker/cli_runtime.py:158`** — `subprocess.Popen(..., stdout=PIPE, stderr=PIPE)` then `proc.communicate(timeout=timeout)` (blocking, line 169). Worker-side waits for **full completion** before returning. No incremental fan-out. |
| Lifecycle event source | `apps/api/app/services/agent_router.py:1066, 1102, 1130, 1167, 1182` — emitted from the **API process** (`_legacy_chain_walk` + `publish_session_event`). API only knows "started/complete" because it `await`s Temporal as one blocking call. |
| Worker DB/Redis access | **None.** Worker uses `httpx` + `X-Internal-Key` to fan back to API (precedents: `workflows.py:323, 354, 517-521, 1238`). |
| Worker knows `chat_session_id`? | **No.** `ChatCliInput.session_id` is the **Claude-CLI native session_id** (for `--resume`), not `chat_sessions.id`. The agentprovision chat_session_id lives in `db_session_memory["chat_session_id"]` in the API and is never put on `_ChatCliInput`. |
| Claude Code `--output-format stream-json`? | Currently `--output-format json` (`cli_executors/claude.py:77`). `stream-json` emits NDJSON per event. Requires `--verbose`. |

### Root cause

**`cli_subprocess_stream` is dead protocol on the producer side.** The wire format, the SSE coalescer, the React renderer, and even tests all exist — but no code ever calls `publish_session_event("cli_subprocess_stream", ...)`. Three blockers:

1. **Worker→API plumbing**: no internal endpoint that accepts stream events.
2. **chat_session_id propagation**: never reaches the worker.
3. **Subprocess draining**: `proc.communicate()` buffers entire stdout. Must switch to line-reader threads.

---

## 2. Output Formatting Per CLI

### 2.1 Claude Code → `--output-format stream-json --verbose`

Switch `cli_executors/claude.py:77` from `"json"` to `"stream-json"` and add `"--verbose"`. CLI emits NDJSON:

```jsonl
{"type":"system","subtype":"init","session_id":"...","tools":[...]}
{"type":"assistant","message":{"content":[{"type":"text","text":"I'll start by..."}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"..."}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","content":"file contents..."}]}}
{"type":"result","subtype":"success","total_cost_usd":0.13,"usage":{...}}
```

Render rules in `TerminalCard.js`:

| stream-json `type` | Terminal line format | `chunk_kind` |
|---|---|---|
| `system.init` | `▷ init claude_code (session=<id8>, tools=N)` | `lifecycle` |
| `assistant.message.content[].text` | text content, wrapped | `text` |
| `assistant.message.content[].thinking` | `· thinking: <abbrev>` (dim) | `reasoning` |
| `assistant.message.content[].tool_use` | `→ Tool(<name>) <abbrev_input>` | `tool_use` |
| `user.message.content[].tool_result` | `← <name> <truncate_400>` or `✗ <name>: <err>` | `tool_result` |
| `result.success` | `✓ done · $<cost> · <in>/<out> tok` | `lifecycle` |
| `result.error_*` | `✗ <subtype>: <message>` | `lifecycle_error` |

Edit-diff detection: when `tool_use.name in {"Edit", "Write", "NotebookEdit"}`, render `  file: <path>` and on the matching `tool_result` extract the diff summary capped at 12 lines.

**Emit one event per parsed line**, not per byte.

### 2.2 Codex → `codex exec ... --json`

Already passes `--json`. Map:

| `kind` | Terminal line | `chunk_kind` |
|---|---|---|
| `reasoning.text` | `· <text>` | `reasoning` |
| `command` | `$ <cmd>` | `tool_use` |
| `command.output` | `<stdout chunk>` | `stdout` |
| `function_call` / `tool_call` | `→ <name>(<args>)` | `tool_use` |
| `agent_message.text` | text | `text` |
| `last_message` | `✓ done` | `lifecycle` |
| `error` | `✗ <msg>` | `lifecycle_error` |

Fallback for unrecognized lines: pass through as `stdout`.

### 2.3 Gemini CLI

Gemini's `--output-format json` only emits one terminal JSON at end-of-run. Live transcript requires stderr streaming:

- `^Error executing tool ...` → `tool_result`, prefix `✗`.
- `[gemini] tool: <name>` patterns → `tool_use`.
- all other stderr → `stderr` (dim).
- final stdout JSON parsed once → `text` + `lifecycle`.

Phase-1: stream stderr verbatim.

### 2.4 Copilot / opencode

Wire emitter with `chunk_kind: "stdout"`/`stderr"` passthrough only.

---

## 3. Event Payload Shape

Fits existing v2 envelope. New `payload`:

```json
{
  "type": "cli_subprocess_stream",
  "payload": {
    "platform": "claude_code",
    "chunk_kind": "text|reasoning|tool_use|tool_result|stdout|stderr|lifecycle|lifecycle_error",
    "chunk": "rendered line string",
    "fd": "stdout|stderr",
    "attempt": 1,
    "ts_worker": "2026-05-16T12:34:56.789Z",
    "raw": { "...": "..." }  // optional, capped 4 KB
  }
}
```

Backward-compat:
- `chunk` is the rendered string `TerminalCard.js:50` already reads.
- `fd` already consumed at `TerminalCard.js:51, 164`.
- `chunk_kind` is **additive** — old code ignores it.
- The 5-second coalescer (`session_events.py:69-140`) keys on `payload.platform`. Update to preserve `chunk_kind` per coalesced chunk: `chunks: [{chunk, chunk_kind, fd}]`.

---

## 4. Backend Implementation Steps

### 4.1 Propagate `chat_session_id` to worker

- `apps/code-worker/workflows.py:1060-1071` — add `chat_session_id: str = ""` and `attempt: int = 1` to `ChatCliInput`.
- `apps/api/app/services/cli_session_manager.py:1209-1242` — add `chat_session_id` to inline `_ChatCliInput`, populate from `db_session_memory.get("chat_session_id", "")`.
- `apps/api/app/services/agent_router.py:1074-1086` — pass `attempt_idx + 1` so the worker can stamp `attempt` on each chunk.

### 4.2 Internal endpoint to emit stream events

**New file:** `apps/api/app/api/v2/internal_session_stream.py`
- `POST /api/v2/internal/sessions/{session_id}/events` (mirror auth from `internal_session_events.py:36-46`).
- Body: `{tenant_id: UUID, type: str, payload: dict}`.
- Whitelist `type` to `{cli_subprocess_stream}` (defense-in-depth).
- Validate `session_id` belongs to `tenant_id`.
- Call `publish_session_event(session_id, type, payload, tenant_id=tenant_id)`.
- Return `{seq_no, event_id}`.

Register in `apps/api/app/api/v2/__init__.py`.

### 4.3 Worker-side emitter helper

**New file:** `apps/code-worker/session_event_emitter.py`
- Class `SessionEventEmitter(chat_session_id, tenant_id, platform, attempt)`.
- `emit_chunk(chunk_kind, chunk, fd="stdout", raw=None)`.
- Internal batching queue (150ms window, max 32 chunks / 16 KB).
- `httpx.Client(timeout=2.0)` reused. POST to `{API_BASE_URL}/api/v2/internal/sessions/{sid}/events` with `X-Internal-Key`.
- **Fail-soft**: HTTP errors log WARNING + drop chunk. Subprocess output must NEVER block on the emit channel.
- Background flusher thread; `close()` flushes + joins.

### 4.4 Streaming subprocess pump

**File:** `apps/code-worker/cli_runtime.py:158-199`

Replace `proc.communicate()` with dual line-reader threads:

```python
proc = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True, bufsize=1)  # line-buffered

stdout_lines, stderr_lines = [], []
def _drain(stream, sink, fd_name):
    for line in iter(stream.readline, ""):
        sink.append(line)
        if on_chunk: on_chunk(line, fd_name)
    stream.close()

t_out = Thread(target=_drain, args=(proc.stdout, stdout_lines, "stdout"))
t_err = Thread(target=_drain, args=(proc.stderr, stderr_lines, "stderr"))
t_out.start(); t_err.start()

while proc.poll() is None:
    if time.monotonic() - start > timeout:
        proc.kill(); break
    activity.heartbeat(f"{label} running... ({elapsed}s)")
    time.sleep(min(heartbeat_interval, 5))

t_out.join(timeout=5); t_err.join(timeout=5)
return CompletedProcess(cmd, proc.returncode, "".join(stdout_lines), "".join(stderr_lines))
```

Add `on_chunk: Callable[[str, str], None] | None = None` to `run_cli_with_heartbeat`.

### 4.5 Per-CLI executor: wire emitter + parser

**Claude:** `cli_executors/claude.py`
- Cmd at line 77: `"--output-format", "stream-json", "--verbose"`.
- Instantiate `SessionEventEmitter(task_input.chat_session_id, task_input.tenant_id, "claude_code", task_input.attempt)`.
- `on_chunk=_make_claude_parser(emitter)` — closure that buffers, JSON-parses (fallback to raw stdout), maps per §2.1, emits.
- Keep existing line-125 JSON parse for `result` event → extract from the **last** non-empty stdout line.
- `finally: emitter.close()`.

**Codex:** `cli_executors/codex.py` — emitter pattern with codex-event parser (§2.2). `command.output` → `chunk_kind="stdout"`.

**Gemini:** `cli_executors/gemini.py` — stderr stream + light classifier.

**Copilot/opencode:** passthrough only.

### 4.6 Update SSE replay coalescer

**File:** `apps/api/app/api/v2/session_events.py:69-140`
- Change `pending["payload"]["chunks"]` from list of strings → list of `{chunk, chunk_kind, fd}` dicts.
- Cap at 3 last chunks unchanged. Live SSE path forwards individual chunks; only replay coalesces.
- Update `apps/api/tests/api/v2/test_session_events.py:158-230` fixtures.

---

## 5. Frontend Implementation Steps

### 5.1 `TerminalCard.js` — per-chunk_kind rendering

- Bump `MAX_LINES_PER_TAB` 500 → 1000.
- In the `cli_subprocess_stream` branch (line 44): read `chunk_kind = p.chunk_kind || 'stdout'`; don't truncate `chunk`; push `{seq, chunk, fd, chunk_kind, ts}`.
- JSX (line 161): add `data-kind={line.chunk_kind}` on `<span>`.
- CSS rules in `TerminalCard.css`:
  - `reasoning` → grey italic
  - `text` → default
  - `tool_use` → blue
  - `tool_result` → muted green (success) / red (`✗` prefix)
  - `lifecycle` → bold
  - `lifecycle_error` → red bold
  - `stderr` → red (existing)
- Replay shape: if `payload.chunks` is array of dicts, spread each as its own line.

### 5.2 `AgentActivityPanel.js` — drop `cli_subprocess_stream` case

- Delete the case at lines 59-60. Terminal owns chunks; activity owns lifecycle.
- Filter (line 122-138): `events.filter(e => (e.type || e.event_type) !== 'cli_subprocess_stream')` before render.

### 5.3 Buffer cap + auto-scroll

- 1000 lines per tab.
- Auto-scroll ONLY when already at bottom (`scrollTop + clientHeight >= scrollHeight - 20`). Track via ref.

---

## 6. Performance — Coalescing & Backpressure

### 6.1 Worker-side batching

Claude stream-json firehose: 50–200 events/sec on tool-heavy turns. One HTTP call per event would hammer the API, Postgres advisory locks, Redis pub/sub.

`SessionEventEmitter` strategy:
- Flush every **150 ms** (`WORKER_STREAM_FLUSH_MS`).
- Size cap: **32 chunks or 16 KB**, whichever first.
- Bundling: pack chunks into `{type: "cli_subprocess_stream", payload: {platform, batch: [{chunk_kind, chunk, fd, ts_worker}, ...]}}`.
- API: on `batch`, split + call `publish_session_event` per chunk (each gets own seq_no, deterministic replay).
- Drop policy at queue >1000: drop `reasoning` first, then `stdout`, then `text`. Never drop `lifecycle*` or `tool_use`. WARNING + counter.

### 6.2 API advisory lock contention

`publish_session_event` per-session lock (`collaboration_events.py:121-132`). 150ms windows = ~7 locks/sec/session — fine. If contention surfaces, batch-allocate `len(batch)` seq_nos in one `nextval` query. Defer until measured.

### 6.3 Frontend

- 1000-line cap via `splice`.
- `useMemo` keyed on `[events]`.
- Wrap `<pre>` in CSS `contain: strict`.

---

## 7. Activity-Panel vs Terminal Boundary

**Activity keeps:** `cli_subprocess_started`, `cli_subprocess_complete`, `cli_routing_decision`, `auto_quality_consensus`, `auto_quality_score`, `plan_step_changed`, `subagent_dispatched`, `subagent_response`, `tool_call_started`, `tool_call_complete`, `resource_referenced`, `chat_message`.

**Terminal owns:** `cli_subprocess_stream` (all `chunk_kind` variants) + lifecycle echoes (▶ start / ✓ end) it already draws.

Filter in §5.2 enforces this — stream chunks never appear in activity.

---

## 8. Test Plan

### 8.1 Unit tests

- `apps/code-worker/tests/test_session_event_emitter.py` — batching, size cap, drop policy, fail-soft, close-flushes.
- `apps/code-worker/tests/test_claude_stream_parser.py` — canned stream-json → `(chunk_kind, chunk)` tuples. Cover system.init, assistant.text, tool_use[Edit], tool_result(error), result.success.
- `apps/code-worker/tests/test_codex_stream_parser.py` — same for codex.
- `apps/code-worker/tests/test_cli_runtime_streaming.py` — subprocess emits two prints w/ sleep — `on_chunk` fires twice in order, timeout-kill still works.
- `apps/api/tests/api/v2/test_internal_session_stream.py` — valid key writes + publishes; bad key 401; cross-tenant 404; non-whitelisted type 400.
- `apps/api/tests/api/v2/test_session_events.py` (extend) — coalescer preserves `chunk_kind`; replay returns new shape.

### 8.2 Frontend tests

- `TerminalCard.js` snapshot with mixed-kind events asserting CSS classes + 1000-line cap.
- `AgentActivityPanel.js` confirms `cli_subprocess_stream` does not appear in activity list.

### 8.3 End-to-end tenant smoke

1. Deploy API + code-worker.
2. Dashboard chat, pin `claude_code`.
3. Send: *"Read apps/api/app/main.py and tell me what router prefixes are registered."*
4. Expected terminal output:
   - `▷ init claude_code (session=abc12345, tools=…)`
   - assistant text streaming
   - `→ Tool(Read) {file_path: apps/api/app/main.py}`
   - `← Read <first lines>`
   - more reasoning
   - `✓ done · $0.0234 · 2104/890 tok`
5. Repeat with `codex`, then `gemini_cli`.
6. Network blip: drop traffic to API:8000 mid-stream. CLI completes; chat reply arrives; terminal shows gap but no crash.
7. Buffer-cap: ask Claude to dump 10000-line file. Terminal tail stays at 1000; tab responsive.

### 8.4 Regression checks

- `pytest apps/api/tests/api/v2/test_session_events.py` (adjust fixtures for new shape).
- `pytest apps/code-worker/tests/test_heartbeat_missed_emission.py` (heartbeat fires from main thread with dual-reader pump).
- Chat ending in `cli_subprocess_complete` with `error="quota"` → activity shows routing fallback, terminal shows partial stream, new tab for next CLI.

---

## 9. Rollout & Risk

- **Flag-gate** `--output-format stream-json` for Claude Code behind `tenant_features.cli_stream_output` (default OFF prod, ON for saguilera test tenant). Fallback to `--output-format json` cleanly.
- **No DB schema changes.** `session_events.payload` JSONB; additive.
- **Rollout order:** Deploy API (new internal endpoint) **before** code-worker change. Worker never POSTs to a 404.
- **Observability:** Prometheus counters `cli_stream_chunks_emitted_total{platform, chunk_kind}` and `cli_stream_chunks_dropped_total{reason}`. Alert if dropped > 5%/min.

---

## Critical Files

- `apps/code-worker/cli_runtime.py` — line-reader threads + `on_chunk` (L129-199)
- `apps/code-worker/cli_executors/claude.py` — `--output-format stream-json --verbose`, emitter + parser (L75-146)
- `apps/code-worker/workflows.py` — add `chat_session_id` and `attempt` to `ChatCliInput` (L1060)
- `apps/api/app/services/cli_session_manager.py` — populate `chat_session_id` on `_ChatCliInput` (L1209-1242)
- `apps/web/src/dashboard/TerminalCard.js` — `chunk_kind` rendering, cap 1000, smarter auto-scroll (L26, L42-80, L100-103, L161-168)
