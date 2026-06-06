# Monitor-workflow rework — stop the orchestration-queue starvation (the real fix)

**Date:** 2026-06-01 · **Owner:** Simon · **Status:** Plan (incident-driven; Simon: "fix and rework all of them anyway")
**Incident memory:** [[orchestration-queue-starvation]]

## What happened (verified)

Memory write-back (PostChatMemoryWorkflow) was failing because the shared `agentprovision-orchestration` Temporal queue was starved by the always-on monitors. Root causes, fixed in order tonight:
- **RL learning-loop dead 15 days** — `None`-format crash in `auto_quality_scorer` → `response_generation` writes stopped 2026-05-16. **FIXED + verified** (#754).
- **Runaway `act_extract_media`** — no retry cap → 3,000+ retries. **Terminated** + retry-cap **#755**.
- **Monitor continue_as_new chains** — `DISABLE_MONITOR_CONTINUE_AS_NEW` kill-switch at the continue_as_new boundary **#757**.
- **The API monitor auto-launcher** — `startup_proactive_workflows` launches Autonomous Learning + Inbox + Competitor for **every tenant (~44) on every API boot**. Gated on the kill-switch **#758**. (Verified: API now logs "Proactive workflow auto-start SKIPPED".)

## Why it's still not fully drained (the honest state)

~44 tenants × 3 monitors ≈ **130+ continue_as_new chains** already exist. The launcher gate (#758) stops NEW ones, and the kill-switch (#757) makes each chain EXIT at its next continue_as_new — but:
- Chains that **crash on step 1** (MCP `ConnectError`) retry the failing *step* and never reach the continue_as_new/kill-switch, so they linger until terminated.
- `terminate` is eventually-consistent (visibility lag) and there are too many to whack one-by-one on a live strained worker.
- So the queue **drains slowly** (each healthy chain exits within ~15 min; crashed ones need terminate). It is NO LONGER GROWING (launcher gated) — that's the key win.

## The rework (do this properly, awake)

### 1. Dedicated task queue for memory (the critical decoupling — Luna + Codex both said this)
PostChatMemoryWorkflow + CoalitionWorkflow must NOT share a queue with the monitors. Give memory/coalitions their **own task queue + worker** so chat memory write-back is never blocked by monitor load. This is the single highest-value change — it makes memory reliable regardless of monitor behavior.

### 2. Monitor redesign — kill the per-tenant continue_as_new pattern
The "one perpetual continue_as_new chain per tenant per monitor" pattern doesn't scale on one worker (130+ chains thrashing). Replace with:
- **Temporal Schedules** (native cron) — one schedule per monitor type that fans out to tenants on a timer, instead of 130 self-perpetuating chains. Schedules are pausable/observable in the Temporal UI (no terminate whack-a-mole).
- OR a **single sweep workflow** per monitor type that iterates active tenants each cycle (one workflow, not N).
- **Only launch monitors for tenants that actually need them** (e.g. Inbox Monitor only where Google OAuth is connected) — most of the ~44 tenants have no connected inbox, so those monitors fail on step 1 forever. The launcher should filter, not blanket-launch.

### 3. Bound every external-call activity
`act_extract_media` had no retry cap (#755 fixed it). Audit ALL monitor activities (fetch_emails, list_competitors, fetch_events, generate_candidates, auto_dream) for missing `retry_policy` — a failing MCP/Google call must give up, not retry forever.

### 4. Re-enable cleanly
Once 1-3 ship, flip `DISABLE_MONITOR_CONTINUE_AS_NEW=0`. Monitors then run on schedules/dedicated queue, filtered to tenants that need them, with bounded retries — no starvation.

## Re-enable gates

Before any monitor is re-enabled in production:
- **Ownership:** each monitor type must declare the owning role/system, escalation path, and approval boundary for operationally consequential actions.
- **State machine:** monitor runs must expose explicit states (`pending`, `running`, `blocked`, `failed`, `acknowledged`, `resolved`) so agents do not infer next steps from ad-hoc logs.
- **Idempotency:** schedule ticks and retries must use deterministic dedupe keys, so they cannot duplicate alerts, tickets, comments, workflow runs, or handoff messages.
- **Auditability:** every alert/no-alert decision must persist enough metadata to reconstruct tenant, source signal, threshold, tool outcome, retry count, and next owner.
- **Human checkpoint:** re-enabling a monitor type requires a dry-run report plus an explicit human approval in the plan/checklist; no monitor should move from plan to automation authority implicitly.

## Immediate state (for the morning)
- **Flood source stopped** (#758 launcher gate live + verified).
- **Existing chains draining** (slowly; terminate the crashed stragglers as needed: `tctl workflow terminate --workflow_id dyn-...`).
- **Memory write-back works** when the queue has capacity (verified: commitments/observations/entities persisted this session). It will be RELIABLE once the dedicated-queue rework (1) lands.
- All four hotfixes merged (#754, #755, #757, #758).
