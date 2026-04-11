# Knowledge Graph Entity Taxonomy + Signal Layer Design

**Date**: 2026-02-19
**Status**: Approved

## Problem

The knowledge graph stores all entities with generic types (`organization`, `person`, `prospect`). For a real lead generation pipeline, scraped data from LinkedIn needs proper categorization: leads vs. investors vs. accelerators vs. hiring signals. Without taxonomy, the graph is unmanageable and unusable for analytics.

## Design: Entity Categories + Signal Layer (Approach A)

### Entity Categories

Add a `category` column to `knowledge_entities`. Categories are the high-level buckets for browsing and filtering. `entity_type` remains fully dynamic for granular agent-assigned types.

| Category | Purpose | Example entity_types |
|---|---|---|
| `lead` | Companies that might buy your product | `ai_company`, `enterprise`, `startup`, `saas_platform` |
| `contact` | Decision makers at companies | `cto`, `vp_engineering`, `ceo`, `head_of_ai` |
| `investor` | VCs, angels, funding sources | `vc_fund`, `angel_investor`, `corporate_vc` |
| `accelerator` | Programs, incubators | `accelerator`, `incubator`, `startup_program` |
| `signal` | Buying signals, market intelligence | `job_posting`, `hiring_signal`, `tech_adoption`, `funding_round`, `news_mention` |
| `organization` | Generic companies (backward compat) | `company`, `nonprofit`, `government` |
| `person` | Generic people (backward compat) | `employee`, `founder`, `researcher` |

- Agent decides both `category` and `entity_type` dynamically based on scraped content
- Presets guide the LLM but don't restrict it - any string is valid
- Users can create custom categories through the agent

### Signal Entities

Signals are first-class entities (`category = 'signal'`) linked to source companies via `knowledge_relations`.

**Signal properties** (stored in `properties` JSON):

```json
{
  "signal_type": "hiring_signal",
  "signal_strength": "high",
  "signal_source": "linkedin",
  "signal_detail": "Hiring AI Platform Engineer - needs orchestration tools",
  "detected_at": "2026-02-19",
  "source_url": "https://linkedin.com/jobs/..."
}
```

**Signal detection behavior**: The web_researcher agent is instructed to always identify buying signals when scraping companies:
- Hiring signals: job titles mentioning AI, platform, orchestration
- Tech stack signals: mentions of LangChain, OpenAI, competing tools
- Funding signals: recent raises, investor mentions
- News signals: product launches, partnerships, expansions

### Data Model Changes

**DB migration** - one new column + backfill:

```sql
ALTER TABLE knowledge_entities ADD COLUMN category VARCHAR(50);
UPDATE knowledge_entities SET category = 'lead' WHERE entity_type IN ('organization', 'company', 'prospect');
UPDATE knowledge_entities SET category = 'contact' WHERE entity_type = 'person';
UPDATE knowledge_entities SET category = 'organization' WHERE category IS NULL;
```

No new tables. Signals are entities with `category = 'signal'` linked via `knowledge_relations`.

### API Changes

- `GET /knowledge/entities?category=<cat>` - new query param filter
- Pydantic schema: add `category: Optional[str] = None`
- Knowledge service: add category filter to `get_entities()`

### Frontend Changes (MemoryPage.js)

- Replace `entity_type` filter dropdown with **Category** filter (lead, contact, investor, accelerator, signal, organization, person)
- Add dynamic **Type** sub-filter showing entity_type values from existing data
- Signal entities get amber/warning badge color
- Add signal count badge next to lead entities in the table

### ADK Changes

- **knowledge_manager.py**: Updated instructions with new taxonomy and signal guidance
- **web_researcher.py**: Instructions to always identify signals when scraping
- **knowledge_graph.py**: `create_entity()` gets optional `category` parameter
- **supervisor agent.py**: Signal detection routing in instructions

### Analytics Integration

Analytics dashboard at analytics.agentprovision.com queries knowledge graph API for:
- `GET /knowledge/entities?category=signal` - all detected signals
- `GET /knowledge/entities?category=lead&status=verified` - verified leads
- Signal-to-lead ratio, signal strength distribution, signals by source

## Files to Modify

1. `apps/api/app/models/knowledge_entity.py` - add `category` column
2. `apps/api/app/schemas/knowledge_entity.py` - add `category` field
3. `apps/api/app/services/knowledge.py` - add category filter
4. `apps/api/app/api/v1/knowledge.py` - add category query param
5. `apps/api/migrations/031_add_entity_category.sql` - migration
6. `apps/web/src/pages/MemoryPage.js` - category filter, signal badges
7. `apps/adk-server/agentprovision_supervisor/knowledge_manager.py` - taxonomy instructions
8. `apps/adk-server/agentprovision_supervisor/web_researcher.py` - signal detection instructions
9. `apps/adk-server/agentprovision_supervisor/agent.py` - supervisor routing
10. `apps/adk-server/services/knowledge_graph.py` - category param in create_entity
