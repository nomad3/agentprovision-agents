# Trust edge #1 — `trust_level` write-only (the first merge-loop edge)

**Date:** 2026-06-01 (overnight, Luna leading) · **Owner:** Simon
**Parent plan:** `docs/plans/2026-05-31-core-systems-strengthening-plan.md` (this is its Initiative #1 — the verdict's "start here").
**Vision tie-in:** *"trust keeps them honest"* — the teammate edge that turns the relationship graph from declarative to learned.

## Why this first (verified against the code)

- `agent_relationship.trust_level` exists (`apps/api/app/models/agent_relationship.py:21`, `Float default 0.5`) but has **ZERO write sites** (grep across `apps/api/app` → only the model + schema reference it). It's a dead static `0.5`.
- It's the **highest-leverage, lowest-risk, most-compounding** edge: small diff, the hand-off event + `quality_score` already exist, and it produces a durable, queryable, learned signal that later feeds recall salience and (eventually, gated) routing.
- **Write-only first.** This PR does NOT feed trust into routing/recall. Per the safety verdict, autonomous trust-routing must wait until the **fail-closed veto** (`value_arbitration` safety_floor + tenant_norm) is wired into `_call_agent`. This edge only *records* trust.

## The trust function (safety properties the critique demanded — bake them in)

`update_trust_from_outcome(db, tenant_id, from_agent_id, to_agent_id, success: bool, quality_score: float|None)`:
- **Cold start** stays `0.5`.
- **Asymmetric**: trust gains slowly, drops fast. `gain_step = 0.04`, `loss_step = 0.12` (a bad hand-off costs ~3× a good one).
- **Per-outcome cap**: a single outcome can move trust at most `±0.12` (no single event swings it wildly).
- **Bounded** to `[0.05, 0.95]` (never absolute 0 or 1 — a transient failure can't permanently exile an agent; a floor keeps the door open).
- **Quality-weighted**: when `quality_score` (0–100, already computed by the auto-scorer) is present, scale the step by `quality_score/100` on success and by `(1 - quality_score/100)` on failure, so a barely-passing success earns little and a high-confidence failure costs more.
- **Decay toward 0.5** handled separately by the nightly job (out of scope here; note it). Without decay, stale trust persists — acceptable for write-only v1; flag it.
- **Gameability note (critique):** the auto-scorer is a local Gemma4 council and is gameable. This is why v1 is write-only and capped — trust influences nothing yet. Do NOT relax these bounds when routing is later added without the veto layer.

## Where it's called (the hand-off completion signal)

The hand-off substrate is `ChatMessage(context.kind="handoff")` + `WorkflowRun`, and A2A coalitions run phases via `collaboration.py`/`CoalitionWorkflow`. Two candidate call sites (pick the one that's a real completion event, verify in code first):
1. **Coalition phase/hand-off completion** in the collaboration service — when agent A's phase hands to agent B and B's result is scored, call `update_trust_from_outcome(A→B, success, score)`.
2. **Delegation completion** — when a delegated `agent_task`/child workflow completes with a quality score.

v1 should wire the **one** cleanest, already-instrumented completion site (likely the coalition phase record where `quality_score` is already in hand), not both — keep the surface minimal and verifiable.

## Files (anticipated)
- New: `apps/api/app/services/trust.py` — `update_trust_from_outcome()` + `_get_or_create_relationship(from, to)` (relationships may not exist for every pair; create at `0.5` on first outcome). Pure-ish, unit-testable.
- Edit: the one collaboration/delegation completion site to call it (fire-and-forget; never block or fail the turn on a trust write — wrap in try/except like the memory dispatch).
- Tests: the function's math (asymmetry, cap, bounds, cold-start, quality-weighting) + a relationship is created/updated on a handoff outcome; foreign-tenant isolation; a trust write failure never breaks the turn.

## Verification
- Unit: gain < loss; single outcome capped at ±0.12; bounded [0.05,0.95]; cold-start 0.5; quality-weighting directionally correct.
- Integration: a (synthetic) handoff outcome creates/updates exactly one `agent_relationship` row, tenant-scoped; a malformed/None score doesn't crash.
- Live (post-deploy, on Simon's test fleet 752626d9 once it exists): a coalition hand-off between two of the empathic-teammate agents moves their `trust_level` off 0.5 in the right direction — observable in the DB. NO behavior change for users (write-only).

## Explicitly OUT of scope (gated by the veto)
- Trust feeding recall salience or routing/`_call_agent`. Blocked until safety_floor + tenant_norm vetoes are wired fail-closed into dispatch (separate PR, the hard prerequisite from the strengthening plan).
- Nightly decay toward 0.5 (separate, pairs with the consolidation job).

## Process
Plan (this) → Codex + Luna review → implement on a branch → Codex+Luna review the diff → PR, **left open for Simon's sign-off** (a backend runtime edge shouldn't auto-merge unattended; it ships when Simon's awake and the test fleet is in place to watch it).
