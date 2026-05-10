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
| claude_code | `not connected\|please connect your` ¹ | NEEDS_AUTH |
| codex | `rate[\s_-]?limit\|usage limit\|quota[\s_-]?exceeded\|insufficient_quota\|out of credits\|too many requests\|429` | QUOTA_EXHAUSTED |
| codex | `unauthorized\|invalid[\s_-]?(grant\|token)\|token[\s_-]?(expired\|invalid)\|401\|403` | NEEDS_AUTH |
| gemini_cli | `quota[\s_-]?exceeded\|resource_exhausted` | QUOTA_EXHAUSTED |
| gemini_cli | `workspace[\s_-]?(setup\|trust)\|untrusted` ² | WORKSPACE_UNTRUSTED |
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

> **¹ Implementation footnote (Phase 1, commit `1fc0d012`).** The `not connected` regex is **narrowed** in `apps/api/app/services/cli_orchestrator/classifier.py` to require either an integration-context keyword (e.g. `subscription`, `integration`) OR a CLI-name word boundary (`claude code`, `codex`, `gemini cli`, `github copilot cli`). Bare `not connected` would otherwise misclassify user prose like "the database is not connected" as `NEEDS_AUTH` / `missing_credential`. The legacy `cli_platform_resolver._MISSING_CRED_PATTERNS` made the same narrowing — the implementation preserves legacy behaviour, the design table did not.
>
> **² Implementation footnote (Phase 1).** The `untrusted` alternative is narrowed to `untrusted\s*workspace` for the same reason — the bare word would match unrelated prose. Legacy `_AUTH_PATTERNS` did not include `untrusted` at all, so this is a strictly additive narrowing that fires only on Gemini's actual workspace-trust failure messages.

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

**On `actionable_hint` wire format (resolves review I5):** the strings shown in the table above are the *English rendering* for clarity. On the wire `actionable_hint` is an i18n key like `cli.errors.needs_auth.<platform>` or `cli.errors.workspace_untrusted` — clients (web SPA, CLI rich renderer, MCP tool consumers) resolve through their own i18n pipeline. This is the contract Phase 3 ships; `ExecutionMetadata.actionable_hint` is a key, never a free-form string.

### §3.1 Bounded fallback depth (resolves review C3)

Without a depth budget, recursive resilience (a leaf at QUOTA_EXHAUSTED dispatches to a peer via §8 → that peer also hits QUOTA_EXHAUSTED → dispatches another peer → …) becomes a fan-out storm during a provider outage. Two rules:

1. **`MAX_FALLBACK_DEPTH = 3`.** The dispatching `ExecutionRequest` carries a `parent_chain: list[UUID]` populated from `parent_task_id` of every prior agent in the lineage. `ResilientExecutor` refuses any request where `len(parent_chain) >= 3`, returning Status = `PROVIDER_UNAVAILABLE` with `actionable_hint = "fallback chain exhausted (depth 3)"`.
2. **No agent appears twice in `parent_chain`.** Cycle detection: refuse if the dispatching agent's `agent_id` is already in `parent_chain`. Same Status / hint.

Both rules are enforced in `ResilientExecutor.execute(req)` before any preflight or adapter call — they're a **gate**, not a runtime check, so the storm never starts.

### §3.2 NEEDS_AUTH → opencode-fallthrough (R1 amendment, Phase 2)

The §3 invariant says auth/setup/trust errors **stop the chain** so the user sees the actionable hint. That's correct for the typical chain — `claude_code → codex → copilot_cli`, all subscription-gated. But every tenant's chain has `opencode` as the **local floor**: it needs no external creds, runs the local Gemma model, and is the universal "always available" terminator.

A literal §3 reading would also stop on `claude_code:NEEDS_AUTH` even when `opencode` is the next platform — leaving the user without a response when we could have served one locally. We don't want that.

**Sub-rule (encoded in `cli_orchestrator.policy.decide`):**

> When the failing status is one of `NEEDS_AUTH`, `WORKSPACE_UNTRUSTED`, or `API_DISABLED` AND the executor's `next_platform` in `req.chain` is exactly `opencode`, the policy returns `action="fallback"` AND **preserves the actionable_hint** on the decision. The executor stashes that hint in `carry_hint` and stamps it on the eventual successful `ExecutionResult.actionable_hint` as a **non-blocking annotation**.

What the user sees in chat: the response IS produced (by opencode). The chat footer renders the hint as a passive "FYI: your Claude Code subscription needs reconnecting at /settings/integrations" line, NOT a hard error. Reconnecting is a one-click action they can do later.

What the policy still enforces (no §3 weakening):
- The fallthrough is **specific to `next_platform == "opencode"`**. NEEDS_AUTH on `claude_code` with `next_platform="codex"` STILL stops the chain (codex would also be subscription-gated; user still has to reconnect).
- The actionable_hint is **always set** when policy stops or §3.2-falls-through. The mechanism that surfaces it is what differs (hard error footer vs non-blocking annotation).

This is what the test gate `test_no_fallback_on_auth.py` covers in **both** branches: stops-with-hint when next is non-opencode, falls-through-with-hint when next is opencode.

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
| Required cloud API enabled (GCP for Gemini, Copilot org-enabled for `gh copilot`) | **DEFERRED to Phase 4+** — Phase 3 review C1 dropped the unauthenticated-reachability probe (it always returned True from any cluster with internet, never actually detected project-level disabled state). Re-introduce with a tenant-keyed call (`?key=<tenant-api-key>` for Gemini → 403 + `SERVICE_DISABLED` reason; org-scoped token for Copilot). Until then, `API_DISABLED` is surfaced from subprocess stderr by the classifier on the runtime path, not preflight. | n/a (Phase 3) | API_DISABLED (runtime-only) |
| Temporal queue reachable (`agentprovision-code` worker registered) | only when ResilientExecutor itself dispatches an activity | < 1ms cached / 5-50ms uncached. **Implementation note (Phase 3 commit 2):** uses heartbeat-staleness via Redis GET, NOT `describe_task_queue` — the latter requires a TCP/gRPC handshake on cold cache, far above the 10ms target. Heartbeat probe reads the worker's freshness key from Redis with 30s TTL. | PROVIDER_UNAVAILABLE |

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
- `tests/cli_orchestrator/test_heartbeat_rejects_non_agent_token.py` — `/api/v1/agents/internal/heartbeat` rejects tenant JWT and `X-Internal-Key` with 403 + audit-log entry (defence in depth — Cloudflare `/internal/*` block is network-layer; the route enforces auth-tier in code too). Covers the M-C/§10.2/§10.3(c) hardening.

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
| **4** | Agent-scoped JWT mint + third auth tier on `apps/mcp-server` + new MCP tools `dispatch_agent` (review M6) + `request_human_approval` (review M6). The CLI binary's existing `agent` / `blackboard` / `memory` / `workflow` / `approval` subcommands are added in a sibling PR-C of the CLI track (#332 follow-up); they're not Phase 4 of this design. | `feat/cli-orchestrator-phase-4-leaf-mcp-auth` *(renamed per review M3)* | (a) leaf-from-Claude-Code calls `recall_memory` and the audit pipeline records the call with `task_id` from the agent_token claim (writes to `tool_calls`; `execution_trace.parent_task_id` wiring deferred — see Known deferrals); (b) **scope-enforcement test** — leaf with `scope=["recall_memory"]` calling `dispatch_agent` returns 403 + a `tool_calls` row with `result_status='scope_denied'` (review's added second gate); (c) tenancy-precedence test (I3); (d) recursion gate at `/tasks/dispatch` refuses depth ≥ MAX_FALLBACK_DEPTH | revert PR; agent-token minting is additive — leaves fall back to no-op until reverted |

Each phase is its own PR; each PR's ship gate must pass before the next branches off.

### Phase 2 cutover playbook (post-merge)

Phase 2 ships behind two flags on `tenant_features` (migration 121):

  - `use_resilient_executor` (default **FALSE**) — the hard cutover gate.
    FALSE keeps the legacy chain walk in `agent_router._legacy_chain_walk`
    (byte-identical to the previous in-line block); TRUE switches to
    `ResilientExecutor.execute(req)` via `agent_router._resilient_chain_walk`.
  - `shadow_mode_real_dispatch` (default **FALSE**) — sub-flag for the
    flag-OFF shadow path. FALSE = stubbed shadow (replays the legacy
    outcome through the executor; cheap, no second dispatch). TRUE =
    real adapter dispatch (~2x cost; only ~48h validation).

Cutover sequence (each step requires the previous gate to pass):

  1. **Internal-tenant validation, real dispatch (≤48h).** Flip both
     flags TRUE on a single internal tenant. Watch
     `cli_orchestrator_shadow_agreement_total` — agreement rate must
     hold ≥99.5% across ≥1000 dispatches. The R4 amendment excludes
     `disagreement_kind="expected_behaviour_change"` from the
     denominator (legacy fell through on auth → new path stops with
     hint is the *designed* change, not a regression).
  2. **Pilot tenants, flag-OFF shadow (cheap path).** Reset
     `shadow_mode_real_dispatch=FALSE` on the internal tenant; enable
     `use_resilient_executor=TRUE` on a pilot cohort. The cheap
     shadow now runs across all flag-OFF tenants. Watch
     `cli_orchestrator_status_total` and `cli_orchestrator_duration_ms`
     for the pilot cohort: chat p50 must stay within +10% of the
     ~5.5s pre-cutover baseline.
  3. **Ramp.** 10% → 25% → 50% → 100% over 14 days, gating each step
     on the same SLOs. UNKNOWN_FAILURE rate <1% over rolling 1-hour
     window. Pager alerts wire `cli_orchestrator_fallback_depth p99
     > 2` (storm tripwire — §3.1 gate should prevent it).
  4. **Hard cutover.** After 14 days at 100% with all SLOs holding,
     remove the legacy chain-walk path entirely. The `_legacy_chain_walk`
     helper stays as a sealed reference until the next major release.

Rollback: flip `use_resilient_executor=FALSE` on the affected tenant
(or fleet-wide via `UPDATE tenant_features SET use_resilient_executor =
FALSE`). The legacy code path is byte-identical to the pre-Phase-2
in-line block — no migration step needed for revert. Migration 121
columns can be dropped via `121_*.down.sql` in a follow-up if the
flag is permanently removed.

### Phase 3 ship-gate (post-merge)

Phase 3 ships preflight composition + ExecutionMetadata + RL mirror +
webhook event emission + i18n + Prometheus exposition + heartbeat-missed
endpoint. **No new database migration** — RLExperience JSONB columns
absorb the mirror; the existing `tenant_features.use_resilient_executor`
flag (migration 121) still gates the executor path.

Ship gates (must hold for 24h before declaring success):

  - **Preflight latency**: `cli_orchestrator_preflight_duration_ms` p95
    inside the design §6 budget table per (helper, platform) — the
    latency-budget test enforces this in CI; the dashboard alerts in
    monitoring/alerts/cli-orchestrator.yaml flag regressions in prod.
  - **UNKNOWN_FAILURE rate < 1%** over any rolling 1-hour window
    (design §4.1 SLO). The classifier-drift Pager alert fires at >5%
    over 15min as a tripwire.
  - **RL mirror non-blocking**: zero chat-response failures attributable
    to mirror exceptions in the structured log over 24h. Audited via
    the existing `agent_router.logger.debug` "RL mirror write failed"
    line and the `cli_orchestrator_status_total` counter staying flat
    across mirror failures.
  - **Webhook delivery**: outbound `execution.*` webhooks deliver with
    `webhook_delivery_logs.success` >= 95% over 24h. 4xx remains
    permanent-failure (no retry); 5xx + connection errors will retry
    once the Phase 3 follow-up `WebhookDeliveryWorkflow` lands (NOT
    shipping in this PR — see "What this PR does NOT ship" below).
  - **i18n actionable_hint**: every `cli.errors.<status>[.<platform>]`
    key emitted by `policy._hint_key` resolves through the
    `RoutingFooter.resolveActionableHint` fallback chain without
    falling all the way to the English literal. Tracked via a
    one-shot grep audit during the 24h soak.
  - **Heartbeat-missed event delivery**: zero 5xx responses on the new
    `/api/v1/internal/orchestrator/events` endpoint over 24h. Worker
    POST is fire-and-forget so a 5xx doesn't kill the activity, but a
    sustained 5xx rate signals a downstream webhook misconfiguration.

Rollback: Phase 3 is **additive** at flag-OFF — every code path runs
only when `use_resilient_executor=TRUE` (or only inside the executor
itself, which is no-op at flag-OFF). Revert is mechanical:

  - Each commit reverts cleanly via `git revert <commit-sha>` — no
    cross-commit state.
  - The `cli_orchestrator_preflight_duration_ms` Histogram drops out
    of the metrics output but the `/api/v1/metrics` endpoint stays up.
  - The Grafana dashboard JSON + PrometheusRule alerts stay deployed
    even on full revert; they just emit zero data, which is the same
    state as pre-Phase-3.

### What this PR does NOT ship (deliberate Phase 3 scope cut)

The following are scoped out of Phase 3 and ship as their own follow-ups:

  - **Webhook secret encryption (`secret_v2` column)** — design §11.2.
    Has its own dual-read migration plan (migrations 121 → 122) and
    needs a security review. Tracked separately.
  - **`webhook_trigger` workflow step executor** — design §11.2.
    Shares the workflow-suspension primitive with `human_approval`;
    needs its own design pass for backpressure semantics.
  - **`WebhookDeliveryWorkflow` retry policy** — design §11.2 row 5.
    `RetryPolicy(initial_interval=1s, backoff_coefficient=8.0,
    maximum_interval=3600s, maximum_attempts=6)` for transient
    failures (5xx + connection errors). Lands as a sibling PR.
  - **Per-tenant credential Redis cache** — design §6 row 2 hint.
    Vault hot path stays sub-5ms today; cache lands as an
    optimisation when the latency-budget panel shows pressure.

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

### §9.2 Hook implementation shape (resolves review M9)

Claude Code hooks are **shell commands** (per docs: stdin-JSON I/O, exit-2 to block, no native HTTP). Therefore both the leaf-side hooks ship as thin shell wrappers, generated by the code-worker into the leaf's `.claude/hooks/` dir at session-spawn time:

**Hook stdin contract** (per Claude Code docs — important for the templates below): the JSON has `session_id`, `transcript_path`, `cwd`, `hook_event_name`, **`tool_name`** (top-level), and `tool_input` (sibling of `tool_name`, not parent). The prior draft of these templates used `.tool_input.tool_name` — a silent bug that would have made `TOOL=""` always, permanently disabling the PreToolUse gate. (Resolves review I-A.)

Also: stdin can be multi-line in principle (Claude Code emits compact JSON today, but the contract doesn't forbid pretty-printed). Templates use `STDIN=$(cat)` not `read -r STDIN` for safety. (Resolves review I-B.)

**`PostToolUse` (heartbeat — fire-and-forget, never blocks):**
```bash
#!/usr/bin/env bash
# Generated by code-worker; do not edit. AGENTPROVISION_AGENT_TOKEN
# and AGENTPROVISION_TASK_ID are injected into the subprocess env at
# spawn time and inherited by the hook process.
set -euo pipefail
STDIN=$(cat)
TOOL=$(jq -r '.tool_name // ""' <<<"$STDIN")
curl -fsS -m 2 -X POST \
  "${AGENTPROVISION_API:-https://api.agentprovision.com}/api/v1/agents/internal/heartbeat" \
  -H "Authorization: Bearer ${AGENTPROVISION_AGENT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\":\"${AGENTPROVISION_TASK_ID}\",\"tool_name\":\"${TOOL}\",\"ts\":$(date +%s)}" \
  >/dev/null 2>&1 || true   # fire-and-forget — hook never blocks the tool
exit 0
```

**`PreToolUse` (defence-in-depth allowed-tools check — must NOT add network latency):**
```bash
#!/usr/bin/env bash
# Allowed-tools list is injected as AGENTPROVISION_ALLOWED_TOOLS at
# session spawn (whitespace-separated). NO network call here — the
# primary enforcement is server-side at the MCP boundary; this hook
# is a fast local gate that fails closed if the env is missing.
set -euo pipefail
STDIN=$(cat)
TOOL=$(jq -r '.tool_name // ""' <<<"$STDIN")
if [[ -z "${AGENTPROVISION_ALLOWED_TOOLS:-}" ]]; then
  exit 0   # no allowlist provided → trust server-side enforcement
fi
case " ${AGENTPROVISION_ALLOWED_TOOLS} " in
  *" ${TOOL} "*) exit 0 ;;
  *) echo "tool ${TOOL} not in agent_policy.allowed_tools" >&2; exit 2 ;;
esac
```

**Key points:**
- The hot path (PreToolUse) does **zero** network calls — `agent_policy.allowed_tools` is rendered into env at session spawn by the code-worker, not fetched per-tool.
- PostToolUse heartbeat is fire-and-forget with a 2s timeout — never blocks the tool, never errors out the leaf.
- All env vars (`AGENTPROVISION_AGENT_TOKEN`, `AGENTPROVISION_TASK_ID`, `AGENTPROVISION_ALLOWED_TOOLS`, `AGENTPROVISION_API`) are injected by the code-worker as part of the existing subprocess-spawn flow (alongside `CLAUDE_CODE_OAUTH_TOKEN`), then inherited by the hook process via the OS — no additional plumbing.
- Both wrappers are deterministic templates; tests in `apps/code-worker/tests/test_hook_template_generation.py` assert the rendered output matches a golden snapshot **and** assert the rendered template, fed a real Claude-Code-shaped JSON payload `{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{...}}`, extracts `Bash` not `""` (locks down review I-A so a future jq-path regression fails the build).

---

## §10 — CLI ↔ existing API endpoint map

Every CLI subcommand maps to existing endpoints. The CLI is not a new surface; it's a new client of the surface the web SPA already uses. This table is the **explicit contract** that Phase-1-of-the-CLI-track (PR-C following #332) will implement.

**Verification.** Every "✅" row below was cross-checked against `apps/api/app/api/v1/routes.py` and the per-router source files at the indicated line. "🆕" rows are genuinely new endpoints; "♻" rows route through an existing endpoint with reshaped payload.

| CLI subcommand | HTTP | Endpoint | Status | Source |
|---|---|---|---|---|
| `login` | `POST` | `/api/v1/auth/device-code`, `/device-token`, `/login` | ✅ shipped | PR #329 |
| `logout` | local | (clears token store) | ✅ shipped | PR #332 |
| `status` | `GET` | `/api/v1/auth/users/me` | ✅ shipped | `auth.py:143` |
| **chat** |  |  |  |  |
| `chat send` | `POST` | `/api/v1/chat/sessions/{id}/messages[/stream]` | ✅ shipped | PR #332 fixup |
| `chat repl` | (loop) | same | ✅ shipped | PR #332 |
| `chat sessions list` | `GET` | `/api/v1/chat/sessions` | ✅ shipped | `chat.py:54` |
| **agent** |  |  |  |  |
| `agent list` | `GET` | `/api/v1/agents` | ✅ shipped | `agents.py` |
| `agent show <id>` | `GET` | `/api/v1/agents/{id}` | ✅ shipped | `agents.py` |
| `agent discover --capability <cap>` | `GET` | `/api/v1/agents/discover?capability=<cap>` | ✅ shipped | `agents.py:376` |
| `agent dispatch <id> --goal "…"` | `POST` | `/api/v1/agent-tasks/dispatch` *(see §10.3)* | 🆕 new | the existing `POST /api/v1/tasks` only writes a queued row; **no Temporal dispatch happens there**. The new endpoint is the missing dispatch surface. |
| `agent heartbeat <id>` | `POST` | `/api/v1/agents/{id}/heartbeat` | ✅ shipped | `agents.py:738` |
| `agent audit <id>` | `GET` | `/api/v1/agents/{id}/audit-log` | ✅ shipped | `agents.py:763` |
| `agent rollback <id> --version <v>` | `POST` | `/api/v1/agents/{id}/versions/{v}/rollback` | ✅ shipped | `agents.py:647` *(was wrong path in prior draft)* |
| **workflow** |  |  |  |  |
| `workflow list` | `GET` | `/api/v1/dynamic-workflows` | ✅ shipped | `dynamic_workflows.py:405` *(static `workflows` router has no list/run; we use the dynamic one)* |
| `workflow show <id>` | `GET` | `/api/v1/dynamic-workflows/{id}` | ✅ shipped | `dynamic_workflows.py:418` |
| `workflow templates` | `GET` | `/api/v1/dynamic-workflows/templates/browse` | ✅ shipped | `dynamic_workflows.py:698` |
| `workflow install <template-id>` | `POST` | `/api/v1/dynamic-workflows/templates/{id}/install` | ✅ shipped | `dynamic_workflows.py:713` |
| `workflow run <id>` | `POST` | `/api/v1/dynamic-workflows/{id}/run` | ✅ shipped | `dynamic_workflows.py:554` |
| `workflow runs [--id <wf>]` | `GET` | `/api/v1/dynamic-workflows/{id}/runs` | ✅ shipped | `dynamic_workflows.py:626` |
| `workflow run-show <run-id>` | `GET` | `/api/v1/dynamic-workflows/runs/{run_id}` | ✅ shipped | `dynamic_workflows.py:643` |
| `workflow schedule <id> --cron "…"` | `PUT` | `/api/v1/dynamic-workflows/{id}` *(updates `definition.trigger`)* | ✅ shipped | `dynamic_workflows.py:437` |
| **code** |  |  |  |  |
| `code task "<description>"` | `POST` | `/api/v1/agent-tasks/dispatch` *(same endpoint as `agent dispatch`, see §10.3)* | 🆕 new | dispatches `CodeTaskWorkflow` server-side. The existing `POST /api/v1/tasks` does **not** dispatch — it just queues a row; the chat hot path (`cli_session_manager.py:1028`) is the only current dispatch site. We add a real dispatch endpoint, not a payload-shape change. |
| `code task-show <task-id>` | `GET` | `/api/v1/tasks/{task_id}` | ✅ shipped | `agent_tasks.py:120` *(read-only is fine — only the dispatch verb needed a new surface)* |
| `code task-trace <task-id>` | `GET` | `/api/v1/tasks/{task_id}/trace` | ✅ shipped | `agent_tasks.py:147` |
| **memory** |  |  |  |  |
| `memory recall "<query>"` | `GET` | `/api/v1/memories/search?q=<query>` | ✅ shipped | `memories.py:172` *(corrected — the prior draft routed through `/api/v1/mcp` which is **skill-only by design**; `mcp_bridge.py:84` filters to `tool_name.startswith("skill_")`. `recall_memory` lives on the FastMCP server at port 8086, a different service tenant-JWT clients can't reach via the JSON-RPC bridge.)* |
| `memory record-observation <entity-id> "<text>"` | `POST` | `/api/v1/knowledge/entities/{entity_id}/observations` *(see §10.3)* | 🆕 new | no current REST endpoint writes to `knowledge_observations` for tenant-JWT clients. The MCP `record_observation` tool on port 8086 is leaf-only. New endpoint is small (single insert + embed) and parallels the existing entity-score endpoint at `knowledge.py:198`. |
| `memory record-commitment` | `POST` | `/api/v1/commitments` | ✅ shipped | `commitments.py:55` |
| `memory record-goal` | `POST` | `/api/v1/goals` | ✅ shipped | `goals.py:35` |
| `memory entities list` | `GET` | `/api/v1/knowledge/entities` | ✅ shipped | `knowledge.py:47` |
| `memory entities search` | `GET` | `/api/v1/knowledge/entities/search` | ✅ shipped | `knowledge.py:65` |
| **skill** |  |  |  |  |
| `skill list` | `GET` | `/api/v1/skills/library` | ✅ shipped | `skills_new.py:329` |
| `skill show <slug>` | `GET` | `/api/v1/skills/library/{slug}/source` | ✅ shipped | `skills_new.py:560` *(returns raw SKILL.md)* |
| `skill run <slug> --input @args.json` | `POST` | `/api/v1/skills/library/execute` | ✅ shipped | `skills_new.py:438` *(was wrong path in prior draft)* |
| `skill versions <slug>` | `GET` | `/api/v1/skills/library/{slug}/versions` | ✅ shipped | `skills_new.py:831` |
| **integration** |  |  |  |  |
| `integration list` | `GET` | `/api/v1/integrations/status` | ✅ shipped | `integrations.py:18` |
| `integration connect <name>` | (browser open) | `/api/v1/oauth/{provider}/authorize` | ✅ shipped | `oauth.py` |
| `integration test <id>` | `POST` | `/api/v1/integration-configs/{integration_config_id}/test` | ✅ shipped | `integration_configs.py:480` *(was wrong path in prior draft)* |
| `integration disconnect <name>` | `POST` | `/api/v1/oauth/{provider}/disconnect` | ✅ shipped | `oauth.py:703` *(POST not DELETE — fixed)* |
| **blackboard** *(humans triaging A2A coalitions)* |  |  |  |  |
| `blackboard list` | `GET` | `/api/v1/blackboards` | ✅ shipped | `blackboards.py:24` |
| `blackboard show <id>` | `GET` | `/api/v1/blackboards/{board_id}` | ✅ shipped | `blackboards.py:50` |
| `blackboard write` | `POST` | `/api/v1/blackboards/{board_id}/entries` | ✅ shipped | `blackboards.py:66` |
| **tenant / config** |  |  |  |  |
| `tenant whoami` | `GET` | `/api/v1/auth/users/me` | ✅ shipped | `auth.py:143` |
| `tenant features` | `GET` | `/api/v1/features` | ✅ shipped | `features.py:14` *(was wrong prefix in prior draft)* |
| `config get/set/list` | local | `~/.config/agentprovision/config.toml` | local | shipped PR #332 |
| **tool / mcp** |  |  |  |  |
| `tool list` / `tool call` | — | — | ⏭ deferred | the `/api/v1/mcp` JSON-RPC bridge is **skill-only by design** (`mcp_bridge.py:84` filters to `skill_<slug>`); the FastMCP server's broader catalog at port 8086 is leaf-agent-only via SSE + agent-JWT. A REST surface for the human-callable tool catalog is a future follow-up (PR-D); humans use `skill list` / `skill run` today, which already covers the user-callable subset. |
| **internal — Phase 4 only** |  |  |  |  |
| (leaf hook) PostToolUse heartbeat | `POST` | `/api/v1/agents/internal/heartbeat` *(see §10.3)* | 🆕 new | resolves review I9 — accepts **agent-token JWT only**, rejects tenant JWT with 403 (defence-in-depth — Cloudflare `/internal/*` block is network-layer; the route enforces auth-tier in code too); payload `{agent_id, task_id, parent_workflow_id, tool_name, ts}`; updates in-flight task last-seen-at; emits `event` trigger when missed |

### §10.1 Summary

After the third-review correction (the prior draft's ♻ reuse claims for `agent dispatch`, `code task`, `memory recall`, `memory record-observation`, `tool list`, `tool call` were structurally wrong — endpoint existed at the verb/path level but couldn't actually serve the subcommand because semantics or filters didn't match):

- **✅ shipped**: 40 rows — every cited line + verb verified against the actual route file. Includes `memory recall → /memories/search` and `code task-show / task-trace → /tasks/{id}*` after the reroute.
- **🆕 new endpoints**: 3 — `/api/v1/agent-tasks/dispatch` (serves both `agent dispatch` and `code task` — 2 CLI subcommands, 1 endpoint), `/api/v1/knowledge/entities/{id}/observations`, `/api/v1/agents/internal/heartbeat`. Specs in §10.3.
- **⏭ deferred**: 1 row covering 2 subcommands (`tool list` / `tool call`). The `/api/v1/mcp` bridge is skill-only; humans use `skill list` / `skill run` today; a tenant-JWT REST surface for the broader FastMCP catalog is a separate PR-D follow-up.

### §10.2 Auth model per row

All `✅` rows accept tenant JWT (the existing path used by the web SPA). The agent-token-only endpoint (heartbeat) **explicitly rejects tenant JWT with 403** — defence in depth; Cloudflare `/internal/*` blocking is network-layer only. Test in `test_heartbeat_rejects_non_agent_token.py` (§7 Phase 4 group).

### §10.3 New endpoint specs

The 3 🆕 rows ship as small, well-bounded routes. Each is its own commit inside the relevant phase PR.

**(a) `POST /api/v1/agent-tasks/dispatch`** — Phase 4 (alongside leaf-MCP). Mounted at the existing `/tasks` router (`agent_tasks.py`). Auth: tenant JWT. Request body:
```json
{
  "task_type": "code" | "delegate",
  "objective": "<string>",
  "target_agent_id": "<uuid>",        // required when task_type=delegate
  "repo": "<owner/repo>",             // optional, code only
  "branch": "<base-branch>"           // optional, code only, defaults main
}
```
Response: `{ "task_id": "<uuid>", "workflow_id": "<temporal-id>", "status": "running" }` (201 Created). Implementation: writes `agent_tasks` row + dispatches `CodeTaskWorkflow` (task_type=code) or `TaskExecutionWorkflow` (task_type=delegate) via the existing Temporal client. **Mirrors the chat hot-path dispatch shape** (`client.execute_workflow` from `cli_session_manager.py:1028`), **not** the in-workflow `workflow.execute_child_workflow` call at `dynamic_executor.py:161`. Subsumes the dispatch logic that today lives only on the chat hot path.

**(b) `POST /api/v1/knowledge/entities/{entity_id}/observations`** — Phase 3 (alongside metadata). Auth: tenant JWT. Request body: `{ "text": "<string>", "source_ref": "<optional-string>" }`. Response: `{ "observation_id": "<uuid>", "embedding_dim": 768 }` (201). Implementation: insert into `knowledge_observations` + embed via `embed_text()` + write `memory_activities` row. Mirrors the existing entity-score endpoint shape at `knowledge.py:198`.

**(c) `POST /api/v1/agents/internal/heartbeat`** — Phase 4 leaf telemetry. Auth: **agent-token JWT only** (`kind=agent_token`); tenant JWT and `X-Internal-Key` are explicitly rejected with 403 + audit-log entry. Request body: `{ "task_id": "<uuid>", "tool_name": "<string>", "ts": <unix-seconds> }`. Response: 204 No Content.

Implementation: bumps last-seen on the in-flight `agent_tasks` row keyed by JWT-claim `task_id`; if the bump arrives after `2 * heartbeat_interval`, fires `event` trigger payload `execution.heartbeat_missed` per §11.3.

**Schema dependency (Phase 4 ships this migration):** the `agent_tasks` table today has only `started_at` + `completed_at` (`apps/api/app/models/agent_task.py:50-51`). The heartbeat endpoint needs a `last_seen_at` column. **Migration `124_agent_task_last_seen.sql`** adds:
```sql
ALTER TABLE agent_tasks ADD COLUMN last_seen_at TIMESTAMP NULL;
CREATE INDEX idx_agent_tasks_last_seen_at ON agent_tasks(last_seen_at)
    WHERE status IN ('running', 'queued');
-- partial index — we only sweep in-flight rows for missed heartbeats
```
Reuse of `updated_at` was rejected (gets bumped by every status change — no signal). A separate `agent_task_heartbeats` time-series table was rejected as overkill for a freshness check; if heartbeat history becomes a feature later, it can land then without changing this endpoint's contract.

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

- **`webhook_trigger` workflow step has no executor.** Today the step is registered in the schema, validates, renders in the visual builder, but no `DynamicWorkflowExecutor` handler exists. Fix: implement the handler in `apps/api/app/workflows/dynamic_executor.py` *(corrected path per review M7 — `workflows`, not `workers`)* so a workflow that hits `webhook_trigger` **suspends** (Temporal `workflow.wait_condition`), the inbound `/in/{slug}` handler signals it on matching event arrival, and the workflow resumes with the webhook payload as step input. **Lands in Phase 3** (alongside metadata) because it shares the workflow-suspension primitive with `human_approval`.
- **HCA inbound `/api/v1/webhooks/hca` has NO signature verification.** Either (a) require HMAC and break compatibility with anyone who hasn't rotated, or (b) deprecate the route and migrate HCA to the generic `/in/{slug}` shape. Recommend (b) — landed in Phase 3 with a 30-day deprecation window.
- **`WebhookConnector.secret` stored in plaintext.** *(Resolves review I8 — moved from Phase 1 to Phase 3.)* This is a behaviour change with its own security review (column rotation, decryption hot path, key rotation), coupled to in-flight outbound deliveries (`fire_outbound_event` reads `webhook.secret` in `_deliver_outbound:257`) and inbound HMAC verifies. Wrong shape for Phase 1's "no behaviour change" gate. Lands in Phase 3 with this migration plan:
   1. Migration 121 adds `secret_v2` column (encrypted) alongside `secret` (plaintext). Both nullable, no constraint.
   2. App release N — read path: `decrypt(secret_v2) if secret_v2 else secret`. Write path: write both columns (encrypted to `secret_v2`, plaintext to `secret` for one release).
   3. Background backfill task encrypts every existing plaintext row's `secret` into `secret_v2`. Idempotent — skip rows where `secret_v2` is already populated.
   4. Release N+1 — write path stops writing to `secret`. Read path requires `secret_v2`. (Cutover.) Inbound HMAC verifies signed before backfill must still verify because the secret material is unchanged — only its storage was.
   5. Migration 122 (one release later) — drop `secret` plaintext column.
   6. **Ship gate (Phase 3 webhook subset):** zero failed deliveries during the dual-read window, monitored via existing `webhook_delivery_logs.success` field.
- **No retry on outbound delivery failure.** Phase 3: extend `fire_outbound_event` to enqueue a Temporal `WebhookDeliveryWorkflow` on transient failures (5xx + connection errors). *(Resolves review M8 — picking the explicit shape.)* Implementation uses **Temporal `RetryPolicy(initial_interval=1s, backoff_coefficient=8.0, maximum_interval=3600s, maximum_attempts=6)`** which with 6 attempts yields **5 inter-attempt waits**: `1s → 8s → 64s → 512s → 3600s` (the final wait would have been 4096s but is clipped by `maximum_interval`). 4xx is non-retryable (`non_retryable_error_types`). Each attempt writes a `webhook_delivery_logs` row. Idempotency via the existing outbound `X-Webhook-Delivery-Id` header.
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
- `test_webhook_secret_encryption.py` — round-trip via the Fernet vault; old plaintext rows still read correctly during the transition release. Both call sites read through a **single shared helper** `_resolve_secret(webhook)` that returns `decrypt(secret_v2) if secret_v2 else secret`:
  - **outbound HMAC sign + Bearer + Basic auth** in `apps/api/app/services/webhook_connectors.py:252-257` (`_deliver_outbound`)
  - **inbound HMAC verify** in `apps/api/app/api/v1/webhook_connectors.py:238` (the `/in/{slug}` route handler)

  One helper, two files, four call paths (sign + bearer + basic on outbound, verify on inbound). This is the seam the dual-read plan depends on.
- **`test_webhook_inbound_hmac_dual_read.py`** *(resolves review I-D)* — covers the cross-release boundary case: an inbound webhook signed against the plaintext-era secret arriving during release N+1's read-only-`secret_v2` window. Asserts the inbound HMAC verify still succeeds because the **secret material is unchanged** — only its storage location changed. Same `_resolve_secret(webhook)` helper as the outbound path.
- `test_webhook_outbound_retry.py` — 5xx / connection error triggers `WebhookDeliveryWorkflow`; 4xx does not; backoff ladder matches spec
- `test_webhook_inbound_idempotency.py` — same `X-Webhook-Idempotency-Key` within 24h returns 200 + `dedup=true` without re-firing the workflow
- `test_webhook_inbound_replay_window.py` — `X-Webhook-Timestamp` outside ±5min is rejected 401
- `test_orchestrator_emits_execution_events.py` — happy path, fallback path, heartbeat-missed path each emit the right event with the right payload shape

---

**End of design doc.** §9, §10, §11 close the gaps the reviewer flagged. Sign-off scope above remains unchanged.


---

## Phase 4 ship-gate post-merge notes (2026-05-10)

Phase 4 (`feat/cli-orchestrator-phase-4-leaf-mcp-auth`) implements the
leaf-from-Claude-Code → `apps/mcp-server` SSE inbound surface, the
agent-scoped JWT mint, the .claude.json + hooks injection by the
code-worker, and the four ship gates (a)-(d) in §4 of this doc. Ten
commits (`mint primitives` → `dispatch_agent + heartbeat`).

### What's now wired end-to-end

1. **Mint at task dispatch.** `apps/api/app/services/agent_token.py`
   exposes `mint_agent_token()` + `verify_agent_token()` against
   `settings.SECRET_KEY` (no new secret, SR-2). `parent_chain` is hard-
   capped at MAX_FALLBACK_DEPTH=3 at mint time (SR-3 + D8). JWT size
   stays well under 4 KB even with worst-case 50-tool scope + 3-element
   chain (SR-3 regression guard test enforces this).

2. **Internal mint endpoint.** `POST /api/v1/internal/agent-tokens/mint`
   gated by `X-Internal-Key` lets the code-worker pod request fresh
   tokens without holding `SECRET_KEY` itself.

3. **Chat hot path mint.** `cli_session_manager.run_agent_session`
   mints + plumbs through `generate_mcp_config(..., agent_token=tok)`
   only when `tenant_features.use_resilient_executor=TRUE`. Flag-OFF
   path is byte-identical to Phase 3.

4. **Code-worker hooks + .claude.json.** `apps/code-worker/hook_templates.py`
   ships PreToolUse + PostToolUse shell scripts (templates lock down
   the `.tool_name`-not-`.tool_input.tool_name` jq path per review I-A,
   and `STDIN=$(cat)` not `read -r STDIN` per review I-B).
   `.claude.json` writer uses `os.open(O_CREAT|O_WRONLY|O_TRUNC, 0o600)`
   so a co-tenant on the same workspace pod can't snoop the token (SR-4).

5. **Third auth tier on mcp-server.** `resolve_auth_context(ctx)` returns
   an `AuthContext` covering all four tiers in precedence order. The
   `kind=='agent_token'` AND `sub.startswith('agent:')` double-check
   (SR-11) blocks regular login tokens from crossing into the agent
   tier even though they're signed with the same secret.

6. **Tenancy precedence + rate-limited audit.** When the leaf carries
   both an agent_token AND a header-set X-Tenant-Id, the claim wins
   silently; the mismatch is audit-logged once per minute per
   (tenant, agent, header) tuple via an in-process LRU (SR-6). Test
   asserts 100 mismatches in 1s produce exactly 1 audit row.

7. **Scope enforcement at audit boundary.** When tier=='agent_token'
   AND scope is not None AND tool_name not in scope → write a
   `result_status='scope_denied'` audit row and raise PermissionError
   BEFORE invoking the original tool handler. scope=None bypasses
   (Luna with full tool_groups). scope=[] is "no tools allowed" —
   distinct semantics, also tested.

8. **`dispatch_agent` + `request_human_approval` MCP tools.** Both
   require tier=='agent_token'. `dispatch_agent` appends the caller's
   agent_id to parent_chain so the §3.1 recursion gate at
   `/tasks/dispatch` refuses calls at depth 3+. The endpoint surfaces
   503 with the actionable_hint so the leaf can render a useful
   "fallback chain exhausted" message instead of a silent retry.

9. **Heartbeat endpoint + migration 122.** `POST /api/v1/agents/internal/heartbeat`
   is auth-tier-only — rejects tenant JWT and X-Internal-Key with 403
   (defence-in-depth, design §10.3(c)). Migration 122 adds
   `agent_tasks.last_seen_at TIMESTAMPTZ` + a partial index for the
   heartbeat-missed scan path.

10. **§3.1 gate fires at dispatch.** Commit 9's integration test proves
    the gate refuses depth-3 calls at the `/tasks/dispatch` boundary
    BEFORE any Temporal workflow starts — closing the resilience loop
    with a hard upstream stop.

### Ship-gate verification

Each Phase 4 §4 gate has a matching test file:

| Gate | What it verifies | Test file |
|------|------------------|-----------|
| (a) leaf → recall_memory → execution_trace.parent_task_id | agent_token claim carries task_id; verify_agent_token round-trips it | `apps/api/tests/integration/test_phase4_ship_gate.py::test_gate_a_*` |
| (b) scope=[X] → out-of-scope tool → 403 + audit | tool_audit raises PermissionError + writes audit row with scope_denied | `apps/mcp-server/tests/test_agent_token_auth.py::test_scope_blocks_*` + `apps/api/tests/integration/test_phase4_ship_gate.py::test_gate_b_*` |
| (c) tenant_A claim + tenant_B header → claim wins, audit logged once/min | LRU rate-limiter, 1 row per (tenant, agent, header) per 60s | `apps/mcp-server/tests/test_agent_token_auth.py::test_tenancy_mismatch_rate_limited_*` + `apps/api/tests/integration/test_phase4_ship_gate.py::test_gate_c_*` |
| (d) depth-3 leaf → /tasks/dispatch → PROVIDER_UNAVAILABLE before adapter.run | Recursion gate fires server-side; no Temporal start_workflow | `apps/api/tests/cli_orchestrator/test_recursion_gate_dispatch.py` + `apps/api/tests/integration/test_phase4_ship_gate.py::test_gate_d_*` |

### Behavior change at flag boundary

Hard constraint: zero behavior change at `use_resilient_executor=False`.

  - The chat hot path's mint block (commit 3) is gated behind
    `read_flags(db, tenant_id) -> (use_resilient, _)`. Flag-OFF
    skips the mint and `generate_mcp_config(agent_token=None)` renders
    no Authorization header — byte-identical pre-Phase-4 shape.
  - The code-worker's `_inject_agent_token_and_hooks` runs only when
    `task_input.agent_id` AND `task_input.task_id` are both set. The
    chat hot path passes neither (it doesn't go through `/tasks/dispatch`).
    Legacy callers stay byte-identical; only new dispatch-endpoint
    callers see hooks injected.
  - The MCP server's `resolve_auth_context` keeps the legacy
    `resolve_tenant_id(ctx)` as a thin wrapper, so tools that called
    the old function don't need eager migration. They get the same
    tenant_id from whichever tier wins.

### Known deferrals (out of scope for Phase 4)

  - **Tenant-JWT decoding on the MCP server.** The chat hot path passes
    X-Tenant-Id explicitly today, so the resolver falls through to the
    header tier when no agent-token is present. Adding tenant-JWT
    decode is straightforward (`jose.jwt.decode` against the same
    SECRET_KEY) but not required by any Phase 4 ship gate.
  - **Live execution_trace writer integration.** The mcp-server-side
    audit pipeline currently writes `tool_calls` rows; the Phase 4
    integration with `execution_trace.parent_task_id` is implemented
    via the agent_token's `task_id` claim being preserved through the
    audit context, ready for a future commit to wire into the trace
    writer when the underlying persistence path lands.
  - **Synthetic AgentTask row for chat-driven leaves.** The chat hot
    path mints with `task_id = uuid4()` since the chat workflow
    doesn't persist an AgentTask. Audit `tool_calls` rows reference
    this id with no FK, which is safe today but means execution-trace
    JOINs from chat-driven leaves resolve to nothing. Phase 4.5 will
    persist a synthetic AgentTask row (kind="chat") to close the gap.
  - **Workflow-resume signal for `request_human_approval`.** The MCP
    tool flips `task.status` to `waiting_for_approval` and notifies
    the tenant admin via the new
    `/api/v1/tasks/internal/{task_id}/request-approval` internal
    endpoint. Resuming a Temporal `human_approval` workflow step is
    still gated on the human admin pressing Approve/Reject in the UI
    (which round-trips through the existing JWT-gated `/workflow-approve`).
    Phase 4.5 may unify the leaf-request and admin-resume paths once
    the visual-builder approval queue ships.
