# Core-systems reliability batch — E2E-caught regressions + Temporal queue-starvation fixes

**Date:** 2026-06-01 · **Status:** Backfilled (shipped)
**PRs:** #754, #755, #757, #758, #761
**Files:** `apps/api/app/services/auto_quality_scorer.py`, `apps/api/app/services/local_inference.py`, `apps/api/app/memory/classifiers/commitment.py`, `apps/api/app/workflows/learn_from_media_workflow.py`, `apps/api/app/workflows/dynamic_executor.py`, `apps/api/app/workflows/activities/dynamic_step.py`, `apps/api/app/main.py`, `apps/code-worker/workflows.py`, `docker-compose.yml`, `helm/values/agentprovision-{api,orchestration-worker}.yaml`

## Problem / context

The empathic-fleet **E2E test** (2026-06-01) found the teammate *behavior* worked — recall fired, the agent flagged risk honestly — but the *engine plumbing* silently dropped data: memory **recall worked while write-back was empty**, and the RL learning loop had been dark for 15 days. Tracing it bottomed out in two layers: (a) backend data-capture regressions, and (b) a `agentprovision-orchestration` Temporal worker that was **starved** — one worker serves every tenant's always-on monitors *plus* every chat turn's `PostChatMemoryWorkflow`, and several runaway/poison-pill patterns were saturating it. This is the retrospective of what actually shipped to fix it; the forward-looking design lives in the sibling plan doc.

## What shipped

**#754 — repair 3 engine data-capture regressions** (API-only deploy, commit `ddb0f9ed`):
1. **RL bridge dead since 2026-05-16.** `cost_usd`/tokens arrive `None` on gemini_cli/codex turns; `f"{cost_usd:.4f}"` raised `NoneType.__format__` *inside* the RL-log try-block, so the `auto_quality_consensus` event still emitted (scoring looked healthy) while `rl_experiences.response_generation` stopped writing. Fix in `_score_and_log`: a type-safe `_num(v, cast, default)` coercion up front (Codex review caught that `x or 0` leaves a truthy string like `"1.23"` intact and would still throw).
2. **Memory write-back lost under load.** `extract_knowledge_with_prompt_sync` returned empty because `generate_sync` holds the process-wide `_ollama_sync_lock` for the whole call. Fix: a single budget-bounded retry gated on `is_available_sync()` (a cheap `GET /api/tags`) — Codex's BLOCKER rejected the naive 3×90s retry as blowing the 60s activity timeout and hogging the lock; the gate distinguishes a real Ollama outage from transient contention.
3. **Commitment capture dropped.** Same root cause in `classify_commitment`. Same retry, plus a deterministic rule-based fallback (low-confidence 0.35, user-confirmable) so an obvious self-commitment is recorded even if the LLM keeps returning empty. Also corrected landing copy that claimed RL feedback during the 15-day outage.

**#755 — cap `act_extract_media` retries** (commit `44aac467`): the external-MCP extraction activity in `learn_from_media_workflow.py` had **no `retry_policy`**, so Temporal's default unlimited retry (`maximum_attempts=0`) applied. A persistent MCP `ConnectError` hit **attempt 3053**, saturating the orchestration worker and pushing `PostChatMemoryWorkflow` close-times to 5–20h. Fix: bounded `RetryPolicy(maximum_attempts=5, 2s→30s backoff)` so a failing call falls through to the existing quarantine path. The runaway (`luna-learn-752626d9-…`) was operator-terminated.

**#757 + #758 — kill-switch + gate for self-perpetuating monitor loops** (commits `cf4b6040`, `147bd3e7`): inbox/competitor/autonomous-learning monitors run as `continue_as_new` `DynamicWorkflowExecutor` chains; their steps are baked into each running workflow's `input` (continue_as_new carries state, does **not** re-read the DB), so pausing DB rows is a no-op and `terminate` is whack-a-mole. **#757** added activity `monitors_continue_as_new_disabled()` (env reads are non-deterministic in workflow code) checked *in* the `continue_as_new` branch of `dynamic_executor.py` — when `DISABLE_MONITOR_CONTINUE_AS_NEW=1`, each chain exits as it wakes. But fresh instances crash on step 1 (MCP error) and retry *before* reaching that boundary, and the API relaunches a full set every boot — so **#758** gated `startup_proactive_workflows` (`main.py`) on the same flag (the actual flood source — `@app.on_event('startup')` launching monitors for ~44 tenants on every API boot). Flag defaults **ON (=1)** in compose + helm on both the worker (#757) and the API (#758); flip to 0 to re-enable.

**#761 — ProviderCouncil poison-pill** (commit `bf7a32cf`): `auto_quality_scorer._maybe_trigger_provider_council` starts `ProviderReviewWorkflow` with a dict omitting `providers`, but `ProviderCouncilInput` declared `providers: List[str]` as **required**. Temporal decodes the start payload via `ProviderCouncilInput(**matched_keys)`, so the missing field raised `TypeError → Failed decoding arguments`, and a **workflow-task decode failure retries forever** — the same queue-loading starvation pattern. Fix: default every field (`providers` via `field(default_factory=list)`) so a version-skewed dispatch can never fail to decode; the review activities pick the provider set themselves, so the field is advisory.

## Outcome

RL `response_generation` experiences write again; memory/commitment extraction survives Ollama contention; the orchestration queue drains (runaway capped, monitor auto-launch + perpetuation halted, council poison-pill removed). These are **hotfixes that stop the bleeding** — every PR body names the same owed structural follow-up: a **dedicated Temporal task queue for `PostChatMemory`** (decoupled from the monitor-heavy orchestration queue) **+ worker scaling**, and a **monitor redesign** off the per-tenant `continue_as_new` pattern. Memory write-back stays best-effort/laggy under load until that lands. Recovery for a thrashing worker: `docker compose restart orchestration-worker` (stateless, safe).

## Related

- `docs/plans/2026-05-31-core-systems-strengthening-plan.md` — the forward design (memory + emotion + teamwork merge) this batch complements; this doc is the reliability retrospective beneath it.
- Memory `orchestration_queue_starvation` — the diagnosis chain (RL outage → 3053-retry runaway → worker overload) and the owed dedicated-queue fix.
- Memory `orchestration_cascade_root_cause` — prior (2026-05-10/11) `InFailedSqlTransaction` cascade on the same worker from `PermissionError`-blocked workflow steps; same monitors, same queue.
- Memory `empathic_teammate_fleet` — the 6-agent test fleet (tenant 752626d9) whose E2E run surfaced these regressions.
