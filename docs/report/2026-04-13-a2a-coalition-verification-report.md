# A2A Coalition Workflow — End-to-End Verification Report

**Date:** 2026-04-13  
**Author:** Simon Aguilera  
**Status:** Verified ✓  
**PR:** [#140 fix/coalition-a2a-sync-activity](https://github.com/nomad3/servicetsunami-agents/pull/140)

---

## 1. Objective

Verify that the Agent-to-Agent (A2A) CoalitionWorkflow runs all four phases of an incident investigation (triage → investigate → analyze → command) end-to-end without Temporal timeouts, dropped activities, or silent failures.

---

## 2. Root Causes Identified and Fixed

Two independent defects were blocking end-to-end execution.

### 2.1 WORKFLOW_TASK_TIMED_OUT — Event Loop Blocking

**Symptom:** Every `ChatCliWorkflow` child died with `WORKFLOW_TASK_TIMED_OUT` before Gemini CLI could respond. No phase ever completed.

**Root cause:**  
`execute_chat_cli` was declared `async def`. Inside it, `_execute_gemini_chat` used a `subprocess.Popen` poll loop with `time.sleep(60)` to wait for the CLI. Because this ran on the asyncio event loop, the 60-second sleep starved workflow-decision tasks (which have a 10 s timeout), causing every child workflow to time out.

**Fix (`apps/code-worker/workflows.py`):**
- Changed `async def execute_chat_cli` → `def execute_chat_cli` (sync)
- Replaced the Popen poll loop + `time.sleep(60)` with `subprocess.run(..., timeout=1500)`
- Added a background daemon thread calling `activity.heartbeat()` every 60 s, keeping Temporal's 5-minute heartbeat timeout satisfied without touching the event loop

**Fix (`apps/code-worker/worker.py`):**
- Added `from concurrent.futures import ThreadPoolExecutor`
- Added `activity_executor=ThreadPoolExecutor(max_workers=10)` to `Worker(...)` — required by Temporal SDK when any registered activity is a sync function

### 2.2 Pattern Inference Miss → Schema Validation Error

**Symptom:** For MDM/pipeline incident tasks, `create_session` raised:  
`Pattern 'propose_critique_revise' requires role assignments for: ['verifier']`

**Root cause (part 1):** `_infer_pattern` lacked keywords for MDM/pipeline failures. A task containing "pricing data stale", "pipeline failure", "MDM sync" fell through to the default `propose_critique_revise` pattern instead of `incident_investigation`.

**Root cause (part 2):** `_required_roles_for_pattern("propose_critique_revise")` returned `["planner", "critic"]` but the collaboration schema's "verify" phase requires a `verifier` role — causing validation failure on session creation.

**Fix (`apps/api/app/workflows/activities/coalition_activities.py`):**
```python
# Before
if any(k in task_lower for k in ["incident", "investigate", "outage", "degraded", "crash", "alert"]):

# After — added failure/stale/pipeline/mdm/master data/sync
if any(k in task_lower for k in [
    "incident", "investigate", "outage", "degraded", "crash", "alert",
    "failure", "stale", "pipeline", "mdm", "master data", "sync",
]):
    return "incident_investigation"

# Before
"propose_critique_revise": ["planner", "critic"],

# After — verifier added to satisfy schema validation
"propose_critique_revise": ["planner", "critic", "verifier"],
"research_synthesize": ["researcher", "synthesizer", "verifier"],
```

---

## 3. Verification Run

**Trigger:** Chat message via API  
```
@coalition investigate: pricing data is stale across EMEA and APAC regions —
SKU metadata pipeline failure from SAP S4 to Hybris via MDM sync is causing
wrong prices on the storefront
```

**Coalition ID:** `coalition-914583fb-2ac5-48f9-a617-ad6f40f795a6-b1e81a92`  
**Collaboration ID:** `9dcd0902-c67c-42c9-8319-761cedcefbf2`  
**Pattern resolved:** `incident_investigation`  
**Roles:** `triage_agent`, `investigator`, `analyst`, `commander`

### Phase Execution Log

| Phase | Child Workflow | Status | Events | Exit |
|-------|---------------|--------|--------|------|
| triage (step-0) | `...9dcd0902...-step-0` | COMPLETED | 11 | 0 |
| investigate (step-1) | `...9dcd0902...-step-1` | COMPLETED | 11 | 0 |
| analyze (step-2) | `...9dcd0902...-step-2` | COMPLETED | 11 | 0 |
| command (step-3) | `...9dcd0902...-step-3` | COMPLETED | 11 | 0 |

**Parent workflow:** COMPLETED — 110 events, no WORKFLOW_TASK_TIMED_OUT

### Database Outcome

```
status:            completed
rounds_completed:  1
consensus_reached: yes
confidence:        0.95
```

**Commander output excerpt:**

> **Incident Remediation Plan: EMEA/APAC Pricing Staleness (P1)**
>
> **Incident ID:** LEVI-MDM-2026-04-13-PRC  
> **Confidence Score:** 0.95 (Root Cause Confirmed)
>
> **Root Cause:** `currency_precision` field dropped during SAP PI/PO → Informatica MDM transformation. A schema change adding a `NOT NULL` constraint to `product_master` was not preceded by a mapping impact analysis — causing batch-level rejection of 1,247 SKUs (340 NULL records blocking the full batch).
>
> **Immediate Steps:**
> 1. Update SAP PI/PO transformation to correctly extract `currency_precision` from IDoc/API
> 2. Emergency SQL patch: default `currency_precision=2` for EUR/GBP/HKD to unblock pipeline within <2 hours
> 3. Force batch resync for 1,247 affected SKUs; monitor Hybris EMEA/APAC endpoints
> 4. Cache invalidation on Hybris storefronts once sync confirms `SUCCESS (RECORDS UPDATED: 1247)`
>
> **Preventive Measures:**
> - Anomaly detection: alert if SAP-to-MDM sync reports "No Change" when Sentinel sees >10 price changes
> - Schema governance SOP: require Mapping Impact Analysis before any `NOT NULL` constraint addition
> - Fail-soft pipeline: configure Informatica to handle record-level rejections, not batch-level blockers

---

## 4. Temporal Event Trace

```
Parent (110 events):
  [1]  WORKFLOW_EXECUTION_STARTED
  [5]  ACTIVITY_TASK_SCHEDULED  → select_coalition_template
  [7]  ACTIVITY_TASK_COMPLETED
  [11] ACTIVITY_TASK_SCHEDULED  → initialize_collaboration
  [13] ACTIVITY_TASK_COMPLETED
  [17] ACTIVITY_TASK_SCHEDULED  → prepare_collaboration_step (triage)
  [19] ACTIVITY_TASK_COMPLETED
  [26] START_CHILD_WORKFLOW_EXECUTION_INITIATED → step-0 (triage)
  [27] CHILD_WORKFLOW_EXECUTION_STARTED
       ... (step-0 Gemini CLI runs ~60s, heartbeat thread keeps activity alive)
  [32] CHILD_WORKFLOW_EXECUTION_COMPLETED
  [36] ACTIVITY_TASK_SCHEDULED  → record_collaboration_step
  [38] ACTIVITY_TASK_COMPLETED
       ... (steps 1, 2, 3 follow same pattern)
  [109] ACTIVITY_TASK_COMPLETED → finalize_collaboration
  [110] WORKFLOW_EXECUTION_COMPLETED
```

Child workflows each follow:
```
[1]  WORKFLOW_EXECUTION_STARTED
[5]  ACTIVITY_TASK_SCHEDULED  → execute_chat_cli (sync, ThreadPoolExecutor)
[6]  ACTIVITY_TASK_STARTED
     [heartbeat daemon: fires every 60s]
[7]  ACTIVITY_TASK_COMPLETED
[10] WORKFLOW_EXECUTION_COMPLETED  (via return value)
[11] WORKFLOW_EXECUTION_COMPLETED
```

---

## 5. Files Changed in PR #140

| File | Change |
|------|--------|
| `apps/code-worker/workflows.py` | `async def` → `def`, `subprocess.run` + heartbeat thread |
| `apps/code-worker/worker.py` | `ThreadPoolExecutor(max_workers=10)` added to `Worker()` |
| `apps/api/app/workflows/activities/coalition_activities.py` | Pattern keywords + verifier role |

---

## 6. Deployment Note

The fix was hot-patched to running containers via `docker cp` pending CI merge. After PR #140 is merged to `main`, the self-hosted runner will rebuild and redeploy the `code-worker` and `api` images automatically via `.github/workflows/local-deploy.yaml`.

---

## 7. Status

| Item | Status |
|------|--------|
| All 4 coalition phases complete E2E | ✓ Verified |
| No WORKFLOW_TASK_TIMED_OUT | ✓ Verified |
| Pattern inference: MDM → incident_investigation | ✓ Verified |
| DB outcome recorded with consensus | ✓ Verified |
| PR #140 open for review | ✓ Open |
| Hot-patch applied to running containers | ✓ Applied |
