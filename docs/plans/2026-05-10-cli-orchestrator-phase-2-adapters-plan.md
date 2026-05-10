# Phase 2 — ProviderAdapter + FallbackPolicy + ResilientExecutor (retrospective plan)

**Status:** ✅ Merged via PR #339 (commit `c5d9d7af`) on 2026-05-10
**Branch:** `feat/cli-orchestrator-phase-2-adapters` (deleted post-merge)
**The structural cutover** — first phase that changes chat hot-path behaviour (gated by `tenant_features.use_resilient_executor`, default off)

> Retrospective. Planning-time Plan-agent output (sub-agent `ae51c476`) is consolidated below.

## Goal

Land the `ProviderAdapter` Protocol + 6 concrete adapters (Claude Code / Codex / Gemini CLI / Copilot CLI / shell / Temporal-activity api-side) + `FallbackPolicy` pure-function decision table + `ResilientExecutor` chain walker behind a per-tenant feature flag, with shadow-mode parity validation. Replace `agent_router`'s ad-hoc chain-walk loop with a single typed entry point.

## The 6 self-review refinements that landed in the design itself

The Plan-agent's self-review caught 6 issues that required substantive design adjustments. **All folded into the implementation:**

### R1 — NEEDS_AUTH UX regression → §3.2 amendment to design doc

A strict NEEDS_AUTH-stops policy regresses free-tier UX. Today's `cli_session_manager.run_agent_session` substitutes local Gemma when `subscription_missing` (line 720); under §3 strict, free-tier tenants with no CLI creds would get an `actionable_hint` and **no reply**.

Resolution: NEEDS_AUTH stops the chain UNLESS the next platform is `opencode` (the local floor), in which case fall through AND surface the actionable_hint as a non-blocking annotation on the eventual successful `ExecutionResult`. Captured as **§3.2** in the design doc, riding alongside this PR.

### R2 — Bounded-recursion gate is dormant in Phase 2

The `parent_chain` populated from `dispatch_agent` MCP tool is Phase 4 work. Phase 2's gate is defence-in-depth (synthetic `parent_chain=(uuid1, uuid2, uuid3)` test inputs fire the gate, but no caller populates it in production). This is fine — the gate activates when Phase 4 lands.

### R3 — Shadow mode 2x cost mitigation

Real shadow dispatch doubles Temporal workflow + CLI subprocess + LLM cost during validation. Resolution: migration 121 adds a **second column** `shadow_mode_real_dispatch BOOLEAN NOT NULL DEFAULT FALSE`. Synthetic-stub default; internal tenants flip on real dispatch for the 48h validation window only.

### R4 — 1% disagreement isn't actually 1%

The intentional UX shift (NEEDS_AUTH stops vs. legacy silent fallback) WILL show up as disagreement and would paralyse the rollout. Resolution: `disagreement_kind="expected_behaviour_change"` excluded from the 99% gate denominator. Fired when legacy fell-through on auth/missing_credential AND new path's status ∈ {NEEDS_AUTH, WORKSPACE_UNTRUSTED, API_DISABLED}.

### R5 — Phase 1.6 worker refactor as soft prerequisite

Worker-side adapters need `_run_cli_with_heartbeat` + `_execute_*_chat` from a 2,318-line `workflows.py`. Hoisting them to clean public modules first eliminates a real Phase 2 fragility. Phase 1.6 PR #338 shipped first; Phase 2 PR #339 was rebased on top.

### R6 — `routing_summary` shape parity

The legacy chat UI footer reads specific keys from `routing_summary` (`served_by`, `requested`, `chain_length`, `fallback_reason`, `error_state`, `last_attempted`). `ExecutionResult.to_metadata_dict()` must reproduce the exact same keys with the exact same shapes — otherwise the UI footer silently degrades on flag-on. Pinned by explicit assertion in `test_executor_integration.py`.

## Architectural decisions

### Wrapping boundary — option **(A) ResilientExecutor REPLACES agent_router's chain loop**

agent_router lines 938-1068 ARE a primitive resilient executor. Option (B) "executor slots inside per-platform try" forces the router to re-implement chain advancement, retry decisions, cooldown marks scattered across two files — exactly the bug Phase 2 set out to fix.

Concrete cutover: at flag-ON, `agent_router._resilient_chain_walk` builds `ExecutionRequest`, calls `executor.execute(req)` once, reads `result.to_metadata_dict()`. The legacy block stays as `_legacy_chain_walk` for shadow-mode comparison and rollback (deleted in a future cleanup once flag is at 100% for 14 days).

### Adapter location — split by runtime, Protocol shared

- **`ProviderAdapter` Protocol + dataclasses** in `packages/cli_orchestrator/adapters/base.py` — both runtimes import this
- **`TemporalActivityAdapter` (api-side)** in `packages/cli_orchestrator/adapters/temporal_activity.py` — single class, parameterised by platform string, dispatches via `client.execute_workflow("ChatCliWorkflow", ...)`
- **6 worker-side concrete adapters** in `apps/code-worker/cli_orchestrator_adapters/` — subclass the Protocol and call into the Phase-1.6 public surface (`cli_executors.<platform>.execute_<platform>_chat`); top-level imports stay pure (no `from workflows import` at module load)

### `ResilientExecutor` is sync at its public boundary

The chat hot path is sync SQLAlchemy. The executor wraps `await adapter.run(req)` in the same `asyncio.run`/threadpool dance the existing `cli_session_manager._run_workflow` uses — we reuse that loop, don't add a second one.

## File tree

```
packages/cli_orchestrator/
├── adapters/
│   ├── __init__.py                # exports Protocol + dataclasses
│   ├── base.py                    # ExecutionRequest, ExecutionResult, PreflightResult, ProviderAdapter Protocol
│   └── temporal_activity.py       # TemporalActivityAdapter
├── policy.py                      # FallbackDecision, MAX_FALLBACK_DEPTH=3, decide() pure fn
├── executor.py                    # ResilientExecutor.execute(req) → ExecutionResult
└── shadow.py                      # compute_legacy_outcome, run_shadow_comparison

apps/api/app/services/cli_orchestrator_shadow.py    # read_flags + maybe_run_shadow + _ReplayAdapter

apps/code-worker/cli_orchestrator_adapters/
├── __init__.py
├── _common.py                     # binary_on_path memoisation, map_chat_cli_result_to_execution_result
├── claude_code.py
├── codex.py
├── gemini_cli.py
├── copilot_cli.py
├── opencode.py
└── shell.py                       # generic _run_cli_with_heartbeat passthrough

apps/api/migrations/121_tenant_features_resilient_executor.{sql,down.sql}

apps/api/tests/cli_orchestrator/
├── test_provider_adapter_contract.py    # 5 cases (api-side)
├── test_fallback_policy_table.py        # 23 cases — every (Status, attempt) row
├── test_temporal_failure_normalization.py  # CancelledError / ApplicationError → WORKFLOW_FAILED
├── test_no_fallback_on_auth.py          # 9 cases — NEEDS_AUTH stops + §3.2 fallthrough
├── test_recursion_gate.py               # 3 cases — depth 3, cycle, depth 2 pass
├── test_shadow_mode_agreement.py        # 10 cases — agree/disagree/expected_behaviour_change/error
├── test_shadow_wiring.py                # 7 cases — read_flags + maybe_run_shadow plumbing
└── test_executor_integration.py         # 4 cases — full chat hot path with flag ON

apps/code-worker/tests/test_provider_adapter_contract.py  # 20 cases (worker-side)
```

## Issues caught in layered review

| Layer | Catch |
|---|---|
| Plan-agent self-review | The 6 R-items above (NEEDS_AUTH UX regression / inert recursion gate / 2x shadow cost / disagreement-kind exclusion / Phase 1.6 prerequisite / routing_summary parity) |
| Implementation self-review | `read_flags` MagicMock isinstance defense (a brittle test pattern surfaced during integration testing — `db_mock = MagicMock` returned truthy MagicMocks for `.first()`, breaking the flag read; fixed via `isinstance(row, TenantFeatures)` guard) |
| Independent review | **C-1** `routing_summary.fallback_reason` legacy-enum mismatch. Stamping `result.status.value` (e.g. `"quota_exhausted"`) directly into `routing_summary.fallback_reason` would make the React footer's `_FALLBACK_REASON_LABELS[reason]` lookup miss → every flag-on failure footer renders as "internal error", and successful quota fallbacks lose their fallback pill (`fallbackFired = !!summary.fallback_reason` becomes False). Fix: added `ExecutionResult.fallback_trigger_status: Optional[Status]` field; executor tracks `first_failed_status` through chain walk; new `_legacy_reason_for_status(status) → Optional[str]` mapper translates Status → legacy enum; `_resilient_chain_walk` uses the mapper on both branches |
| Final pass | "Ready to merge." Bare `forbidden` contract pinned with one parametrize case before merge; 1187 / 1187 tests green |

## Lessons

1. **Plan-agent self-review can catch design-doc bugs.** R1 (NEEDS_AUTH UX regression) was a substantive amendment to the design doc itself, not just the plan. The Plan-agent doing recon against the actual codebase found a UX path the design hadn't accounted for.
2. **Independent review catches cross-system contract violations.** C-1 was invisible to the implementation agent's structured 10-point self-review — it took an outside frame holding both the Python `to_metadata_dict()` AND the React `_FALLBACK_REASON_LABELS` enum to spot the mismatch.
3. **Feature flags + shadow mode + 99% agreement gate make scary cutovers boring.** The auth/setup/trust → stop-with-actionable-hint behaviour change is genuinely user-visible, but rolling it out per-tenant with a real-dispatch shadow window meant we found C-1 before any tenant flipped the flag.
