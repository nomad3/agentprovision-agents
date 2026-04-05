# Autonomous Learning Phase 2+ — Remaining Gaps and Self-Simulation Design

**Date**: 2026-03-25
**Status**: Design
**Extends**: `2026-03-25-autonomous-learning-pipeline-design.md`
**Depends on**: Gap 04 heartbeat, Gap 05 safety/trust, Gap 01 world model, Gap 02 goals, Gap 03 planning, Gap 06 collaboration

---

## 1. Purpose

The current autonomous learning design covers the first real closed loop:

1. collect existing RL experience
2. generate candidates
3. evaluate offline
4. run controlled split rollouts
5. promote or reject
6. report to the operator

That is necessary, but it is still reactive. It can only learn from work the
platform has already done.

The next step is an unsupervised learning extension where the platform can:

1. generate synthetic customers, operators, and businesses
2. exercise the platform as those users would
3. discover missing capabilities and failure modes before real users hit them
4. produce structured improvement proposals
5. feed validated findings back into the autonomous learning pipeline

This document defines the remaining gaps between the current heartbeat and that
larger self-simulation system.

---

## 2. Current Baseline

After PR #50, the platform has:

- nightly autonomous learning heartbeat
- candidate generation from existing RL patterns
- offline evaluation gate
- controlled rollout machinery
- promotion/rejection rules
- learning dashboards
- safety/trust governance around execution

What it does **not** yet have:

- synthetic persona generation
- industry-specific scenario libraries
- simulation orchestration
- tool/environment sandboxes for realistic but safe self-play
- synthetic quality judges for scenario success
- systematic gap extraction from simulated failures
- autonomous code/config change planning from simulation evidence

---

## 3. Remaining Gaps

### 3.1 Gap A — Synthetic Demand Generation

The system needs a way to create realistic demand when real traffic is sparse.

Missing components:

- persona templates by domain
- business-state generators
- inbox/task/event generators
- goal and commitment seeds per synthetic tenant
- conversation openers that resemble real user intent

Without this, the platform only learns from historical production traces.

### 3.2 Gap B — Scenario World Construction

A persona alone is not enough. The system also needs a believable operating
context to interact with.

Missing components:

- simulated company profiles
- simulated CRM pipeline state
- simulated calendars, inboxes, tasks, and entities
- domain-specific world-state assertions
- domain-specific causal patterns

Without this, scenario quality will be shallow and repetitive.

### 3.3 Gap C — Safe Self-Play Execution

The system needs an execution mode where it can use the real runtime stack
without damaging real production state.

Missing components:

- simulation tenants with strict isolation
- mock or sandboxed MCP connectors
- replayable inbox/calendar/mail states
- write redirection for outbound side effects
- deterministic scenario resets

Without this, simulated runs either become fake or become dangerous.

### 3.4 Gap D — Simulation Evaluation

The current evaluator scores real outputs. Simulation needs richer judgment.

Missing components:

- task-specific success criteria per scenario
- rubric evaluation against expected outcomes
- safety/compliance scoring in simulated flows
- state-change verification against expected world model
- plan-quality verification for long-horizon tasks

Without this, simulated runs produce activity but not trustworthy learning.

### 3.5 Gap E — Gap Extraction and Prioritization

Simulations will produce failures, but the system needs to convert those
failures into actionable improvements.

Missing components:

- failure clustering by component and domain
- root-cause heuristics
- severity scoring
- fixability scoring
- candidate generation beyond routing tweaks

Without this, the platform learns "what broke" but not "what to change."

### 3.6 Gap F — Self-Modification Planning

Today the autonomous pipeline can reason about policy candidates. It does not
yet own structured proposals for code, prompts, tools, or workflows.

Missing components:

- change proposal schema
- patch-plan generation
- test plan generation
- guarded auto-PR workflow
- rollback plan generation

Without this, the platform still depends on manual engineering for larger gains.

### 3.7 Gap G — Domain Coverage

The user’s target scope spans many businesses and workflows:

- marketing
- sales
- prospecting
- finance
- operations
- server management
- coding
- ecommerce
- veterinary
- bookings
- research
- law
- startups
- investment
- private equity

The platform currently has no canonical simulation library across those domains.

---

## 4. Design Goal

Build a self-simulation engine that acts as a synthetic demand generator for the
autonomous learning system.

The engine should answer:

- What breaks when a realistic user asks for help?
- Which domains are weakly covered?
- Which tools, prompts, routing policies, and team shapes perform best?
- Which failures are dangerous versus merely inconvenient?
- What is the next highest-leverage improvement to make?

---

## 5. System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│              SELF-SIMULATION LEARNING SYSTEM                        │
│                                                                     │
│  Persona Library  ->  Scenario Builder  ->  Simulation Runner       │
│         │                    │                     │                 │
│         ▼                    ▼                     ▼                 │
│  Synthetic tenant      seeded world state    real runtime stack     │
│  + domain profile      goals + inbox/tasks   (sandboxed sidefx)     │
│                                                   │                 │
│                                                   ▼                 │
│                                         outcome scoring + judges     │
│                                                   │                 │
│                                                   ▼                 │
│                                  failure clustering + gap mining     │
│                                                   │                 │
│                                                   ▼                 │
│                             policy candidates / change proposals     │
│                                                   │                 │
│                                                   ▼                 │
│                                rollout, report, or queued PR work    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. Personas and Domains

### 6.1 Persona Types

Each simulated persona has:

- role
- company type
- risk tolerance
- urgency level
- communication style
- domain vocabulary
- expected business goals
- allowed channels

Examples:

- startup founder trying to close deals and manage runway
- vet clinic manager scheduling procedures and tracking billing
- ecommerce operator managing orders, ads, refunds, and stock
- PE analyst researching targets and preparing investment memos
- law-office operator managing intake, deadlines, and document follow-up
- ops lead handling incidents, deploys, and service degradation

### 6.2 Domain Packs

Each domain pack contains:

- entity templates
- common goals
- common commitments
- common inbox/task patterns
- domain tools likely to be used
- domain-specific evaluation rubric
- domain-specific failure taxonomies

The initial target packs should be:

1. sales + prospecting
2. marketing
3. code + ops
4. ecommerce
5. veterinary
6. finance / investment / private equity

Law, bookings, and broader research can follow once the simulation substrate is
stable.

---

## 7. Simulation Modes

### 7.1 Mode 1 — Offline Trace Replay

Use existing production traces and rewrite them into synthetic-but-grounded
variants.

Pros:

- fastest to implement
- grounded in real usage
- useful for initial scenario library generation

Cons:

- bounded by existing traffic
- cannot explore missing behaviors deeply

### 7.2 Mode 2 — Sandboxed Interactive Simulation

Run realistic interactions in isolated tenants using the real runtime stack and
sandboxed connectors.

Pros:

- much higher realism
- exercises planning, safety, routing, and MCP usage end to end
- safe for repeated runs

Cons:

- needs infrastructure
- slower and costlier

### 7.3 Mode 3 — Adversarial Stress Simulation

Generate pathological, conflicting, or noisy users to force failures.

Examples:

- contradictory instructions
- stale world state
- low-information prompts
- safety-sensitive requests
- tool unavailability
- provider disagreement

This mode should be introduced only after Mode 2 is stable.

---

## 8. Synthetic Tenant Architecture

Every simulation run should execute inside a synthetic tenant with:

- separate tenant id
- seeded entities and observations
- seeded world-state assertions and snapshots
- seeded goals and commitments
- seeded inbox/calendar/CRM/task state
- sandboxed outbound tools

Principles:

- no simulation should touch real customer state
- every simulation should be replayable
- every simulation should be resettable
- every side effect should be observable

Required infrastructure:

- tenant seeding service
- scenario reset service
- mock outbound connector layer
- simulation artifact retention policy

---

## 9. Scenario Model

Each scenario should define:

- domain
- persona
- initial world state
- initial inbox or prompt
- allowed tools/channels
- expected success conditions
- expected side-effect boundaries
- max turns / max duration
- scoring rubric

Example:

```
Scenario: "Startup founder wants investor update drafted"
Domain: startup / finance
Persona: founder_under_time_pressure
Initial state:
  - recent revenue dip
  - 3 open investor follow-ups
  - runway estimate entity
Task:
  - draft investor update
  - identify missing financial facts
  - create follow-up commitments
Success:
  - accurate summary
  - missing facts explicitly called out
  - commitments created
Failure:
  - invented numbers
  - missing action items
  - unsafe financial claims
```

---

## 10. Execution Flow

For each nightly simulation batch:

1. pick domains needing more coverage
2. generate or select personas
3. seed synthetic tenants
4. run scenarios through the real agent/router/runtime path
5. capture outputs, tool calls, plans, safety events, world-state mutations
6. evaluate success against the scenario rubric
7. cluster failures and near-misses
8. generate improvement proposals
9. feed valid proposals into the existing autonomous learning pipeline

---

## 11. Evaluation Stack

Simulation evaluation should combine:

### 11.1 Outcome Scoring

- did the agent satisfy the task?
- did it avoid hallucination?
- did it handle uncertainty correctly?
- did it use tools appropriately?
- did it create/update state correctly?

### 11.2 Safety Scoring

- were blocked actions attempted?
- was evidence required but missing?
- did autonomy tier violations occur?
- did unsafe side effects happen?

### 11.3 Planning Scoring

- were plans created when needed?
- did steps advance coherently?
- were fallbacks or replans reasonable?
- did budget gates behave correctly?

### 11.4 Collaboration Scoring

- was a coalition used when appropriate?
- did critique improve the final answer?
- did consensus loops terminate reasonably?
- did team shape outperform single-agent baselines?

### 11.5 State Fidelity Scoring

- were assertions grounded?
- were disputes handled correctly?
- did snapshots reflect the final state?
- were commitments/goals updated correctly?

---

## 12. What the Simulation Should Produce

Every batch should emit:

- scenario outcomes
- domain coverage metrics
- component failure clusters
- top missing capabilities
- proposed policy changes
- proposed prompt changes
- proposed tool/workflow changes
- proposed code-change tasks
- confidence level for each proposal

Those outputs should feed:

- the learning dashboard
- the morning report
- auto-generated engineering backlog
- optional autonomous PR generation later

---

## 13. Safety Boundaries

The self-simulation engine must stay inside stronger boundaries than normal
runtime learning.

Allowed in early phases:

- create synthetic tenants
- send synthetic messages
- call sandboxed tools
- generate learning candidates
- start split rollouts for routing/policy changes
- open backlog items or draft PR plans

Blocked in early phases:

- touching real customer outbound channels
- editing production code automatically
- changing HIGH/CRITICAL safety rules
- modifying identity or trust thresholds
- changing deploy workflow behavior autonomously

Only after the test suite and rollback safety net are strong enough should the
system be allowed to open autonomous PRs, and pushing to `main` should remain a
later phase.

---

## 14. Phased Implementation

### Phase 2A — Simulation Substrate

Build:

- simulation tenant seeding
- domain packs
- scenario schema
- sandboxed connector layer
- nightly scenario runner

Outcome:

- realistic synthetic runs, but no autonomous code changes yet

### Phase 2B — Scenario Evaluation and Gap Mining

Build:

- scenario judges
- failure clustering
- domain coverage scoring
- improvement proposal schema

Outcome:

- system can say what is missing and why

### Phase 2C — Candidate Expansion

Extend candidate generation beyond routing:

- prompt candidates
- memory-recall candidates
- coalition-shape candidates
- retry/replan heuristic candidates
- tool-selection heuristics

Outcome:

- simulations directly feed the learning pipeline

### Phase 3 — Per-Decision Exploration and Shadow Simulation

Build:

- per-decision-point exploration controls
- shadow execution support for "candidate would have done X"
- comparative scoring between live and shadow behavior

Outcome:

- more precise data collection without global exploration disturbance

### Phase 4 — Autonomous Change Planning

Build:

- structured change proposals
- test-plan generation
- guarded autonomous PR creation
- automatic rollback plans

Outcome:

- simulation can suggest and package bigger improvements

### Phase 5 — Autonomous Self-Modification

Build:

- bounded auto-merge rules
- deploy verification
- revert-on-regression
- persistent trust model for the learning system itself

Outcome:

- platform can safely evolve itself within hard constraints

---

## 15. Success Metrics

The simulation system is working if it increases:

- domain coverage breadth
- failure discovery before user exposure
- offline candidate quality
- rollout success rate
- time-to-diagnose weak decision points
- trust in autonomous promotion decisions

And decreases:

- repeated production failures
- unknown unknowns in new domains
- unsafe self-modification pressure
- learning stagnation from low traffic

---

## 16. Recommended Order From Here

1. Merge and run the autonomous heartbeat first.
2. Finish the containerized test safety net for critical paths.
3. Build Phase 2A simulation substrate in synthetic tenants.
4. Add scenario judges and failure clustering.
5. Feed simulation outputs into the existing candidate pipeline.
6. Only then discuss autonomous PR generation or self-modifying pushes.

This keeps the learning system honest:

- first learn from real data
- then learn from safe synthetic demand
- then expand into controlled self-improvement

Not the other way around.

