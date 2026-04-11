# Lead Scoring Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace signal entities with an LLM-powered composite scoring tool that writes a 0-100 score onto lead entities.

**Architecture:** A new `LeadScoringTool` in the existing tool framework loads entity context, sends it to the LLM with a scoring rubric, and writes the result back. Signal entities are removed entirely. The ADK knowledge_manager gets a `score_entity` tool. The Memory page shows a sortable score column.

**Tech Stack:** Python (FastAPI, SQLAlchemy), LLM via existing service, ADK FunctionTool (httpx), React Bootstrap

---

### Task 1: Database Migration — Add score columns

**Files:**
- Create: `apps/api/migrations/032_add_lead_scoring.sql`

**Step 1: Write the migration**

```sql
-- 032_add_lead_scoring.sql
-- Add lead scoring columns to knowledge_entities
ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS score INTEGER;
ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS scored_at TIMESTAMP;
```

**Step 2: Run the migration against local DB**

Run: `docker-compose exec db psql -U postgres agentprovision -f /dev/stdin < apps/api/migrations/032_add_lead_scoring.sql`
Expected: ALTER TABLE (x2)

**Step 3: Run against prod Cloud SQL**

Run: `kubectl exec -n prod deploy/agentprovision-api -c cloud-sql-proxy -- psql "$DATABASE_URL" -c "ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS score INTEGER; ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS scored_at TIMESTAMP;"`

**Step 4: Commit**

```bash
git add apps/api/migrations/032_add_lead_scoring.sql
git commit -m "feat: add score and scored_at columns to knowledge_entities"
```

---

### Task 2: Update SQLAlchemy model

**Files:**
- Modify: `apps/api/app/models/knowledge_entity.py`

**Step 1: Add score columns to the model**

Add after line 33 (`source_url = Column(String, nullable=True)`):

```python
    # Lead scoring
    score = Column(Integer, nullable=True)  # Composite lead score 0-100
    scored_at = Column(DateTime, nullable=True)  # When last scored
```

**Step 2: Add the Integer import if missing**

Ensure line 3 includes `Integer`:
```python
from sqlalchemy import Column, String, Float, Integer, DateTime, Text, JSON, ForeignKey
```

**Step 3: Commit**

```bash
git add apps/api/app/models/knowledge_entity.py
git commit -m "feat: add score and scored_at to KnowledgeEntity model"
```

---

### Task 3: Update Pydantic schemas

**Files:**
- Modify: `apps/api/app/schemas/knowledge_entity.py`

**Step 1: Add score fields to the response schema**

Find the `KnowledgeEntity` response schema class. Add:

```python
    score: Optional[int] = None
    scored_at: Optional[datetime] = None
```

**Step 2: Commit**

```bash
git add apps/api/app/schemas/knowledge_entity.py
git commit -m "feat: add score fields to KnowledgeEntity schema"
```

---

### Task 4: Implement LeadScoringTool

**Files:**
- Modify: `apps/api/app/services/tool_executor.py`

**Step 1: Add the LeadScoringTool class**

Add after the `KnowledgeSearchTool` class, following the same pattern as `EntityExtractionTool`:

```python
class LeadScoringTool(Tool):
    """Tool for computing a composite lead score for knowledge entities."""

    SCORING_PROMPT = """You are a lead scoring specialist. Analyze the following entity and compute a composite score from 0 to 100 based on how likely this entity is to become a customer for an AI agent orchestration platform.

## Scoring Rubric (0-100 total)

| Category | Max Points | What to look for |
|---|---|---|
| hiring | 25 | Job posts mentioning AI, ML, agents, orchestration, automation, platform engineering |
| tech_stack | 20 | Uses or evaluates LangChain, OpenAI, Anthropic, CrewAI, AutoGen, or similar agent frameworks |
| funding | 20 | Recent funding round (Series A/B/C within 12 months scores highest) |
| company_size | 15 | Mid-market (50-500 employees) and growth-stage companies score highest |
| news | 10 | Recent product launches, partnerships, expansions, AI initiatives |
| direct_fit | 10 | Explicit mentions of orchestration needs, multi-agent workflows, workflow automation |

## Entity to Score

Name: {name}
Type: {entity_type}
Category: {category}
Description: {description}
Properties: {properties}
Enrichment Data: {enrichment_data}
Source URL: {source_url}

## Related Entities
{relations_text}

## Instructions

Return ONLY a JSON object with this exact structure:
{{
  "score": <integer 0-100>,
  "breakdown": {{
    "hiring": <integer 0-25>,
    "tech_stack": <integer 0-20>,
    "funding": <integer 0-20>,
    "company_size": <integer 0-15>,
    "news": <integer 0-10>,
    "direct_fit": <integer 0-10>
  }},
  "reasoning": "<one paragraph explaining the score>"
}}
"""

    def __init__(self, db, tenant_id):
        super().__init__(
            name="lead_scoring",
            description="Compute a composite lead score (0-100) for a knowledge entity based on hiring signals, tech stack, funding, and other factors"
        )
        self.db = db
        self.tenant_id = tenant_id

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "UUID of the entity to score"
                    },
                    "entity_name": {
                        "type": "string",
                        "description": "Name of the entity to score (used if entity_id not provided)"
                    },
                },
                "required": []
            }
        }

    def execute(self, **kwargs) -> ToolResult:
        try:
            import uuid as uuid_mod
            from datetime import datetime
            from app.models.knowledge_entity import KnowledgeEntity
            from app.models.knowledge_relation import KnowledgeRelation
            from app.services.llm import get_llm_response

            entity_id = kwargs.get("entity_id")
            entity_name = kwargs.get("entity_name")

            if not entity_id and not entity_name:
                return ToolResult(success=False, error="Either entity_id or entity_name is required")

            # Find the entity
            if entity_id:
                entity = self.db.query(KnowledgeEntity).filter(
                    KnowledgeEntity.id == uuid_mod.UUID(entity_id),
                    KnowledgeEntity.tenant_id == self.tenant_id,
                ).first()
            else:
                entity = self.db.query(KnowledgeEntity).filter(
                    KnowledgeEntity.tenant_id == self.tenant_id,
                    KnowledgeEntity.name.ilike(f"%{entity_name}%"),
                ).first()

            if not entity:
                return ToolResult(success=False, error=f"Entity not found: {entity_id or entity_name}")

            # Load relations and related entities
            relations = self.db.query(KnowledgeRelation).filter(
                (KnowledgeRelation.from_entity_id == entity.id) |
                (KnowledgeRelation.to_entity_id == entity.id)
            ).all()

            relations_text = ""
            for rel in relations:
                other_id = rel.to_entity_id if rel.from_entity_id == entity.id else rel.from_entity_id
                other = self.db.query(KnowledgeEntity).filter(KnowledgeEntity.id == other_id).first()
                if other:
                    direction = "→" if rel.from_entity_id == entity.id else "←"
                    relations_text += f"- {direction} {rel.relation_type}: {other.name} ({other.entity_type}, {other.category})\n"
                    if other.properties:
                        relations_text += f"  Properties: {json.dumps(other.properties)[:200]}\n"

            if not relations_text:
                relations_text = "No related entities found."

            # Build the prompt
            prompt = self.SCORING_PROMPT.format(
                name=entity.name,
                entity_type=entity.entity_type or "",
                category=entity.category or "",
                description=entity.description or "No description",
                properties=json.dumps(entity.properties) if entity.properties else "None",
                enrichment_data=json.dumps(entity.enrichment_data)[:500] if entity.enrichment_data else "None",
                source_url=entity.source_url or "None",
                relations_text=relations_text,
            )

            # Call LLM
            response = get_llm_response(prompt)

            # Parse response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return ToolResult(success=False, error="LLM did not return valid JSON")

            result = json.loads(json_match.group())
            score = max(0, min(100, int(result.get("score", 0))))
            breakdown = result.get("breakdown", {})
            reasoning = result.get("reasoning", "")

            # Write score to entity
            entity.score = score
            entity.scored_at = datetime.utcnow()
            props = entity.properties or {}
            props["score_breakdown"] = breakdown
            props["score_reasoning"] = reasoning
            entity.properties = props
            self.db.commit()
            self.db.refresh(entity)

            return ToolResult(
                success=True,
                data={
                    "entity_id": str(entity.id),
                    "entity_name": entity.name,
                    "score": score,
                    "breakdown": breakdown,
                    "reasoning": reasoning,
                    "scored_at": entity.scored_at.isoformat(),
                },
                metadata={"entity_type": entity.entity_type, "category": entity.category}
            )
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Failed to parse LLM scoring response: {str(e)}")
        except Exception as e:
            return ToolResult(success=False, error=f"Lead scoring failed: {str(e)}")
```

**Step 2: Register the tool in the tool initialization**

Find where tools are registered (look for `EntityExtractionTool` instantiation) and add:

```python
LeadScoringTool(db, tenant_id),
```

**Step 3: Commit**

```bash
git add apps/api/app/services/tool_executor.py
git commit -m "feat: add LeadScoringTool to tool framework"
```

---

### Task 5: Add API scoring endpoint

**Files:**
- Modify: `apps/api/app/api/v1/knowledge.py`
- Modify: `apps/api/app/services/knowledge.py`

**Step 1: Add score_entity function to knowledge service**

Add to `apps/api/app/services/knowledge.py`:

```python
def score_entity(db: Session, entity_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[dict]:
    """Score an entity using the LeadScoringTool."""
    from app.services.tool_executor import LeadScoringTool
    tool = LeadScoringTool(db, tenant_id)
    result = tool.execute(entity_id=str(entity_id))
    if result.success:
        return result.data
    return None
```

**Step 2: Add the POST endpoint to knowledge router**

Add to `apps/api/app/api/v1/knowledge.py`:

```python
@router.post("/entities/{entity_id}/score")
def score_entity(
    entity_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Compute and store a lead score for an entity."""
    result = service.score_entity(db, entity_id, current_user.tenant_id)
    if not result:
        raise HTTPException(status_code=404, detail="Entity not found or scoring failed")
    return result
```

**Step 3: Commit**

```bash
git add apps/api/app/api/v1/knowledge.py apps/api/app/services/knowledge.py
git commit -m "feat: add POST /knowledge/entities/{id}/score endpoint"
```

---

### Task 6: Add score_entity tool to ADK knowledge_manager

**Files:**
- Modify: `apps/adk-server/agentprovision_supervisor/knowledge_manager.py`

**Step 1: Add the score_entity function tool**

Add after the existing tool functions (e.g., after `get_entity_timeline`):

```python
async def score_entity(entity_id: str) -> dict:
    """Compute a composite lead score (0-100) for an entity.

    Uses LLM analysis of the entity's properties, relations, and context to score
    based on hiring signals, tech stack alignment, funding, company size, news, and direct fit.

    Args:
        entity_id: UUID of the entity to score.

    Returns:
        Dict with score (0-100), breakdown by category, and reasoning.
    """
    return await _call_api("POST", f"/knowledge/entities/{entity_id}/score")
```

**Step 2: Add score_entity to the agent's tools list**

Find the `tools=[` list in the `knowledge_manager = Agent(...)` definition and add `score_entity`:

```python
    tools=[
        create_entity,
        find_entities,
        get_entity,
        update_entity,
        merge_entities,
        create_relation,
        find_relations,
        get_path,
        get_neighborhood,
        search_knowledge,
        store_knowledge,
        record_observation,
        ask_knowledge_graph,
        get_entity_timeline,
        score_entity,
    ],
```

**Step 3: Update agent instructions**

Replace the signal entity creation instructions with scoring instructions. In the `instruction="""` string:

Remove the entire "## Signal Entities" section and replace with:

```
## Lead Scoring

After creating or enriching a lead entity, score it using the score_entity tool.
This computes a composite 0-100 score based on:
- Hiring signals (AI/ML/agent job posts): 0-25 pts
- Tech stack alignment (LangChain, OpenAI, etc.): 0-20 pts
- Funding recency: 0-20 pts
- Company size/stage fit: 0-15 pts
- News/momentum: 0-10 pts
- Direct fit indicators: 0-10 pts

Always report the score and key factors to the user after scoring.

Do NOT create separate signal entities. Instead, store raw intelligence
(hiring posts, tech mentions, funding data) directly in the entity's properties field.
```

**Step 4: Commit**

```bash
git add apps/adk-server/agentprovision_supervisor/knowledge_manager.py
git commit -m "feat: add score_entity tool to ADK knowledge_manager"
```

---

### Task 7: Update web_researcher to stop creating signals

**Files:**
- Modify: `apps/adk-server/agentprovision_supervisor/web_researcher.py`

**Step 1: Update web_researcher instructions**

In the `instruction="""` string, replace the entire "## Signal Detection - ALWAYS DO THIS" section with:

```
## Intelligence Gathering - ALWAYS DO THIS

When scraping any company or job board page, extract and store raw intelligence
in the entity's properties field (via knowledge_manager). Do NOT create separate
signal entities. Instead, enrich the entity directly:

1. **Hiring data**: Job titles, count, seniority levels → store in properties as "hiring_data"
2. **Tech stack**: Technologies mentioned → store as "tech_stack"
3. **Funding info**: Round, amount, date, investors → store as "funding_data"
4. **News**: Recent announcements → store as "recent_news"

After enriching an entity, ask knowledge_manager to score it using score_entity.
```

**Step 2: Commit**

```bash
git add apps/adk-server/agentprovision_supervisor/web_researcher.py
git commit -m "refactor: web_researcher stores raw intel in properties instead of signal entities"
```

---

### Task 8: Update Memory page UI — add Score column

**Files:**
- Modify: `apps/web/src/pages/MemoryPage.js`

**Step 1: Remove 'signal' from categories array**

Change line 122 from:
```javascript
const categories = ['lead', 'contact', 'investor', 'accelerator', 'signal', 'organization', 'person'];
```
To:
```javascript
const categories = ['lead', 'contact', 'investor', 'accelerator', 'organization', 'person'];
```

**Step 2: Remove signal badge color**

In `getCategoryBadgeColor`, remove the signal case:
```javascript
case 'signal': return 'warning';
```

**Step 3: Add Score column header**

In the `<thead>` section, add `<th>Score</th>` after `<th>Status</th>`:

```javascript
<tr>
  <th>Name</th>
  <th>Category</th>
  <th>Type</th>
  <th>Status</th>
  <th>Score</th>
  <th>Confidence</th>
  <th>Source</th>
  <th>Created</th>
  <th>Actions</th>
</tr>
```

**Step 4: Add Score column cell**

In the `<tbody>` row mapping, add after the Status `<td>` and before the Confidence `<td>`:

```javascript
<td>
  {entity.score != null ? (
    <Badge
      bg={entity.score >= 61 ? 'success' : entity.score >= 31 ? 'warning' : 'danger'}
      className="bg-opacity-25 border border-secondary"
      style={{ fontSize: '0.75rem', minWidth: '36px' }}
    >
      {entity.score}
    </Badge>
  ) : (
    <span className="text-muted small">—</span>
  )}
</td>
```

**Step 5: Update colSpan for empty state**

Change the empty state `colSpan="8"` to `colSpan="9"`.

**Step 6: Commit**

```bash
git add apps/web/src/pages/MemoryPage.js
git commit -m "feat: add Score column to Memory page, remove signal category"
```

---

### Task 9: Add lead_scoring to agent wizard tools

**Files:**
- Modify: `apps/web/src/components/wizard/SkillsDataStep.js`
- Modify: `apps/web/src/components/wizard/TemplateSelector.js`

**Step 1: Add lead_scoring tool to TOOLS array in SkillsDataStep.js**

Add to the end of the TOOLS array:

```javascript
  {
    id: 'lead_scoring',
    name: 'Lead Scoring',
    icon: FaChartLine,
    description: 'Score leads 0-100 based on hiring signals, tech stack, funding, and fit',
    requiresDataset: false,
    helpText: 'Your agent can compute composite lead scores using AI analysis of entity data',
  },
```

Add the import at the top: `import { FaChartLine } from 'react-icons/fa';` (or reuse an existing icon).

**Step 2: Add lead_scoring to Lead Generation Agent template in TemplateSelector.js**

Find the `lead_generation` template and update its tools:

```javascript
tools: ['entity_extraction', 'knowledge_search', 'lead_scoring'],
```

Also add to `research_agent`:

```javascript
tools: ['entity_extraction', 'knowledge_search', 'data_summary', 'lead_scoring'],
```

**Step 3: Commit**

```bash
git add apps/web/src/components/wizard/SkillsDataStep.js apps/web/src/components/wizard/TemplateSelector.js
git commit -m "feat: add lead_scoring tool to agent wizard"
```

---

### Task 10: Deploy and test end-to-end

**Step 1: Push and trigger builds**

```bash
git push origin main
```

**Step 2: Run migration on prod**

```bash
kubectl exec -n prod deploy/agentprovision-api -c cloud-sql-proxy -- psql "$DATABASE_URL" -c "ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS score INTEGER; ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS scored_at TIMESTAMP;"
```

**Step 3: Verify ADK deploy**

```bash
gh run list --limit 3 --json workflowName,status,headSha
```

**Step 4: Test scoring via API**

```bash
# Get an existing entity ID
curl -s https://agentprovision.com/api/v1/knowledge/entities -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; entities=json.load(sys.stdin); print(entities[0]['id'], entities[0]['name'])"

# Score it
curl -X POST https://agentprovision.com/api/v1/knowledge/entities/{ENTITY_ID}/score -H "Authorization: Bearer $TOKEN"
```

**Step 5: Test via chat**

Send a chat message: "Score the Anthropic lead entity" — verify the agent calls score_entity and returns a score.

**Step 6: Verify Memory page**

Navigate to /memory — confirm Score column appears with colored badges.
