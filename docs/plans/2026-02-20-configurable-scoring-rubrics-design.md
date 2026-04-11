# Configurable Scoring Rubrics Design

**Goal:** Extend the lead scoring system from a single hardcoded AI-lead rubric to a pluggable registry of scoring rubrics, enabling multi-signal intelligence across different business verticals (AI leads, M&A deal intelligence, marketing signals).

**Architecture:** A Python registry pattern (`scoring_rubrics.py`) stores rubric templates keyed by ID. Each rubric defines an LLM prompt template with signal categories, weights, and scoring instructions. Rubrics are selectable per agent kit (stored as JSONB) and per API scoring call (query parameter). The `LeadScoringTool` dynamically loads the appropriate rubric at execution time.

**Tech Stack:** Python (FastAPI, SQLAlchemy, Anthropic SDK), PostgreSQL JSONB, React Bootstrap wizard UI

---

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    Scoring Rubric Registry                       │
│                  (scoring_rubrics.py)                             │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐        │
│  │  ai_lead    │  │  hca_deal   │  │ marketing_signal │        │
│  │  (default)  │  │  (M&A)      │  │ (campaigns)      │        │
│  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘        │
│         │                │                   │                   │
│         └────────────────┼───────────────────┘                   │
│                          │                                       │
│                   get_rubric(id)                                  │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │   LeadScoringTool      │
              │                        │
              │  1. Load entity context │
              │  2. Select rubric       │
              │  3. Format LLM prompt   │
              │  4. Parse JSON response │
              │  5. Write score + meta  │
              └────────────┬───────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         API endpoint   ADK agent   Agent wizard
         /score?rubric  score_entity  template config
```

---

## Rubric Registry

### Location
`apps/api/app/services/scoring_rubrics.py`

### Interface

```python
RUBRICS: Dict[str, Dict[str, Any]] = {}

def _register(rubric_id: str, rubric: Dict[str, Any]) -> None
def get_rubric(rubric_id: str) -> Optional[Dict[str, Any]]
def list_rubrics() -> Dict[str, Dict[str, Any]]
```

### Rubric Schema

Each registered rubric contains:

| Field | Type | Description |
|---|---|---|
| `name` | string | Display name (e.g., "HCA Deal Intelligence") |
| `description` | string | What this rubric scores for |
| `system_prompt` | string | LLM system instruction |
| `prompt_template` | string | Template with `{name}`, `{entity_type}`, `{category}`, `{description}`, `{properties}`, `{enrichment_data}`, `{source_url}`, `{relations_text}` placeholders |
| `categories` | dict | Signal categories with `max` (and optional `min`) point values |

### Template Variables

All rubric prompt templates receive these variables from the entity being scored:

| Variable | Source |
|---|---|
| `{name}` | `entity.name` |
| `{entity_type}` | `entity.entity_type` |
| `{category}` | `entity.category` |
| `{description}` | `entity.description` |
| `{properties}` | JSON dump of `entity.properties` |
| `{enrichment_data}` | JSON dump of `entity.enrichment_data` |
| `{source_url}` | `entity.source_url` |
| `{relations_text}` | Formatted list of related entities with their types and names |

---

## Registered Rubrics

### 1. AI Lead Scoring (`ai_lead`)

**Purpose:** Score leads 0-100 on likelihood of becoming a customer for an AI/agent orchestration platform.

| Category | Max Points | Signals |
|---|---|---|
| `hiring` | 25 | Job posts mentioning AI, ML, agents, orchestration, automation, platform engineering |
| `tech_stack` | 20 | Uses or evaluates LangChain, OpenAI, Anthropic, CrewAI, AutoGen, or similar agent frameworks |
| `funding` | 20 | Recent funding round (Series A/B/C within 12 months scores highest) |
| `company_size` | 15 | Mid-market (50-500 employees) and growth-stage companies score highest |
| `news` | 10 | Recent product launches, partnerships, expansions, AI initiatives |
| `direct_fit` | 10 | Explicit mentions of orchestration needs, multi-agent workflows, workflow automation |

**Output JSON:**
```json
{
  "score": 85,
  "breakdown": {
    "hiring": 22, "tech_stack": 18, "funding": 15,
    "company_size": 12, "news": 8, "direct_fit": 10
  },
  "reasoning": "Strong AI hiring signals, uses LangChain..."
}
```

### 2. HCA Deal Intelligence (`hca_deal`)

**Purpose:** Score companies 0-100 on sell-likelihood for middle-market M&A advisory. Designed for investment banking deal sourcing.

| Category | Weight | Max Points | Signals |
|---|---|---|---|
| `ownership_succession` | 0.30 | 30 | Owner age 55+, years in business 20+, no visible succession plan, owner reducing involvement, key person risk |
| `market_timing` | 0.25 | 25 | Industry M&A activity trending up, multiples at cycle highs, competitor exits, industry consolidation, regulatory sell pressure |
| `company_performance` | 0.20 | 20 | Revenue plateau after strong run, revenue $10M-$200M sweet spot, EBITDA margins expanding, customer concentration decreasing, recurring revenue growing |
| `external_triggers` | 0.15 | 15 | Recent leadership changes (new CFO/COO), hiring for corp dev/M&A roles, capex slowdown, debt maturity approaching, recent press/awards |
| `negative_signals` | 0.10 | -10 | Recent PE acquisition (-5), recent capital raise (-3), founder very young (-3), rapid hiring/growth mode (-2), new product launches (-2). These REDUCE the score. |

**Key design decision:** `negative_signals` uses a `min: -10, max: 0` range — it's a penalty category that subtracts from the total score, unlike all other categories which only add.

**Output JSON:**
```json
{
  "score": 65,
  "breakdown": {
    "ownership_succession": 20, "market_timing": 20,
    "company_performance": 15, "external_triggers": 10,
    "negative_signals": -5
  },
  "reasoning": "Owner is 62 with no succession plan..."
}
```

### 3. Marketing Signal Scoring (`marketing_signal`)

**Purpose:** Score leads 0-100 based on marketing engagement, campaign response, and buying intent signals. Designed for marketing-qualified lead (MQL) scoring and future integration with the ai-marketing-platform.

| Category | Max Points | Signals |
|---|---|---|
| `engagement` | 25 | Website visits, content downloads, webinar attendance, demo requests, email open/click rates |
| `intent_signals` | 25 | Searched for competitor products, visited pricing page, compared solutions, asked for proposal |
| `firmographic_fit` | 20 | Industry match, company size in ICP range, geography alignment, technology stack compatibility |
| `behavioral_recency` | 15 | How recent the engagement (last 7 days = highest, last 30 = medium, 30+ = low), frequency of interactions |
| `champion_signals` | 15 | Multiple contacts engaged, senior decision-maker involved, internal champion identified, shared content internally |

**Output JSON:**
```json
{
  "score": 72,
  "breakdown": {
    "engagement": 20, "intent_signals": 18, "firmographic_fit": 15,
    "behavioral_recency": 10, "champion_signals": 9
  },
  "reasoning": "Strong engagement with demo request and pricing page visits..."
}
```

---

## Data Model Changes

### Migration 033 (`apps/api/migrations/033_add_scoring_rubric.sql`)

```sql
ALTER TABLE agent_kits ADD COLUMN IF NOT EXISTS scoring_rubric JSONB;
ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS scoring_rubric_id VARCHAR(50);
```

### `agent_kits.scoring_rubric`

JSONB column storing the rubric configuration for the agent kit. Set during wizard creation when a template with a `scoring_rubric` field is selected.

### `knowledge_entities.scoring_rubric_id`

VARCHAR(50) tracking which rubric was used to produce the entity's current score. Written by `LeadScoringTool` after scoring. Enables querying "all entities scored with hca_deal rubric" and re-scoring with updated rubrics.

---

## LeadScoringTool Integration

### Location
`apps/api/app/services/tool_executor.py`

### Rubric Resolution Order

1. Per-call `rubric_id` (via `kwargs` or API query param)
2. Constructor `rubric_id` (set when tool is instantiated)
3. Constructor `custom_rubric` (full rubric dict, for tenant-specific overrides)
4. Default: `"ai_lead"`

### Execution Flow

```
score_entity(entity_id, rubric_id="hca_deal")
  │
  ├─ Load entity from DB (with tenant isolation)
  ├─ Load related entities via knowledge_relation joins
  ├─ Resolve rubric: get_rubric("hca_deal")
  ├─ Format prompt_template with entity context
  ├─ Call LLM (Anthropic Claude via multi-provider router)
  ├─ Parse JSON response
  ├─ Write to entity:
  │   ├─ entity.score = result["score"]
  │   ├─ entity.scored_at = now()
  │   ├─ entity.scoring_rubric_id = "hca_deal"
  │   ├─ entity.properties["score_breakdown"] = result["breakdown"]
  │   └─ entity.properties["score_reasoning"] = result["reasoning"]
  └─ Return ToolResult with score data
```

---

## API Endpoints

### Score Entity
`POST /api/v1/knowledge/entities/{entity_id}/score?rubric_id=hca_deal`

- `rubric_id` query parameter (optional, defaults to `ai_lead`)
- Returns: `{entity_id, entity_name, score, breakdown, reasoning, scored_at, rubric_id, rubric_name}`

### List Rubrics
`GET /api/v1/knowledge/scoring-rubrics`

- Returns: `{rubric_id: {name, description}, ...}` for all registered rubrics
- No auth required (rubric catalog is public information)

---

## Agent Wizard Templates

Three templates pre-configure the `scoring_rubric` field:

| Template | Rubric ID | Tools |
|---|---|---|
| Research Agent | `ai_lead` | entity_extraction, knowledge_search, data_summary, lead_scoring |
| Lead Generation Agent | `ai_lead` | entity_extraction, knowledge_search, lead_scoring |
| Deal Intelligence Agent | `hca_deal` | entity_extraction, knowledge_search, lead_scoring |
| Marketing Intelligence Agent | `marketing_signal` | entity_extraction, knowledge_search, lead_scoring |

### Wizard State Flow

1. **TemplateSelector** — template defines `scoring_rubric: 'hca_deal'`
2. **AgentWizard** — propagates `scoring_rubric` into wizard state
3. **ReviewStep** — displays rubric name badge (e.g., "M&A Deal Scoring") under Skills
4. **handleCreate** — sends `scoring_rubric` in API payload to `POST /api/v1/agents`

---

## Future Integration: ai-marketing-platform

The `marketing_signal` rubric is designed to integrate with the ai-marketing-platform project. The integration path:

1. **ai-marketing-platform** pushes engagement events (page visits, email clicks, demo requests) to AgentProvision via API
2. Events are stored as entity `properties` or `enrichment_data` on lead entities
3. `marketing_signal` rubric scores entities using these engagement signals
4. Scores flow back to ai-marketing-platform for campaign prioritization

### Shared entity properties schema (proposed)

```json
{
  "marketing_engagement": {
    "page_visits": 12,
    "last_visit": "2026-02-19",
    "content_downloads": ["whitepaper-ai-agents.pdf"],
    "email_opens": 5,
    "email_clicks": 3,
    "demo_requested": true,
    "pricing_page_visited": true
  },
  "firmographic": {
    "industry": "technology",
    "employee_count": 150,
    "annual_revenue": "$25M",
    "geography": "US-West"
  }
}
```

---

## Adding New Rubrics

To add a new scoring rubric:

1. Add `_register("rubric_id", {...})` call in `scoring_rubrics.py`
2. Define: `name`, `description`, `system_prompt`, `prompt_template`, `categories`
3. The rubric becomes immediately available via API and agent tools
4. Optionally add a wizard template in `TemplateSelector.js`

No migration, no model changes, no deployment beyond the API service.

### Custom Tenant Rubrics (future)

The `agent_kits.scoring_rubric` JSONB column supports storing full custom rubric definitions per tenant. When populated, `LeadScoringTool` uses it instead of the registry. This enables:

- Tenants defining their own scoring criteria
- Industry-specific rubrics without code changes
- A/B testing different scoring approaches

---

## Files Modified

| File | Change |
|---|---|
| `apps/api/app/services/scoring_rubrics.py` | NEW — Rubric registry with 3 default rubrics |
| `apps/api/app/services/tool_executor.py` | Refactored `LeadScoringTool` to accept `rubric_id` and `custom_rubric` |
| `apps/api/app/services/knowledge.py` | `score_entity()` accepts optional `rubric_id` |
| `apps/api/app/api/v1/knowledge.py` | Added `rubric_id` query param and `GET /scoring-rubrics` endpoint |
| `apps/api/app/models/agent_kit.py` | Added `scoring_rubric` JSONB column |
| `apps/api/app/models/knowledge_entity.py` | Added `scoring_rubric_id` column |
| `apps/api/app/schemas/agent_kit.py` | Added `scoring_rubric` to schemas |
| `apps/api/app/schemas/knowledge_entity.py` | Added `scoring_rubric_id` to response schema |
| `apps/api/migrations/033_add_scoring_rubric.sql` | DB migration for new columns |
| `apps/web/src/components/wizard/TemplateSelector.js` | Added Deal Intelligence and Marketing Intelligence templates |
| `apps/web/src/components/wizard/AgentWizard.js` | Wire `scoring_rubric` through wizard state |
| `apps/web/src/components/wizard/ReviewStep.js` | Display rubric name badge in review |
| `apps/web/src/components/wizard/SkillsDataStep.js` | Updated lead_scoring description |
