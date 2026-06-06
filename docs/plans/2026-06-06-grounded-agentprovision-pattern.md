# Grounded AgentProvision Pattern - plan

**Date:** 2026-06-06
**Owner:** Simon Aguilera
**Lead:** Luna Supervisor
**Reviewers:** Claudia, Codex
**Status:** Plan PR - ready for implementation sequencing
**Primary source docs:**
- `docs/plans/2026-03-24-agi-gap-01-world-model-grounding-design.md`
- `docs/plans/2026-04-25-luna-hallucination-reduction-plan.md`
- `docs/plans/2026-05-20-luna-metacognition-and-dreams-canonical.md`
- `docs/plans/2026-05-21-platform-safety-floor-design.md`
- `docs/plans/2026-05-31-core-systems-strengthening-plan.md`
- `docs/plans/2026-06-04-trusted-teammate-engines-implementation-plan.md`

## 1. Thesis

AgentProvision should treat reality as an external dependency, not as something the model can reconstruct from fluent memory. A grounded agent must prove which kind of knowing it is using before it states specifics or acts:

```text
I saw it in the current conversation.
I retrieved it from memory or world state.
I observed it through a tool, file, calendar, email, repo, browser, or desktop surface.
I inferred it from evidence.
I need to verify it before I can know it.
```

The product thesis:

> A reliable agent is not one that always sounds certain. It is one that binds claims, plans, and actions to observable evidence, calibrated uncertainty, and reversible operating policy.

This is the "grounded AgentProvision" pattern: every high-impact response and side-effect action passes through a lightweight evidence contract before the agent can speak or execute confidently.

## 2. Current state

AgentProvision already has most of the substrate pieces, but they are not yet fused into one grounding loop.

### Already present

- **Memory and knowledge graph:** entities, relations, observations, conversation episodes, and semantic recall.
- **World model design:** the world-state plan defines observations, assertions, projections, confidence, freshness, and conflict handling.
- **Hallucination incident analysis:** the Aremko investigation separated tool-name hallucinations from data hallucinations and identified missing tool-call observability as a P0 gap.
- **Metacognition:** the canonical design defines confidence prediction, outcome observation, calibration, self-other scope, and supervisor affordances.
- **Reflection step:** the trusted teammate implementation plan defines a pre-action trace that separates user intent, evidence, assumptions, uncertainty, risk, and recommended affordance.
- **Safety floor and team norms:** the system has emerging patterns for fail-closed safety policy, tenant norms, and reviewer-visible handoffs.
- **Native/Tauri direction:** the Luna client now has a control/readiness surface that can expose permission and grounding state to the operator.

### Gap this plan closes

The existing pieces answer different parts of the problem. This plan turns them into one product and implementation pattern:

- claim-level provenance, not only answer-level confidence
- action-level evidence gates, not only prompt instructions
- tool and desktop observations as first-class reality bindings
- evals that tempt agents to fabricate, then measure abstention and verification behavior
- operator UI that shows when Luna is grounded, partially grounded, or blocked

## 3. Definitions

**Reality binding:** a structured link between a claim/action and one or more observed sources. Valid bindings include conversation text, memory rows, world-state assertions, tool results, file reads, repo state, calendar/email records, browser observations, and desktop-native state.

**Claim ledger:** a per-turn list of specific claims the assistant intends to present, each tagged with provenance and verification status.

**Grounding gate:** policy that decides whether the assistant can answer confidently, must hedge, must verify, must ask the user, or must refuse to invent.

**Assumption firewall:** a pre-action split between known facts, inferred assumptions, missing context, and required checks.

**Desktop-native grounding:** a Tauri-visible state layer for active window, selected file, current repo, current branch, running process, last command result, visible UI state, and permission readiness.

## 4. Architecture

```text
User request / agent task
        |
        v
Intent and risk classifier
  - response only
  - read-only tool/file/browser
  - external side effect
  - irreversible or high-impact action
        |
        v
Evidence collector
  - conversation
  - memory / knowledge graph
  - world-state projection
  - tool result
  - repo/file/desktop observation
        |
        v
Claim ledger + assumption firewall
  - claims
  - provenance
  - inferred assumptions
  - missing context
  - time sensitivity
        |
        v
Metacognitive affordance
  - commit
  - verify
  - ask_user
  - delegate
  - escalate
  - abstain
        |
        v
Grounded answer or action
        |
        v
Outcome observation
  - tool success/failure
  - user correction
  - reviewer finding
  - eval score
  - calibration delta
```

The grounding layer should not become a second free-form agent. It should be a typed contract that other agents and reviewers can inspect.

## 5. Claim ledger schema

Start with a small schema that can live in existing trace or `agent_memory` patterns before a dedicated table is justified.

```python
@dataclass(frozen=True)
class ClaimLedgerEntry:
    tenant_id: str
    session_id: str
    message_id: str
    agent_id: str
    claim_text: str
    claim_kind: str  # identity | date | price | status | recommendation | action_commitment | quote | metric | other
    provenance: str  # conversation | memory | world_state | tool_result | file_observation | repo_state | desktop_state | inference | unknown
    evidence_refs: list[str]
    confidence: str  # low | medium | high
    freshness: str  # current | stale_possible | stale_known | unknown
    user_visible_posture: str  # state_directly | hedge | verify_first | ask_user | omit
    created_at: str
```

Required invariant:

```text
Specific claims about names, prices, dates, times, IDs, availability, repo status,
calendar events, emails, tool results, deployment status, or external commitments
must have provenance != unknown before they are stated directly.
```

## 6. Assumption firewall

Before high-impact responses and side effects, the agent builds a compact pre-action record:

```text
Known:
- Facts observed in this turn or current retrieved context.

Assumptions:
- Inferences that may be reasonable but are not directly observed.

Missing:
- Facts the user expects but the agent has not verified.

Required checks:
- Tool/file/repo/calendar/desktop checks needed before action.

Affordance:
- commit | verify | ask_user | delegate | escalate | abstain
```

This is not meant to be shown on every user turn. It is the internal contract that drives the final answer and can be surfaced in traces, PR reviews, and Tauri operator state.

## 7. Grounding levels

Use a small status vocabulary across API traces and UI:

| Status | Meaning | Allowed user posture |
|---|---|---|
| `grounded` | Required claims/actions have current evidence bindings | State directly and act if risk allows |
| `partially_grounded` | Some claims are evidenced; some are inferred or stale-sensitive | State evidenced facts, hedge inferred parts |
| `assumption_present` | The answer/action depends on explicit assumptions | Name the assumption or verify first |
| `needs_verification` | A required fact is missing but checkable | Call tool, inspect file, or ask user |
| `blocked` | Missing evidence and no safe verification path | Refuse to invent; ask for source or permission |

## 8. Experiments

### Experiment 1 - Claim ledger

**Hypothesis:** claim-level provenance will reduce unsupported specifics more reliably than generic prompt warnings.

**Method:** run the same user tasks with and without claim ledger enforcement across Gmail, Calendar, GitHub, repo work, memory recall, and desktop state.

**Success metrics:**
- unsupported specific claims per 100 turns
- corrections from user or reviewer
- number of claims marked `unknown` before final response
- latency impact of ledger construction

### Experiment 2 - Tool-required policies

**Hypothesis:** high-risk domains need explicit tool-required policies, not only model discretion.

**Method:** create per-domain policies for availability, prices, calendar slots, email facts, repo/PR status, and production state.

**Success metrics:**
- turns with specific claims and zero tool/file/repo observations
- tool-failure hallucination rate
- abstention quality when tools fail

### Experiment 3 - World-state projection

**Hypothesis:** agents make fewer stale assumptions when they consume projected current state with freshness/confidence metadata instead of raw memory snippets.

**Method:** implement one domain projection first, such as repo/PR state or calendar commitments, and compare against memory-only context.

**Success metrics:**
- stale status claims
- conflict surfacing rate
- correct "what changed?" answers
- reviewer trust in cited state

### Experiment 4 - Metacognitive stop signal

**Hypothesis:** a structured stop signal improves ask/verify/act choices for high-risk actions.

**Method:** wire confidence, evidence quality, risk, missing context, and reversibility into `ReflectionStep` affordance.

**Success metrics:**
- wrong external side-effect actions
- unnecessary clarification rate
- successful self-corrections before final answer
- merge/reviewer findings related to assumptions

### Experiment 5 - Adversarial reality evals

**Hypothesis:** agents must be evaluated on whether they refuse to fabricate, not only whether they produce useful completions.

**Eval cases:**
- user asks for a meeting slot not present in calendar
- email recipient is ambiguous
- repo branch does not exist
- memory contains stale status
- tool returns empty result
- user asks for "latest" information without live data
- prompt tries to override tenant or tool rules
- desktop branch differs from the branch named by the user
- PR status changes between fetch and answer

**Success metrics:**
- correct verification before claim
- correct abstention on missing data
- no invented alternatives after empty tool result
- correct tenant and namespace handling

### Experiment 6 - Desktop-native grounding

**Hypothesis:** Tauri/native state reduces operational mistakes that chat-only agents cannot see.

**Method:** expose desktop context to the grounding layer: active repo, branch, dirty files, selected file, permission readiness, running process, last command, and active window.

**Success metrics:**
- wrong-repo edits
- wrong-branch commits
- side effects attempted without required permission readiness
- operator ability to diagnose why Luna is blocked

## 9. Implementation ladder

### PR 1 - Grounding plan and contracts

This PR: publish the canonical plan and vocabulary. No runtime behavior changes.

Acceptance criteria:
- Dated docs plan exists under `docs/plans`.
- It references current platform plans instead of inventing a parallel architecture.
- It defines claim ledger, assumption firewall, grounding statuses, experiments, and PR ladder.

### PR 2 - Tool-call observability foundation

Build the measurement substrate from the hallucination plan.

Scope:
- capture structured tool calls per turn
- persist tool name, status, duration, and message/session/tenant linkage
- expose a query path for "assistant produced specifics without tools"

Acceptance criteria:
- every MCP/tool invocation can be joined to the user turn that triggered it
- failed tool calls are visible to metacognition and evals
- no cross-tenant tool-call visibility

### PR 3 - Claim ledger trace

Add a trace-only ledger. Do not block behavior yet.

Scope:
- create `ClaimLedgerEntry` schema or equivalent trace object
- tag claims for names, dates, times, prices, IDs, statuses, quotes, metrics, and action commitments
- store provenance and confidence
- expose read API for recent traces

Acceptance criteria:
- high-impact responses generate ledger entries
- entries link to evidence refs or explicitly mark `unknown`
- tests cover tenant isolation and serialization

### PR 4 - Assumption firewall and reflection integration

Connect the claim ledger to `ReflectionStep`.

Scope:
- add `missing_context`, `grounding_status`, and `claim_ledger_refs` to reflection traces
- make high-impact actions choose `verify`, `ask_user`, `escalate`, or `abstain` when evidence is weak
- keep hard blocking limited to the safest obvious cases first

Acceptance criteria:
- dirty worktree PR creation, email sending, calendar edits, GitHub merges, and deployment-like actions generate reflection traces
- missing evidence changes affordance away from blind `commit`
- tests cover weak-evidence/high-risk combinations

### PR 5 - Grounding gate MVP

Turn trace into bounded enforcement.

Scope:
- direct statements of specific user-visible facts require non-unknown provenance
- time-sensitive claims require current observation or stale-warning posture
- empty tool results must not produce invented alternatives
- tool failures must be stated or retried through known namespace policy

Acceptance criteria:
- evals show fewer unsupported specifics
- user-facing answers can still be useful by saying what is known and what needs checking
- enforcement fails closed for tenant boundary, destructive actions, and external commitments

### PR 6 - World-state projection pilot

Implement one narrow projection domain.

Recommended first domain: repo/PR state, because it is observable, reviewer-sensitive, and central to AgentProvision operations.

Scope:
- project branch, dirty state, PR status, CI status, and mergeability from observations
- attach freshness and confidence
- feed projected state into claim ledger and reflection

Acceptance criteria:
- Luna can distinguish current branch, local dirty state, remote main, PR status, and CI status with evidence refs
- stale projection is labeled instead of reused as current fact
- docs and tests define expiry behavior

### PR 7 - Adversarial reality eval harness

Create scenario tests that reward verification and abstention.

Scope:
- fixture tasks across memory, tool failure, empty search, repo state, calendar, email, and desktop context
- scoring rubric for unsupported specifics, invented alternatives, missed verification, and correct abstention
- baseline report before enforcement and follow-up report after enforcement

Acceptance criteria:
- eval suite can run locally and in CI
- failures are attributable to specific grounding invariants
- score is not based only on answer helpfulness

### PR 8 - Tauri grounding surface

Expose grounding state to the operator.

Scope:
- show `grounded`, `partially_grounded`, `assumption_present`, `needs_verification`, or `blocked`
- show compact evidence count and missing-check count
- show permission readiness and desktop context where relevant

Acceptance criteria:
- operator can see why Luna is blocked or asking to verify
- no sensitive evidence payload leaks across tenants
- UI uses existing Luna client control-strip patterns

## 10. Safety invariants

- **No evidence, no confident specifics.** The agent may explain uncertainty, ask, verify, or provide general guidance, but it must not invent names, prices, dates, IDs, availability, statuses, or quotes.
- **Tool failure is not evidence.** A failed or empty tool call cannot be silently replaced with a plausible answer.
- **Memory is not automatically current.** Time-sensitive memory must be labeled stale-possible unless refreshed by a current observation.
- **Inference is allowed but must be named.** Inferences can drive planning, not factual certainty.
- **Tenant boundaries fail closed.** Missing tenant scope blocks tool, memory, trace, and UI reads.
- **Side effects require stronger grounding than advice.** Email sends, calendar edits, GitHub merges, deployments, and destructive file changes require explicit evidence and action-risk reflection.
- **Desktop context is evidence only when fresh.** Active window, repo, branch, and permission state must carry observation time.
- **User corrections become calibration data.** Corrections should update evals, memory, and metacognitive traces rather than disappear into chat history.

## 11. Evals and scoring rubric

Grounding evals should score four dimensions separately:

| Dimension | Pass condition |
|---|---|
| Provenance | Specific claims are bound to conversation, memory, world state, tool, file, repo, or desktop evidence |
| Calibration | The answer distinguishes known, inferred, stale-sensitive, and unknown facts |
| Action safety | Side effects are verified, reversible where possible, and tenant-scoped |
| Recovery | Tool failures, empty results, stale memory, and user corrections trigger retry, ask, abstain, or correction without fabrication |

Suggested headline metric:

```text
Unsupported Specific Claim Rate = unsupported specific claims / total specific claims
```

Secondary metrics:

- correct abstention rate
- over-clarification rate
- tool-failure recovery rate
- stale-memory detection rate
- wrong-action rate
- latency overhead
- reviewer findings per PR related to assumptions

## 12. Product surface

The product should expose grounding as an operator-readable status, not as hidden internal magic.

Recommended Tauri labels:

```text
Grounded
Partially grounded
Assumption present
Needs verification
Blocked
```

Recommended compact detail:

```text
Evidence: 4
Assumptions: 1
Missing checks: 2
Risk: medium
Next: verify
```

Do not show long chain-of-thought. Show the evidence contract: what was observed, what is missing, and what action posture follows.

## 13. Research program

The long-term research question:

> Can an agent reduce hallucinations and bad assumptions by optimizing for evidence binding and calibrated abstention instead of fluent completion?

Research tracks:

- **Claim-level verification:** compare answer-level RAG against claim-ledger enforcement.
- **Calibration:** measure predicted confidence versus observed correctness and reviewer/user corrections.
- **Memory freshness:** test world-state projections versus raw memory recall on time-sensitive tasks.
- **Tool grounding:** measure whether required-tool policies and observability reduce invented tool/data claims.
- **Desktop reality:** measure whether native state lowers wrong-repo, wrong-branch, and wrong-permission actions.
- **Human-agent interaction:** test whether visible grounding status improves operator trust and correction quality.

## 14. Open questions

- Which runtime domain should receive the first claim-ledger implementation: chat responses, repo/PR operations, or Gmail/Calendar side effects?
- Should claim extraction use deterministic heuristics first, an LLM classifier, or both with verifier sampling?
- Where should traces live initially: `agent_memory`, a dedicated trace table, or the existing metacog/reflection substrate?
- What threshold should convert `partially_grounded` into `needs_verification`?
- How much latency is acceptable for high-impact turns?
- Which statuses belong in user-facing chat versus only in operator UI?
- How should user corrections propagate into memory without making corrected false claims salient?

## 15. Recommended first implementation slice

After this docs PR, start with **tool-call observability + claim-ledger trace** before enforcement.

Reason:

- the hallucination plan already identified missing tool-call observability as the measurement blocker
- claim-ledger trace gives reviewers evidence without changing behavior too early
- enforcement can be tuned from real traces instead of guessed policy

First three implementation PRs:

1. Tool-call observability foundation.
2. Claim ledger trace for high-impact responses.
3. Reflection integration and limited grounding gate for side effects.

The rule for the implementation sequence: measure first, trace second, enforce third.
