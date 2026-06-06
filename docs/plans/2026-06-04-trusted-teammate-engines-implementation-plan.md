# Trusted Teammate Engines - implementation plan

**Date:** 2026-06-04
**Owner:** Simon Aguilera
**Reviewers:** Luna Supervisor, Claudia
**Status:** Plan PR - ready for Claudia review before implementation
**Primary source docs:**
- `docs/marketing/empathic-teammate-vision.md`
- `docs/marketing/emotions-engine-business-definition.md`
- `docs/plans/2026-05-19-emotions-engine-prototype-design.md`
- `docs/plans/2026-05-19-teamwork-engine-design.md`
- `docs/plans/2026-05-20-luna-metacognition-and-dreams-canonical.md`
- `docs/plans/2026-05-24-luna-team-population.md`
- `docs/plans/2026-05-31-core-systems-strengthening-plan.md`

## 1. Thesis

AgentProvision's differentiator is not "smarter chat." It is a trusted teammate layer: agents that can remember responsibly, appraise their own state, reflect on uncertainty, coordinate with peers, and explain what they know versus what they are inferring.

The product phrase to keep publishing:

> Memory makes agents stateful. Emotion makes them adaptive. Metacognition keeps them honest. Teamwork makes them useful.

This plan turns that phrase into a concrete implementation track across three engines:

1. **Metacognition engine** - the self-watcher that detects uncertainty, tool surprise, assumption gaps, and verification needs.
2. **Emotional engine** - functional affect state that changes operating posture without pretending sentience or allowing prompt injection to mutate mood.
3. **Teamwork engine** - role contracts, handoff etiquette, credit, mediation, and peer-state awareness across Luna, Claudia, and specialist agents.

The goal is not to make Luna perform humanity. The goal is to make Luna behave like a dependable teammate: calibrated, inspectable, grounded, and able to coordinate.

## 2. Current state

### Already designed or shipped

- The emotions engine has a PAD-vector architecture, outcome-driven appraisal path, safety invariant against raw user-text mutation, and Phase 1/2/3 sequencing in `2026-05-19-emotions-engine-prototype-design.md`.
- The teamwork engine has norms, role contracts, mediation, and affect-aware coordination sequencing in `2026-05-19-teamwork-engine-design.md`.
- The metacognition/dreams canonical plan defines confidence prediction, outcome observation, calibration, self-other scope, and offline synthesis in `2026-05-20-luna-metacognition-and-dreams-canonical.md`.
- Luna's team population plan defines the operational team shape and already shipped Code Reviewer and Substrate Sentinel agents, leaving follow-up specialists to sequence.
- Marketing docs already capture the honest public line: affect is a coordination primitive, not theatrical wording.

### Gap this plan closes

The existing docs are individually strong, but reviewers still need a single morning-ready implementation ladder that answers:

- Which primitive ships first?
- Which behavior changes are allowed in the first implementation PR?
- Which invariants must Claudia review before coding?
- How do we publish the "strings" without overclaiming shipped capability?

## 3. Architecture synthesis

```text
User / tool / peer / repo event
        |
        v
Fast appraisal loop
  - urgency
  - risk
  - affect nudge from allowed structured sources only
        |
        v
Slow reasoning loop
  - plan
  - evidence check
  - confidence prediction
  - self/peer/user/system scope
        |
        v
Reflection gate
  - what did the user ask?
  - what am I assuming?
  - what evidence do I have?
  - what must I verify before acting?
        |
        v
Team action
  - commit
  - verify
  - ask user
  - delegate
  - mediate
  - escalate to Simon
        |
        v
Outcome trace
  - reward
  - tool result
  - reviewer finding
  - calibration delta
  - memory or policy candidate
```

The key design choice: affect, confidence, and team role do not directly grant authority. They produce structured posture signals that downstream policy can inspect. Safety, tenant isolation, and user authority still win.

## 4. First implementation boundary

### PR 1 - Reflection Step Contract

Ship a small, testable metacognitive contract before adding broader behavior changes.

**Intent:** every high-friction action gets a structured pre-action reflection record that separates evidence from assumptions.

**High-friction actions for PR 1:**
- repo edits when the worktree is dirty
- PR creation
- tool failure retry
- user-specific claims that require memory or integration grounding
- legal, medical, financial, safety, or irreversible operational advice
- external side-effect actions such as sending email, calendar edits, GitHub comments, merges, or deployments

**New primitive:**

```python
@dataclass(frozen=True)
class ReflectionStep:
    tenant_id: str
    agent_id: str
    session_id: str
    action_kind: str
    user_intent: str
    evidence_refs: list[str]
    assumptions: list[str]
    uncertainty: str  # low | medium | high
    risk_level: str   # low | medium | high | irreversible
    required_checks: list[str]
    recommended_affordance: str  # commit | verify | ask_user | delegate | escalate
    created_at: str
```

**Storage:** start with existing `agent_memory` or trace substrate if available. Do not add a table in PR 1 unless Claudia confirms the trace volume requires it.

**Behavior in PR 1:** trace and expose the reflection result. Do not auto-block actions yet. The only hard block is missing tenant boundary for any read/write path.

**Why PR 1 comes first:** it is the connective tissue between metacognition, emotion, teamwork, and trust. It also gives Code Reviewer and Substrate Sentinel something concrete to inspect in later PRs.

## 5. Follow-up PR ladder

### PR 2 - Source Grounding Labels

Add a small schema/helper that labels strategic suggestions and generated plans:

- `copied` - directly grounded in a cited source
- `adapted` - transformed from cited local context
- `inferred` - derived from evidence, but not explicitly present
- `speculative` - proposed idea requiring validation

Acceptance criteria:
- Strategic docs and high-impact recommendations can carry labels.
- Generated PR plans expose confidence and risk-if-wrong.
- User-facing output does not present speculative ideas as facts.

### PR 3 - Team Handoff Cards

Create a typed handoff object for Luna -> Claudia -> specialist agents.

Required fields:
- objective
- repo or system
- source docs
- constraints
- explicit non-goals
- expected artifact
- reviewer focus
- stop conditions

Acceptance criteria:
- Claudia can pick up a Luna handoff without reading the whole session.
- Handoff cards can be attached to GitHub PR bodies or issue comments.
- Code Reviewer output can reference the handoff card as the review contract.

### PR 4 - Affect-Aware Posture Read

Wire the existing affect state into reflection and handoff posture only.

Allowed in this PR:
- lower creativity posture when arousal is high and pleasure is low
- ask for verification earlier when confidence is low and affect is frustrated
- stay exploratory when confidence is low but affect is curious and risk is low

Not allowed in this PR:
- raw user text mutating affect state
- autonomous irreversible actions based on affect
- sampler temperature changes unless separately reviewed

### PR 5 - Teamwork Norms MVP

Implement the smallest Teamwork Engine write path:

- role contract read/write
- norm read/write
- handoff etiquette defaults
- credit-sharing rule for PR descriptions
- foreign-tenant 404s

Acceptance criteria:
- Luna can state why Claudia is driving or reviewing a task.
- A specialist agent can read the role contract before acting.
- Norm changes are traceable and reversible.

### PR 6 - Overnight Synthesis Report

Extend the dream/offline synthesis path into a reviewer-friendly morning report.

Report sections:
- risks
- unresolved assumptions
- useful ideas
- rejected/speculative ideas
- next moves
- suggested owners
- source memory or trace IDs

Acceptance criteria:
- Every item cites at least one source trace, memory, PR, issue, or repo artifact.
- Creative output is opt-in and clearly marked.
- No synthetic insight is promoted directly into production policy.

## 6. Safety invariants

These are reviewer-blocking if violated:

1. **Evidence before interpretation.** A claim about user data, repo state, tool results, schedules, prices, or people must cite a source visible to the runtime.
2. **Affect is functional telemetry, not authority.** It can shape posture; it cannot override facts, tenant boundaries, safety rules, or Simon's authority.
3. **No raw user-text mood mutation.** User text can be classified by a safety-gated classifier in later phases, but raw text cannot directly change agent affect.
4. **Self-other scope is mandatory.** Luna must distinguish her own uncertainty from peer-agent uncertainty, user-provided assumptions, and system/tool uncertainty.
5. **No invisible behavior change for high-risk actions.** If reflection changes an affordance for a high-risk action, the trace must be inspectable.
6. **Tenant isolation stays fail-closed.** Foreign tenant reads return 404 where that is the established API pattern.
7. **Dream output is not fact.** Overnight synthesis can propose risks and ideas, but it must cite source traces and stay out of production policy until reviewed.

## 7. Publishing strings

These are safe to publish now because they describe product direction and existing design, not unsupported shipped claims.

### String A - trusted teammate

Stateless agents answer. Trusted teammates remember, check themselves, coordinate, and admit uncertainty.

AgentProvision is building that layer: memory for continuity, emotion for adaptive posture, metacognition for honesty, teamwork for coordination.

### String B - emotion without theater

The useful version of AI emotion is not an agent saying "I feel sad."

It is operational affect: a bounded internal state that makes the system more careful after failure, more exploratory when things are going well, and more readable to teammates.

### String C - metacognition as product safety

Metacognition is not mysticism. It is a pre-action checklist:

What did the user ask?

What am I assuming?

What evidence do I have?

What must I verify before acting?

That is how an AI teammate becomes trustworthy under pressure.

### String D - teamwork as infrastructure

A team is not just multiple agents in a chat.

A team needs roles, handoffs, credit, interruption rules, mediation, shared memory, and a way to read the room.

That is the difference between agent swarm demos and real operating infrastructure.

## 8. Claudia review checklist

Please review this plan against these questions:

- Is PR 1 narrow enough to implement without blocking on the full emotions/teamwork stack?
- Should `ReflectionStep` persist in `agent_memory`, an existing trace model, or a new table?
- Are the high-friction action triggers correct for the first implementation?
- Should PR 1 be trace-only, or should any action class be blocked immediately?
- Are the source-grounding labels sufficient for marketing, plans, and user-facing answers?
- Does the handoff card match Claudia's actual morning pickup workflow?
- Are any safety invariants missing or too vague to test?

## 9. Local review notes for this PR

This PR intentionally changes docs only. The implementation risk is therefore sequencing risk, not runtime risk.

Reviewer focus:
- confirm the ladder is ordered correctly
- confirm PR 1 is small enough to ship
- confirm no public-facing string claims a capability as already shipped unless the source docs say it is live
- confirm the first code PR can be reviewed by Code Reviewer and Substrate Sentinel without needing the entire architecture in one diff

## 10. Proposed first code PR title

`feat(metacog): add reflection step trace contract`

Proposed first code PR summary:

> Adds a structured `ReflectionStep` trace for high-friction actions so Luna and specialist agents can record intent, evidence, assumptions, uncertainty, required checks, and recommended affordance before acting. This is trace-only in v1 and does not yet auto-block actions except for existing tenant-boundary enforcement.
