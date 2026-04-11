# Luna Optimization & Agent-Driven Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Luna's token consumption by 50-75% and response latency by adding model tiering (Haiku/Sonnet), agent-scoped context loading, and infrastructure fixes.

**Architecture:** Extend the existing agent_router with embedding-based intent classification to select model tier (light/full) and responding agent. Each agent declares its tool groups and memory domains, which drive scoped context loading in cli_session_manager. RL learns optimal tier per tenant over time.

**Tech Stack:** Python 3.11, SQLAlchemy, FastAPI, nomic-embed-text-v1.5, pgvector, Temporal, Claude Code CLI

**Spec:** `docs/plans/2026-04-03-luna-optimization-agent-driven-runtime-design.md`

**PR #106 conflict avoidance:** Do NOT modify `apps/web/src/components/workflows/`, `apps/web/src/pages/WorkflowsPage.js`, `apps/api/app/api/v1/dynamic_workflows.py`, `apps/mcp-server/src/mcp_tools/dynamic_workflows.py`, or `scripts/local-deploy.sh`.

---

## Task 1: Database Migration — Agent Tier Fields

**Files:**
- Create: `apps/api/migrations/082_add_agent_tier_and_toolgroups.sql`
- Modify: `apps/api/app/models/agent.py`
- Modify: `apps/api/app/schemas/agent.py`

- [ ] **Step 1: Write migration SQL**

```sql
-- Migration 082: Add agent-driven runtime fields
-- Supports: model tier routing, tool group scoping, memory domain filtering, escalation

ALTER TABLE agents ADD COLUMN IF NOT EXISTS tool_groups JSONB;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS default_model_tier VARCHAR(10) DEFAULT 'full';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS persona_prompt TEXT;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS memory_domains JSONB;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS escalation_agent_id UUID REFERENCES agents(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_agents_tool_groups ON agents USING GIN(tool_groups);
CREATE INDEX IF NOT EXISTS idx_agents_memory_domains ON agents USING GIN(memory_domains);
CREATE INDEX IF NOT EXISTS idx_agents_escalation_id ON agents(escalation_agent_id);
```

Create file at `apps/api/migrations/082_add_agent_tier_and_toolgroups.sql`.

- [ ] **Step 2: Add columns to Agent model**

In `apps/api/app/models/agent.py`, add after existing columns:

```python
from sqlalchemy.dialects.postgresql import JSONB

tool_groups = Column(JSONB, nullable=True)  # ["calendar", "email"]
default_model_tier = Column(String(10), default="full")  # "light" or "full"
persona_prompt = Column(Text, nullable=True)  # compact persona ~2-5k chars
memory_domains = Column(JSONB, nullable=True)  # ["client", "appointment"]
escalation_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
```

- [ ] **Step 3: Update Pydantic schemas**

In `apps/api/app/schemas/agent.py`, add to `AgentBase`:

```python
tool_groups: Optional[List[str]] = None
default_model_tier: str = "full"
persona_prompt: Optional[str] = None
memory_domains: Optional[List[str]] = None
escalation_agent_id: Optional[uuid.UUID] = None
```

- [ ] **Step 4: Commit**

```bash
git add apps/api/migrations/082_add_agent_tier_and_toolgroups.sql apps/api/app/models/agent.py apps/api/app/schemas/agent.py
git commit -m "feat: add agent tier, tool_groups, memory_domains, escalation fields"
```

---

## Task 2: Tool Groups Registry

**Files:**
- Create: `apps/api/app/services/tool_groups.py`

- [ ] **Step 1: Create tool groups registry**

Create `apps/api/app/services/tool_groups.py`:

```python
"""Tool group registry for agent-scoped MCP tool loading.

Maps logical tool group keys to MCP tool names. Agents declare which groups
they need via agent.tool_groups. At runtime, only tools from declared groups
are passed to the CLI via --allowedTools.
"""

TOOL_GROUPS: dict[str, list[str]] = {
    "calendar": [
        "list_calendar_events",
        "create_calendar_event",
    ],
    "email": [
        "search_emails",
        "send_email",
        "read_email",
        "download_attachment",
        "search_drive_files",
    ],
    "ecommerce": [
        "query_sql",
        "generate_excel_report",
        "query_data_source",
    ],
    "knowledge": [
        "search_knowledge",
        "find_entities",
        "recall_memory",
        "record_observation",
        "create_entity",
        "create_relation",
        "find_relations",
        "get_neighborhood",
        "ask_knowledge_graph",
        "merge_entities",
        "update_entity",
        "get_entity_timeline",
    ],
    "sales": [
        "qualify_lead",
        "update_pipeline_stage",
        "draft_outreach",
        "get_pipeline_summary",
        "schedule_followup",
    ],
    "bookings": [
        "list_calendar_events",
        "create_calendar_event",
        "schedule_followup",
        "search_emails",
        "send_email",
    ],
    "data": [
        "query_sql",
        "query_data_source",
        "discover_datasets",
        "get_dataset_schema",
    ],
    "reports": [
        "generate_excel_report",
        "generate_insights",
        "forecast",
        "compare_periods",
    ],
    "github": [
        "list_github_repos",
        "list_github_issues",
        "list_github_pull_requests",
        "get_github_issue",
        "get_github_pull_request",
        "get_github_repo",
        "search_github_code",
        "read_github_file",
        "get_git_history",
        "get_pr_status",
    ],
    "jira": [
        "list_jira_projects",
        "search_jira_issues",
        "get_jira_issue",
        "create_jira_issue",
        "update_jira_issue",
    ],
    "competitor": [
        "list_competitors",
        "add_competitor",
        "remove_competitor",
        "get_competitor_report",
        "check_competitor_monitor_status",
        "start_competitor_monitor",
        "stop_competitor_monitor",
    ],
    "ads": [
        "list_meta_campaigns",
        "list_google_campaigns",
        "list_tiktok_campaigns",
        "get_meta_campaign_insights",
        "get_google_campaign_metrics",
        "get_tiktok_campaign_insights",
        "pause_meta_campaign",
        "pause_google_campaign",
        "pause_tiktok_campaign",
        "compare_campaigns",
        "search_meta_ad_library",
        "search_google_ads_transparency",
        "search_tiktok_creative_center",
    ],
    "monitor": [
        "start_inbox_monitor",
        "stop_inbox_monitor",
        "check_inbox_monitor_status",
        "start_competitor_monitor",
        "stop_competitor_monitor",
        "check_competitor_monitor_status",
    ],
    "drive": [
        "search_drive_files",
        "read_drive_file",
        "create_drive_file",
        "list_drive_folders",
    ],
    "shell": [
        "execute_shell",
        "deploy_changes",
    ],
    "workflows": [
        "list_dynamic_workflows",
        "create_dynamic_workflow",
        "run_dynamic_workflow",
        "get_workflow_run_status",
        "activate_dynamic_workflow",
        "install_workflow_template",
    ],
    "skills": [
        "list_skills",
        "run_skill",
        "match_skills_to_context",
        "get_skill_gaps",
    ],
    "webhooks": [
        "register_webhook",
        "list_webhooks",
        "delete_webhook",
        "test_webhook",
        "send_webhook_event",
        "get_webhook_logs",
    ],
    "mcp_servers": [
        "list_mcp_servers",
        "connect_mcp_server",
        "disconnect_mcp_server",
        "health_check_mcp_server",
        "get_mcp_server_logs",
        "discover_mcp_tools",
        "call_mcp_tool",
    ],
    "learning": [
        "start_autonomous_learning",
        "stop_autonomous_learning",
        "check_autonomous_learning_status",
        "submit_learning_feedback",
        "get_simulation_summary",
    ],
}

# Tier-to-model mapping per CLI platform
TIER_MODEL_MAP: dict[str, dict[str, str]] = {
    "light": {
        "claude_code": "claude-haiku-4-5-20251001",
        "codex": "codex-mini",
        "gemini_cli": "gemini-2.5-flash",
    },
    "full": {
        "claude_code": "claude-sonnet-4-6-20250514",
        "codex": "codex",
        "gemini_cli": "gemini-2.5-pro",
    },
}

# Context loading limits per tier
TIER_LIMITS: dict[str, dict] = {
    "light": {
        "entities": 3,
        "observations_per_entity": 1,
        "include_relations": False,
        "include_episodes": False,
        "include_world_state": False,
        "include_goals": False,
        "include_commitments": False,
        "history_messages": 4,
    },
    "full": {
        "entities": 10,
        "observations_per_entity": 3,
        "include_relations": True,
        "include_episodes": True,
        "include_world_state": True,
        "include_goals": True,
        "include_commitments": True,
        "history_messages": 6,
    },
}


def resolve_tool_names(tool_groups: list[str] | None) -> list[str] | None:
    """Convert tool group keys to flat list of MCP tool names.
    
    Returns None if tool_groups is None (meaning load all tools).
    """
    if tool_groups is None:
        return None
    names = set()
    for group in tool_groups:
        if group in TOOL_GROUPS:
            names.update(TOOL_GROUPS[group])
    return sorted(names)


def format_allowed_tools(tool_names: list[str]) -> str:
    """Format tool names for --allowedTools CLI flag.
    
    Prefixes each tool with 'mcp__agentprovision__' for MCP tool matching.
    """
    return ",".join(f"mcp__agentprovision__{name}" for name in tool_names)
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/app/services/tool_groups.py
git commit -m "feat: add tool groups registry with tier model mapping and context limits"
```

---

## Task 3: Intent Embedding Cache

**Files:**
- Modify: `apps/api/app/services/embedding_service.py`

- [ ] **Step 1: Add intent definitions and cache to embedding_service.py**

Add at module level (after imports):

```python
import numpy as np

# Canonical intent definitions for tier routing
# Language-agnostic via nomic multilingual embeddings
INTENT_DEFINITIONS = [
    {"name": "greeting or small talk", "tier": "light", "tools": [], "mutation": False},
    {"name": "check calendar or schedule or upcoming events", "tier": "light", "tools": ["calendar"], "mutation": False},
    {"name": "read or search emails", "tier": "light", "tools": ["email"], "mutation": False},
    {"name": "what do we know about a person or company", "tier": "light", "tools": ["knowledge"], "mutation": False},
    {"name": "search files or documents in drive", "tier": "light", "tools": ["drive"], "mutation": False},
    {"name": "check status of a workflow or task", "tier": "light", "tools": ["workflows"], "mutation": False},
    {"name": "list or check jira issues or tickets", "tier": "light", "tools": ["jira"], "mutation": False},
    {"name": "list or check github issues or pull requests", "tier": "light", "tools": ["github"], "mutation": False},
    {"name": "check competitor status or report", "tier": "light", "tools": ["competitor"], "mutation": False},
    {"name": "check ad campaign metrics or performance", "tier": "light", "tools": ["ads"], "mutation": False},
    {"name": "show me pipeline or sales summary", "tier": "light", "tools": ["sales"], "mutation": False},
    {"name": "book appointment or create reservation or schedule meeting", "tier": "full", "tools": ["bookings"], "mutation": True},
    {"name": "send email or compose message", "tier": "full", "tools": ["email"], "mutation": True},
    {"name": "create or update jira issue or ticket", "tier": "full", "tools": ["jira"], "mutation": True},
    {"name": "process order refund or cancellation", "tier": "full", "tools": ["ecommerce"], "mutation": True},
    {"name": "analyze data or compare metrics or generate report", "tier": "full", "tools": ["data", "reports"], "mutation": False},
    {"name": "create or run a workflow", "tier": "full", "tools": ["workflows"], "mutation": True},
    {"name": "write code or fix bug or create pull request", "tier": "full", "tools": ["github", "shell"], "mutation": True},
    {"name": "manage competitors or add competitor", "tier": "full", "tools": ["competitor"], "mutation": True},
    {"name": "pause or modify ad campaign", "tier": "full", "tools": ["ads"], "mutation": True},
    {"name": "update deal or advance pipeline stage", "tier": "full", "tools": ["sales"], "mutation": True},
    {"name": "create entity or record observation in knowledge graph", "tier": "full", "tools": ["knowledge"], "mutation": True},
    {"name": "execute shell command or deploy changes", "tier": "full", "tools": ["shell"], "mutation": True},
    {"name": "forecast revenue or predict trends", "tier": "full", "tools": ["data", "reports"], "mutation": False},
    {"name": "generate proposal or draft outreach", "tier": "full", "tools": ["sales", "email"], "mutation": True},
    {"name": "connect or manage mcp servers", "tier": "full", "tools": ["mcp_servers"], "mutation": True},
    {"name": "register or manage webhooks", "tier": "full", "tools": ["webhooks"], "mutation": True},
    {"name": "start or stop inbox or competitor monitor", "tier": "full", "tools": ["monitor"], "mutation": True},
]

# In-memory intent embedding cache (populated at startup)
_intent_cache: list[dict] | None = None
```

Add new functions:

```python
def initialize_intent_embeddings():
    """Embed canonical intents at API startup. Call once from main.py."""
    global _intent_cache
    model = _get_model()
    if not model:
        logger.warning("Embedding model not available, intent matching disabled")
        return
    _intent_cache = []
    for intent_def in INTENT_DEFINITIONS:
        try:
            vec = model.encode(intent_def["name"], prompt_name="search_query")
            _intent_cache.append({**intent_def, "vector": vec})
        except Exception as e:
            logger.error(f"Failed to embed intent '{intent_def['name']}': {e}")
    logger.info(f"Intent embedding cache initialized: {len(_intent_cache)} intents")


def match_intent(message: str) -> dict | None:
    """Embed message and cosine-match against cached intent vectors.
    
    Returns best matching intent dict with 'similarity' score, or None if
    no match above threshold (0.4) or cache not initialized.
    """
    if not _intent_cache:
        return None
    model = _get_model()
    if not model:
        return None
    try:
        msg_vec = model.encode(message, prompt_name="search_query")
        best_match = None
        best_score = 0.0
        for intent in _intent_cache:
            score = float(np.dot(msg_vec, intent["vector"]) / (
                np.linalg.norm(msg_vec) * np.linalg.norm(intent["vector"])
            ))
            if score > best_score:
                best_score = score
                best_match = intent
        if best_score >= 0.4 and best_match:
            return {
                "name": best_match["name"],
                "tier": best_match["tier"],
                "tools": best_match["tools"],
                "mutation": best_match["mutation"],
                "similarity": best_score,
            }
    except Exception as e:
        logger.error(f"Intent matching failed: {e}")
    return None
```

- [ ] **Step 2: Initialize intent cache at API startup**

In `apps/api/app/main.py`, add after existing startup logic:

```python
from app.services.embedding_service import initialize_intent_embeddings

# Inside startup event or lifespan:
initialize_intent_embeddings()
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/services/embedding_service.py apps/api/app/main.py
git commit -m "feat: add intent embedding cache for tier routing classification"
```

---

## Task 4: RL Exploration Rate Decay

**Files:**
- Modify: `apps/api/app/services/rl_policy_engine.py`

- [ ] **Step 1: Add decay function**

Add after existing `get_exploration_rate()` function:

```python
def get_exploration_rate_with_decay(
    db: Session,
    tenant_id: uuid.UUID,
    decision_point: str,
) -> float:
    """Get exploration rate with automatic decay as sample count grows.
    
    Formula: base_rate * max(0.05, 1.0 - sample_count / (min_samples * 4))
    
    At 30 samples (min_samples): 0.25 * 0.75 = 0.1875
    At 120 samples: 0.25 * 0.05 = 0.0125 (floor)
    """
    base_rate = get_exploration_rate(db, tenant_id, decision_point)
    
    min_samples = 30  # default
    # Check for per-decision override
    features = db.query(TenantFeatures).filter(
        TenantFeatures.tenant_id == tenant_id
    ).first()
    if features and features.rl_settings:
        overrides = features.rl_settings.get("per_decision_overrides", {})
        if decision_point in overrides:
            min_samples = overrides[decision_point].get(
                "min_samples_before_exploit", min_samples
            )
    
    sample_count = db.query(RLExperience).filter(
        RLExperience.tenant_id == tenant_id,
        RLExperience.decision_point == decision_point,
    ).count()
    
    decay_factor = max(0.05, 1.0 - sample_count / (min_samples * 4))
    return base_rate * decay_factor
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/app/services/rl_policy_engine.py
git commit -m "feat: add exploration rate decay for model tier RL learning"
```

---

## Task 5: Memory Recall — Domain Filtering & Budget Parameters

**Files:**
- Modify: `apps/api/app/services/memory_recall.py`

- [ ] **Step 1: Extend build_memory_context signature**

Find the `build_memory_context` or `build_memory_context_with_git` function and add parameters:

```python
def build_memory_context_with_git(
    db: Session,
    tenant_id,
    message: str,
    session_entity_names: list = None,
    # New parameters for agent-driven runtime:
    domains: list[str] | None = None,
    max_entities: int = 10,
    max_observations: int = 3,
    include_relations: bool = True,
    include_episodes: bool = True,
) -> dict:
```

- [ ] **Step 2: Apply domain filtering to entity search**

In the semantic entity search query, add domain filter:

```python
# Where entities are queried via pgvector, add:
if domains:
    entity_query = entity_query.filter(
        KnowledgeEntity.category.in_(domains)
    )
```

- [ ] **Step 3: Apply budget limits**

Replace hardcoded entity/observation limits with the parameters:

```python
# Replace hardcoded "top 10" with max_entities
recalled_entities = sorted_entities[:max_entities]

# Replace hardcoded "top 3 observations" with max_observations
observations = observations[:max_observations]

# Conditionally include relations and episodes
if include_relations:
    # existing relations fetch code
    ...
if include_episodes:
    # existing episodes fetch code
    ...
```

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/services/memory_recall.py
git commit -m "feat: add domain filtering and budget params to memory recall"
```

---

## Task 6: Agent Router — Tier Selection & Agent Matching

**Files:**
- Modify: `apps/api/app/services/agent_router.py`

- [ ] **Step 1: Add intent-based tier selection**

After the existing task type inference (keyword matching), add intent matching:

```python
from app.services.embedding_service import match_intent
from app.services.tool_groups import TIER_LIMITS

# After task_type inference, before RL routing:
intent = match_intent(message)
if intent:
    agent_tier = intent["tier"]
    intent_tool_groups = intent["tools"]
    is_mutation = intent["mutation"]
    # Mutations always go to full tier
    if is_mutation:
        agent_tier = "full"
else:
    # No match or embedding unavailable — safe default
    agent_tier = "full"
    intent_tool_groups = None
    is_mutation = False
```

- [ ] **Step 2: Add agent selection by tool group overlap**

```python
# After intent matching, select responding agent:
from app.models.agent import Agent as AgentModel

responding_agent = None
if intent_tool_groups:
    # Query tenant's agents that have tool_groups configured
    tenant_agents = db.query(AgentModel).filter(
        AgentModel.tenant_id == tenant_id,
        AgentModel.tool_groups.isnot(None),
    ).all()
    
    best_overlap = 0
    for agent_candidate in tenant_agents:
        if agent_candidate.tool_groups:
            overlap = len(set(intent_tool_groups) & set(agent_candidate.tool_groups))
            if overlap > best_overlap:
                best_overlap = overlap
                responding_agent = agent_candidate
    
    if responding_agent and best_overlap > 0:
        agent_slug = responding_agent.name.lower().replace(" ", "-")
        agent_tier = responding_agent.default_model_tier or agent_tier
```

- [ ] **Step 3: Pass tier to run_agent_session**

Update the call to `run_agent_session()` to include tier and agent config:

```python
response, trace = await run_agent_session(
    db=db,
    tenant_id=tenant_id,
    # ... existing params ...
    agent_tier=agent_tier,
    agent_tool_groups=responding_agent.tool_groups if responding_agent else None,
    agent_memory_domains=responding_agent.memory_domains if responding_agent else None,
)
```

- [ ] **Step 4: Extend RL experience logging**

In the RL action dict, add tier and tool info:

```python
action = {
    "platform": platform,
    "agent": agent_slug,
    "model_tier": agent_tier,
    "tool_groups": intent_tool_groups or [],
    "entity_count": len(recalled_entities) if recalled_entities else 0,
}
```

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/agent_router.py
git commit -m "feat: add intent-based tier selection and agent matching to router"
```

---

## Task 7: CLI Session Manager — Tiered Context Loading

**Files:**
- Modify: `apps/api/app/services/cli_session_manager.py`

- [ ] **Step 1: Add tier parameters to run_agent_session**

Extend function signature:

```python
def run_agent_session(
    db, tenant_id, user_id, platform, agent_slug, message, channel,
    sender_phone=None, conversation_summary="", image_b64="", image_mime="",
    db_session_memory=None, pre_built_memory_context=None,
    # New parameters:
    agent_tier: str = "full",
    agent_tool_groups: list[str] | None = None,
    agent_memory_domains: list[str] | None = None,
):
```

- [ ] **Step 2: Apply tier limits to memory recall**

When calling `build_memory_context_with_git()`, pass tier limits:

```python
from app.services.tool_groups import TIER_LIMITS

limits = TIER_LIMITS.get(agent_tier, TIER_LIMITS["full"])

if pre_built_memory_context is not None:
    memory_context = pre_built_memory_context
else:
    memory_context = build_memory_context_with_git(
        db=db,
        tenant_id=tenant_id,
        message=message,
        domains=agent_memory_domains,
        max_entities=limits["entities"],
        max_observations=limits["observations_per_entity"],
        include_relations=limits["include_relations"],
        include_episodes=limits["include_episodes"],
    )
```

- [ ] **Step 3: Apply tier limits to generate_cli_instructions**

Modify `generate_cli_instructions()` to accept and use tier:

```python
def generate_cli_instructions(
    skill_body, tenant_name, user_name, channel, conversation_summary,
    memory_context, agent_slug="luna",
    tier: str = "full",  # NEW
):
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["full"])
    
    # Conditionally skip world state and goals sections
    if not limits["include_world_state"]:
        # Skip world state injection
        ...
    if not limits["include_goals"]:
        # Skip goals/commitments injection
        ...
```

- [ ] **Step 4: Add model and allowed_tools to _ChatCliInput**

```python
@_dc
class _ChatCliInput:
    platform: str
    message: str
    tenant_id: str
    instruction_md_content: str = ""
    mcp_config: str = ""
    image_b64: str = ""
    image_mime: str = ""
    session_id: str = ""
    model: str = ""  # NEW
    allowed_tools: str = ""  # NEW
```

- [ ] **Step 5: Set model and allowed_tools from tier + agent config**

When building the _ChatCliInput:

```python
from app.services.tool_groups import TIER_MODEL_MAP, resolve_tool_names, format_allowed_tools

model_slug = TIER_MODEL_MAP.get(agent_tier, {}).get(platform, "")
tool_names = resolve_tool_names(agent_tool_groups)
allowed_tools_str = format_allowed_tools(tool_names) if tool_names else ""

cli_input = _ChatCliInput(
    platform=platform,
    message=message,
    tenant_id=str(tenant_id),
    instruction_md_content=instruction_md,
    mcp_config=json.dumps(mcp_config),
    model=model_slug,
    allowed_tools=allowed_tools_str,
    # ... rest ...
)
```

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/services/cli_session_manager.py
git commit -m "feat: add tiered context loading with model and tool filtering"
```

---

## Task 8: Code Worker — Pass Model & AllowedTools to CLI

**Files:**
- Modify: `apps/code-worker/session_manager.py`

- [ ] **Step 1: Extend SessionConfig**

```python
@dataclass
class SessionConfig:
    claude_md_content: str = ""
    mcp_config: str = ""
    oauth_token: str = ""
    model: str = ""  # NEW: e.g., "claude-haiku-4-5-20251001"
    allowed_tools: str = ""  # NEW: comma-separated MCP tool names
```

- [ ] **Step 2: Update CLI command construction**

In `_create_session()`, add model flag to the command:

```python
cmd = [
    "claude",
    "--input-format", "stream-json",
    "--output-format", "stream-json",
    "--session-id", session_id,
]
if config.model:
    cmd.extend(["--model", config.model])
# ... rest of command building ...
```

- [ ] **Step 3: Update Temporal workflow to pass model and allowed_tools**

In the workflow activity that receives `_ChatCliInput`, extract `model` and `allowed_tools` and pass them to `SessionConfig`.

- [ ] **Step 4: Commit**

```bash
git add apps/code-worker/session_manager.py
git commit -m "feat: pass model tier and allowed tools to Claude CLI subprocess"
```

---

## Task 9: Auto Quality Scorer — Extended RL Logging

**Files:**
- Modify: `apps/api/app/services/auto_quality_scorer.py`

- [ ] **Step 1: Add tier params to _score_and_log**

Extend function signature:

```python
async def _score_and_log(
    tenant_id, user_message, agent_response, trajectory_id,
    platform, agent_slug, task_type, channel,
    tokens_used, response_time_ms, cost_usd,
    tools_called, entities_recalled,
    rollout_experiment_id=None, rollout_arm=None,
    routing_trajectory_id=None,
    # New parameters:
    agent_tier: str = "full",
    tool_groups: list = None,
    entity_count: int = 0,
    prompt_tokens: int = 0,
):
```

- [ ] **Step 2: Include tier info in RL experience action**

Where the RL experience action dict is built, extend it:

```python
action = {
    "platform": platform,
    "agent": agent_slug,
    "model_tier": agent_tier,
    "tool_groups": tool_groups or [],
    "entity_count": entity_count,
    "prompt_tokens": prompt_tokens,
    # ... existing fields ...
}
```

- [ ] **Step 3: Update callers to pass tier info**

In `apps/api/app/services/chat.py` where `score_and_log_async()` is called, pass the tier:

```python
score_and_log_async(
    # ... existing params ...
    agent_tier=agent_tier,
    tool_groups=tool_groups,
    entity_count=entity_count,
    prompt_tokens=prompt_tokens,
)
```

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/services/auto_quality_scorer.py apps/api/app/services/chat.py
git commit -m "feat: extend RL logging with model tier and tool group metadata"
```

---

## Task 10: Chat Service — Wire Tier Through Response Flow

**Files:**
- Modify: `apps/api/app/services/chat.py`

- [ ] **Step 1: Pass tier from router to session manager**

In the `_generate_agentic_response()` method, where `route_and_execute()` is called, capture the tier from the response and pass it forward:

```python
response, trace = route_and_execute(
    db=db,
    tenant_id=tenant_id,
    user_id=user_id,
    message=message,
    # ... existing params ...
)
# trace dict should now contain agent_tier, tool_groups from router
```

- [ ] **Step 2: Pass tier info to auto quality scorer**

When spawning the async quality scoring thread, include tier from trace:

```python
agent_tier = trace.get("agent_tier", "full")
tool_groups = trace.get("tool_groups", [])
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/services/chat.py
git commit -m "feat: wire model tier through chat response flow to RL logging"
```

---

## Task 11: Fix Double Memory Recall

**Files:**
- Modify: `apps/api/app/services/agent_router.py`
- Modify: `apps/api/app/services/cli_session_manager.py`

- [ ] **Step 1: Ensure pre_built_memory_context is always set in router**

In `agent_router.py`, make sure when `recalled_entities` is provided externally, `pre_built_memory_context` is still built:

```python
# After memory context building (around line 244):
if recalled_entities and not pre_built_memory_context:
    pre_built_memory_context = build_memory_context_with_git(
        db=db, tenant_id=tenant_id, message=message,
        domains=agent_memory_domains,
        max_entities=limits["entities"],
        max_observations=limits["observations_per_entity"],
        include_relations=limits["include_relations"],
        include_episodes=limits["include_episodes"],
    )
```

- [ ] **Step 2: In cli_session_manager, assert single recall**

Add a log warning if rebuild happens:

```python
if pre_built_memory_context is not None:
    memory_context = pre_built_memory_context
else:
    logger.warning("Memory context not pre-built — rebuilding (should not happen)")
    memory_context = build_memory_context_with_git(...)
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/services/agent_router.py apps/api/app/services/cli_session_manager.py
git commit -m "fix: eliminate double memory recall between router and session manager"
```

---

## Task 12: Wizard Templates — Pre-populate Agent Fields

**Files:**
- Modify: `apps/web/src/components/wizard/AgentTemplates.js` (or wherever templates are defined)

- [ ] **Step 1: Find template definitions**

Locate the agent creation wizard templates (likely in `apps/web/src/components/wizard/`).

- [ ] **Step 2: Add default values for new fields per template**

Each template should include sensible defaults:

```javascript
const TEMPLATES = {
  bookings: {
    name: "Booking Agent",
    // ... existing fields ...
    tool_groups: ["bookings", "calendar", "email", "knowledge"],
    default_model_tier: "light",
    memory_domains: ["client", "appointment", "schedule"],
    persona_prompt: "You are a booking assistant...",
  },
  ecommerce: {
    name: "E-Commerce Agent",
    tool_groups: ["ecommerce", "email", "knowledge", "reports"],
    default_model_tier: "full",
    memory_domains: ["customer", "order", "product"],
    persona_prompt: "You are an e-commerce support agent...",
  },
  // ... other templates ...
};
```

- [ ] **Step 3: Update wizard form to show/edit new fields**

Add form fields for tool_groups (multi-select), default_model_tier (dropdown), memory_domains (tags input), persona_prompt (textarea).

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/wizard/
git commit -m "feat: add tier and tool group defaults to agent wizard templates"
```

---

## Task 13: Verification & Integration Test

**Files:**
- No new files — verify end-to-end

- [ ] **Step 1: Verify migration runs cleanly**

Check the migration applies without errors on the running database.

- [ ] **Step 2: Verify intent matching works**

Test that `match_intent("hello")` returns a light tier intent, and `match_intent("create a booking for tomorrow")` returns a full tier intent.

- [ ] **Step 3: Verify tier routing end-to-end**

Send a simple message through chat and verify:
- The router selects the correct tier
- The CLI receives the correct `--model` flag
- The RL experience logs include `model_tier`

- [ ] **Step 4: Verify scoped context loading**

Check that a light tier request loads fewer entities/observations than a full tier request by examining the generated CLI instructions.

- [ ] **Step 5: Push and run CI**

```bash
git push origin <branch>
gh pr create --title "feat: Luna optimization — agent-driven runtime with model tiering" --body "..."
```

---

## Task 14: Fix Fake Streaming (Deferred — implement last)

**Files:**
- Modify: `apps/api/app/api/v1/chat.py`
- Modify: `apps/code-worker/session_manager.py`
- Requires: Redis dependency

- [ ] **Step 1: Add Redis pubsub to code-worker**

In the code-worker activity, publish CLI stdout lines to Redis `stream:{workflow_id}`:

```python
import redis
r = redis.Redis(host="redis", port=6379)

# In subprocess stdout loop:
for line in process.stdout:
    r.publish(f"stream:{workflow_id}", line)
r.publish(f"stream:{workflow_id}", '{"done": true}')
```

- [ ] **Step 2: Update SSE endpoint to subscribe to Redis**

In `apps/api/app/api/v1/chat.py`, the SSE endpoint subscribes to the stream channel:

```python
async def stream_response(workflow_id: str):
    pubsub = redis_client.pubsub()
    pubsub.subscribe(f"stream:{workflow_id}")
    for message in pubsub.listen():
        if message["type"] == "message":
            data = message["data"]
            if data == b'{"done": true}':
                break
            yield f"data: {data.decode()}\n\n"
```

- [ ] **Step 3: Add 180s timeout with fallback**

If no Redis message arrives within 180s, fall back to polling the Temporal workflow result.

- [ ] **Step 4: Graceful degradation**

If Redis is unavailable, fall back to current fake-streaming behavior.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/api/v1/chat.py apps/code-worker/session_manager.py
git commit -m "feat: real SSE streaming via Redis pubsub side channel"
```
