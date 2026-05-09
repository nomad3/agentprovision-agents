# Resilient CLI Orchestrator — Network/Execution Layer Design

**Status:** DRAFT — pending user signoff before any implementation lands
**Date:** 2026-05-09
**Author:** Simon (with Luna design input)
**Branch:** `design/resilient-cli-orchestrator`

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
   runs INSIDE the activity. The activity returns one ExecutionResult,
   not an exception. Workflow-level failures (CancelledError, activity
   timeout, worker crash) get their own status (WORKFLOW_FAILED) and
   the workflow_id/activity_id is preserved on the result.
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

**Key invariant:** auth/setup/trust errors **never** trigger silent fallback. The user must see the actionable hint. Today, missing-credential triggers chain fallback (cli_platform_resolver line 214); under the new policy, chain fallback only happens on transient errors.

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
    error_class: str | None               # e.g. "QUOTA_EXHAUSTED:gemini_cli"
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
8. `(?i)(api[_-]?key|password|secret|token)["']?\s*[:=]\s*["']?([\w\-\.]+)` → `\1=<redacted>`

Plus a **structural pass**: when the input is parseable JSON, walk every key matching `(?i)(token|key|secret|password|cookie|auth)` and replace its value with `<redacted>`.

Plus the **env-var sanitiser** already in `skill_manager._SENSITIVE_ENV_KEYS` extended with platform-specific keys (`CLAUDE_CODE_OAUTH_TOKEN`, `COPILOT_GITHUB_TOKEN`, etc.) and reused at the CLI subprocess boundary.

**Tests** (§7):
- Each rule has a positive test (matches, redacts) and a negative test (a similar but legitimate string survives unchanged).
- A "concatenated leak" test feeds a 50KB log line containing a bearer + a JWT + a `sk-ant-…` key + a git URL, asserts every secret is redacted, every other character preserved verbatim.
- A property-based test (hypothesis-style) generates random secrets in random surrounding text and asserts the secret never survives.

## §6 — Preflight checks

`ProviderAdapter.preflight(req)` runs **before** subprocess spawn and returns either `PreflightResult.ok()` or a structured failure with the same `Status` enum (so the executor / fallback policy treats it identically to a runtime failure):

| Check | When | Status on fail |
|-------|------|----------------|
| Binary on `$PATH` (`shutil.which("claude")`, etc.) | every dispatch | PROVIDER_UNAVAILABLE |
| Credentials present in vault for this platform | every dispatch | NEEDS_AUTH (with actionable_hint to integrations page) |
| Workspace trust file (Codex `~/.codex/config.toml`, Gemini workspace setup marker) | every dispatch | WORKSPACE_UNTRUSTED |
| Required cloud API enabled (GCP for Gemini, Copilot org-enabled for `gh copilot`) — best-effort, cached 5min | every dispatch | API_DISABLED |
| Temporal queue reachable (`agentprovision-code` worker registered) | only when ResilientExecutor itself dispatches an activity | PROVIDER_UNAVAILABLE |

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
- `tests/cli_orchestrator/test_metadata_emission.py` — happy path emits one ExecutionMetadata with `attempt_count == 1`, `platform_attempted == [winner]`, `status == EXECUTION_SUCCEEDED`; failure path emits the full attempt chain and matching decision lists

## §8 — CLI as agent control-plane (Phase 4)

The `agentprovision` CLI binary doubles as the inbound surface for leaf agents (Claude Code / Codex / Gemini / Copilot subprocesses + sandboxed skills). When the orchestrator dispatches a task to a runtime, it mints a short-lived **agent-scoped JWT** and propagates:

- `AGENTPROVISION_AGENT_TOKEN` — JWT bound to `(agent_id, task_id, parent_workflow_id)`, TTL = activity heartbeat timeout × 2
- `AGENTPROVISION_TASK_ID` — same UUID as `ExecutionMetadata.run_id`
- `AGENTPROVISION_PARENT_WORKFLOW_ID`

CLI's `Context::new` already supports a token-store priority chain (PR #332). New tier inserted at the top: **env-token store** (read-only, no save/clear) — when both env vars are set, that's the active store. Falls through to keychain → file as today.

**Inbound subcommands** (Phase 4 implementation, not Phase 1–3):
- `agentprovision agent dispatch <id> --goal "…"` — delegate to a peer; returns child run_id, links to parent via `parent_task_id`
- `agentprovision blackboard write|read --pattern <name> --phase <name>` — A2A coordination
- `agentprovision memory recall <query>` / `record-observation` / `record-commitment`
- `agentprovision workflow run <template> --input @args.json` — child workflow trigger
- `agentprovision approval request "…"` — HITL gate; returns approval token

**Scope = `agent_policy`.** The minted JWT inherits the dispatching agent's `agent_policy` row — `allowed_tools`, `blocked_actions`, `rate_limits`. A leaf cannot escalate beyond what its dispatching agent could do. The API's existing `deps.require_agent_permission` enforces this; the new mint just stamps the right claims.

**Audit linkage.** Every inbound call writes an `execution_trace` row with `parent_task_id` set, so the trace tree reflects actual delegation. The `RLExperience` from the inbound work links back to the parent's `trajectory_id`.

**Closes the resilience loop.** When a leaf hits `QUOTA_EXHAUSTED` mid-task and policy says fall-back, the leaf itself can `agentprovision agent dispatch <peer>` to do the handoff — recursive resilient orchestration without per-runtime SDKs.

## Phased rollout

| Phase | Scope | Branch | Verification |
|-------|-------|--------|--------------|
| **1** | error contract enum + classifier (subsumes existing patterns) + redaction primitive + tests. Wired in at the seams; no behavioural change yet — every legacy classification site still works because the old pattern lookups become wrappers around the new classifier. | `feat/cli-orchestrator-phase-1-error-contract` | every Classification-table row has a named test; redaction property test passes; no public API surface change |
| **2** | `ProviderAdapter` trait + 6 concrete adapters + `FallbackPolicy` + `ResilientExecutor`. Existing `cli_session_manager.run_agent_session` is rewritten to call `ResilientExecutor.execute(req)`. | `feat/cli-orchestrator-phase-2-adapters` | per-adapter contract test, fallback-policy table test, Temporal-failure normalization test, no-fallback-on-auth test |
| **3** | `preflight()` per adapter + `ExecutionMetadata` table mirror to `RLExperience` + UI surfacing of `actionable_hint` in the chat routing footer. | `feat/cli-orchestrator-phase-3-preflight-metadata` | preflight tests, metadata emission tests, end-to-end test that triggers QUOTA_EXHAUSTED → fallback → success and asserts metadata reflects the chain |
| **4** | Agent-scoped JWT mint + env-token store in CLI + inbound subcommands (`agent dispatch`, `blackboard`, `memory`, `workflow run`, `approval request`). | `feat/cli-orchestrator-phase-4-control-plane` | leaf-from-Claude-Code calls `agentprovision memory recall` and the call appears in execution_trace with `parent_task_id` set |

Each phase is its own PR; each PR's verification gate must pass before the next branches off.

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

## Open questions for signoff

1. **Phase ordering.** Phase 1 lands the contract without changing behaviour. Phase 2 cuts over the chat hot path. Is "no behaviour change in Phase 1, full cutover in Phase 2" acceptable, or do we want a feature-flagged gradual cutover (`USE_RESILIENT_EXECUTOR` per-tenant)?
2. **Where the executor lives.** Proposal: `apps/api/app/services/cli_orchestrator/` (Python). Alternative: build it in Rust inside `agentprovision-core` and have Python call it via a thin gRPC. Python is faster to ship and matches existing code; Rust is more aligned with the long-game where the core crate becomes the orchestrator. Recommendation: **Python now, Rust port deferred to a separate plan after Phase 4 stabilises.**
3. **Status enum extensibility.** The 10 listed statuses cover everything the recon found. If a new provider class shows up (e.g. local-Ollama OOM), do we extend the enum or fold into UNKNOWN_FAILURE? Proposal: **extend** — UNKNOWN_FAILURE should stay rare so dashboards can flag it.
4. **Backwards compatibility.** `cli_platform_resolver.classify_error()` returns string labels (`"quota"` / `"auth"` / `"missing_credential"`). Phase 1 maps these onto Status; Phase 2 deletes the function. OK to delete in Phase 2 or keep as a thin alias indefinitely?

---

**Ready for signoff.** No code lands until you sign off on §3 (fallback policy), §5 (redaction surface), §8 (control-plane scope), and the four open questions above.
