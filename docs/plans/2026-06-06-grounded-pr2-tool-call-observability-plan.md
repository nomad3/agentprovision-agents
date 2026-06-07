# Grounded Pattern PR 2 — Tool-Call Observability Foundation

**Date:** 2026-06-06
**Status:** Draft
**Owner:** Simon Aguilera
**Lead:** Luna Supervisor
**Reviewers:** Codex (gpt-5.5), Luna
**Branch:** `codex/grounded-pr2-tool-call-observability`, branched off fresh `origin/main` (the grounded parent doc lives on `main`; PR 2 touches backend files disjoint from the signing/computer-use branch, so no chaining needed and it avoids colliding with the Luna-Tauri/alpha-CLI work)
**Parent:** `docs/plans/2026-06-06-grounded-agentprovision-pattern.md` §9 "PR 2 - Tool-call observability foundation" + §15 "Recommended first implementation slice"

> Sequence rule from the parent (§15): **measure first, trace second, enforce third.** This PR is the *measure* step. It changes no agent behavior — it only makes tool calls joinable to the user turn that triggered them and queryable for "specifics without tools."

---

## Current State

The audit substrate already exists and is partly fused; the gap is **per-turn linkage** and a **read path**, not the absence of a log. Grounded entirely in the substrate maps:

### Tool-call audit (MCP path — already built)
- **`tool_calls` table** — `apps/api/migrations/108_tool_calls_audit.sql`. Columns: `id` (UUID), `tenant_id` (UUID, NOT NULL, **no FK** by design), `tool_name` (TEXT), `arguments` (JSONB), `result_status` (TEXT: `ok` | `error` | `scope_denied` | `tier_denied`), `result_summary` (TEXT, truncated ~800 chars), `error` (TEXT), `duration_ms` (INTEGER), `started_at` (TIMESTAMPTZ DEFAULT NOW()), `ended_at` (TIMESTAMPTZ). Indexes: `ix_tool_calls_tenant_started`, `ix_tool_calls_tool_name`, `ix_tool_calls_tenant_errors` (filtered `WHERE result_status='error'`). **No `session_id`, `message_id`, or `agent_id` columns.**
- **Single interception point** — `install_audit(mcp)` → `audited_handler` in `apps/mcp-server/src/tool_audit.py` (lines 365-614), installed once at startup via `apps/mcp-server/src/mcp_serve.py:35-39`. Wraps the FastMCP lowlevel `CallToolRequest` handler, so **both SSE and streamable-HTTP transports** feed the same audit path. Captures `tool_name`, `arguments`, `started_at` + monotonic `started`, resolves auth via `mcp_auth.resolve_auth_context()`, executes the handler, classifies result (`ok`/`error`/`scope_denied`/`tier_denied`), and fires `_log_call` (lines 220-328) fire-and-forget via executor.
- **Auth/tenant resolution** — `apps/mcp-server/src/mcp_auth.py:137-200` returns `AuthContext(tier, tenant_id, agent_id, task_id, user_id, scope)`. `agent_id`/`task_id` are present **only** in the `agent_token` tier; `tenant_header`/`internal_key` tiers carry no agent context. **`agent_id` is received in `audited_handler` but is NOT extracted before `_log_call`** — so it is never persisted.
- **Drop safety net** — `apps/mcp-server/src/audit_breadcrumb.py` writes minimal rows to `tool_audit_drops` (`apps/api/migrations/148_tool_audit_drops.sql`) at three drop sites: `no_tenant_id`, `sql_insert_failed`, `scheduling_failed`. Separate pool (size 2). Counters in `apps/mcp-server/src/audit_metrics.py`. The breadcrumb table deliberately has **no `tenant_id`** (the whole point is it was unresolvable).
- **Redaction** — `_log_call` applies three-layer arg redaction (`_SENSITIVE_ARG_TOOLS` frozenset → keys-only; credential-key pattern; value-side `Bearer`/`sk-`/`xoxb-`/JWT pattern). `tool_audit_drops.args_keys` is top-level keys only, capped at 20.
- **Enforcement gate** — `tenant_features.enforce_strict_tool_scope` (`apps/api/migrations/149_p0a_tool_permission_gate.sql`, default FALSE; model `apps/api/app/models/tenant_features.py:141-143`). FALSE = shadow-log only; TRUE = reject denials. Fail-closed when `tenant_id` is None regardless of flag.

### Turn model and the CLI subprocess path
- **`chat_messages`** — `apps/api/app/models/chat.py:46-76`. PK `id` (UUID), FKs `session_id`, `agent_id` (nullable), `task_id` (nullable). `role` (`user`|`assistant`), `content`, `context` (JSON), `created_at` (server_default `func.now()`). **This `id` is the join key to the user turn.**
- **`chat_sessions`** — same file. FKs `tenant_id`, `agent_id`, `owner_user_id`. Tenant boundary lives here.
- **Turn entry point** — `chat.post_user_message()` (`apps/api/app/services/chat.py:293`). Creates the user message, calls `_generate_agentic_response`, and the assistant `ChatMessage.id` is available by ~line 384. It is **not** threaded into `run_agent_session` / `agent_router` / the worker, so the worker does not know which turn spawned a tool call.
- **CLI subprocess path** — code-worker emits tool activity as `cli_subprocess_stream` events: `apps/code-worker/session_event_emitter.py` `emit_chunk(chunk_kind, …)` with `chunk_kind in {tool_use, tool_result, …}` (lines 135, 241-280, batch-posted to the internal endpoint). The internal write endpoint is `apps/api/app/api/v2/internal_session_stream.py:70` (`POST /api/v2/internal/sessions/{session_id}/events`, `X-Internal-Key` auth, type-whitelisted to `cli_subprocess_stream`), which fans the batch out to `publish_session_event` per chunk (line ~126). **These CLI tool chunks never reach the MCP `tool_calls` audit path** — they are unstructured JSONB in `session_events`.

### Generic event log (already built, PR 1 substrate)
- **`session_events`** — `apps/api/migrations/133_session_events.sql`, model `apps/api/app/models/session_event.py`. Columns: `id`, `session_id` (FK chat_sessions, NOT NULL), `tenant_id` (NOT NULL, no FK), `seq_no` (BIGINT, monotonic per session via `pg_advisory_xact_lock(hashtext(session_id))`), `event_type` (VARCHAR 64), `payload` (JSONB), `created_at`. `UNIQUE(session_id, seq_no)` for replay dedup. Written via `publish_session_event(chat_session_id, event_type, payload, tenant_id=None)` in `apps/api/app/services/collaboration_events.py:73-200` (resolves `tenant_id` from the session row if not supplied). Read via `apps/api/app/api/v2/session_events.py` (SSE + paginated replay, tenant-scoped via `_ensure_session_visible()`). The dual-write test `apps/api/tests/services/test_publish_session_event_dual_write.py` already exercises a `tool_call_started` event type.

### Existing correlation (imprecise) and the gap
- **`vw_fabrication_candidates`** — `apps/api/migrations/109_fabrication_candidate_view.sql`. Joins `chat_messages` (assistant, content ≥ 200 chars) to `tool_calls` on a **±90s time window** (`tc.started_at BETWEEN cm.created_at - 90s AND cm.created_at + 5s`). Returns `tenant_id, message_id, session_id, created_at, resp_chars, platform, agent_slug, response_preview, stderr_tool_errors, audit_tool_calls`. This is the only existing "specifics without tools" path. The migration comment itself acknowledges: *precise per-turn correlation needs `session_id` threading through MCP*.

**Net:** name/status/duration/tenant are captured for MCP tools; **`message_id`/`session_id`/`agent_id` are not**, the CLI subprocess tool path is not in `tool_calls` at all, and there is no REST read API — only a diagnostic view with time-window approximation.

---

## Goal & Acceptance Criteria

**Goal (parent §9, PR 2):**
- capture structured tool calls per turn
- persist tool name, status, duration, and message/session/tenant linkage
- expose a query path for "assistant produced specifics without tools"

**Acceptance (parent §9 + §10 + §15):**
1. Every MCP/tool invocation can be **joined to the user turn** that triggered it (precise, not time-window).
2. **Failed tool calls** (`error`, `scope_denied`, `tier_denied`, and CLI tool errors) are **visible to metacognition and evals**.
3. **No cross-tenant tool-call visibility** — reads fail closed on missing tenant scope (§10 "Tenant boundaries fail closed").
4. **Measure first** (§15): this PR changes no agent behavior — it only records and exposes. Enforcement is PR 5; trace ledger is PR 3.

---

## Design Decision: where observations live

**Decision: EXTEND the existing `tool_calls` table (migration 108) with turn-linkage columns, and ALSO capture CLI subprocess tool chunks into the same table at the internal-stream ingress.** Do not create a parallel `tool_call_observations` table for PR 2.

### Why `tool_calls` is the primary home
The grounded doc forbids inventing a parallel architecture (§2 gap, §15). `tool_calls` is already the canonical audit spine:
- It is written from the single MCP interception point (`tool_audit.audited_handler`) — every MCP tool already flows through it.
- It already has `tool_name`, `result_status`, `duration_ms`, `arguments`, `error`, `started_at`/`ended_at`, and tenant-scoped indexes.
- `vw_fabrication_candidates` already queries it; extending it makes that view's join *precise* instead of time-windowed.
- The breadcrumb fail-safe (`tool_audit_drops`) already protects it.

Adding `session_id` / `message_id` / `agent_id` columns turns the existing ±90s approximation in migration 109 into a direct PK join with **zero duplication**.

### Why NOT `session_events`
`session_events` is the control-plane viewport stream (replay/SSE for the dashboard). Tool chunks already pass through it as unstructured `cli_subprocess_stream` payloads. Forcing structured tool-call audit into `session_events` would (a) duplicate the `tool_calls` data, (b) require either a new FK column or fragile `payload->>'message_id'` JSON-extraction joins, and (c) couple audit retention (high value for evals) to the 30-day viewport retention sweep. Keep `session_events` for viewport visibility; keep `tool_calls` for audit/grounding. (`session_events` does, however, give us the bridge for the CLI path — see below.)

### Why NOT a brand-new `tool_call_observations` table (now)
A separate table is the natural home for **PR 3's `ClaimLedgerEntry`** (claims, a different granularity), per parent §5. For PR 2's granularity (tool *invocations*), a new table would duplicate `tool_calls` and split the audit spine. Defer the new table to PR 3 where it carries claim-level provenance, not tool invocations.

### Covering BOTH paths
- **API/MCP tool path:** extend `tool_calls`; populate the new linkage columns inside `tool_audit._log_call` from `AuthContext` + request headers (see Schema). This is the only interception point — guaranteed coverage.
- **Code-worker CLI subprocess path:** these tools never enter `tool_audit`. Capture them where the batch is already fanned out: in `apps/api/app/api/v2/internal_session_stream.py`, for each `cli_subprocess_stream` chunk with `chunk_kind in {tool_use, tool_result}`, write a structured `tool_calls` row (in addition to the existing `publish_session_event` call) via a new API-side service. This reuses an existing ingress with `X-Internal-Key` auth and tenant validation — no new endpoint, no parallel architecture.

> Migration number: the next available is **163** (current max `162_desktop_command_approval_grants.sql`, confirmed in `apps/api/migrations/`). Down migration required (repo convention: every `NNN_*.sql` has a matching `NNN_*.down.sql`).

---

## Schema

Single additive migration, idempotent (`ADD COLUMN IF NOT EXISTS`), reversible via `.down.sql`.

**`163_tool_calls_turn_linkage.sql`** — extend `tool_calls`:

| Column | Type | Null | Notes |
|---|---|---|---|
| `session_id` | UUID | nullable | FK → `chat_sessions(id)`. Turn-context + access-control key. Nullable so async/internal calls without session context still record (and fail-safe to `tool_audit_drops`, not silently lost). |
| `message_id` | UUID | nullable | FK → `chat_messages(id)`. **Precise join key to the user turn.** `WHERE message_id IS NULL` on a long assistant turn = "specifics without tools" candidate. |
| `agent_id` | UUID | nullable | FK → `agents(id)`. The agent that invoked the tool (from `AuthContext.agent_id` or the CLI run's agent). Needed for turn-level agent→tools attribution. |
| `source` | TEXT | nullable | `mcp` (audited_handler) vs `cli_subprocess` (internal stream). Lets evals separate the two ingress paths. |

Keep existing `tenant_id` (UUID, NOT NULL, **no FK**) per the 108 design — allows forensics on deleted tenants and avoids cascade deletes; isolation is enforced at the API/service layer (the `agent_tasks` precedent: `service.get_*(db, …, current_user.tenant_id)`).

`result_status` keeps its existing vocabulary (`ok`/`error`/`scope_denied`/`tier_denied`). For the CLI path, map `tool_result` chunks carrying an error to `error` and successful ones to `ok`. (Extending the enum for `timeout`/`async_pending` is noted as a gap but is **out of scope for PR 2** to keep this measurement-only.)

**Indexes (additive):**
- `idx_tool_calls_message_started ON tool_calls(message_id, started_at DESC) WHERE message_id IS NOT NULL` — per-turn lookup.
- `idx_tool_calls_session_started ON tool_calls(session_id, started_at DESC) WHERE session_id IS NOT NULL` — per-session audit trail.
- Keep existing tenant/error indexes.

**Tenant-isolation invariant:** every read path filters `WHERE tenant_id = :current_tenant_id`; if tenant scope is missing, **fail closed** (return empty / 403, never a cross-tenant row). The MCP-side fail-safe already drops to `tool_audit_drops` when `tenant_id` is unresolvable (drop site #1).

**Join to the user turn:**
```sql
-- precise per-turn (post-PR2)
SELECT cm.id AS message_id, tc.tool_name, tc.result_status, tc.duration_ms
FROM chat_messages cm
LEFT JOIN tool_calls tc ON tc.message_id = cm.id
WHERE cm.session_id = :session_id
  AND cm.tenant_id IS NOT DISTINCT FROM :tenant_id   -- via chat_sessions scope
  AND cm.role = 'assistant';
```

---

## Phased Tasks

Each phase is individually testable and changes no agent behavior.

### Phase 0 — Branch + plan
- [ ] Create branch `codex/grounded-pr2-tool-call-observability` off fresh `origin/main` (PR 2 is backend with files disjoint from the signing/computer-use branch; the grounded parent doc is on `main`).
- [ ] Land this plan doc at `docs/plans/2026-06-06-grounded-pr2-tool-call-observability-plan.md`.
- [ ] Review the plan with Codex (gpt-5.5) and Luna before implementation (project rule for CLI-orchestration work).

### Phase 1 — Schema migration (additive, reversible)
- [ ] Add `apps/api/migrations/163_tool_calls_turn_linkage.sql`: `ADD COLUMN IF NOT EXISTS session_id/message_id/agent_id/source` + the two partial indexes above.
- [ ] Add `apps/api/migrations/163_tool_calls_turn_linkage.down.sql`: drop indexes + columns.
- [ ] Apply via the documented local pattern (`kubectl cp` + `psql -f`, or docker exec + manual `_migrations` insert with column `filename`; `git add -f` for the `.sql`).
- **Test:** migration applies and rolls back cleanly against CI's isolated Postgres; `tool_calls` still accepts existing inserts (NULL linkage columns).

### Phase 2 — Thread `message_id` + `agent_id` to the MCP tool path
- [ ] Pass the assistant `ChatMessage.id` and `agent_id` from `chat.post_user_message()` (`apps/api/app/services/chat.py:293`, id available ~line 384) down through `_generate_agentic_response` → `cli_session_manager.run_agent_session()` (`apps/api/app/services/cli_session_manager.py:747`) → `agent_router` so they reach the MCP request context.
- [ ] Emit `X-Message-Id` (+ reuse existing `X-Tenant-Id`, agent JWT) on MCP-over-SSE calls so they are present in the request the audited handler sees.
- [ ] In `apps/mcp-server/src/mcp_auth.py`, surface `message_id`/`session_id` from headers alongside `tenant_id` (extend `_get_header` usage / `AuthContext`).
- [ ] In `apps/mcp-server/src/tool_audit.py` `audited_handler` + `_log_call`, extract `agent_id` (already on `AuthContext`, currently dropped) and the new `session_id`/`message_id`, and INSERT them with `source='mcp'`. If `session_id`/`message_id` unavailable, record the row with NULLs (do **not** force a drop — only missing `tenant_id` drops, per existing drop site #1).
- **Test:** an MCP tool call originating from a known turn lands a `tool_calls` row whose `message_id` equals the assistant `ChatMessage.id`; `agent_id` populated when an agent token is present.

### Phase 3 — Capture the CLI subprocess tool path
- [ ] In `apps/api/app/api/v2/internal_session_stream.py`, in the batch fan-out loop (~line 126), detect chunks with `chunk_kind in {tool_use, tool_result}` and write a structured `tool_calls` row (`source='cli_subprocess'`) in addition to the existing `publish_session_event`.
- [ ] Extend `apps/code-worker/session_event_emitter.py` `emit_chunk` so tool chunks carry structured metadata (`tool_name`, `status`, `duration_ms`, `message_id`, `agent_id`) — thread `message_id`/`agent_id` from the worker run context (the same values posted to the internal endpoint body).
- [ ] Pair `tool_use` + `tool_result` chunks into one `tool_calls` row (use the run/chunk correlation already present in the stream) so `duration_ms` and `result_status` reflect the full tool invocation; a lone error `tool_result` still records `result_status='error'`.
- **Test:** a code-worker run that invokes a CLI tool produces a `tool_calls` row with `source='cli_subprocess'`, correct `tool_name`/`status`, and `message_id` matching the turn.

### Phase 4 — Service layer (tenant-scoped)
- [ ] Add `apps/api/app/services/tool_observations.py` (mirroring `apps/api/app/services/execution_traces.py`): `get_tool_calls_by_session(db, session_id, tenant_id, skip, limit)`, `get_tool_calls_by_message(db, message_id, tenant_id)`, `get_ungrounded_turns(db, session_id, tenant_id)` (assistant messages with zero linked `tool_calls` and `content` length ≥ 200). Every query filters `tenant_id` at the service layer; fail closed when `tenant_id` is None.
- [ ] Add `apps/api/app/schemas/tool_observation.py`: `ToolCallObservation` response model (id, tool_name, result_status, duration_ms, message_id, session_id, agent_id, source, started_at).
- **Test:** service functions never return rows for a foreign `tenant_id`; `get_ungrounded_turns` returns long assistant turns with no `tool_calls`.

### Phase 5 — Read/Query API
- [ ] Add `apps/api/app/api/v1/observations.py`, mount in `apps/api/app/api/v1/routes.py`, all routes `Depends(get_current_user)` (`apps/api/app/api/deps.py`) for tenant scope:
  - `GET /api/v1/observations/tool-calls?session_id=…&since=…&until=…` → tool calls for a session.
  - `GET /api/v1/observations/tool-calls?message_id=…` → tool calls for one turn (precise join).
  - `GET /api/v1/observations/ungrounded-turns?session_id=…` → assistant turns with zero tool calls ("specifics without tools").
- [ ] Each endpoint validates the `session_id`/`message_id` belongs to `current_user.tenant_id` before returning (reuse the `_ensure_session_visible` style check from `apps/api/app/api/v2/session_events.py`).
- **Test:** cross-tenant `session_id` → 404/empty; failed tool calls appear in results.

### Phase 6 — Make the diagnostic view precise (optional, additive)
- [ ] Add a comment in `apps/api/migrations/109_fabrication_candidate_view.sql` (or a new `163`-adjacent migration) noting the ±90s window is superseded by the precise `message_id` join; keep the view for backward compatibility. (Do not drop it in PR 2.)
- **Test:** precise join and the view agree for turns where `message_id` is populated.

---

## Read/Query API

The "assistant produced specifics without tools" path, tenant-scoped, consistent with existing `/api/v1` patterns (the `agent_tasks` + `execution_traces` precedent: `Depends(get_current_user)` → `current_user.tenant_id` passed as a filter, not FK enforcement).

```
GET /api/v1/observations/ungrounded-turns?session_id=<uuid>
Auth: Bearer JWT (Depends(get_current_user))
Tenant: derived from current_user.tenant_id — never a query param
Returns: [
  { message_id, session_id, created_at, resp_chars, agent_id, response_preview, tool_call_count: 0 }
]
```
Backing query (precise, post-PR2 — replaces the ±90s logic of `vw_fabrication_candidates`):
```sql
SELECT cm.id, LEFT(cm.content, 300) AS preview, COUNT(tc.id) AS tool_calls
FROM chat_messages cm
JOIN chat_sessions cs ON cs.id = cm.session_id
LEFT JOIN tool_calls tc ON tc.message_id = cm.id
WHERE cm.role = 'assistant'
  AND cm.session_id = :session_id
  AND cs.tenant_id = :tenant_id           -- fail-closed tenant scope
GROUP BY cm.id, cm.content
HAVING COUNT(tc.id) = 0 AND LENGTH(cm.content) >= 200;
```
Companion endpoints `GET /api/v1/observations/tool-calls?session_id=…` and `?message_id=…` return the per-session / per-turn tool-call lists (including `result_status='error'|'scope_denied'|'tier_denied'`) so metacognition and evals can see failures.

---

## Testing

Per project verification discipline: **DB-touching tests run against CI's isolated Postgres, never the live prod DB** (false failures + leaked throwaway tenants). Pure-logic and serialization tests can run locally against the image.

- **Migration round-trip** (CI Postgres): `163` applies and `163.down` reverts; pre-existing `tool_calls` rows unaffected.
- **Tenant isolation** (CI Postgres): seed two tenants; assert every `tool_observations` service function and every `/api/v1/observations/*` route returns only the caller's tenant rows; foreign `session_id`/`message_id` → 404/empty; missing tenant scope → fail closed.
- **Join-to-turn** (CI Postgres): synthesize a turn (`chat_messages` row) + an MCP `tool_calls` row carrying that `message_id`; assert `get_tool_calls_by_message` returns it and `message_id` matches the assistant `ChatMessage.id`.
- **CLI path capture** (CI Postgres): post a `cli_subprocess_stream` batch with `tool_use`/`tool_result` chunks to `internal_session_stream`; assert a `tool_calls` row with `source='cli_subprocess'` and correct `result_status`.
- **Failed-tool visibility** (CI Postgres): rows with `result_status in {error, scope_denied, tier_denied}` surface in the read API and in `get_ungrounded_turns` accounting.
- **Ungrounded-turn query** (CI Postgres): a long assistant turn with zero linked tool calls appears; a turn with tool calls does not.
- **Serialization / schema** (local, pure-logic): `ToolCallObservation` pydantic round-trip; redaction unchanged.
- **MCP-side audit** (mcp-server tests): extend `apps/mcp-server` audit tests to assert `agent_id`/`message_id`/`session_id`/`source` are persisted; reuse the existing `tool_call_started` event-type precedent from `apps/api/tests/services/test_publish_session_event_dual_write.py`.
- **Drop-path unchanged** (CI Postgres): missing `tenant_id` still routes to `tool_audit_drops` (no regression to the three drop sites).

---

## Safety / Non-Goals

- **Trace only — no enforcement.** No grounding gate, no tool-required policy, no behavior change. Enforcement is parent §9 PR 5; this PR is the §15 *measure* step.
- **No cross-tenant reads.** Tenant filter on every service + API path; fail closed when tenant scope is missing (§10 "Tenant boundaries fail closed"). `tool_audit_drops` stays tenant-less by design.
- **`tenant_id` stays no-FK** on `tool_calls` (108 design) — forensics on deleted tenants; isolation at the API layer.
- **No new audit table for tool invocations.** `ClaimLedgerEntry` (parent §5) is PR 3's separate table; PR 2 reuses `tool_calls`.
- **No `session_events` schema change.** It remains the viewport stream; tool-call audit stays in `tool_calls`.
- **Redaction unchanged.** Reuse the existing three-layer arg redaction; do not widen what is persisted.
- **Internal `tool_executor.py` tools out of scope.** Only `LeadScoringTool` remains there and does not go through MCP; documenting it as out-of-scope (potential PR 4+ hook).
- **No `result_status` enum extension** (`timeout`/`async_pending`) in this PR — noted as a follow-up gap.

---

## Risks

- **Threading `message_id` through the chat hot path** touches `chat.py` → `cli_session_manager.py` → `agent_router.py` → MCP request context. Risk of breaking the chat path. Mitigation: nullable columns + optional header — if `message_id` is absent the row still records with NULL (no exception, no behavior change).
- **CLI tool pairing** (`tool_use` + `tool_result` into one row) depends on stream correlation in `session_event_emitter`; mis-pairing skews `duration_ms`/`status`. Mitigation: record a lone error `tool_result` as `error` even if unpaired.
- **Double-counting** if a tool somehow flows through both MCP and CLI ingress. Mitigation: `source` column lets queries disambiguate; MCP and CLI paths are disjoint in practice.
- **Latency** of an extra synchronous insert on the CLI internal-stream ingress. Mitigation: MCP side stays fire-and-forget; CLI side inserts inside the existing fan-out transaction (already per-chunk).
- **Retention coupling.** If `tool_calls` ever inherits a retention sweep, failed-call evidence for evals could age out. Mitigation: out of scope here, but note that `tool_calls` is the audit spine and should retain failures (mirror the `auto_quality_score` "keep indefinitely" precedent in migration 133 if a sweep is later added).

## Open Questions

- **(Parent §14, "Where should traces live initially")** Confirmed for PR 2: extend `tool_calls` for tool invocations; `agent_memory`/dedicated trace table deferred to PR 3 for claim-level entries. Reviewer to ratify.
- Should `session_id`/`message_id` be **NOT NULL** once threading is proven stable (a later tightening migration), with `tool_audit_drops` gaining a `no_session_id` drop reason — or stay nullable indefinitely?
- For the CLI path, is reliable `tool_use`↔`tool_result` pairing available in the current `stream-json` chunk stream, or do we need a correlation id added to `emit_chunk`?
- Does `agent_id` need to be threaded for `tenant_header`-tier MCP calls (which currently carry no agent context), or is NULL acceptable for PR 2's measurement goal?
- Should `/api/v1/observations/*` be superuser-only or available to any tenant member? (Default proposed: any authenticated tenant member, tenant-scoped — matches `execution_traces`.)