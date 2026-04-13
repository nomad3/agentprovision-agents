# AgentProvision — Live Demo: Autonomous Incident Response
### Levi Strauss & Co. Management Briefing
**Date:** April 13, 2026  
**Audience:** Engineering Leadership, IT Operations, Digital Commerce  
**Duration:** 20 minutes (demo + Q&A)

---

## The Problem We're Solving Today

**It's 2 AM in San Francisco. Your EMEA storefronts are showing wrong prices.**

1,247 SKUs across Europe and Asia-Pacific are displaying stale pricing because a schema change in Informatica MDM silently dropped `currency_precision` records from the SAP S/4HANA → Hybris sync pipeline. The batch succeeded — but 27% of records were quietly rejected.

Your on-call SRE gets paged. They open a Slack war room. They pull in a data engineer, a middleware specialist, and a Hybris admin. Three hours later they have a remediation plan.

**What if that took 4 minutes instead?**

---

## What You're About to See

A single chat message triggers a **four-agent coalition** that autonomously:

1. **Triages** the incident — classifies severity, maps blast radius across SAP → MDM → Hybris
2. **Investigates** — pulls timeline, correlates events, identifies the schema change as root cause
3. **Analyzes** — validates with quantitative reasoning (1,247 SKUs, 340 NULL records, 27% rejection rate)
4. **Commands** — produces an actionable P1 remediation plan with validation steps and preventive measures

All four agents run in parallel pipelines on a **Shared Blackboard**. Each agent reads what the previous one wrote, builds on it, and passes a richer context forward. No copy-paste between Slack threads. No tribal knowledge required.

---

## The Live Demo

### Step 1 — Trigger the Coalition

In the AgentProvision chat interface, type:

```
@coalition investigate: pricing data is stale across EMEA and APAC regions —
SKU metadata pipeline failure from SAP S4 to Hybris via MDM sync is causing
wrong prices on the storefront
```

The platform responds immediately:
> "Multi-agent coalition assembled. 4 specialist agents deployed on incident_investigation pattern."

### Step 2 — Watch the Blackboard Fill

The Collaboration Panel (right sidebar) shows agents contributing in sequence:

```
[00:00] Coalition assembled — triage_agent, investigator, analyst, commander
[00:45] TRIAGE (Gemini) — P1 severity. Affected: EMEA, APAC storefronts.
        Root system: Informatica MDM outbound connector. Blast radius: 1,247 SKUs.
[01:30] INVESTIGATE (Gemini) — Timeline: schema change on 2026-04-12 17:32 UTC.
        currency_precision NOT NULL constraint added. SAP PI/PO mapping does not
        populate this field. Batch processor rejects records silently.
[02:15] ANALYZE (Gemini) — Confirmed: 340 NULL records (27%) block full batch of 1,247.
        Revenue impact: ~€2.3M/day in EMEA from incorrect pricing display.
        Cross-region: Hybris APAC endpoints not updated since 2026-04-12 17:35 UTC.
[03:50] COMMAND (Gemini) — Remediation plan delivered. Confidence: 0.95.
```

### Step 3 — The Output

The platform produces a structured P1 remediation plan:

---

**Incident ID:** LEVI-MDM-2026-04-13-PRC  
**Root Cause:** `currency_precision` field dropped in SAP PI/PO → Informatica MDM transformation due to undeclared `NOT NULL` schema change.

**Immediate Remediation (execute now):**
1. Update SAP PI/PO transformation mapping to extract `currency_precision` from IDoc/API
2. Emergency SQL patch: `UPDATE product_master SET currency_precision=2 WHERE currency_precision IS NULL AND currency_code IN ('EUR','GBP','HKD')` — unblocks pipeline in <2 hours without waiting for middleware deployment
3. Trigger manual "Full Refresh" for the 1,247 affected SKUs; monitor Hybris EMEA/APAC sync
4. Invalidate Hybris pricing cache once MDM confirms `SUCCESS (RECORDS UPDATED: 1247)`

**Validation:**
- Query `product_master`: zero NULL `currency_precision` values for affected SKUs
- Parse Informatica logs: no "Validation Failure" or "Record Dropped" events
- Auditor cross-check: SAP S/4HANA vs Hybris delta = 0% discrepancy

**Preventive Measures:**
- Anomaly detection: alert if MDM sync reports "No Change" while Sentinel sees >10 price changes in outbound queue
- Schema governance SOP: mandatory Mapping Impact Analysis before any `NOT NULL` addition
- Fail-soft config: Informatica to handle record-level rejections — 340 bad records should not block 907 good ones

---

**Total time from trigger to actionable plan: under 4 minutes.**  
**Traditional process: 2–4 hours of war room.**

---

## Why This Is Different From Existing Tools

| | Traditional Incident Response | Chatbot / Single LLM | AgentProvision Coalition |
|---|---|---|---|
| **Who investigates** | 3–5 humans in war room | One model, one context window | 4 specialized agents, shared memory |
| **Context handoff** | Copy-paste in Slack | Lost between prompts | Shared Blackboard — persistent, versioned |
| **Audit trail** | Slack history (fragile) | None | Full Temporal event log + blackboard entries |
| **Time to plan** | 2–4 hours | Hallucinated answer in 30s | Grounded 4-min investigation |
| **Learns from outcomes** | Post-mortem docs (rarely read) | None | RL experience logged, policy improves |
| **On-call burden** | High — pages humans at 2AM | Zero (but wrong) | Low — humans review plan, not build it |

---

## What This Means for Levi's Operations

**Immediate value:**
- MDM pipeline failures surface a remediation plan in <5 minutes, not 2–4 hours
- On-call engineer reviews and approves a plan instead of building one from scratch at 2 AM
- Every incident generates a structured post-mortem automatically (blackboard entries = audit log)

**Medium-term value:**
- The RL layer learns which remediation patterns work — the platform gets faster and more accurate over time
- Memory layer stores entity relationships (SAP system IDs, Hybris endpoint mappings, team contacts) so the next incident starts with pre-loaded context
- The coalition pattern is configurable — add a "compliance reviewer" agent for regulated markets, a "cost estimator" for rollback decisions

**The SRE team stops being a human API.**  
They set policy, review plans, and handle truly novel situations. The platform handles pattern-matched incidents autonomously.

---

## Architecture in 60 Seconds

```
User: "@coalition investigate: pricing pipeline failure..."
        |
        v
   Agent Router (zero LLM cost — pattern match)
        |
        v
   CoalitionWorkflow (Temporal — durable, crash-safe)
        |
   ┌────┴─────────────────────────────────┐
   |        Shared Blackboard (Postgres)  |
   |  ┌──────────┐  ┌──────────────────┐  |
   |  │ Triage   │→ │  Investigate     │→ |
   |  │ (Gemini) │  │  (Gemini)        │  |
   |  └──────────┘  └──────────────────┘  |
   |  ┌──────────┐  ┌──────────────────┐  |
   |  │ Analyze  │→ │  Command         │  |
   |  │ (Gemini) │  │  (Gemini)        │  |
   |  └──────────┘  └──────────────────┘  |
   └──────────────────────────────────────┘
        |
        v
   Final Report → Chat UI + SSE stream
   RL Experience logged → policy improves
   Memory activity logged → future context
```

- **No single point of failure** — Temporal retries any crashed activity automatically
- **No vendor lock-in** — agents route to Gemini, Claude, or Codex per RL recommendation
- **No context loss** — the Shared Blackboard persists across all agents, all phases
- **Full auditability** — every agent contribution is versioned, timestamped, and queryable

---

## What We're Asking For

**Phase 1 (now — 30 days):**  
Connect one real Levi's data source (e.g., MDM pipeline health endpoint or SAP alert feed) to the coalition trigger. Run shadow mode: coalition runs alongside existing war room, compare plans.

**Phase 2 (60 days):**  
On-call engineer receives coalition plan at page-time. Reviews and approves. Human still in loop for execution.

**Phase 3 (90 days):**  
For pre-approved remediation playbooks (e.g., cache invalidation, SQL hotfix for known patterns), coalition executes autonomously. Human approves via mobile push notification.

**What we need from Levi's:**
- Read access to one data source (MDM logs or SAP event stream)
- 2-hour session with an SRE to map entity vocabulary (system names, team contacts, runbook structure)
- A designated technical point of contact for the shadow-mode evaluation

---

## Frequently Asked Questions

**Q: What if the coalition gets it wrong?**  
A: The Commander phase outputs a plan, not an execution. A human approves before anything runs. Every recommendation includes a confidence score and the evidence it was derived from. The blackboard is fully auditable.

**Q: Where does our data go?**  
A: AgentProvision is deployable on-premise or in your VPC. All LLM calls can be routed through your Gemini enterprise license. No data leaves your network boundary.

**Q: What about the existing runbooks and SOPs?**  
A: The memory layer ingests existing documentation. Your runbooks become pre-loaded context that agents reference during investigation. They don't replace your SOPs — they execute them faster.

**Q: How does it know about SAP, Hybris, and Informatica?**  
A: The knowledge graph is seeded with your architecture (entities, relationships, ownership). The coalition agents query this graph during investigation. It's not generic LLM knowledge — it's your architecture, encoded.

**Q: What if Gemini is down?**  
A: The RL routing layer falls back to Claude or Codex. The coalition continues. Temporal guarantees at-least-once execution of every phase.

---

## One-Sentence Summary

**AgentProvision turns a 3-hour war room into a 4-minute autonomous investigation — every incident, every time, with full audit trail and no 2 AM pages.**

---

*Contact: Simon Aguilera — saguilera1608@gmail.com*  
*Platform: agentprovision.com*  
*Repository: github.com/nomad3/servicetsunami-agents*
