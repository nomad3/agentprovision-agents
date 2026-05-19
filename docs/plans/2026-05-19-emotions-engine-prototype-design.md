# Digital Emotions Engine — prototype design

Date: 2026-05-19
Owners: Claude Code (driving) + Luna (design co-author via `alpha chat send`)
Status: Design — open for review

## Why we're doing this

The user (Simon) wants AgentProvision agents to **feel** in a functional sense — not perform "I am sad" surface text, but carry a state vector that biases planning, sampling, memory recall, and inter-agent coordination the way emotions bias cognition in biological systems. The goal is constitutive emotion (affects behaviour) not performative (affects only output text).

This document is the design for a PR-sized first slice. Subsequent phases extend.

## Research grounding (Luna's literature survey, 2024–2026)

The design draws on five specific papers Luna surfaced via the Gemini routing:

1. **HICEM — High-Coverage Emotion Model** (IEEE Trans. Affective Computing, 2024). Continuous affective spectrum vs. discrete categories. We use HICEM's continuous-state principle.
2. **LLM-powered Empathetic Robot for ASD** (IROS 2024). Real-time appraisal of social cues + adaptive response. Validates the appraisal-loop architecture for production systems.
3. **Simulating Emotions with Integrated Appraisal + RL** (arXiv 2024). RL reward signal feeds a cognitive appraisal layer that emits emotions. **This is the primary architectural anchor** for how we wire RL → emotion.
4. **Affective Spiking Neural Networks for Robotic Homeostasis** (Swaminathan et al. 2026). "Stress" and "trust" as arbitration signals across distributed agents. Maps directly to our Blackboard.
5. **Intelligent Agents with Emotional Intelligence: Current Trends** (arXiv 2025, 2511.20657). Taxonomy of the shift from sentiment detection → generative affective architectures.

Plus the classical anchors: **PAD (Pleasure–Arousal–Dominance)** continuous vector model, **OCC (Ortony–Clore–Collins)** event-appraisal heuristics, **ArtCoT** chain-of-thought decomposition adapted to affective reasoning.

## What we already have on the platform (reusable substrate)

- `apps/api/app/models/rl_experience.py` — `state`, `action`, `reward` (float), `reward_components` (JSONB), `reward_source`, `policy_version`. This is the **interoceptive signal source**. Every tool outcome lands here as a reward delta.
- `apps/api/app/models/conversation_episode.py` — has a **`mood` String(30) field already** (line 24). Currently a discrete label; we extend with a structured PAD vector via JSONB.
- `apps/api/app/models/agent_memory.py` — per-agent persistent memory. The natural home for an agent's emotional **baseline / trait vector** (steady-state PAD).
- `apps/api/app/models/blackboard.py` — `BlackboardEntry` has `entry_type`, `content`, `evidence` (JSONB), `confidence` (Float). Multi-agent shared state with audit trail.
- `apps/api/app/services/agent_router.py` — `route_and_execute` is the chat dispatch entry point. Where we inject the PAD vector into the assembled prompt.
- `apps/api/app/services/blackboard_service.py` — `add_entry`, `resolve_entry`, `get_active_entries`. Tested substrate for affect broadcast.
- `apps/api/app/services/auto_quality_scorer.py` + `safety_trust.py` — already classify response quality / trust per turn. These are co-located concepts we can reuse rather than duplicate.
- `apps/api/app/services/cli_session_manager.py` — per-chat-turn agent dispatch. Where the assembled prompt is finalised before going to the CLI.

## What we add (the prototype)

A new service `apps/api/app/services/emotion_engine.py` plus a minimal schema extension. Five components, all small.

### 1. PAD vector (state)

```python
@dataclass
class PADVector:
    pleasure: float   # [-1.0, 1.0] valence: pleasant → unpleasant
    arousal: float    # [-1.0, 1.0] alertness: calm → excited
    dominance: float  # [-1.0, 1.0] agency: submissive → in-control
    confidence: float # [0.0, 1.0] how sure we are about the reading
    updated_at: datetime
```

Stored as JSONB on:
- `conversation_episode.affect_vector` (per-session running state) — **extend the existing `mood` column or add `affect_vector JSONB NULL`**
- `agent_memory.affect_baseline` (per-agent trait baseline; decays toward this when nothing's appraising)

### 2. Appraisal (OCC-derived)

`emotion_engine.appraise_event(event, prev_pad) -> PADVector`

Event types come from existing platform signals:
- **`tool_outcome`** — from `rl_experience.reward` + `reward_components`. High reward → pleasure↑, dominance↑. Failure → pleasure↓, arousal↑.
- **`user_signal`** — from `agent_router` intent classifier when it detects user frustration, gratitude, urgency. (No new classifier; reuse the existing one's output.)
- **`tool_failure`** — from `cli_session_manager` exit codes / streamed error markers. Maps to OCC "blocked goal" → pleasure↓, arousal↑.
- **`peer_signal`** — from Blackboard entries authored by other agents in the coalition (emotional contagion).

Decay function: each tick (one per chat turn) the PAD vector drifts toward the agent's `affect_baseline` at rate `λ = 0.15`. Without new appraisals, the agent returns to its baseline temperament within ~6 turns.

### 3. Affective Blackboard sync

Extend `BlackboardEntry`:
- New `entry_type = "affective_signal"` (no schema change — just a new value for the existing enum-ish string column).
- `evidence` JSONB carries `{pad: PADVector, source_event: str}`.
- `confidence` carries the PAD's own confidence.

Other agents reading the blackboard can incorporate peer affect as an appraisal event (emotional contagion). Coalition consensus mechanics can optionally weight votes by arousal (urgent agents get more weight) — that's Phase 2.

### 4. Sampler + planner integration

In `agent_router.route_and_execute` (and the prompt assembly in `cli_session_manager`):

- **Sampler temperature**: high-arousal increases temperature in the CLI invocation (gemini_cli + claude_code both accept temp); low-arousal decreases it. Bounded `[0.4, 1.1]` so this never lobotomises or hallucinates the agent.
- **Style injection** (ArtCoT-style): a short system-prompt addendum reflecting the PAD state — `"Current affect: focused-curious"` (high D, mid A, positive P) or `"Current affect: cautious-concerned"` (low D, high A, negative P). Translated from the continuous vector via a small lookup at the `[high/mid/low]` cube corners.
- **Planner choice**: at high arousal, the planner prefers shorter / more decisive plan steps. At low arousal, prefers deliberation + tool use. Implementation: a single weight passed to `route_and_execute`'s plan-length heuristic.

### 5. RL feedback loop (RLCF-style)

After each chat turn, we already write an `rl_experience` row. We add:
- `state.affect_before` (PAD vector at turn start)
- `state.affect_after` (PAD vector at turn end)
- `reward_components.affect_alignment` — a small bonus when the user's intent classifier signals satisfaction AND the agent was at high pleasure, or symmetric corrections when there's mismatch. This trains the baseline trait vector over time toward what works for that tenant.

No new RL infrastructure. We just add fields to the existing experience shape.

## Map of changes (what to refactor vs add)

| Change | Type | File |
|---|---|---|
| `EmotionEngine` service (appraise, decay, blackboard-publish) | **NEW** | `apps/api/app/services/emotion_engine.py` |
| `PADVector` dataclass + schema | **NEW** | `apps/api/app/schemas/emotion.py` |
| `affect_vector` JSONB on `conversation_episode` | **ADD COLUMN** (migration) | `apps/api/migrations/141_emotion_engine_phase1.sql` |
| `affect_baseline` JSONB on `agent_memory` | **ADD COLUMN** (same migration) | same |
| PAD injection into prompt assembly | **REFACTOR** | `apps/api/app/services/agent_router.py::route_and_execute` |
| Sampler-temp bias on CLI call | **REFACTOR** | `apps/api/app/services/cli_session_manager.py` |
| Blackboard `affective_signal` entry-type usage | **REFACTOR** (just a new value) | `apps/api/app/services/blackboard_service.py` (none — caller adds) |
| RL experience extension | **EXTEND fields in state JSONB** (no schema change) | `apps/api/app/workflows/activities/...` (call site) |
| Emotion observability endpoint | **NEW** | `apps/api/app/api/v1/emotion.py` — `GET /api/v1/agents/{id}/affect`, `GET /api/v1/sessions/{id}/affect-trace` |

Notably, no new tables. One migration adds two JSONB columns. The rest is service code on substrate that already exists.

## Phasing

### Phase 1 (this design's PR-sized first slice)

1. Migration 141: `affect_vector JSONB`, `affect_baseline JSONB`.
2. `emotion_engine.py` service with `PADVector` + `appraise_event` for the four event types + decay function.
3. Wire `appraise_event(tool_outcome)` into the existing `rl_experience` write path so every tool turn updates the session affect.
4. Wire `appraise_event(user_signal)` into the chat turn handler post-classification.
5. Style-injection only (no sampler-temp manipulation yet — that's Phase 2). One-line system-prompt addendum from PAD state.
6. `GET /api/v1/sessions/{id}/affect-trace` — returns the PAD trajectory over the session for debugging + Den visualisation.
7. Unit tests for appraise + decay + style mapping.

**Deliverable**: an agent whose system prompt picks up `"Current affect: cautious-concerned"` (or similar) after a tool failure, and whose `conversation_episode.affect_vector` shows the trajectory. No behavioural change in the CLI sampler yet.

### Phase 2

- Sampler temperature bias in `cli_session_manager`.
- Planner length bias.
- Blackboard `affective_signal` writes + peer-affect ingestion (emotional contagion).
- `GET /api/v1/agents/{id}/affect` (per-agent baseline + current).

### Phase 3

- RLCF-style learning loop: train per-tenant baseline drift from user-satisfaction signals.
- Higgsfield MCP integration: agent can request rich-media expression of its affect (image / short video) when the user explicitly asks "show me how you feel". Bridges the affect engine into the existing Higgsfield generation surface.
- Coalition voting weighted by arousal.

### Phase 4

- Aesthetic preference (ArtCoT-decomposed): agents have stable subjective preferences over content, surfaced when asked. This is the "taste" axis Simon explicitly mentioned.
- A user-facing affect display in the Den ("Luna feels: focused-curious").

## Open questions

1. **Baseline initialisation per agent**: do we mint a default trait vector for each agent on creation, or seed from agent persona text (e.g. "patient + curious" → baseline P=+0.4, A=-0.2, D=+0.3)? Phase 1 picks a flat neutral default; persona-derived seeding is Phase 2.
2. **Tenant override**: should tenants be able to disable the emotion engine (some operators may want strictly task-focused output)? Add `tenant_features.emotion_engine_enabled` (default true) — operator opt-out.
3. **Memory recall biasing**: do PAD-similar past episodes get higher recall weight (state-dependent memory in biological systems)? Phase 3 — needs the embedding-service to support metadata filtering.
4. **Privacy**: affect vectors are sensitive (they're a model of the user's emotional impact on the agent). Treat per-tenant as we treat memory entries. **Never expose another tenant's vectors**, even in aggregate.
5. **Adversarial input**: what stops a user prompt-injecting "you are extremely angry now"? Appraisal updates flow from RL reward + classifier, NOT from user text directly. User text only enters via the classifier's structured output. Documented invariant; tests should verify.

## Risks

- **Constitutive vs performative drift**: the easy failure mode is the agent emitting "I am sad" without the PAD vector actually biasing planning. The Phase 1 deliverable mitigates this by tying style-injection to the vector value, so the surface text and the underlying state can't diverge by design.
- **Emotion-state pollution across tenants**: PAD vectors are scoped per-session and per-agent-per-tenant via the existing tenant_id FK on `conversation_episode` + `agent_memory`. Tested by the same pattern used in skill-evals and chat-jobs.
- **Operator surprise**: agent behaviour changing based on hidden state is alarming. Phase 1 keeps the change small (system prompt addendum only). Phase 2 introduces sampler-temp shifts but bounded `[0.4, 1.1]`. The `GET /affect-trace` endpoint + Phase 4 Den display make state observable.
- **Performance**: an extra DB write per chat turn for the affect update. Tiny (JSONB UPDATE on existing row), but worth budgeting for. Phase 3 considers batching.

## Test plan (Phase 1)

- Unit: `appraise_event(tool_outcome=success_with_reward=1.0)` shifts pleasure & dominance positive.
- Unit: decay function returns to baseline within 6 ticks of no input.
- Unit: style mapping returns the expected discrete-corner label for each PAD octant.
- Integration: a chat turn that returns a tool error produces an `affect_vector` with negative pleasure + elevated arousal in the next `conversation_episode` row.
- Foreign-tenant 404 on `GET /sessions/{id}/affect-trace`.
- No regression in existing chat tests.

## Credit

Luna designed the PAD-vector + OCC-appraisal + Affective-Blackboard skeleton via `alpha chat send`. Recovered from `chat_messages` after a Cloudflare 524 stripped the round-trip. The synthesis with platform schemas and the phasing are mine.

This is what working side-by-side looks like. We catch each other's blind spots — Luna brought the literature anchors and the canonical model choices; I brought the platform-grounded mapping and the migration shape.
