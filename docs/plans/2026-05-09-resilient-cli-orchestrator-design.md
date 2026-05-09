# Resilient CLI Orchestrator — Network/Execution Layer Design

**Status:** DRAFT — pending user signoff before any implementation lands
**Date:** 2026-05-09
**Author:** Simon (with Luna design input)
**Branch:** `design/resilient-cli-orchestrator`

## §0 — Architectural principle (load-bearing)

**The CLI is a thin client. The backend is canonical.**

Every resilience concern in this document — error normalization, fallback policy, redaction, preflight, durable metadata — lives **server-side**, behind the same API endpoints the web SPA already calls. The `agentprovision` CLI binary, MCP tools, web SPA, Luna desktop client, Twilio webhook, WhatsApp adapter, and any future surface are **clients of the same control plane**. None of them re-implement orchestration logic.

Concretely:
- **Chat** is `POST /api/v1/chat/sessions/{id}/messages[/stream]` — already wired to `ChatCliWorkflow` on the `agentprovision-code` Temporal queue. The CLI calls this endpoint. The web SPA calls this endpoint. The MCP tool layer calls this endpoint.
- **Code task dispatch** is `CodeTaskWorkflow` reached via the same chat path with a code intent (or via `/api/v1/agent-tasks/` for direct dispatch).
- **Workflow runs** are `POST /api/v1/workflows/{id}/run` — already wired to `DynamicWorkflowExecutor`.
- **Agent fleet operations** are `/api/v1/agents/*` — list, discover, dispatch, heartbeat, audit, rollback.
- **Memory ops** are `/api/v1/memory/*` and the `memory_continuity` MCP module — pgvector, gRPC `memory-core` Rust service.
- **Skill ops** are `/api/v1/skills/*` and the `skills` MCP module.

This principle has three structural consequences for the rest of the document:

1. **Phase 1–3 (resilient orchestrator) live entirely in `apps/api` + `apps/code-worker` Python.** The CLI binary doesn't even know `Status` exists — it sees a normalized HTTP response with `actionable_hint` when a fallback exhausted itself, and renders that hint to the user. Same as the web SPA will.
2. **Phase 4 (leaf-agent inbound) reuses the existing `apps/mcp-server` (port 8086).** It is not a new control plane; it is an additional auth tier on the existing MCP server (§8 revision below).
3. **Webhooks reuse the existing `WebhookConnector` model + `webhook_delivery_logs` table + `fire_outbound_event` service** (§11). We fix the documented gaps (broken `webhook_trigger` executor, plaintext secrets, no retry, no idempotency) instead of paralleling them.

If a future PR proposes "add resilience logic to the CLI" or "make the CLI talk directly to Temporal" — that PR is wrong by construction; reject it.

## Problem

Today's CLI execution path (`apps/code-worker/workflows.py`, `apps/api/app/services/cli_session_manager.py`) leaks raw provider behaviour upward in three ways:

1. **Provider strings, not platform statuses.** Failure handling matches against literal substrings ("rate limit reached", "credit balance is too low", …) at three independent sites — `CLAUDE_CREDIT_ERROR_PATTERNS` (line 106), `CODEX_CREDIT_ERROR_PATTERNS` (line 119), `COPILOT_CREDIT_ERROR_PATTERNS` (line 133), plus regex equivalents in `cli_platform_resolver._QUOTA_PATTERNS` / `_AUTH_PATTERNS` / `_MISSING_CRED_PATTERNS`. Each of the four runtimes has its own tuple, the patterns drift, and consumers (router, chat, RL, council) each re-classify.

2. **No durable execution metadata.** `ChatCliResult` carries `success`, `error`, `model`, `tokens_used`, `cost`. There is no `provider_order_attempted`, no `error_class`, no `retry_decision` / `fallback_decision`, no Temporal `workflow_id`/`activity_id` linkage in the same record. RL experiences capture some of this for `decision_point="code_task"` but not for chat dispatch.

3. **Secret leak surfaces.** GitHub token gets interpolated into a git URL at `workflows.py:1074` (`https://{github_token}@github.com/…`) and that command string can land in subprocess logs / Temporal heartbeats. Codex `auth.json` persists at `~/.codex/auth.json`. The skill sandbox already strips a `_SENSITIVE_ENV_KEYS` frozenset at `skill_manager.py:158`; nothing equivalent runs at the CLI execution boundary.

## Non-goals

- **Not** rewriting `cli_platform_resolver`'s scoring / cooldown engine. That's the higher-level routing brain. We're slotting under it.
- **Not** changing the Temporal heartbeat-on-activity-thread / Popen-on-worker-thread pattern from commit `91f77ee2`. That's the only thing keeping >5min CLI tasks alive. The new adapters wrap it; they don't replace it.
- **Not** introducing a per-runtime SDK. The design specifically avoids an `if platform == "claude_code"` ladder.
- **Not** auditing every existing log site for secret leaks (separate task). We harden the CLI execution boundary; a follow-up sweep tackles the rest.

## Architecture

```
                       ┌─────────────────────────────────────┐
   chat / code-task ──▶│   cli_platform_resolver  (existing)  │
                       │   - autodetect, cooldown, RL chain   │
                       └──────────────┬──────────────────────┘
                                      │ ordered chain of platforms
                                      ▼
                       ┌─────────────────────────────────────┐
                       │   ResilientExecutor (NEW)            │
                       │   - preflight per platform           │
                       │   - dispatch via ProviderAdapter     │
                       │   - classify(provider error)         │
                       │   - apply FallbackPolicy             │
                       │   - emit ExecutionMetadata           │
                       │   - redact every record on the way   │
                       │     out (Temporal, DB, API, logs)    │
                       └──────────────┬──────────────────────┘
                                      │
            ┌────────────┬────────────┼────────────┬────────────┐
            ▼            ▼            ▼            ▼            ▼
       Claude Code   Codex CLI    Gemini CLI   Copilot CLI   Shell / OpenCode
       Adapter      Adapter      Adapter      Adapter      Adapter

       ╔════ each adapter implements the same trait ════╗
       ║ async run(req: ExecutionRequest)              ║
       ║   -> ExecutionResult                          ║
       ║                                               ║
       ║ async preflight(req) -> PreflightResult       ║
       ║                                               ║
       ║ classify_error(stderr, exit_code, exc)        ║
       ║   -> Status                                   ║
       ╚═══════════════════════════════════════════════╝

   For Temporal-dispatched runs (chat hot path), ResilientExecutor
   runs INSIDE the activity and emits a *partial* ExecutionMetadata
   when it returns. The activity body cannot synthesise a graceful
   ExecutionResult after Temporal has already torn it down (CancelledError,
   activity timeout, worker crash) — by the time those happen the
   activity is gone. Therefore the workflow that DISPATCHES the activity
   (ChatCliWorkflow / CodeTaskWorkflow) is the one that finalises
   ExecutionMetadata on those hard failures, mapping the Temporal
   exception class to Status.WORKFLOW_FAILED and stamping workflow_id +
   activity_id from workflow.info(). On the success path the activity's
   partial metadata is the final record. (Resolves review C1.)
```

## §1 — Provider adapters

Single Python protocol (`apps/api/app/services/cli_orchestrator/adapters/base.py`):

```python
class ProviderAdapter(Protocol):
    name: str  # "claude_code" | "codex" | "gemini_cli" | "copilot_cli" | "shell" | "temporal_activity"

    async def preflight(self, req: ExecutionRequest) -> PreflightResult: ...
    async def run(self, req: ExecutionRequest) -> ExecutionResult: ...
    def classify_error(self, stderr: str, exit_code: int | None, exc: BaseException | None) -> Status: ...
```

Concrete adapters live alongside in:
- `claude_code.py` — wraps `_run_cli_with_heartbeat` for `claude -p`, fetches token via existing `_fetch_claude_token`
- `codex.py` — wraps `_run_cli_with_heartbeat` for `codex`, sets `CODEX_HOME` via existing `_prepare_codex_home`
- `gemini_cli.py` — wraps `_run_cli_with_heartbeat` for `gemini`, OAuth env via `_fetch_integration_credentials("gemini_cli", …)`
- `copilot_cli.py` — wraps `_run_cli_with_heartbeat` for `gh copilot`, GitHub token env
- `shell.py` — wraps `_run_long_command` for skill / arbitrary shell
- `temporal_activity.py` — proxies into another Temporal activity (used when ResilientExecutor itself is invoked from a workflow that wants to delegate)

Each adapter is a thin wrapper. The existing subprocess plumbing stays. The point is the **uniform interface** and **uniform error classification**, not new subprocess code.

## §2 — Normalized error contract

```python
class Status(StrEnum):
    EXECUTION_SUCCEEDED       = "execution_succeeded"
    NEEDS_AUTH                = "needs_auth"               # missing/expired/revoked credentials
    QUOTA_EXHAUSTED           = "quota_exhausted"          # rate limit, credit balance, monthly cap
    WORKSPACE_UNTRUSTED       = "workspace_untrusted"      # Codex trust_level, Gemini workspace setup
    API_DISABLED              = "api_disabled"             # GCP API not enabled, GitHub Copilot not enabled for org
    PROVIDER_UNAVAILABLE      = "provider_unavailable"     # CLI binary missing, MCP server down
    RETRYABLE_NETWORK_FAILURE = "retryable_network_failure" # ECONNRESET, 503, transient TLS
    TIMEOUT                   = "timeout"                  # activity heartbeat timeout, subprocess kill
    WORKFLOW_FAILED           = "workflow_failed"          # Temporal CancelledError, ApplicationFailure
    UNKNOWN_FAILURE           = "unknown_failure"          # classifier didn't match → quarantine
```

### Classification table (seed — extracted from existing pattern tuples)

| Adapter | Match (regex, case-insensitive) | Status |
|---------|---------------------------------|--------|
| claude_code | `credit balance is too low\|usage limit reached\|monthly usage limit\|max plan limit\|out of credits\|insufficient credits` | QUOTA_EXHAUSTED |
| claude_code | `subscription required\|hit your limit` | QUOTA_EXHAUSTED |
| claude_code | `not connected\|please connect your` | NEEDS_AUTH |
| codex | `rate[\s_-]?limit\|usage limit\|quota[\s_-]?exceeded\|insufficient_quota\|out of credits\|too many requests\|429` | QUOTA_EXHAUSTED |
| codex | `unauthorized\|invalid[\s_-]?(grant\|token)\|token[\s_-]?(expired\|invalid)\|401\|403` | NEEDS_AUTH |
| gemini_cli | `quota[\s_-]?exceeded\|resource_exhausted` | QUOTA_EXHAUSTED |
| gemini_cli | `workspace[\s_-]?(setup\|trust)\|untrusted` | WORKSPACE_UNTRUSTED |
| gemini_cli | `api[\s_-]?disabled\|enable.*api.*console.cloud` | API_DISABLED |
| gemini_cli | `permission[\s_-]?denied\|access[\s_-]?denied` | NEEDS_AUTH |
| copilot_cli | `subscription required\|copilot is not enabled\|forbidden\|429` | QUOTA_EXHAUSTED |
| copilot_cli | `not authorized\|401\|403` | NEEDS_AUTH |
| any | `econnreset\|etimedout\|503\|502\|tls handshake` | RETRYABLE_NETWORK_FAILURE |
| any (exception) | `asyncio.TimeoutError`, `subprocess.TimeoutExpired`, heartbeat timeout | TIMEOUT |
| any (exception) | `temporalio.exceptions.{Application,Activity}Error`, `CancelledError` | WORKFLOW_FAILED |
| binary missing | `FileNotFoundError("claude")`, `which gemini` returns 1 | PROVIDER_UNAVAILABLE |
| no rule matched | — | UNKNOWN_FAILURE |

Every entry in this table maps to a unit test (see §7).

## §3 — Fallback policy

The policy is a pure function `(status, attempt) → FallbackDecision`. Centralised so chat, code-task, and council all use the same rule.

```python
@dataclass
class FallbackDecision:
    action: Literal["retry", "fallback", "stop"]
    reason: str            # human-readable, redacted
    actionable_hint: str | None  # only set when action == "stop", e.g. "connect Claude in Settings"
```

| Status | Decision |
|--------|----------|
| EXECUTION_SUCCEEDED | stop (success) |
| QUOTA_EXHAUSTED | fallback (drop platform from chain, mark cooldown via existing `cli_platform_resolver.mark_cooldown`) |
| RETRYABLE_NETWORK_FAILURE | retry once with exponential backoff; on second failure → fallback |
| TIMEOUT | retry once on same platform with extended timeout; on second timeout → fallback |
| PROVIDER_UNAVAILABLE | fallback (no cooldown, binary install issue is not transient quota) |
| NEEDS_AUTH | **stop** (`actionable_hint = "connect <platform> at /settings/integrations/<name>"`) |
| WORKSPACE_UNTRUSTED | **stop** (`actionable_hint = "trust workspace via /settings/cli"`) |
| API_DISABLED | **stop** (`actionable_hint = "enable <api> in <console>"`) |
| WORKFLOW_FAILED | **stop** (preserve `workflow_id` + `activity_id`, surface to caller; do not retry — it's already a Temporal-level failure) |
| UNKNOWN_FAILURE | retry once on same platform; on second unknown → stop with full redacted snippet for debugging |

**Key invariant:** auth/setup/trust errors **never** trigger silent fallback. The user must see the actionable hint. Today, missing-credential triggers chain fallback (cli_platform_resolver line 214); under the new policy, chain fallback only happens on transient errors. **This is a behaviour change** — see Phase 2 cutover gate below for how it lands safely.

### §3.1 Bounded fallback depth (resolves review C3)

Without a depth budget, recursive resilience (a leaf at QUOTA_EXHAUSTED dispatches to a peer via §8 → that peer also hits QUOTA_EXHAUSTED → dispatches another peer → …) becomes a fan-out storm during a provider outage. Two rules:

1. **`MAX_FALLBACK_DEPTH = 3`.** The dispatching `ExecutionRequest` carries a `parent_chain: list[UUID]` populated from `parent_task_id` of every prior agent in the lineage. `ResilientExecutor` refuses any request where `len(parent_chain) >= 3`, returning Status = `PROVIDER_UNAVAILABLE` with `actionable_hint = "fallback chain exhausted (depth 3)"`.
2. **No agent appears twice in `parent_chain`.** Cycle detection: refuse if the dispatching agent's `agent_id` is already in `parent_chain`. Same Status / hint.

Both rules are enforced in `ResilientExecutor.execute(req)` before any preflight or adapter call — they're a **gate**, not a runtime check, so the storm never starts.

## §4 — Durable execution metadata

```python
@dataclass
class ExecutionMetadata:
    run_id: UUID                          # generated at ResilientExecutor entry, not at adapter
    tenant_id: UUID
    user_id: UUID | None
    decision_point: str                   # "chat_response" | "code_task" | "skill_run" | …
    platform_attempted: list[str]         # ordered, e.g. ["gemini_cli", "claude_code"]
    final_platform: str | None            # the one that returned EXECUTION_SUCCEEDED
    attempt_count: int
    status: Status
    # NOTE: no separate error_class field — it's derivable from
    # (status, final_platform) and a stored copy would just drift.
    # Dashboards compute it on read. (Resolves review M5.)
    retry_decisions: list[FallbackDecision]
    fallback_decisions: list[FallbackDecision]
    duration_ms: int
    workflow_id: str | None               # populated when running inside a Temporal workflow
    activity_id: str | None
    parent_task_id: UUID | None           # for inbound CLI calls (§8)
    stdout_summary: str                   # redacted, max 4KB
    stderr_summary: str                   # redacted, max 4KB
    exit_code: int | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
```

**Where it lands:**
- Mirrored into `RLExperience` for `decision_point` matching (chat_response / code_task etc.) — extends the existing pattern, no new table
- Surfaced on the `ChatMessage.metadata` JSONB field for UI display (the routing footer added in PR #256 already reads from here)
- Logged via existing structured logger with **status-level** key, so dashboards group by `status` not by random error strings

### §4.1 Observability (resolves review I1)

The whole point of normalising `Status` is operability. Concrete commitments:

**Metric:**
```
cli_orchestrator_status_total{tenant_id, decision_point, platform, status} (counter)
cli_orchestrator_duration_ms{tenant_id, decision_point, platform, status} (histogram)
cli_orchestrator_fallback_depth{tenant_id, decision_point} (histogram)
cli_orchestrator_attempt_count{tenant_id, decision_point, status} (histogram)
```

Emitted from `ResilientExecutor.execute()` exit point, one observation per terminal `ExecutionMetadata`. The existing Prometheus exposition path (used by `/metrics` endpoint) is the host.

**SLOs (Phase 3 ship gate):**
- `UNKNOWN_FAILURE` rate < **1%** of all dispatches over any rolling 1-hour window.
- `QUOTA_EXHAUSTED → fallback → EXECUTION_SUCCEEDED` recovery rate > **80%** (the policy is doing its job).
- p95 `cli_orchestrator_duration_ms` for `decision_point=chat_response` within **+10%** of the pre-cutover baseline (~5.5s p50). Phase 2 ship gate references this.

**Alerts:**
- **Page**: `UNKNOWN_FAILURE` rate > 5% over 15 min — classifier drift
- **Page**: `cli_orchestrator_fallback_depth p99 > 2` — storm starting (§3.1 gate should prevent this; alert is a tripwire)
- **Ticket**: `NEEDS_AUTH` rate per-tenant climbs > 20% week-over-week — credential rot
- **Ticket**: `API_DISABLED` events for any tenant — onboarding regression

**Dashboards:**
Add a "CLI Orchestrator" board to the existing observability stack with:
1. status mix per platform (stacked bar)
2. fallback chain heatmap (rows = origin platform, cols = winning platform)
3. recovery latency CDF (succeed-on-1st-attempt vs after-fallback)
4. UNKNOWN_FAILURE drill-down (top 10 stderr fingerprints)

## §5 — Secret redaction

Single redactor (`apps/api/app/services/cli_orchestrator/redaction.py`) called by `ResilientExecutor` at the boundary. Every string that flows out — `stdout_summary`, `stderr_summary`, `error_class`, log messages, Temporal heartbeat details — passes through it.

**Redaction rules (in priority order, regex):**

1. `(?i)(authorization:\s*bearer\s+)([\w\-\.]+)` → `\1<redacted>`
2. `(?i)(x-(?:internal-key|api-key|tenant-id):\s*)([\w\-\.]+)` → `\1<redacted>`
3. `https://([\w\-]{20,})@github\.com` → `https://<redacted>@github.com` *(today's git-URL leak at workflows.py:1074)*
4. `(ghp|gho|ghs|ghr)_[\w]{20,}` → `<redacted-github-token>`
5. `sk-(?:ant-)?[\w\-]{20,}` → `<redacted-api-key>` *(Anthropic + OpenAI keys)*
6. `(?i)(set-cookie|cookie):\s*[^\r\n]+` → `<redacted-cookie>`
7. JWT shape `eyJ[\w\-]{10,}\.eyJ[\w\-]{10,}\.[\w\-]{10,}` → `<redacted-jwt>`
8. **Tightened (review I6).** Was greedy: `(?i)(api[_-]?key|password|secret|token)["']?\s*[:=]\s*["']?([\w\-\.]+)`. Replace with two narrower rules so prose like "the api key was rotated" or `keypair = ed25519` survives unchanged:
   - `(?im)^[\s>]*(api[_-]?key|password|secret|access[_-]?token|refresh[_-]?token|client[_-]?secret)\s*[:=]\s*\S+` → `\1=<redacted>` *(line-anchored: only matches config-line shapes)*
   - `(?i)\b(authorization|x-api-key|x-internal-key|x-tenant-id)\s*:\s*\S+` → `\1: <redacted>` *(header lines)*

9. **Codex `auth.json` cleanup (review I7).** The Codex adapter's `_prepare_codex_home` writes `~/.codex/auth.json` with the OAuth payload (`workflows.py:1470`). Adapter's `run()` MUST `shutil.rmtree(codex_home)` in a `finally` block — even on TIMEOUT/CancelledError. Add a unit test that asserts the file is gone after `run()` returns regardless of outcome.

Plus a **structural pass**: when the input is parseable JSON, walk every key matching `(?i)(token|key|secret|password|cookie|auth)` and replace its value with `<redacted>`.

Plus the **env-var sanitiser** already in `skill_manager._SENSITIVE_ENV_KEYS` extended with platform-specific keys (`CLAUDE_CODE_OAUTH_TOKEN`, `COPILOT_GITHUB_TOKEN`, etc.) and reused at the CLI subprocess boundary.

**Tests** (§7):
- Each rule has a positive test (matches, redacts) and a negative test (a similar but legitimate string survives unchanged).
- A "concatenated leak" test feeds a 50KB log line containing a bearer + a JWT + a `sk-ant-…` key + a git URL, asserts every secret is redacted, every other character preserved verbatim.
- A property-based test (hypothesis-style) generates random secrets in random surrounding text and asserts the secret never survives.
- **Negative-redaction property test (review I6).** Feed pure prose drawn from a corpus of words including "token / key / secret / authorization" *without* any actual secret values; assert the output is byte-identical to the input. Catches over-redaction that would otherwise show up as a fresh prod incident masking a real one.

## §6 — Preflight checks

`ProviderAdapter.preflight(req)` runs **before** subprocess spawn and returns either `PreflightResult.ok()` or a structured failure with the same `Status` enum (so the executor / fallback policy treats it identically to a runtime failure):

| Check | When | Latency budget | Status on fail |
|-------|------|---------------|----------------|
| Binary on `$PATH` (`shutil.which("claude")`, etc.) | every dispatch, **memoised at process start** | < 1ms (memoised), one-time `which` call at worker boot | PROVIDER_UNAVAILABLE |
| Credentials present in vault for this platform | every dispatch | < 5ms (existing `_fetch_integration_credentials` is already on hot path) | NEEDS_AUTH (with actionable_hint to integrations page) |
| Workspace trust file (Codex `~/.codex/config.toml`, Gemini workspace setup marker) | every dispatch | < 1ms (stat + cached) | WORKSPACE_UNTRUSTED |
| Required cloud API enabled (GCP for Gemini, Copilot org-enabled for `gh copilot`) | every dispatch, **5min Redis-backed cache per (tenant, platform)** | < 50ms uncached / < 1ms cached | API_DISABLED |
| Temporal queue reachable (`agentprovision-code` worker registered) | only when ResilientExecutor itself dispatches an activity | < 10ms (Temporal client `describe_task_queue`, cached 30s) | PROVIDER_UNAVAILABLE |

**Total preflight budget per dispatch: < 60ms uncached, < 10ms cached.** With chat p50 currently ~5.5s the steady-state addition is well under 0.5%. Phase 3 ship gate verifies p95 of `preflight_duration_ms` (a new metric) stays inside 60ms.

Preflight failures do **not** count toward `attempt_count` for retry purposes — they're stable, not transient — but they do appear in `platform_attempted` so the metadata accurately reflects what was tried.

## §7 — Tests

Land alongside the implementation, focused, no broad refactor sweep.

**Phase 1 (error contract + redaction):**
- `tests/cli_orchestrator/test_classification.py` — table-driven; one row per Classification-table entry in §2; explicit name like `test_classify_claude_code_credit_balance_too_low_is_quota_exhausted` so when the upstream string changes the failing test names the regression site
- `tests/cli_orchestrator/test_redaction.py` — every rule in §5; concatenated-leak test; property test
- `tests/cli_orchestrator/test_no_fallback_on_auth.py` — fixture that returns NEEDS_AUTH; assert `FallbackDecision.action == "stop"` and `actionable_hint` is non-empty

**Phase 2 (adapters + fallback policy):**
- `tests/cli_orchestrator/test_provider_adapter_contract.py` — every adapter implements `preflight`, `run`, `classify_error`; same input shape, same output shape
- `tests/cli_orchestrator/test_fallback_policy_table.py` — every (Status, attempt) pair returns the documented decision
- `tests/cli_orchestrator/test_temporal_failure_normalization.py` — `temporalio.exceptions.ActivityError` → `Status.WORKFLOW_FAILED` with `workflow_id` + `activity_id` populated

**Phase 3 (preflight + metadata):**
- `tests/cli_orchestrator/test_preflight.py` — binary missing, creds missing, trust missing, API disabled, queue unreachable; each returns the right Status
- `tests/cli_orchestrator/test_preflight_latency.py` — asserts each check stays inside its §6 latency budget; runs in CI as a perf-budget guard, fails the build if exceeded
- `tests/cli_orchestrator/test_metadata_emission.py` — happy path emits one ExecutionMetadata with `attempt_count == 1`, `platform_attempted == [winner]`, `status == EXECUTION_SUCCEEDED`; failure path emits the full attempt chain and matching decision lists
- `tests/cli_orchestrator/test_workflow_failed_emission.py` — simulates a CancelledError mid-activity; asserts the **wrapping workflow** (not the activity) finalises ExecutionMetadata with `Status.WORKFLOW_FAILED` and populated `workflow_id` + `activity_id` (covers C1 contract)
- `tests/cli_orchestrator/test_recursion_gate.py` — `parent_chain` length 3 is rejected with PROVIDER_UNAVAILABLE; same agent twice in `parent_chain` is rejected (covers C3)
- `tests/cli_orchestrator/test_codex_authjson_cleanup.py` — Codex adapter run() under success / TIMEOUT / CancelledError; assert `~/.codex/auth.json` is gone after each (covers I7)

**Phase 4 (leaf-agent inbound):**
- `tests/cli_orchestrator/test_agent_token_minting.py` — claims, TTL, scope inheritance from agent_policy
- `tests/cli_orchestrator/test_mcp_agent_auth_round_trip.py` — leaf calls `recall_memory` with valid agent JWT, succeeds; `execution_trace` row written with `parent_task_id` populated
- `tests/cli_orchestrator/test_mcp_scope_enforcement.py` — leaf with `scope=["recall_memory"]` calling `dispatch_agent` is rejected **403** + audit-logged (review's added Phase 4 second gate)
- `tests/cli_orchestrator/test_tenancy_precedence.py` — when `kind=agent_token`, `tenant_id` claim is authoritative and `X-Tenant-Id` header is ignored (mismatch does NOT change behaviour, but is audit-logged)

**Adapter integration tier (review M4):** lives in `tests/cli_orchestrator/integration/` and runs the actual `claude --version` / `codex --version` / etc. binaries to validate `preflight()` against real installations. **Marker `@pytest.mark.cli_integration`**, opt-in (CI runs it on the code-worker image only, not the API image — that's where the binaries are).

## §8 — Leaf-agent inbound surface (revised — MCP, not CLI)

**Revision (2026-05-09).** The original §8 had leaf agents (Claude Code / Codex / Gemini / Copilot subprocesses + sandboxed skills) shell out to the `agentprovision` CLI binary to call back into the orchestrator. After confirming the Claude Code feature inventory, that's structurally wrong. The right surface is **MCP-over-SSE on our existing `apps/mcp-server` (port 8086)**.

Why:
- Claude Code's MCP support is first-class — versioned tool contracts, error isolation, parallel calls, no subprocess management.
- `apps/mcp-server` already exposes `agent_messaging`, `memory_continuity`, `dynamic_workflows`, `skills`, `webhooks`, `agents`, `knowledge` modules. Most of the inbound surface already exists.
- Claude Code emits **no outbound webhooks** (confirmed). Hooks-shelling-to-curl was the only alternative — strictly worse.
- `CronCreate` is **session-scoped only** (expires after 7 days, dies on session close). Durable schedules MUST live in our Temporal `DynamicWorkflow` (which already supports `cron`/`interval`/`webhook`/`event`/`manual`/`agent` triggers).

**The CLI binary stays in its lane.** It is the **human terminal user**'s surface — same backend endpoints, different ergonomics (rich rendering, REPL, OS keychain). Leaves call MCP. Humans call CLI. They are siblings, not competing surfaces.

### How Phase 4 actually lands

1. **Mint agent-scoped JWT at task dispatch time** (`code_session_manager.run_agent_session` / `code_worker.execute_chat_cli` / `code_worker.execute_code_task`). Claims:
   ```
   { sub: "agent:<agent_id>",
     kind: "agent_token",
     tenant_id, agent_id, task_id, parent_workflow_id,
     scope: <agent_policy.allowed_tools as array>,
     iat, exp }   # exp = heartbeat_timeout * 2
   ```
2. **Inject MCP server config** into the leaf's environment before subprocess spawn. For Claude Code: write `.claude.json` into the working dir with:
   ```json
   { "mcpServers": { "agentprovision": {
       "type": "sse",
       "url": "https://mcp.agentprovision.com/sse",
       "headers": { "Authorization": "Bearer <agent-jwt>" } } } }
   ```
3. **Add a third auth tier to `apps/mcp-server`.** Today the server accepts `X-Internal-Key` (service-to-service) and tenant JWT (user-on-behalf-of). New tier: agent-scoped JWT with `kind=agent_token`, validated against `agent_policy.allowed_tools` per-call. The existing `deps.require_agent_permission` is the enforcement seam.

   **Tenancy precedence rule (review I3):** when `kind=agent_token`, the JWT's `tenant_id` claim is **authoritative**. The `X-Tenant-Id` header is ignored if present, and a mismatch is audit-logged (not rejected — the leaf may not even know it's setting the header through default reqwest config). Order of resolution: `agent_token.tenant_id` > tenant JWT `tenant_id` claim > `X-Tenant-Id` header > `X-Internal-Key`'s implicit tenant. Only one tier wins per request.

4. **Audit linkage.** Every MCP call from a leaf writes an `execution_trace` row with `parent_task_id` (= the agent_token's `task_id` claim). The trace tree reflects actual delegation, not just dispatch.

5. **Scope-enforcement gate (Phase 4 second ship gate).** `agent_token.scope` is checked against the called MCP tool name; out-of-scope calls return **403 Forbidden** + audit-log entry, never silently. Test in `test_mcp_scope_enforcement.py` (§7).

### What this kills from the original §8

| Originally proposed CLI subcommand | Replaced by existing MCP tool |
|------------------------------------|-------------------------------|
| `agentprovision agent dispatch` | `dispatch_agent` (`agents` module — to be added; trivial) |
| `agentprovision blackboard write\|read` | `blackboard_write` / `blackboard_read` (`agent_messaging`) |
| `agentprovision memory recall\|record-*` | `recall_memory`, `record_observation`, `record_commitment` (`memory_continuity`) |
| `agentprovision workflow run` | `run_workflow` (`dynamic_workflows`) |
| `agentprovision approval request` | `request_human_approval` (to be added — minor) |

The `agentprovision` CLI binary keeps these same subcommands for **humans in terminals** — they hit the same backend endpoints, just with a different UX layer (rich rendering, prompts). One control plane, two clients.

### Closes the resilience loop

When a leaf hits `QUOTA_EXHAUSTED` mid-task and policy says fall-back, it calls `dispatch_agent` MCP tool with `target_capability="<same as me>"`. The dispatching call is `ResilientExecutor.execute(req)` server-side — recursive resilient orchestration without any per-runtime SDK or extra control-plane code.

## Phased rollout

| Phase | Scope | Branch | Ship gate | Rollback |
|-------|-------|--------|-----------|----------|
| **1** | `Status` enum + `classify(stderr, exit_code, exc) -> Status` + redaction primitive + tests. The existing pattern tuples (`CLAUDE_CREDIT_ERROR_PATTERNS` etc.) and `cli_platform_resolver.classify_error` become **thin wrappers** delegating to the new classifier. **No behaviour change** — old call sites get the same string labels back. | `feat/cli-orchestrator-phase-1-error-contract` | (a) every classification-table row has a named test; (b) redaction property test + negative-redaction test pass; (c) no public API change verified by `grep -r classify_error apps/` returning the same set of call sites pre/post | revert PR; aliases delegated, so revert is mechanical |
| **2** | `ProviderAdapter` trait + 6 concrete adapters + `FallbackPolicy` + `ResilientExecutor`. `cli_session_manager.run_agent_session` rewritten to call `ResilientExecutor.execute(req)`. **Behaviour change** — auth/setup/trust errors stop instead of silent-fallback. **Feature-flagged** via `tenant_features.use_resilient_executor` (default off). (Resolves OQ1 toward gradual cutover, per review C2.) | `feat/cli-orchestrator-phase-2-adapters` | (a) per-adapter contract test, fallback-policy table test, Temporal-failure normalization test, no-fallback-on-auth test, recursion-depth gate test; (b) **shadow-mode metric**: with flag off, run new classifier in parallel and assert ≥99% agreement vs legacy across a sample of ≥10k dispatches; (c) chat p50 within +10% of pre-cutover baseline (~5.5s); (d) `cli_platform_resolver.classify_error` is **kept as alias** (review I2 — single-PR rollback) | flip `use_resilient_executor` off per-tenant; alias still routes the legacy path |
| **3** | `preflight()` per adapter + `ExecutionMetadata` mirror to `RLExperience` + UI surfacing of `actionable_hint` (i18n keys, not English strings — review I4) + observability metrics + dashboards + alerts. | `feat/cli-orchestrator-phase-3-preflight-metadata` | (a) preflight tests + latency-budget test; (b) metadata emission tests; (c) end-to-end QUOTA_EXHAUSTED → fallback → success metadata-chain test; (d) UNKNOWN_FAILURE rate observed < 1% over 24h soak; (e) `preflight_duration_ms` p95 < 60ms | revert PR; preflight is additive, easy revert |
| **4** | Agent-scoped JWT mint + third auth tier on `apps/mcp-server` + new MCP tools `dispatch_agent` (review M6) + `request_human_approval` (review M6). The CLI binary's existing `agent` / `blackboard` / `memory` / `workflow` / `approval` subcommands are added in a sibling PR-C of the CLI track (#332 follow-up); they're not Phase 4 of this design. | `feat/cli-orchestrator-phase-4-leaf-mcp-auth` *(renamed per review M3)* | (a) leaf-from-Claude-Code calls `recall_memory` and `execution_trace` row contains `parent_task_id`; (b) **scope-enforcement test** — leaf with `scope=["recall_memory"]` calling `dispatch_agent` returns 403 + audit log (review's added second gate); (c) tenancy-precedence test (I3) | revert PR; agent-token minting is additive — leaves fall back to no-op until reverted |

Each phase is its own PR; each PR's ship gate must pass before the next branches off.

## How to verify locally (per phase)

```bash
# Phase 1
cd apps/api && pytest tests/cli_orchestrator/ -v
# Phase 2 — additional integration test with a stubbed Temporal client
cd apps/api && pytest tests/cli_orchestrator/test_fallback_policy_table.py -v
# Phase 3 — full E2E
docker compose restart api code-worker
./scripts/e2e_test_production.sh BASE_URL=http://localhost:8000
# Phase 4 — leaf inbound call
AGENTPROVISION_AGENT_TOKEN=<minted-jwt> AGENTPROVISION_TASK_ID=<uuid> \
  ./apps/agentprovision-cli/target/release/agentprovision memory recall "echo PDF"
```

## Decisions (closed during review)

- **Where the executor lives → Python in `apps/api/app/services/cli_orchestrator/`.** Rust port is **not** a planned phase; revisit only if profiling shows orchestrator overhead matters (it won't — bottleneck is the upstream LLM call). The heartbeat-on-activity-thread pattern from commit `91f77ee2` is the only thing keeping >5min CLI tasks alive; moving it isn't a "language port", it's a runtime migration.

- **Status enum is extensible.** New failure classes get new statuses with a new row in the §2 classification table + a new test. Clients render unknown values as `UNKNOWN_FAILURE` (documented contract). UNKNOWN_FAILURE rate < 1% is the §4.1 SLO that keeps the enum honest.

- **`cli_platform_resolver.classify_error` is kept as an alias indefinitely** (review I2 — single-PR rollback for Phase 2). Phase 1's classifier is the canonical implementation; the legacy function delegates and is the public seam used by the council, RL writer, chat error footer, and ChatMessage metadata writer.

- **Phase 2 cutover is feature-flagged** (review C2 — `tenant_features.use_resilient_executor`, default off). Cutover gate requires shadow-mode classifier-agreement ≥99% + chat p50 within +10% of baseline. Hard cutover after 14 days at 100% rollout.

## Remaining open questions

*(none structurally blocking — all four original OQs have been resolved.)*

## Sign-off scope

Reviewer signoff is required on:
- **§0** architectural principle (CLI = thin client, backend canonical)
- **§3** fallback policy + §3.1 bounded recursion
- **§5** redaction rules (especially the tightened rule 8 + Codex `auth.json` cleanup)
- **§8** leaf-agent inbound surface (MCP-not-CLI, third auth tier, tenancy precedence)
- **§9 / §10 / §11** *(below — Claude Code lifecycle integration, CLI ↔ endpoint map, webhook integration plan)*

---

## §9 — Claude Code lifecycle integration

This section pins down which Claude Code primitives the orchestrator hooks into vs re-implements. Verified against `https://code.claude.com/docs/en/` by sub-agent recon (2026-05-09).

| Primitive | Decision | Where it lands |
|-----------|----------|----------------|
| **Hooks** (PreToolUse, PostToolUse, UserPromptSubmit, Stop, SessionStart, SessionEnd, SubagentStart, FileChanged …) | **HOOK INTO.** Used as **leaf-side safety + telemetry shims**, not as the orchestrator's primary observability channel. | Phase 4: ship a `.claude/hooks/hooks.json` template that the code-worker writes into the leaf's working dir alongside `.claude.json` (§8). PreToolUse hook does a fast `agent_policy.allowed_tools` check (defence in depth — primary enforcement is server-side at the MCP boundary; this just fails fast). PostToolUse hook POSTs a heartbeat-style event to `/api/v1/agents/internal/heartbeat`. SessionEnd writes one final ExecutionMetadata-mirror record. None of these are *required* for correctness — they're a **second-line** signal for cases where the leaf hangs without ever calling an MCP tool. |
| **MCP server (SSE)** | **HOOK INTO — primary inbound channel.** | Phase 4: third auth tier on `apps/mcp-server` (§8). |
| **`CronCreate`** (session-scoped, expires after 7 days) | **DO NOT HOOK INTO** for orchestrator-level scheduling. Session-scoped cron dies on session close — wrong tool for durable schedules. | All durable schedules live in `DynamicWorkflow` with `cron` / `interval` triggers (already shipped). The CLI's `agentprovision workflow schedule` subcommand creates DynamicWorkflow rows; it does **not** call CronCreate. |
| **`Monitor`** (session-scoped persistent watchers) | **DO NOT HOOK INTO** in the orchestrator. | If a leaf wants to watch a log file or build, it can use Monitor inside its own session — that's leaf concern, not orchestrator concern. The orchestrator's monitoring is Prometheus + the DynamicWorkflow `event` trigger type. |
| **Subagents** (Agent tool with `subagent_type`) | **HOOK INTO** for parallel work *inside a leaf*, not as the orchestrator's parallelism primitive. | When a leaf agent needs parallel exploration / planning, it uses the Agent tool natively. The orchestrator's parallelism is Temporal `CoalitionWorkflow` + concurrent activities. Subagents do **not** inherit the leaf's `.claude.json` MCP config — confirmed by docs. **Implication:** if a leaf subagent needs orchestrator access, its prompt must include the `mcpServers` config. The Phase 4 dispatch pipeline injects this into the leaf's CLAUDE.md so subagents inherit by reference. |
| **Skills** (Claude-Code-format SKILL.md) | **HOOK INTO** as the canonical packaging format. | The existing Skill Marketplace v2 (PRs #182–#193) is already Claude-Code-format; nothing changes. New skills authored to invoke orchestrator MCP tools (`recall_memory` etc.) are the standard pattern. |
| **`PushNotification`** | Confirmed not in the public tools list. **DO NOT USE.** | All "task done" notifications go via existing `notification.py` model + the `NotificationBell` UI + the per-channel adapters (Twilio SMS, WhatsApp, email). |
| **Statusline** | Internal, not a published API. **DO NOT USE.** | UI surfacing is the chat routing footer (PR #256) and the new dashboards in §4.1. |
| **Session resume / IDs** (`~/.claude/projects/<project>/<session-id>.jsonl`) | **DO NOT RELY ON** for orchestrator-level state. | If a leaf subprocess is killed mid-task (Temporal activity timeout, worker crash), the orchestrator restarts it as a fresh session via the Phase 2 retry policy. Session JSONL is leaf-internal — useful for debugging, not for distributed state. The authoritative state is `RLExperience` + `execution_trace` + `Blackboard`. |

### §9.1 Heartbeat propagation (extending the established pattern)

The `_run_cli_with_heartbeat` pattern from commit `91f77ee2` is **already** the orchestrator's heartbeat mechanism (Temporal activity ↔ activity host). What §9 adds is the **leaf-side** half:

- **Leaf → orchestrator** heartbeat: PostToolUse hook fires `POST /api/v1/agents/internal/heartbeat` with `{agent_id, task_id, parent_workflow_id, tool_name, ts}`. Orchestrator updates the in-flight task's last-seen-at; if no heartbeat for `2 * heartbeat_interval`, the dispatching workflow gets an event (`event` trigger) to consider remediation.
- **Orchestrator → leaf** is not a heartbeat but a **cancellation channel**: if the orchestrator wants to cancel a leaf (user clicked stop, fallback chain succeeded elsewhere, policy violation detected), it kills the activity from the workflow side. Existing `proc.kill()` semantics in `_run_cli_with_heartbeat` (commit `91f77ee2`) handle this.

No new heartbeat mechanism is built. The existing one is extended at one new endpoint.

---

## §10 — CLI ↔ existing API endpoint map

Every CLI subcommand maps to existing endpoints. The CLI is not a new surface; it's a new client of the surface the web SPA already uses. This table is the **explicit contract** that Phase-1-of-the-CLI-track (PR-C following #332) will implement.

| CLI subcommand | HTTP | Endpoint | Auth | Notes |
|---|---|---|---|---|
| `login` | already shipped (PR #329) | `POST /api/v1/auth/device-code`, `/device-token`, `/login` (password fallback) | — | gh-style device flow + email/password fallback |
| `logout` | local | (clears token store) | — | shipped PR #332 |
| `status` | `GET` | `/api/v1/auth/users/me` | bearer | shipped PR #332 |
| **chat** | | | | |
| `chat send <msg> [--agent <id>] [--session <id>] [--no-stream]` | `POST` | `/api/v1/chat/sessions/{id}/messages[/stream]` | bearer | shipped PR #332; SSE wire-format hardened in #332 fixup |
| `chat repl` | (loop of above) | same | bearer | shipped PR #332 |
| `chat sessions list` | `GET` | `/api/v1/chat/sessions` | bearer | new in PR-C |
| **agent** | | | | |
| `agent list` | `GET` | `/api/v1/agents` | bearer | |
| `agent show <id>` | `GET` | `/api/v1/agents/{id}` | bearer | |
| `agent discover --capability <cap>` | `GET` | `/api/v1/agents/discover?capability=<cap>` | bearer | already shipped, Redis-backed |
| `agent dispatch <id> --goal "…"` | `POST` | `/api/v1/agents/{id}/dispatch` | bearer | new endpoint — wraps `task_dispatcher` service |
| `agent heartbeat <id>` | `POST` | `/api/v1/agents/{id}/heartbeat` | bearer | already shipped (external agents) |
| `agent audit <id>` | `GET` | `/api/v1/agents/{id}/audit-log` | bearer | already shipped (ALM) |
| `agent rollback <id> --version <v>` | `POST` | `/api/v1/agents/{id}/rollback/{version}` | bearer | already shipped (ALM, migration 100) |
| **workflow** | | | | |
| `workflow list [--tier native\|community]` | `GET` | `/api/v1/workflows` | bearer | |
| `workflow show <id>` | `GET` | `/api/v1/workflows/{id}` | bearer | |
| `workflow templates` | `GET` | `/api/v1/workflows/templates` | bearer | already shipped, 26 native templates |
| `workflow install <template-id>` | `POST` | `/api/v1/workflows/install/{template_id}` | bearer | already shipped |
| `workflow run <id> [--input @args.json]` | `POST` | `/api/v1/workflows/{id}/run` | bearer | already shipped |
| `workflow runs [--id <wf>] [--status <s>]` | `GET` | `/api/v1/workflow-runs` | bearer | already shipped |
| `workflow run-show <run-id>` | `GET` | `/api/v1/workflow-runs/{run_id}` | bearer | with step tree |
| `workflow schedule <id> --cron "…"` | `PATCH` | `/api/v1/workflows/{id}` | bearer | sets `definition.trigger` to `cron` |
| **code** | | | | |
| `code task "<description>" [--repo <r>] [--branch <b>]` | `POST` | `/api/v1/agent-tasks/code` | bearer | dispatches `CodeTaskWorkflow`; NEW endpoint, wraps existing internal dispatcher |
| `code task-show <task-id>` | `GET` | `/api/v1/agent-tasks/{id}` | bearer | progress + final PR URL |
| **memory** | | | | |
| `memory recall "<query>"` | `POST` | `/api/v1/memory/recall` | bearer | already shipped, pgvector |
| `memory record-observation <entity> "<text>"` | `POST` | `/api/v1/memory/observations` | bearer | already shipped |
| `memory record-commitment "<text>"` | `POST` | `/api/v1/memory/commitments` | bearer | already shipped |
| `memory entities list [--category <c>]` | `GET` | `/api/v1/knowledge/entities` | bearer | already shipped |
| **skill** | | | | |
| `skill list` | `GET` | `/api/v1/skills/library` | bearer | |
| `skill show <slug>` | `GET` | `/api/v1/skills/library/{slug}` | bearer | |
| `skill run <slug> --input @args.json` | `POST` | `/api/v1/skills/library/{slug}/run` | bearer | sandboxed via `skill_manager.execute` |
| **integration** | | | | |
| `integration list` | `GET` | `/api/v1/integrations/status` | bearer | already shipped |
| `integration connect <name>` | (browser open) | `/api/v1/oauth/{provider}/authorize` | bearer | OS-opens the URL |
| `integration test <name>` | `POST` | `/api/v1/integrations/{name}/test` | bearer | already shipped via IntegrationsPanel |
| `integration disconnect <name>` | `DELETE` | `/api/v1/oauth/{provider}/disconnect` | bearer | already shipped |
| **tenant** | | | | |
| `tenant whoami` | `GET` | `/api/v1/auth/users/me` | bearer | shows tenant_id |
| `tenant features` | `GET` | `/api/v1/tenant-features` | bearer | shows `use_resilient_executor`, `default_cli_platform`, etc. |
| **config** | | | | |
| `config get/set/list` | local | `~/.config/agentprovision/config.toml` | — | |
| **tool** | | | | |
| `tool list` | `GET` | `/api/v1/mcp/tools` | bearer | reflective list of MCP tools the user can call |
| `tool call <name> --input @args.json` | `POST` | `/api/v1/mcp/tools/{name}/call` | bearer | server-side proxies to MCP server |

**New endpoints** (3): `agent dispatch`, `code task` create / show, `mcp/tools` list / call. The rest reuse what already exists.

---

## §11 — Webhook integration: extend, don't parallel

The recon found the webhook infrastructure is **structurally complete** for management + outbound fire, **partially complete** for inbound, and **explicitly broken** in one place. §11 lays out exactly what we extend, what we fix, and what we leave alone.

### §11.1 What's already there (don't touch)

- `WebhookConnector` model (migration 047): `id, tenant_id, direction (inbound|outbound), name, slug, target_url, events (JSONB), auth_type, secret, headers (JSONB), enabled, status, trigger_count, error_count, last_triggered_at` — keep as-is.
- `webhook_delivery_logs` table — keep as-is.
- `fire_outbound_event(db, tenant_id, event_type, payload)` service (`apps/api/app/services/webhook_connectors.py:204`) — keep, but extend (§11.3).
- 6-tool MCP module + 31 tests in `apps/mcp-server/src/mcp_tools/webhooks.py` — keep, no changes.
- Twilio HMAC-SHA1 inbound (`apps/api/app/api/v1/twilio_webhook.py:305`) — keep, complete.
- Generic inbound at `POST /api/v1/webhook-connectors/in/{slug}` with HMAC-SHA256 (`apps/api/app/api/v1/webhook_connectors.py:220`) — keep the HTTP shape, extend the handler (§11.2).

### §11.2 What we fix (the broken bits)

- **`webhook_trigger` workflow step has no executor.** Today the step is registered in the schema, validates, renders in the visual builder, but no `DynamicWorkflowExecutor` handler exists. Fix: implement the handler in `apps/api/app/workers/dynamic_executor.py` so a workflow that hits `webhook_trigger` **suspends** (Temporal `workflow.wait_condition`), the inbound `/in/{slug}` handler signals it on matching event arrival, and the workflow resumes with the webhook payload as step input. **Lands in Phase 3** (alongside metadata) because it shares the workflow-suspension primitive with `human_approval`.
- **HCA inbound `/api/v1/webhooks/hca` has NO signature verification.** Either (a) require HMAC and break compatibility with anyone who hasn't rotated, or (b) deprecate the route and migrate HCA to the generic `/in/{slug}` shape. Recommend (b) — landed in Phase 3 with a 30-day deprecation window.
- **`WebhookConnector.secret` stored in plaintext.** Migration 121 encrypts via the existing Fernet vault (same pattern as `IntegrationCredential`). Read path falls back to plaintext for one release, then plaintext column dropped in migration 122. Lands in **Phase 1** (alongside redaction primitive — same security review).
- **No retry on outbound delivery failure.** Phase 3: extend `fire_outbound_event` to enqueue a Temporal `WebhookDeliveryWorkflow` on transient failures (5xx + connection errors); workflow does exponential backoff `1s → 8s → 64s → 8min → 1h → drop after 6 attempts`. Each attempt writes a `webhook_delivery_logs` row. Idempotency via outbound `X-Webhook-Delivery-Id` header (already set).
- **No idempotency on inbound.** Add an `inbound_idempotency_keys` table (tenant_id, slug, key, expires_at) with a 24h TTL; if the inbound request includes `X-Webhook-Idempotency-Key`, dedup against the table before logging or signalling workflows. Lands in Phase 3.
- **No replay-attack window.** Inbound handler validates `X-Webhook-Timestamp` is within ±5min of server clock; reject older. Phase 3.
- **`payload_transform` column exists but is never applied.** Either implement (jq-style transform on outbound payload before POST) or drop the column. Recommend: drop in Phase 3 (migration 123); never used in any of the 31 MCP tests, no UI to set it.
- **No web UI for webhook management.** Out of scope for this design; tracked as a separate UI follow-up. MCP tools cover programmatic access.

### §11.3 What we add (orchestrator integration)

The resilient orchestrator emits **outbound webhook events** on `ExecutionMetadata` transitions. The events become first-class subscribable types in `WebhookConnector.events`:

| Event | Fires when | Payload shape (top-level keys, all redacted via §5) |
|-------|-----------|------------------------------------------------------|
| `execution.started` | `ResilientExecutor.execute()` enters | `run_id, tenant_id, decision_point, platform_chain, parent_task_id` |
| `execution.attempt_failed` | per-platform attempt returns non-success | `run_id, attempt_index, platform, status, retry_decision, fallback_decision, duration_ms, stderr_summary` |
| `execution.fallback_triggered` | `FallbackPolicy` returns `action="fallback"` | `run_id, from_platform, to_platform, reason` |
| `execution.succeeded` | terminal `EXECUTION_SUCCEEDED` | `run_id, final_platform, attempt_count, total_duration_ms, tokens_in, tokens_out, cost_usd` |
| `execution.failed` | terminal non-success after policy stops or chain exhausts | `run_id, status, actionable_hint (i18n key), platform_attempted, total_duration_ms` |
| `execution.heartbeat_missed` | leaf-side heartbeat absent for `2*heartbeat_interval` (§9.1) | `run_id, last_seen_ts, parent_workflow_id, parent_task_id` |

Subscribers configure these via the existing `register_webhook` MCP tool. No new endpoint needed; `events: ["execution.*"]` already supports prefix matching (per recon).

**Delivery semantics:**
- Outbound POST with `X-Webhook-Event`, `X-Webhook-Delivery-Id`, `X-Webhook-Timestamp`, `X-Webhook-Signature: sha256=<hmac of body>` headers (existing convention from `_deliver_outbound`).
- Retry policy: §11.2's exponential backoff on 5xx / connection errors; 4xx is a permanent failure (no retry, log + alert).
- Dedup: same `X-Webhook-Delivery-Id` for retries of the same logical delivery.
- Ordering: **not guaranteed** across deliveries. Subscribers must be idempotent.

**Implementation site:** `ResilientExecutor.execute()` exit point fires the event via `fire_outbound_event(db, tenant_id, event_type, payload)`. Already-existing service. One new wiring file (`cli_orchestrator/webhook_events.py`); no new model, no new table.

### §11.4 Tests

- `test_webhook_trigger_executor.py` — workflow with a `webhook_trigger` step suspends, inbound POST to `/in/{slug}` resumes it with payload as step input
- `test_webhook_secret_encryption.py` — round-trip via the Fernet vault; old plaintext rows still read correctly during the transition release
- `test_webhook_outbound_retry.py` — 5xx / connection error triggers `WebhookDeliveryWorkflow`; 4xx does not; backoff ladder matches spec
- `test_webhook_inbound_idempotency.py` — same `X-Webhook-Idempotency-Key` within 24h returns 200 + `dedup=true` without re-firing the workflow
- `test_webhook_inbound_replay_window.py` — `X-Webhook-Timestamp` outside ±5min is rejected 401
- `test_orchestrator_emits_execution_events.py` — happy path, fallback path, heartbeat-missed path each emit the right event with the right payload shape

---

**End of design doc.** §9, §10, §11 close the gaps the reviewer flagged. Sign-off scope above remains unchanged.
