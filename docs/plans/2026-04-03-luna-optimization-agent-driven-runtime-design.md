# Luna Optimization & Agent-Driven Runtime

**Date:** 2026-04-03
**Status:** Draft
**Scope:** Token optimization, model tiering, agent-scoped context loading, infrastructure fixes

## Problem

Every user message — from "hi" to "refactor the auth system" — takes the same heavy path:

1. Luna loads her full persona (~19.6k chars / ~3k tokens)
2. Memory recall runs 15-20 pgvector queries fetching ALL entities, observations, relations, episodes
3. Self-model, world state, goals, commitments all injected
4. All 81 MCP tool schemas loaded
5. Full Temporal workflow cycle (dispatch → code-worker → Claude CLI → return)
6. Memory recall runs TWICE (agent_router + cli_session_manager)
7. SSE streaming is fake — waits for full response then chunks it

Result: ~3500-8000 tokens consumed and 500-1200ms overhead before Claude even starts generating. Simple conversational messages get the same treatment as complex multi-tool workflows. Token cost and latency are unnecessarily high for the majority of messages.

Additionally, Luna is the bottleneck for all tenants. A vet clinic's booking agent, an ecommerce support agent, and a research assistant all route through Luna's generalist persona, loading tools and context they don't need.

## Goals

1. Reduce token consumption by 50-75% for simple/medium messages
2. Reduce response latency for conversational messages
3. Enable specialist agents to handle their domains independently with scoped context
4. Maintain accuracy and full tool access for complex tasks
5. Let the RL system learn optimal routing over time per-tenant
6. No breaking changes — existing tenants keep working as-is

## Non-Goals

- Moving off Claude CLI / Temporal architecture (Approach B — optimize in-place)
- Building a separate direct API path
- Replacing Luna entirely — she remains the default for new tenants

## Design

### 1. Model Tier Routing (RL-Driven)

Extend the existing `agent_router.py` routing decision with a new dimension: model tier selection.

**Current routing decision:**
```json
{"platform": "claude_code", "agent": "luna"}
```

**Extended:**
```json
{
  "platform": "claude_code",
  "agent": "booking-agent",
  "model_tier": "light",
  "tool_groups": ["calendar", "email"],
  "entity_count": 3,
  "prompt_tokens": 1500
}
```

**Two tiers:**

| Tier | Model | Use Cases |
|------|-------|-----------|
| Light | Claude Haiku 4.5 | Conversational, memory lookups, single tool calls, read-only queries |
| Full | Claude Sonnet 4.6 | Multi-step reasoning, mutations, code generation, complex analysis, multi-tool orchestration |

Each CLI platform has equivalents: Codex mini (Light) / Codex (Full), Gemini Flash (Light) / Gemini (Full).

**Tier selection uses embedding-based intent classification** for the initial heuristic:

At API startup, embed ~20-30 canonical intent descriptions in memory (not DB) using the existing `nomic-embed-text-v1.5` model. Each intent carries metadata:

```
Intent: "greeting or small talk"
  → tier: light, tools: [], mutation: false

Intent: "check calendar or schedule"
  → tier: light, tools: [calendar], mutation: false

Intent: "book appointment or create reservation"
  → tier: full, tools: [calendar, email], mutation: true

Intent: "process order refund or cancellation"
  → tier: full, tools: [ecommerce], mutation: true

Intent: "analyze data or compare metrics"
  → tier: full, tools: [data, reports], mutation: false
```

Per message: embed the user text (already happening), cosine-match against the in-memory intent vectors — no DB query, ~10ms, fully language-agnostic (Spanish and English both match the same intents via nomic's multilingual embeddings).

**Routing rules:**
- Similarity score < 0.4 → default to Full (safe fallback)
- Any mutation detected → always Full
- Multi-tool chain detected → always Full
- Otherwise → use matched intent's tier

**RL integration:** The intent heuristic is the cold-start default policy. The existing RL system learns from quality scores whether the tier was appropriate:

- Light tier on complex task → low accuracy/helpfulness → negative reward → RL learns to use Full
- Full tier on simple greeting → high scores but low efficiency → RL learns to use Light

**Exploration config** in `decision_point_config`:
```json
{
  "decision_point": "model_tier_selection",
  "exploration_rate": 0.25,
  "min_samples_before_exploit": 30
}
```

25% exploration rate. Approximately 120 messages needed to accumulate minimum exploration data for the most common message patterns. Actual policy convergence depends on pattern diversity and quality score variance.

**Exploration rate decay** (new — does not exist in current RL policy engine): As sample count grows past `min_samples_before_exploit`, reduce exploration rate to avoid wasting tokens on already-learned patterns:

```python
effective_rate = base_rate * max(0.05, 1.0 - sample_count / (min_samples_before_exploit * 4))
# At 30 samples: 0.25 * max(0.05, 1.0 - 30/120) = 0.25 * 0.75 = 0.1875
# At 120 samples: 0.25 * max(0.05, 1.0 - 120/120) = 0.25 * 0.05 = 0.0125
```

This needs to be added to `rl_policy_engine.py` as part of this work.

**Model tier to CLI flag mapping:**

| Platform | Light | Full |
|----------|-------|------|
| Claude Code | `--model claude-haiku-4-5-20251001` | `--model claude-sonnet-4-6-20250514` |
| Codex CLI | `--model codex-mini` | `--model codex` |
| Gemini CLI | `--model gemini-2.5-flash` | `--model gemini-2.5-pro` |

The `ChatCliInput` dataclass gets a new `model` field. The code-worker activity passes it as `--model <slug>` to the CLI subprocess, overriding the default `CLAUDE_CODE_MODEL` env var.

### 2. Agent-Driven Runtime

The responding agent's configuration drives context loading, not a hardcoded Luna path.

**New fields on the existing `agent` table:**

| Field | Type | Purpose | Example |
|-------|------|---------|---------|
| `tool_groups` | JSONB | Tool group keys this agent uses | `["calendar", "email"]` |
| `default_model_tier` | VARCHAR | Agent's default tier | `"light"` or `"full"` |
| `persona_prompt` | TEXT | Compact persona prompt | ~2-5k chars |
| `memory_domains` | JSONB | Entity categories this agent cares about | `["client", "appointment"]` |
| `escalation_agent_id` | UUID FK | Who to escalate to when out of scope | Luna's agent ID |

**Tool groups** — MCP tools organized into logical groups, cached at startup:

```
calendar:   [list_calendar_events, create_calendar_event]
email:      [search_emails, send_email, read_email, download_attachment]
ecommerce:  [query_sql, generate_excel_report]
knowledge:  [search_knowledge, find_entities, recall_memory, record_observation]
sales:      [qualify_lead, update_pipeline_stage, draft_outreach]
bookings:   [list_calendar_events, create_calendar_event, schedule_followup]
data:       [query_sql, query_data_source, discover_datasets, get_dataset_schema]
reports:    [generate_excel_report, generate_insights, forecast, compare_periods]
github:     [list_github_repos, get_github_issue, search_github_code, create_github_issue]
jira:       [search_jira_issues, create_jira_issue, update_jira_issue]
competitor: [list_competitors, add_competitor, get_competitor_report]
ads:        [list_meta_campaigns, list_google_campaigns, get_meta_campaign_insights]
monitor:    [start_inbox_monitor, start_competitor_monitor, check_inbox_monitor_status]
drive:      [search_drive_files, read_drive_file, create_drive_file, list_drive_folders]
shell:      [execute_shell, deploy_changes]
workflows:  [list_dynamic_workflows, create_dynamic_workflow, run_dynamic_workflow]
```

An agent with `tool_groups: ["calendar", "email"]` loads ~10 tools instead of 81.

**Tool filtering mechanism:** Claude Code CLI supports `--allowedTools` glob patterns. The code-worker activity passes tool filters based on the agent's `tool_groups`:

```bash
# Booking agent with tool_groups: ["calendar", "email"]
claude -p --model claude-haiku-4-5-20251001 \
  --allowedTools "mcp__servicetsunami__list_calendar_events,mcp__servicetsunami__create_calendar_event,mcp__servicetsunami__search_emails,mcp__servicetsunami__send_email,mcp__servicetsunami__read_email,mcp__servicetsunami__download_attachment"
```

The tool group registry (cached at startup) maps group keys to MCP tool names. The `ChatCliInput` dataclass gets a new `allowed_tools` field containing the resolved tool name list. For Codex and Gemini CLI, equivalent tool filtering flags will be used (or all tools loaded if no filtering flag is available for that platform).

Tools not in any group are assigned to a `_misc` catch-all group. Tenant-specific tool modules (aremko, supermarket, devices) are excluded from the default grouping and only available when explicitly assigned to an agent.

**Memory scoping** — `build_memory_context()` receives a `domains` filter. A booking agent with `memory_domains: ["client", "appointment"]` only recalls entities matching those categories. The filter goes into the pgvector query's WHERE clause on `knowledge_entity.category`.

**Escalation** — If the intent match confidence is low or the user explicitly asks for something outside scope, the agent escalates to `escalation_agent_id` (typically Luna). Luna remains the safety net without being the bottleneck.

**Agent selection logic:** When multiple agents exist in a tenant's kit, the router selects the responding agent by matching the intent's `tool_groups` against each agent's `tool_groups` field. The agent with the highest tool group overlap wins. Ties are broken by checking `memory_domains` overlap with the inferred topic. If no specialist agent matches (overlap = 0 or confidence < 0.4), the message falls through to Luna as the default generalist. Agents with `escalation_agent_id` set can also explicitly escalate mid-conversation if the user's follow-up goes out of their scope.

**Runtime flow:**
```
User message
  → embed message, cosine-match against intent vectors
  → match intent tool_groups against tenant's agent tool_groups → select agent
  → load THAT agent's config (tool_groups, persona, memory_domains, default_tier)
  → RL adjusts tier if it has learned a better policy
  → cli_session_manager builds context using agent's scoped config
  → dispatch to CLI with --model and --allowedTools based on agent + tier
```

**Agent creation wizard** — Existing templates (booking, ecommerce, vet, HR, etc.) populate the new fields with sensible defaults. A tenant creating a "Bookings Agent" from the template gets tool_groups, memory_domains, and a compact persona pre-filled.

### 3. Scoped Context Loading

`cli_session_manager.generate_cli_instructions()` loads context based on the responding agent and tier.

**Tiered token budgets:**

| Component | Light (Haiku) | Full (Sonnet) |
|-----------|--------------|---------------|
| Skill/persona prompt | Agent's `persona_prompt` (~2-5k chars) | Agent's `persona_prompt` or full skill |
| Memory recall | Top 3 entities, 1 observation each, no relations | Top 10 entities, 3 observations each, relations, episodes |
| Self-model | Identity only | Identity + goals + commitments |
| World state | Skip | Full injection |
| Conversation history | Last 4 messages | Last 6 messages |
| MCP tool schemas | Agent's tool_groups subset (~5-15 tools) | Agent's tool_groups or all |
| **Estimated total** | **~2000-3500 tokens** | **~4000-8000 tokens** |

Note: Token estimates include MCP tool schemas (~100-200 tokens per tool). A 10-tool subset adds ~1000-2000 tokens; all 81 tools add ~3000-4000 tokens. Exact counts will be validated during implementation by measuring representative tool groups.

**Implementation in `generate_cli_instructions(agent, tier)`:**

```python
TIER_LIMITS = {
    "light": {
        "entities": 3,
        "observations_per_entity": 1,
        "include_relations": False,
        "include_episodes": False,
        "include_world_state": False,
        "include_goals": False,
        "history_messages": 4,
    },
    "full": {
        "entities": 10,
        "observations_per_entity": 3,
        "include_relations": True,
        "include_episodes": True,
        "include_world_state": True,
        "include_goals": True,
        "history_messages": 6,
    },
}
```

**Memory recall scoping** — `build_memory_context()` signature extends:

```python
def build_memory_context(
    message: str,
    tenant_id: UUID,
    domains: list[str] | None = None,      # agent's memory_domains
    max_entities: int = 10,                  # from tier limits
    max_observations: int = 3,               # from tier limits
    include_relations: bool = True,          # from tier limits
    include_episodes: bool = True,           # from tier limits
) -> dict:
```

When `domains` is provided, the pgvector search adds `WHERE category IN (domains)` to the entity query. This reduces both query time and result size.

**Token impact estimates:**

| Scenario | Current | Optimized | Savings |
|----------|---------|-----------|---------|
| Booking agent, Light tier | ~6000 tokens | ~1500 tokens | 75% |
| Booking agent, Full tier | ~6000 tokens | ~3000 tokens | 50% |
| Luna generalist, Light tier | ~6000 tokens | ~3000 tokens | 50% |
| Luna generalist, Full tier | ~6000 tokens | ~6000 tokens | 0% (unchanged) |

### 4. Infrastructure Fixes

Three fixes that apply regardless of agent or tier.

**Fix 1: Eliminate double memory recall**

The agent_router already builds `pre_built_memory_context` and passes it to `run_agent_session()`. The cli_session_manager already checks for it (`if pre_built_memory_context is not None`). The double-recall only happens in edge cases where `recalled_entities` is provided externally but `pre_built_memory_context` is not built. Fix: ensure `pre_built_memory_context` is always set when `recalled_entities` is provided, so cli_session_manager never re-calls `build_memory_context_with_git()`.

**Fix 2: Fix fake streaming**

Currently `chat.py` (routes layer) waits for the complete response from Temporal, then fake-streams the finished text in chunks via SSE. Fix using Redis pubsub as a streaming side channel:

1. The code-worker activity publishes CLI stdout lines to Redis channel `stream:{workflow_id}` as they arrive
2. The SSE endpoint subscribes to `stream:{workflow_id}` and emits tokens to the browser in real-time
3. On workflow completion, the activity publishes a `{"done": true}` sentinel
4. The SSE endpoint has a 180s timeout — if no message arrives within that window, it falls back to polling the Temporal workflow result directly
5. If Redis is unavailable, the system falls back to the current fake-streaming behavior (graceful degradation)

First-token latency drops from "wait for full response" to "wait for first CLI output line."

This is the most complex fix. Implement last, after tier routing and scoped context are working.

**Fix 3: Compact skill prompts**

Each agent template ships with a compact persona prompt (2-5k chars) that captures voice and behavior rules without examples and edge-case verbosity. Luna herself gets a compact version for Light tier and the full version for Full tier. Both maintained in the skill file.

### 5. RL Integration

The existing RL system learns from the new routing dimensions without architectural changes.

**Extended RL experience action:**
```json
{
  "platform": "claude_code",
  "agent": "booking-agent",
  "model_tier": "light",
  "tool_groups": ["calendar", "email"],
  "entity_count": 3,
  "prompt_tokens": 1500
}
```

**Reward signal** — unchanged. The auto quality scorer's 6-dimension rubric naturally captures tier appropriateness:

- Low accuracy/helpfulness → tier was too light → negative reward
- High scores + low efficiency → tier was too heavy → RL learns to use Light
- Low tool_usage → wrong tool subset → RL learns correct groups

**Exploration:** 25% exploration rate, 30 samples before exploitation. Approximately 120 messages needed to accumulate minimum exploration data for common patterns. Exploration rate decays via the new decay function added to `rl_policy_engine.py` (see Section 1).

**Tier misclassification recovery:** If a Light-tier response receives negative explicit feedback (thumbs down) or the auto-scorer scores below 40, the system automatically retries the same message on Full tier and logs the tier switch as an RL experience with negative reward for the Light decision. This prevents individual users from suffering while the RL system learns.

### 6. Migration Path

No breaking changes. Gradual, per-tenant transition.

**Phase 1 — Immediate (all tenants):** Infrastructure fixes (double-recall, token budgets on existing Luna path). Every tenant benefits without configuration changes.

**Phase 2 — New tenants:** Luna remains the default agent. New fields on agent table have sensible defaults (tool_groups=null means all, memory_domains=null means all, default_model_tier="full"). Luna works exactly as today but with token budgets.

**Phase 3 — Tenant creates specialists:** Via the existing wizard templates. Templates pre-populate tool_groups, memory_domains, persona_prompt, default_model_tier. Agent router starts considering specialist agents as candidates.

**Phase 4 — Luna offloads naturally:** As specialist agents handle more message types, Luna handles less. She's still there for anything that doesn't match a specialist. A tenant that never creates specialists keeps using Luna with the optimized token budgets.

No migration switch. No forced changes. Tenants graduate at their own pace.

## Files Affected

| File | Changes |
|------|---------|
| `apps/api/app/models/agent.py` | New fields: tool_groups, default_model_tier, persona_prompt, memory_domains, escalation_agent_id |
| `apps/api/app/services/agent_router.py` | Tier selection, intent classifier, extended RL logging |
| `apps/api/app/services/cli_session_manager.py` | Agent-driven context loading, tier-based budgets, accept pre-built memory |
| `apps/api/app/services/memory_recall.py` | Domain filtering, budget parameters, skip double-recall |
| `apps/api/app/services/embedding_service.py` | Intent embedding cache at startup |
| `apps/api/app/services/auto_quality_scorer.py` | Log extended action (tier, tools) to RL |
| `apps/api/app/services/rl_experience_service.py` | Extended action schema |
| `apps/api/app/api/v1/chat.py` | Real streaming via side channel (Fix 2) |
| `apps/api/app/workflows/` | Pass model tier to CLI subprocess |
| `apps/web/src/components/wizard/` | Template defaults for new agent fields |
| `mcp-tools/` | Tool group metadata/tags |
| `apps/api/migrations/` | New columns on agent table |
