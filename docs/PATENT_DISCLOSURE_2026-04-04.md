# Patent Disclosure Document
## ServiceTsunami AI Agent Orchestration Platform
### Confidential — Attorney-Client Privileged

**Inventors:** [To be completed by legal counsel]
**Filing Date:** 2026-04-04
**Document Reference:** ST-PATENT-001

---

## ABSTRACT

This disclosure describes novel systems and methods for a multi-tenant AI agent orchestration platform combining: (1) a hierarchical, vector-indexed, multi-layer memory system with hybrid semantic-keyword recall, decay-adjusted retrieval, anticipatory context injection, and RL-instrumented recall decisions; (2) a fully asynchronous, local-first Reinforcement Learning system that uses a multi-agent consensus council, multi-dimensional quality rubrics, trajectory-discounted reward propagation, federated policy blending, and A/B-tested policy rollout with automatic regression-triggered rollback to continuously improve agent behavior without human labeling; (3) a zero-LLM-cost deterministic agent router augmented by semantic intent classification and RL-derived routing overrides; (4) a trust-earned autonomy tier system that derives agent execution authority from accumulated RL reward signals and multi-provider agreement scores; and (5) a Temporal-based durable dynamic workflow engine with JSON-defined execution plans, integration awareness gating, and visual builder. Taken together, these systems form an end-to-end self-improving AI agent platform that operates with zero cloud inference cost for quality control and continuously narrows the gap between current and ideal agent behavior.

---

## BACKGROUND

### State of the Art in AI Agent Orchestration

Current AI agent orchestration platforms (LangChain, AutoGen, CrewAI, Microsoft Copilot Studio, AWS Bedrock Agents) suffer from several fundamental limitations:

**Memory:** Agents are mostly stateless or rely on crude conversation history windows. Existing solutions like MemGPT (Packer et al., 2024) address long-term memory but do not integrate memory recall decisions into RL training loops, nor do they model memory decay, anticipatory context injection, or relational graph traversal within a single retrieval call.

**Quality Control:** Existing platforms have no automated, cost-free quality scoring. Most rely on human feedback (RLHF) collected offline, or on cloud LLM calls (GPT-4 scoring) that are prohibitively expensive at scale. LLM-as-a-judge approaches (Zheng et al., 2023) use a single evaluator without consensus mechanisms or fragility detection.

**Routing:** Agent routing is largely manual (hardcoded rules, keyword filters) or uses expensive LLM classification. Reinforcement learning has been applied to conversation-level routing (Ramesh et al., 2023) but not to multi-platform CLI routing with semantic intent classification, cold-start handling, and per-decision-point exploration decay.

**Safety:** Current safety approaches (Constitutional AI, RLHF guardrails, content filters) are static policies. None derive dynamic execution authority from an agent's accumulated RL performance history, creating a feedback loop between quality and capability.

**Workflow:** Temporal-based durable execution is well-known (Temporal.io, 2019), but the combination of JSON-defined workflows, integration awareness gating, visual ReactFlow builders, and per-step RL instrumentation represents a novel integration layer.

---

## DETAILED DESCRIPTION OF PREFERRED EMBODIMENTS

---

### INVENTION 1: Hierarchical Multi-Layer Memory System with Hybrid Recall and RL Instrumentation

#### 1.1 Technical Overview

The memory system implements five semantically distinct memory layers within a PostgreSQL/pgvector database:

| Layer | Table | Embedding | Purpose |
|-------|-------|-----------|---------|
| Entity Memory | `knowledge_entities` | Embeddings table (768-dim) | Named entities (people, companies, projects) |
| Episodic Memory | `conversation_episodes` | Vector(768) column | Compressed summaries of past conversations |
| Procedural Memory | `agent_memories` (type=procedure/skill) | Vector(768) column | How-to knowledge and learned capabilities |
| Semantic Memory | `embeddings` table | Vector(768) | Cross-type unified embedding index |
| Journal Memory | `session_journals` | Embedded via `embed_and_store` | Weekly synthesized narrative of user activity |

Additionally, the system maintains:
- `knowledge_observations`: time-stamped facts about entities with per-fact embeddings
- `knowledge_relations`: typed directed graph edges between entities
- `world_state_assertions`: normalized, versioned claims with confidence, corroboration counts, and dispute detection
- `memory_activities`: audit log of all memory operations, itself embedded for semantic recall

#### 1.2 The Hybrid Recall Engine (`memory_recall.py`)

**Novel Algorithm — Hybrid Semantic-Keyword-Boost Recall:**

```
Input: user_message, tenant_id
Output: memory_context{entities, memories, relations, observations, episodes}

Step 1: Embed user_message → 768-dim query vector (nomic-embed-text-v1.5)
Step 2: Semantic search → top-30 entities + top-15 memories via pgvector cosine distance
Step 3: Keyword extraction → filter stop words, deduplicate, cap at 10 terms
Step 4: Keyword boost → entities whose name matches query words: similarity += 0.3 (capped at 1.0)
Step 5: Session entity boost → entities mentioned earlier in conversation: similarity += 0.2
Step 6: Sort by final boosted score, take top-N entities + top-5 memories
Step 7: Pin user/owner entity (category="user") at index 0 regardless of score
Step 8: Per-entity semantic observation retrieval → top-K observations ranked by cosine distance to query
Step 9: Two-hop graph traversal → neighbors of recalled entities via SQL CTE
Step 10: Anticipatory context injection → time-of-day, day-of-week, upcoming calendar events (next 4 hours)
Step 11: Disputed assertion injection → world_state_assertions with status="disputed" for recalled entities
Step 12: Episodic recall → top-5 conversation_episodes ranked by cosine distance (threshold > 0.3)
Step 13: Update recall counters (increment recall_count, last_recalled_at on entities)
Step 14: Update memory access counters (increment access_count, last_accessed_at on memories)
Step 15: Log RL experience at decision_point="memory_recall" for training
Step 16: Fallback: if embedding model unavailable, use ILIKE keyword matching
```

**What is novel:**
- Combining semantic search + keyword boost + session context boost + owner entity pinning in a single recall pipeline
- Per-entity semantic observation retrieval (retrieving the most relevant *facts about* an entity, not just the entity itself)
- Two-hop relational graph traversal in a single SQL CTE as part of memory context building
- Anticipatory time/calendar context injection based on real-time schedule
- Logging each recall decision as an RL experience for future training of the recall policy itself
- Graceful degradation to ILIKE keyword fallback when the embedding model is unavailable
- Decay-adjusted memory retrieval using time since last access and per-memory decay rate

**Decay-Adjusted Memory Scoring (SQL, novel):**
```sql
raw_similarity * GREATEST(0.1,
    1.0 - COALESCE(decay_rate, 0.01)
        * EXTRACT(EPOCH FROM (NOW() - COALESCE(last_accessed_at, NOW()))) / 86400.0
) AS similarity
```
This formula adjusts raw cosine similarity by a time-based decay factor, ensuring recently-accessed memories score higher than stale ones with the same semantic similarity, without requiring Python-side post-processing.

#### 1.3 World State Contradiction Detection

The `world_state_assertions` table stores normalized claims derived from observations. When the memory recall returns entities, the system simultaneously queries for `disputed` assertions on those entities and injects `contradictions` into the memory context. This allows agents to reason about conflicts in their knowledge (e.g., "the stored phone number conflicts with a recently observed different number") without an explicit reconciliation step, implementing a form of *grounded uncertainty awareness*.

#### 1.4 Session Journal Synthesis

The `session_journals` service synthesizes episodic memory into weekly narrative summaries using local LLM inference. These journals are embedded (768-dim) for semantic recall. The `synthesize_morning_context()` function calls the local Qwen model to generate a warm first-person narrative from recent journals, providing *continuity briefing* context at session start.

#### 1.5 Behavioral Signal Tracking (Follow-Through Detection)

The `behavioral_signals` service implements a novel *follow-through detection* loop:
1. After each agent response: regex patterns detect actionable suggestions ("want me to send...", "should I schedule...", etc.) and store them as `pending` signals with 768-dim embeddings
2. After each user message: semantic similarity (threshold 0.72) between user input and pending signals determines if the user acted on a suggestion
3. Direct confirmation tokens ("yes", "sure", "go ahead") short-circuit to the most recent pending signal
4. Acted-on rates per suggestion type are fed back into the system prompt as *self-calibration context* ("follow_up: 67% acted on — keep suggesting")

This creates a *behavioral reinforcement loop* entirely outside the LLM scoring system, using user actions as ground truth.

#### 1.6 Git Context Integration

The `build_memory_context_with_git()` function detects code-related queries via keyword intersection with a predefined set, then appends relevant git observations (`git_commit`, `git_pr`, `file_hotspot` types from `knowledge_observations`) to the memory context. This seamlessly integrates version control history into the agent's working memory for code-related queries.

---

### INVENTION 2: Asynchronous Local-First Reinforcement Learning System for AI Agent Quality Improvement

#### 2.1 Technical Overview

The RL system comprises six interconnected subsystems:
1. **Experience Logger** (`rl_experience_service.py`): trajectory-based decision logging with 768-dim state embeddings
2. **Quality Scorer** (`auto_quality_scorer.py`): async multi-dimensional rubric + consensus review
3. **Consensus Council** (`consensus_reviewer.py`): 3 parallel local LLM reviewers with majority voting and fragility detection
4. **Policy Engine** (`rl_policy_engine.py`): reward-weighted regression, explore/exploit with decay
5. **Policy Rollout** (`policy_rollout_service.py`): A/B experiments with auto-rollback
6. **Learning Pipeline** (`learning_experiment_service.py`): offline evaluation, candidate promotion, auto-generation

#### 2.2 Novel Quality Scoring Architecture

**Multi-Dimensional Rubric with Cost Efficiency Tracking:**

The `agent_response_quality` rubric scores responses on 6 dimensions:

| Dimension | Max Points | Novel Aspect |
|-----------|------------|--------------|
| accuracy | 25 | Includes tool output interpretation accuracy |
| helpfulness | 20 | Distinguishes what-was-asked from what-was-needed |
| tool_usage | 20 | Penalizes both missing-tool and unnecessary-tool calls |
| memory_usage | 15 | Explicitly rewards knowledge graph recall and context building |
| efficiency | 10 | Penalizes over-explanation equally with under-explanation |
| context_awareness | 10 | Rewards conversation continuity explicitly |

The rubric also extracts `cost_efficiency` metrics: tokens-per-quality-point and a platform recommendation (`claude_code|gemini_cli|codex|any`), creating a *cost-performance optimization signal* embedded in every scored experience.

**Fire-and-Forget Async Architecture:**

```python
def score_and_log_async(...):
    threading.Thread(
        target=lambda: asyncio.run(_score_and_log(...)),
        daemon=True,
    ).start()
```

The scoring system is completely non-blocking: the response is returned to the user, *then* scoring runs in a background daemon thread. This ensures zero latency impact from the quality scoring system regardless of LLM inference time.

**GPU Inference Bulkhead:**

```python
_foreground_active = threading.Event()   # Set when any foreground caller holds GPU
_background_lock = threading.Lock()      # Serializes background calls
```

Foreground inference (user-blocking, e.g., free-tier response generation) sets a shared threading.Event that background processes (scoring, consensus) check before acquiring GPU. If the foreground is active, background processes skip rather than contend. This is the *GPU inference bulkhead* pattern — degrading the scorer (non-user-visible) to protect the user experience (user-visible).

#### 2.3 Three-Agent Consensus Council with Fragility Detection

**Parallel Review Architecture:**

Three specialized reviewers execute concurrently via `asyncio.gather()` with `return_exceptions=True`:

```python
REVIEW_AGENTS = [
    ReviewAgent("Accuracy Reviewer", ...),     # Factual correctness, tool output accuracy
    ReviewAgent("Helpfulness Reviewer", ...),  # Actual need satisfaction, actionability
    ReviewAgent("Persona Reviewer", ...),      # Style, tone, no AI-isms, language match
]
```

**Novel: Leave-One-Out Fragility Detection:**

```python
fragile = passed and approved_count == required  # exactly 2/3
```

When consensus passes with exactly the minimum required approvals, the result is flagged as `fragile` — meaning removing one approval would flip the decision. Fragile results trigger escalation to the multi-provider review council (Claude + Codex + Qwen in parallel via Temporal). This is a novel *statistical robustness* signal within a majority-vote reviewer system.

**Consensus-to-RL Blending:**

```python
disapproval_ratio = 1.0 - (consensus.approved_count / consensus.total_reviewers)
consensus_penalty = disapproval_ratio * 15   # Max 15-pt penalty
adjusted_score = max(0, score - int(consensus_penalty))
reward = (adjusted_score - 50) / 50.0        # Maps to [-1.0, +1.0]
```

The rubric score and consensus are blended into a single RL reward, with consensus failure proportionally reducing the reward. This is a *multi-signal reward combination* that avoids binary pass/fail thresholds.

**Scorer Confidence Weighting:**

```python
_SCORER_CONFIDENCE = {
    "admin_review": 1.0,
    "explicit_rating": 1.0,
    "auto_quality_consensus": 0.7,
    "auto_quality": 0.5,
    "auto_quality_backfill": 0.1,
    "response_quality_backfill": 0.1,
}
```

Each RL experience records a `scorer_confidence` weight indicating the reliability of its reward signal. This allows the policy engine and dream system to discount low-confidence scores during training, implementing a form of *sample-importance weighting* in the RL pipeline.

#### 2.4 Trajectory-Based Reward Propagation

**Discount Factor Backward Propagation:**

```python
TRAJECTORY_DISCOUNT = 0.7

for i, exp in enumerate(experiences_reversed):
    if i == 0:
        step_reward = terminal_reward
    else:
        step_reward = downstream_reward * TRAJECTORY_DISCOUNT
    ...
    downstream_reward = step_reward
```

Multi-step decision trajectories (e.g., routing → tool selection → response generation) share credit for the terminal reward via backward propagation with γ=0.7. This implements *temporal credit assignment* across decision steps within a single conversation turn.

**Routing-Response Reward Backfill:**

```python
UPDATE rl_experiences
SET reward = :reward,
    reward_source = 'response_quality_backfill'
WHERE trajectory_id = :traj
  AND decision_point = 'agent_routing'
  AND reward IS NULL
```

The routing decision that selected a platform receives the same quality reward as the final response, creating a *delayed credit assignment* mechanism: the platform selection is credited with the response quality outcome even though the reward is not available at routing time.

#### 2.5 Semantic Experience Retrieval for Policy Learning

**pgvector Cosine Similarity Search over RL Experiences:**

```python
def find_similar_experiences(db, tenant_id, decision_point, state_text, limit=200):
    query_embedding = embed_text(state_text)
    sql = f"""
        SELECT ...,
               1 - (state_embedding <=> CAST('{vector_literal}' AS vector)) AS similarity
        FROM rl_experiences
        WHERE tenant_id = CAST(:tid AS uuid)
          AND decision_point = :dp
          AND reward IS NOT NULL
        ORDER BY state_embedding <=> CAST('{vector_literal}' AS vector)
        LIMIT :lim
    """
```

Instead of bucketing experiences by discrete features (e.g., task_type in ["code","data"]), the system uses *continuous semantic similarity* to find relevant past decisions. This allows generalization across semantically similar-but-lexically-different states.

**Reward-Weighted Regression with Recency Decay:**

```python
lambda_decay = 0.05  # ~14 day half-life

for exp in similar_experiences_for_candidate:
    days_old = (now - exp.created_at).days
    recency = math.exp(-lambda_decay * days_old)
    sim = exp.similarity
    w = recency * sim
    weighted_sum += exp.reward * w
    weight_total += w

candidate_score = weighted_sum / weight_total
```

The system combines two exponential functions: semantic similarity and time-based recency decay. This *dual-exponential scoring* ensures recent, semantically-similar experiences exert more influence on the predicted reward, without hard cutoffs.

#### 2.6 Exploration with Automatic Decay

**Uncertainty-Weighted Exploration:**

```python
# Decay formula
decay_factor = max(0.05, 1.0 - sample_count / (min_samples * 4))
effective_rate = base_rate * decay_factor

# Exploration: sample inversely proportional to experience count
weights = [1.0 / max(c.get("experience_count", 0), 1) for c in candidates]
chosen = random.choices(candidates, weights=weights, k=1)[0]
```

Exploration rate decays automatically as the agent accumulates experience (floor at 5%), and exploration selects less-tried candidates with probability inversely proportional to their experience count. This is a *passive uncertainty sampling* strategy that requires no explicit uncertainty estimation model.

#### 2.7 Federated Policy Learning with Alpha-Blended Global Baseline

```python
if use_global:
    alpha = min(1.0, tenant_policy.experience_count * blend_alpha_growth)
    tenant_policy._blend_alpha = alpha
    tenant_policy._global_weights = global_policy.weights
```

Tenant-specific policies are blended with a global baseline using an alpha coefficient that grows with the tenant's accumulated experience count. New tenants start with the global baseline (α≈0); experienced tenants weight their own history increasingly (α→1). This implements *federated reinforcement learning* at the application layer without model parameter sharing.

#### 2.8 Policy Rollout with Auto-Rollback

**A/B Experiment with Automatic Regression Detection:**

```python
ROLLBACK_REGRESSION_THRESHOLD = -0.15  # -15% regression triggers rollback

regression = (treatment_avg_reward - control_avg_reward) / abs(control_avg_reward)
if regression < ROLLBACK_REGRESSION_THRESHOLD:
    experiment.status = "aborted"
    candidate.status = "rejected"
```

Policy changes (e.g., routing more traffic to platform X) are rolled out as controlled A/B experiments. Running reward averages are maintained as Welford online updates. If the treatment arm shows >15% regression from the control baseline after a minimum sample size, the experiment auto-aborts and the candidate is rejected — without human intervention.

**Counterfactual Offline Evaluation:**

```python
exploration_filter = "action->>'routing_source' LIKE 'exploration_%'"
```

The offline evaluation system uses *only exploration-routed experiences* (those selected randomly for training purposes) as the basis for counterfactual evaluation. This addresses *selection bias* in observational RL data: experiences from the incumbent policy are not used to evaluate policy changes, ensuring the counterfactual comparison is unbiased.

**Auto-Generation of Policy Candidates:**

The `generate_routing_candidates()` function automatically generates `PolicyCandidate` records when any platform shows >10% reward improvement over another, using 7-day rejection cooldowns to prevent thrashing. This closes the self-improvement loop: the system can identify, evaluate, and rollout improvements without human authorship of policy changes.

#### 2.9 Agent Routing Decision Point

Every chat request logs an `agent_routing` RL experience with:
- Platform selected (claude_code, codex, gemini_cli)
- Agent slug, task type, trust score, autonomy tier
- Routing source (default, rl_platform, exploration_codex, rollout_treatment)
- State embedding of the enriched state text (task_type + entity categories + platform history)

This creates a *complete decision audit trail* for the routing policy, enabling the system to learn which platform-agent combinations perform best for which message types and entity contexts.

---

### INVENTION 3: Zero-LLM-Cost Deterministic Agent Router with Semantic Intent Classification and RL Override

#### 3.1 Two-Phase Routing Architecture

**Phase 1 — Deterministic (zero cost):**
- Channel-based default (whatsapp→luna, web→luna)
- Tenant-configured platform preference from `tenant_features.default_cli_platform`
- Session pinning: active Claude Code `--resume` session IDs prevent platform switching to preserve conversational context

**Phase 2 — Semantic Intent Classification (local, no cloud API):**
```python
INTENT_DEFINITIONS = [
    {"name": "check calendar or schedule", "tier": "light", "tools": ["calendar"], "mutation": False},
    {"name": "send email or compose message", "tier": "full", "tools": ["email"], "mutation": True},
    ...
]
```

At API startup, 28 canonical intent definitions are embedded with nomic-embed-text-v1.5. Each request embeds the user message and performs cosine similarity matching against the intent cache (entirely in-memory, no DB query). The best match above threshold (0.4) determines the *agent tier* (light vs full) and *tool groups*, without any LLM call.

Mutations (write operations) are always routed to the `full` tier for safety regardless of the intent match, implementing a *safety-conservative tier override*.

**Phase 3 — Agent Selection by Tool Overlap:**
```python
overlap = len(set(intent_tool_groups) & set(agent_candidate.tool_groups))
```
The agent with the highest tool_groups overlap with the detected intent is selected as the responding agent, along with its `memory_domains` configuration for scoped memory recall.

**Phase 4 — RL Override (when sufficient data):**
```python
if rl_rec.platform and rl_rec.platform_confidence >= 0.4:
    platform = rl_rec.platform
```
The RL routing system may override the default platform when confidence exceeds 0.4 (scaled to 50 experiences). This threshold prevents premature override on sparse data.

#### 3.2 Agent-Scoped Memory Loading

Memory recall parameters are scoped by the selected agent's tier and domain configuration:

```python
limits = TIER_LIMITS.get(agent_tier, TIER_LIMITS["full"])
# light: entities=3, observations_per_entity=1, include_relations=False
# full: entities=10, observations_per_entity=3, include_relations=True, include_episodes=True
```

A light-tier booking agent receives 3 entities from its domains; a full-tier code agent receives 10 entities, 3 observations each, plus git context. This implements *capability-scoped memory* that balances context richness with latency.

---

### INVENTION 4: Trust-Earned Autonomy Tier System Derived from RL Performance

#### 4.1 Dynamic Trust Score Computation

**Composite Trust Score:**

```python
# Signals
reward_signal = normalize_reward(avg_reward)      # From RL experiences
provider_signal = avg_agreement(provider_council)  # From multi-LLM reviews

# Confidence (how much data we have)
confidence = clamp((rated_count / 25.0) * 0.7 + (provider_review_count / 10.0) * 0.3)

# Blended trust score
trust_score = (reward_signal * 0.7 + provider_signal * 0.3) * confidence
             + DEFAULT_TRUST_SCORE * (1.0 - confidence)
```

The trust score is a *confidence-weighted blend* of two independent signals:
1. Local reward signal from automated quality scoring (70% weight)
2. Multi-provider agreement from cloud LLM council (30% weight)

Low-data agents default toward a neutral 0.5 score rather than 0.0, preventing premature penalization of new agents.

**4-Tier Autonomy Ladder:**

```python
def _derive_autonomy_tier(trust_score, confidence):
    if confidence < 0.2 or trust_score < 0.35:  return OBSERVE_ONLY
    if trust_score < 0.55:                        return RECOMMEND_ONLY
    if trust_score < 0.8:                         return SUPERVISED_EXECUTION
    return BOUNDED_AUTONOMOUS_EXECUTION
```

| Tier | Behavior | Novel Aspect |
|------|----------|--------------|
| observe_only | Can read (search/query) but cannot write | Read-only allowed to avoid deadlock — agent can gather evidence to earn promotion |
| recommend_only | Read allowed; writes require REQUIRE_REVIEW | Human review gate on all mutations |
| supervised_execution | Full access; high/critical risk → REQUIRE_REVIEW | Risk-gated, not capability-gated |
| bounded_autonomous_execution | High/critical risk → ALLOW_WITH_LOGGING only | Full trust, logging without blocking |

**Novel: Deadlock Prevention for observe_only:**

The `observe_only` tier deliberately allows read-only operations despite its restrictive name. Without this, new agents could never gather the evidence needed to demonstrate trustworthiness, creating a bootstrapping deadlock. The system solves this by allowing read operations (`risk_class="read_only" AND side_effect_level="none"`) even at the lowest tier.

#### 4.2 Evidence Pack System

For high-risk actions, the system requires an *evidence pack* before execution:

```python
class SafetyEvidencePack:
    world_state_facts: List       # What the agent knows about the current state
    recent_observations: List     # Evidence supporting the action
    assumptions: List             # Explicitly stated assumptions
    uncertainty_notes: List       # Known unknowns
    proposed_action: Dict         # Exactly what will be executed
    expected_downside: str        # Worst-case outcome
```

An evidence pack is *required* (blocking) for `REQUIRE_CONFIRMATION`, `REQUIRE_REVIEW`, and `BLOCK` decisions. A submitted pack that lacks context, proposed action, or downside analysis is insufficient, escalating the decision from `ALLOW` to `REQUIRE_REVIEW`. This implements *structured deliberation* for sensitive actions — requiring the agent to articulate its reasoning before acting, not just log after.

**Automated Channel Restriction:**

Channels that cannot collect inline human confirmation (workflow, webhook, local_agent) automatically escalate `REQUIRE_CONFIRMATION` to `REQUIRE_REVIEW`, routing decisions through the human review queue. This prevents automated channels from bypassing safety gates designed for interactive use.

#### 4.3 Profile Staleness Refresh

Trust profiles are automatically refreshed when stale (configurable via `TRUST_PROFILE_STALE_AFTER_HOURS`, default 6 hours). Each chat request calls `get_agent_trust_profile()` which silently recomputes from recent RL data when the profile is stale, ensuring the autonomy tier tracks recent performance without requiring explicit admin action.

---

### INVENTION 5: Temporal-Based Durable Dynamic Workflow Engine with Integration Awareness and RL Instrumentation

#### 5.1 JSON-Defined Workflow Execution

The `DynamicWorkflowExecutor` Temporal workflow interprets a JSON `definition.steps[]` array at runtime:

```json
{
  "steps": [
    {"id": "s1", "type": "mcp_tool", "tool": "search_emails", "params": {...}},
    {"id": "s2", "type": "condition", "condition": "{{s1.count}} > 0", "then": "s3", "else": "s4"},
    {"id": "s3", "type": "cli_execute", "task": "Summarize the emails found"}
  ]
}
```

Step types include: `mcp_tool`, `agent`, `condition`, `for_each`, `parallel`, `wait`, `transform`, `human_approval`, `webhook_trigger`, `workflow`, `continue_as_new` (infinite-duration), and `cli_execute` (dispatches CodeTaskWorkflow on the code worker queue). A single Temporal workflow handles all step types, eliminating the need for per-workflow Python code.

#### 5.2 Integration Awareness Gate

Before workflow activation, the system checks whether all required integrations are connected:

```python
TOOL_INTEGRATION_MAP = {
    "send_email": "gmail",
    "create_jira_issue": "jira",
    "search_github_code": "github",
    ...
    "find_entities": None,  # built-in, no integration
}
```

Workflows referencing `send_email` that have no Gmail OAuth token are blocked from activation with a specific missing-integration error, rather than failing at runtime. This is *pre-activation capability verification* — the integration check happens at design time, not execution time.

#### 5.3 RL and Memory Wiring

Every workflow run logs `workflow_execution` RL experiences; every step logs `workflow_step` RL experiences. Workflow lifecycle events are logged to `memory_activities`. This creates a complete audit trail of autonomous workflow actions that feeds back into the quality scoring and trust systems.

---

### INVENTION 6: Inference Bulkhead for Multi-Use Local LLM

#### 6.1 Novel Priority Architecture

The local Ollama inference service (`local_inference.py`) implements a two-level priority queue using OS-level threading primitives:

```python
_foreground_active = threading.Event()    # Shared cross-async/sync flag
_ollama_sync_lock  = threading.Lock()     # Sync foreground serialization
_background_lock   = threading.Lock()     # Background serialization
```

**Foreground** callers (user-blocking: free-tier response generation, tool agent) set `_foreground_active` while executing. **Background** callers (non-blocking: quality scoring, consensus review) check the flag with a non-blocking acquire before proceeding. If the flag is set, background callers *skip* their inference call rather than queue, ensuring the foreground always gets full GPU bandwidth.

This is a *degrade-background, protect-foreground* architecture distinct from standard thread pools or priority queues, which would still delay the foreground while background tasks execute.

**Cross-runtime coordination:** The same Event flag is checked by both async (background scorer) and sync (foreground tool agent) code paths, enabling coordination across Python's async and sync execution models without a shared event loop.

---

### INVENTION 7: Multi-Provider Cross-Validation Review Council via Temporal

#### 7.1 Architecture

For high-value or at-risk responses, a `ProviderReviewWorkflow` runs on the `servicetsunami-code` Temporal task queue, dispatching Claude, Codex, and Qwen simultaneously as independent reviewers:

```python
_SIDE_EFFECT_TOOLS = {"send_email", "create_jira_issue", "deploy_changes", "execute_shell"}

def _maybe_trigger_provider_council(...):
    if any(t in _SIDE_EFFECT_TOOLS for t in tools_called):  trigger
    elif consensus_fragile:                                    trigger
    elif adjusted_score < 40:                                 trigger
    elif random.random() < PROVIDER_COUNCIL_SAMPLE_RATE:     trigger
```

Triggers: (1) side-effect tools used, (2) fragile local consensus, (3) low score, (4) random sampling. Results from the council are merged into the original RL experience via a callback endpoint, providing a *ground truth signal* from heterogeneous evaluators.

**Fault isolation:** Provider failures are wrapped in `_safe_review()` handlers. A Qwen timeout does not abort the Claude review; the meta-adjudicator computes agreement over *all reviewers including failed ones* (failed reviewers are excluded from averages but counted in denominator), preventing a single provider failure from inflating the agreement score.

---

## PATENT CLAIMS — MEMORY SYSTEM

### Independent Claims

**Claim 1.** A computer-implemented method for multi-layer hierarchical memory recall in an AI agent system, comprising:
- maintaining a plurality of memory layers in a vector-indexed relational database, including entity memory, episodic memory, procedural memory, and semantic memory;
- receiving a natural language query from a user;
- generating a dense vector embedding of the query using a locally-hosted embedding model;
- performing a first-stage semantic search using cosine distance over stored entity embeddings and memory embeddings to retrieve candidate entities and memories;
- applying a keyword boost factor to entity candidates whose names match extracted query keywords, increasing their cosine similarity score by a predetermined boost value;
- applying a session continuity boost to entity candidates that appeared in earlier turns of the current conversation session;
- sorting all candidates by their boosted similarity scores;
- retrieving, for each top-ranked entity, semantically-relevant observations from a fact-store using a second-stage cosine search against the same query embedding;
- traversing a directed entity relation graph to retrieve two-hop neighbor entities of the top-ranked entities via a structured query;
- injecting anticipatory temporal context comprising the current time-of-day classification and upcoming calendar events within a configurable time window;
- querying a world-state assertion store for disputed or conflicting claims associated with the recalled entities and injecting those contradictions into the context payload;
- updating recall frequency counters on recalled entities and memories in the database; and
- logging the memory recall decision as a reinforcement learning experience record comprising the query state, the recall action, and candidate alternatives.

**Claim 2.** The method of claim 1, wherein the decay-adjusted memory similarity is computed as: `raw_cosine_similarity × max(floor_value, 1 - decay_rate × days_since_last_access)`, where `decay_rate` is a per-memory configurable coefficient, `floor_value` prevents complete decay, and the formula is evaluated in a database query without Python-side post-processing.

**Claim 3.** The method of claim 1, further comprising detecting when the embedding model is unavailable and automatically falling back to case-insensitive substring matching over entity names and memory content.

**Claim 4.** The method of claim 1, further comprising:
- extracting actionable suggestions from agent response text using pattern matching against a library of intent patterns;
- embedding each extracted suggestion with the locally-hosted embedding model;
- for each subsequent user message, computing cosine similarity between the user message embedding and pending suggestion embeddings;
- marking a suggestion as acted-upon when similarity exceeds a predetermined threshold, or when the user message matches a direct confirmation vocabulary; and
- aggregating acted-upon rates per suggestion type and injecting the statistics into subsequent agent system prompts as self-calibration feedback.

**Claim 5.** The method of claim 1, wherein the user/owner entity is pinned at the first position of the recalled entity list regardless of its semantic similarity score, ensuring user identity information is always present in the agent's working context.

### Dependent Claims

**Claim 6.** The method of claim 1, wherein generating the dense vector embedding uses a locally-hosted 768-dimensional embedding model operating without network calls to external APIs, enabling zero-cloud-cost memory operations.

**Claim 7.** The method of claim 1, wherein the episodic memory layer comprises conversation episode records, each containing a compressed narrative summary, key entities, mood classification, and a 768-dimensional embedding of the summary, enabling semantically-relevant past conversation retrieval for present-tense context building.

**Claim 8.** The method of claim 1, further comprising: detecting whether the user query contains code-related keywords; and, if so, appending semantically-matched version control artifacts (commit messages, pull request descriptions, file hotspot records) from the observation store to the memory context payload.

**Claim 9.** A non-transitory computer-readable medium storing instructions that, when executed by one or more processors, implement the method of any of claims 1-8.

**Claim 10.** A system for multi-layer hierarchical memory recall comprising: one or more processors; memory storing a vector-indexed relational database comprising entity, memory, relation, observation, episode, and world-state-assertion tables; an embedding model executing locally on the system; and a recall engine configured to execute the method of claim 1.

---

## PATENT CLAIMS — REINFORCEMENT LEARNING SYSTEM

### Independent Claims

**Claim 11.** A computer-implemented system for autonomous quality improvement of AI agent responses using local reinforcement learning, comprising:
- a response quality scorer configured to asynchronously score agent responses after they are delivered to users, using a locally-hosted language model and a multi-dimensional quality rubric comprising weighted categories for accuracy, helpfulness, tool usage, memory usage, efficiency, and context awareness;
- a parallel consensus review council comprising three specialized review agents executing concurrently on the local language model, each evaluating a different quality dimension, and a majority-vote consensus mechanism that produces a consensus signal including a fragility flag set when the approval count equals the minimum required approvals;
- a composite reward computation module that blends the rubric score and the consensus disapproval ratio into a single scalar reward value in the range [-1.0, +1.0], with a proportional penalty applied for consensus failures;
- a scorer confidence registry that assigns reliability weights to rewards based on their source, wherein automated single-model rewards receive lower weights than consensus rewards, which receive lower weights than human-provided ratings;
- a reinforcement learning experience store that records decision states with 768-dimensional dense vector embeddings, actions, rewards, reward components, and scorer confidence weights;
- a policy engine that retrieves semantically-similar past experiences using cosine distance search and scores candidate actions using reward-weighted regression with exponential recency decay; and
- a policy rollout manager that conducts A/B experiments for policy candidates and automatically aborts experiments when treatment performance regresses from the control baseline by more than a configurable threshold.

**Claim 12.** The system of claim 11, wherein the response quality scorer is executed in a daemon background thread that completes after the agent response has been returned to the user, such that scoring latency is decoupled from user-visible response latency.

**Claim 13.** The system of claim 11, wherein a GPU inference bulkhead comprising a shared threading.Event coordinates between foreground user-blocking inference and background quality-scoring inference, such that background scoring inference is skipped rather than queued when foreground inference is active.

**Claim 14.** The system of claim 11, wherein the policy engine selects actions by:
- retrieving the N most semantically-similar past experiences via pgvector cosine search;
- computing a score for each candidate action as a weighted sum of rewards from matching experiences, wherein each weight is the product of the experience's cosine similarity to the current state and an exponential time-decay factor parameterized by a half-life in days; and
- selecting the highest-scoring candidate during exploitation phases and sampling candidates with probability inversely proportional to their experience count during exploration phases.

**Claim 15.** The system of claim 11, wherein a routing decision that selects a platform for a conversation turn receives the quality reward produced by the response generated on that platform via a deferred reward assignment, whereby the reward is propagated backward to the routing decision using a structured query that matches trajectory identifiers.

**Claim 16.** The system of claim 11, wherein policy candidates are automatically generated by analyzing per-platform reward distributions across accumulated routing experiences and proposing routing changes when any platform shows reward improvement above a minimum threshold, subject to a rejection cooldown period to prevent rapid policy thrashing.

**Claim 17.** The system of claim 11, further comprising a multi-provider review council that executes only when triggered by at least one of: (a) the agent response used tools with external side effects, (b) the local consensus result is fragile, (c) the composite reward is below a low-quality threshold, or (d) a random sample rate, wherein the multi-provider council independently evaluates the response using heterogeneous AI providers and merges its agreement score into the existing reinforcement learning experience record.

**Claim 18.** The system of claim 11, wherein policy experiments use only exploration-routed experiences (experiences selected by a randomized exploration policy, not the incumbent routing policy) as the counterfactual baseline, preventing selection bias in offline policy evaluation.

### Dependent Claims

**Claim 19.** The system of claim 11, wherein tenant-specific policy weights are alpha-blended with a global baseline policy, wherein the blending coefficient alpha is computed as a monotonically increasing function of the tenant's accumulated experience count, such that new tenants inherit the global baseline and experienced tenants weight their own history increasingly.

**Claim 20.** The system of claim 11, wherein the quality rubric additionally produces cost-efficiency metrics comprising tokens-per-quality-point and a platform recommendation, such that each scored experience contributes both a quality signal and a cost-optimization signal to the reinforcement learning history.

**Claim 21.** A non-transitory computer-readable medium storing instructions that, when executed by one or more processors, implement the system of any of claims 11-20.

**Claim 22.** A method for deriving agent execution authority from reinforcement learning reward signals, comprising:
- computing a composite trust score from a first signal derived from average RL reward over agent-attributed experiences and a second signal derived from inter-reviewer agreement in multi-provider evaluation councils, weighted by a confidence coefficient that scales with the number of accumulated rated experiences;
- mapping the trust score to a discrete autonomy tier from a monotonically ordered set of tiers;
- enforcing execution restrictions on agent actions based on the assigned autonomy tier, wherein lower tiers block high-risk operations, intermediate tiers require human review, and the highest tier permits all operations with logging;
- automatically refreshing trust profiles when stale by recomputing from recent RL data without explicit administrator action; and
- allowing read-only operations at the lowest autonomy tier to prevent bootstrapping deadlock for new agents lacking prior RL history.

---

## PRIOR ART CONSIDERATIONS

### Memory Systems

- **MemGPT (Packer et al., 2024):** Addresses long-term memory for LLMs but uses a single unified memory store, lacks multi-signal boosting (semantic + keyword + session), does not log recall decisions as RL experiences, and does not implement decay-adjusted retrieval in SQL.
- **LangChain Memory:** Provides conversation buffer and entity memory but lacks graph traversal, episodic synthesis, anticipatory context injection, and RL integration.
- **Microsoft GraphRAG:** Addresses knowledge graph construction from documents but is not an agent memory system and does not implement the hybrid recall pipeline described herein.

**Distinguishing features:** The claimed invention's novelty lies in: (1) the specific combination of all five boosting mechanisms in a single call, (2) decay-adjustment in SQL, (3) RL instrumentation of recall decisions, (4) behavioral follow-through detection as a separate signal from quality scoring, and (5) the evidence pack system requiring structured deliberation.

### Reinforcement Learning for Agents

- **RLHF (Ouyang et al., 2022):** Requires human labelers; system described herein uses fully automated scoring with local models and no human labeling for baseline operation.
- **Constitutional AI (Bai et al., 2022):** AI-provided feedback but uses cloud API calls; system described herein operates exclusively on local models (Qwen2.5, Ollama) with zero cloud inference cost for quality control.
- **LLM-as-a-Judge (Zheng et al., 2023):** Single evaluator without consensus mechanisms, fragility detection, or routing reward backfill.
- **AutoRL / PbRL systems:** Prior work applies RL to game environments or single-objective tasks; system described herein applies a 15-decision-point RL system across the full agent task stack (routing, memory, tool selection, response generation, workflow execution).

**Distinguishing features:** (1) fire-and-forget async scoring with GPU bulkhead, (2) fragility detection in majority-vote consensus, (3) scorer confidence weighting, (4) routing-to-response reward backfill, (5) counterfactual offline evaluation using only exploration data, (6) auto-regression-rollback in A/B experiments, (7) federated policy blending with experience-count-scaled alpha.

### Agent Safety

- **Constitutional AI guardrails:** Static policy at inference time; system described herein derives execution authority dynamically from performance history.
- **OpenAI tool use safety:** Binary allow/block; system described herein implements a 4-tier graduated autonomy with evidence packs and automated channel restrictions.

---

## FIGURES / DIAGRAMS (TO BE PREPARED BY PATENT COUNSEL)

**FIG. 1** — Multi-Layer Memory Architecture: five memory layers (entity, episodic, procedural, semantic, journal), their database tables, and the hybrid recall pipeline with boost mechanisms.

**FIG. 2** — Hybrid Recall Algorithm Flowchart: 16-step pipeline from user message to memory context, including embedding, semantic search, keyword boost, session boost, owner pinning, observation retrieval, graph traversal, anticipatory context, episode recall, and RL logging.

**FIG. 3** — RL Pipeline End-to-End: decision points, experience logging, async scoring, consensus council, reward computation, policy engine, rollout, auto-rollback.

**FIG. 4** — Consensus Council Architecture: three parallel reviewers, majority vote, fragility detection, penalty blending, provider council trigger.

**FIG. 5** — GPU Inference Bulkhead: foreground/background priority coordination using threading.Event across sync and async code paths.

**FIG. 6** — Trust-Earned Autonomy Tier System: RL rewards → trust score → autonomy tier → execution authority, with evidence pack requirement for sensitive actions.

**FIG. 7** — Agent Router Multi-Phase Architecture: deterministic default → semantic intent classification → tool-group agent selection → RL override → policy rollout.

**FIG. 8** — Reward-Weighted Regression with Dual Exponential Decay: candidate scoring formula combining cosine similarity and recency decay.

**FIG. 9** — A/B Policy Rollout with Auto-Rollback: running reward averages, regression threshold, auto-abort.

**FIG. 10** — Multi-Provider Review Council via Temporal: trigger conditions, parallel execution, fault isolation, experience merge.

---

## IMPLEMENTATION DETAILS

| Component | Technology | Location |
|-----------|-----------|----------|
| Embedding model | nomic-ai/nomic-embed-text-v1.5 (768-dim, sentence-transformers) | Local, API container |
| Vector database | PostgreSQL + pgvector extension | `apps/api/app/models/` |
| Local LLM inference | Ollama (qwen2.5-coder:1.5b, qwen3:1.7b) | Local, ollama container |
| Workflow engine | Temporal.io | `apps/api/app/workers/` |
| RL experience store | PostgreSQL JSONB + pgvector | `rl_experiences` table |
| Trust profiles | PostgreSQL | `agent_trust_profiles` table |
| Memory layers | PostgreSQL | `knowledge_entities`, `agent_memories`, `conversation_episodes`, `session_journals`, `knowledge_observations` |
| Policy rollout | PostgreSQL | `learning_experiments`, `policy_candidates` |

---

## SUMMARY OF NOVEL CONTRIBUTIONS

1. **Hybrid multi-signal memory recall** with semantic search, keyword boost, session boost, owner pinning, decay adjustment in SQL, and RL instrumentation — all in a single pipeline call.

2. **Fragility-detected local consensus review** as a quality signal distinct from the primary rubric scorer, with proportional penalty blending and automatic escalation trigger.

3. **Scorer confidence weighting** as a first-class RL experience attribute, enabling the policy engine to discount low-reliability scores without discarding them.

4. **Routing-to-response reward backfill** implementing deferred credit assignment for platform selection decisions using trajectory identifiers.

5. **Counterfactual offline evaluation** using exploration-only experiences to eliminate selection bias in policy candidate evaluation.

6. **Trust-earned autonomy tiers** derived from RL reward history with confidence-weighted blending of local scoring and multi-provider agreement signals.

7. **Bootstrapping deadlock prevention** in the observe-only autonomy tier by permitting read-only operations.

8. **Auto-regression rollback** in A/B policy experiments using online reward average tracking and configurable regression thresholds.

9. **Federated policy learning** via experience-count-scaled alpha blending of tenant-specific and global baseline policies.

10. **GPU inference bulkhead** using threading.Event for cross-runtime (async/sync) foreground/background priority coordination.

11. **Behavioral follow-through detection** using semantic similarity between agent suggestions and subsequent user messages as a ground-truth quality signal independent of LLM scoring.

12. **Pre-activation integration verification** for dynamic workflows checking integration connectivity before execution, not at runtime.

---

*This disclosure was prepared on 2026-04-04 based on code analysis of the ServiceTsunami AI Agent Orchestration Platform codebase. All claims, prior art analysis, and technical descriptions should be reviewed by registered patent counsel before filing.*
