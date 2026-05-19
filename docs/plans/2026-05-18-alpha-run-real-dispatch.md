# `alpha run` — replace Phase-1 synthetic stub with real Temporal dispatch

**Date:** 2026-05-18
**Status:** **Phase 2 shipped (PR #573).** Single-provider real dispatch via
`--fanout <cli>` is LIVE under `USE_REAL_FANOUT_WORKFLOW=true`
(set in `apps/api/.env`). Multi-provider `--fanout a,b,c` returns the
raw child outputs as a list; `--merge council/all` adjudication is
queued. Plain `alpha run "..."` and `alpha run --providers a,b,c`
still hit the Phase-1 synthetic stub — tracked as Phase 3 follow-ups
in [`2026-05-18-alpha-cli-delegation-pattern.md`](2026-05-18-alpha-cli-delegation-pattern.md).
**Branch (merged):** `feat/alpha-run-real-dispatch`
**Predecessor:** `docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`
**Successor:** `docs/plans/2026-05-18-alpha-cli-delegation-pattern.md`

## Problem

`apps/api/app/api/v1/tasks_fanout.py` ships a synthetic in-memory stub for
`POST /api/v1/tasks-fanout/run`. When the operator runs:

```
alpha run "research X" --background
```

The CLI gets `{task_id, status:queued}` immediately (good — no Cloudflare
524) but `alpha watch <id>` eventually surfaces:

> "This is a Phase-1-prototype synthetic response."

instead of real LLM output. The stub locations are
`tasks_fanout.py:778, 786, 1053`.

The previous PR (#177 Phase-1) already wired `FanoutChatCliWorkflow` for the
`--fanout` (multi-provider parallel) path under the `USE_REAL_FANOUT_WORKFLOW`
flag. The remaining synthetic responses cover:

  1. Single-provider runs (no `--fanout`, no `--providers`)
  2. Fallback-chain runs (`--providers a,b,c`)

These are explicitly NOT routed to Temporal today, even when the flag is on
— see `test_real_fanout_flag_on_without_fanout_still_uses_stub`.

## Phase-2 scope (per the user brief)

Ship:

  - Single-provider real dispatch — the 90% case.
  - `--background` returning immediately with a task_id (already structurally
    correct on the API; verified non-blocking).
  - `alpha watch` polling the real Temporal workflow status.

Defer to Phase-3 (separate PR):

  - `--fanout` aggregation polish (`council` / `all` merge text)
  - `--events <path>` JSONL stream
  - `--timeout N` plumbed through to `execution_timeout` (today fixed at 180m)
  - `--agent <UUID>` propagation to `ChatCliInput` (today the worker logs a
    warning and runs as the tenant default; full propagation needs a new
    `agent_id` field on `ChatCliInput` — separate worker-side PR)

## Strategy: reuse `FanoutChatCliWorkflow` for N=1

The cheapest path. `FanoutChatCliWorkflow` already spawns N
`ChatCliWorkflow` children via `execute_child_workflow` and aggregates with
the `merge` mode. For our three CLI cases we map:

  | CLI flag set | `providers` arg to workflow | `merge` |
  |---|---|---|
  | (none) — single provider, default | `[default_provider]` (N=1) | `first-wins` |
  | `--providers a,b,c` (fallback chain) | `body.providers` (N=k) | `first-wins` |
  | `--fanout a,b,c [--merge M]` (parallel) | `body.fanout` (N=k) | `body.merge` |

`first-wins` is the closest semantic to a quota-fallback chain we can get
without modifying the workflow: the first child to complete wins, others
get cancelled. True quota-aware sequential fallback (try claude → 429 → try
codex) is what `agent_router._resolve_cli_chain` (PR #245) provides for the
synchronous chat path; replicating that exactly in the durable async path
is a separate piece of work and is called out in the design doc Phase-3.
For now, `first-wins` covers the use case the user actually has (research
delegation: "any of these LLMs is fine, give me whichever finishes first").

Default single-provider: `claude_code`. The design doc open question #1 says
auto-detect from tenant via `default_cli_platform` in `tenant_features` is
the long-term home; for this PR we hard-code the safe default and leave a
TODO for the tenant lookup.

## Files touched

  - `apps/api/app/api/v1/tasks_fanout.py` — extend real-dispatch branch to
    cover the three cases; replace synthetic stubs at lines 778, 786, 1053.
  - `apps/api/tests/test_tasks_fanout.py` — new cases for single-provider
    and `--providers` chain real-dispatch.

## Out of scope (won't touch)

  - `apps/code-worker/workflows.py` — `FanoutChatCliWorkflow` already
    handles the new N=1 and N=k+first-wins shapes.
  - Helm values / `apps/api/.env` — flag flip is operational, not in PR.
  - Frontend CLI (`alpha`) — already sends the right shape.

## Verification

  - `pytest apps/api/tests/test_tasks_fanout.py -v`
  - No docker / k8s / helm changes.

## Open follow-ups documented in the PR

  - True quota-fallback semantics for `--providers` (currently first-wins,
    not quota-aware) — `--providers` is also still on the synthetic stub
    today, so wiring it through to real dispatch is the prerequisite.
  - `--timeout` propagation (today backend execution_timeout fixed at 180m;
    CLI honours the foreground tail deadline only).
  - `agent_id` propagation through `ChatCliInput` (worker currently warns
    and runs as the tenant default).
  - Default provider lookup from `tenant_features.default_cli_platform`
    (today hard-coded to `claude_code` for the safe path).
  - `--merge council` LLM adjudication for `--fanout` N>1 (today returns
    the raw list).
  - Naked `alpha run "..."` (no `--fanout`, no `--providers`) still hits
    the Phase-1 stub.

All seven items rolled forward into
[`2026-05-18-alpha-cli-delegation-pattern.md`](2026-05-18-alpha-cli-delegation-pattern.md)
Phase 3.
