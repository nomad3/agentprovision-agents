# Entity Taxonomy + Signal Layer + "Memory" Rebrand — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `category` column to knowledge entities for proper lead-gen taxonomy (lead, contact, investor, accelerator, signal), rebrand "Knowledge Graph" to "Memory" in the UI, and update ADK agents to auto-categorize scraped data and detect buying signals.

**Architecture:** One new DB column (`category VARCHAR(50)`) on `knowledge_entities` with backfill migration. No new tables — signals are entities with `category='signal'` linked via `knowledge_relations`. Frontend gets category filter dropdown replacing the hardcoded type list. ADK agents get updated instructions for taxonomy-aware entity creation and signal detection.

**Tech Stack:** PostgreSQL (migration), FastAPI + SQLAlchemy + Pydantic (API), React 18 + Bootstrap 5 (frontend), Google ADK (agents)

---

## Task 1: DB Migration — Add `category` column + backfill

**Files:**
- Create: `apps/api/migrations/031_add_entity_category.sql`

**Step 1: Write the migration file**

```sql
-- 031_add_entity_category.sql
-- Add category column to knowledge_entities for entity taxonomy

ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS category VARCHAR(50);

-- Backfill existing entities based on current entity_type
UPDATE knowledge_entities SET category = 'lead'
  WHERE entity_type IN ('organization', 'company', 'prospect', 'ai_company', 'enterprise', 'startup', 'saas_platform');

UPDATE knowledge_entities SET category = 'contact'
  WHERE entity_type IN ('person', 'cto', 'vp_engineering', 'ceo', 'head_of_ai', 'founder');

UPDATE knowledge_entities SET category = 'organization'
  WHERE category IS NULL;

-- Index for category filtering
CREATE INDEX IF NOT EXISTS idx_knowledge_entities_category ON knowledge_entities (category);
```

**Step 2: Apply migration locally**

Run: `docker-compose exec db psql -U postgres agentprovision -f /dev/stdin < apps/api/migrations/031_add_entity_category.sql`

If using docker-compose, copy file first:
```bash
docker cp apps/api/migrations/031_add_entity_category.sql agentprovision-agents-db-1:/tmp/031.sql
docker-compose exec db psql -U postgres agentprovision -f /tmp/031.sql
```

Expected: `ALTER TABLE`, `UPDATE N`, `CREATE INDEX` — no errors.

**Step 3: Verify column exists**

Run: `docker-compose exec db psql -U postgres agentprovision -c "SELECT category, count(*) FROM knowledge_entities GROUP BY category;"`

Expected: Rows showing `lead`, `contact`, `organization` with counts.

**Step 4: Commit**

```bash
git add apps/api/migrations/031_add_entity_category.sql
git commit -m "feat: add category column to knowledge_entities with backfill migration"
```

---

## Task 2: SQLAlchemy Model — Add `category` column

**Files:**
- Modify: `apps/api/app/models/knowledge_entity.py` (line ~17, after `entity_type`)

**Step 1: Add the category column to the model**

In `apps/api/app/models/knowledge_entity.py`, add this line after `entity_type = Column(String, nullable=False)` (line 17):

```python
    category = Column(String(50), nullable=True)  # lead, contact, investor, accelerator, signal, organization, person
```

The full block should read:
```python
    # Entity definition
    entity_type = Column(String, nullable=False)  # customer, product, concept, person, organization, location
    category = Column(String(50), nullable=True)  # lead, contact, investor, accelerator, signal, organization, person
    name = Column(String, nullable=False, index=True)
```

**Step 2: Commit**

```bash
git add apps/api/app/models/knowledge_entity.py
git commit -m "feat: add category column to KnowledgeEntity model"
```

---

## Task 3: Pydantic Schema — Add `category` field

**Files:**
- Modify: `apps/api/app/schemas/knowledge_entity.py`

**Step 1: Add category to all schema classes**

In `KnowledgeEntityBase` (line 8-14), add `category`:

```python
class KnowledgeEntityBase(BaseModel):
    entity_type: str
    category: Optional[str] = None
    name: str
    attributes: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = 1.0
    status: Optional[str] = "draft"
    source_url: Optional[str] = None
```

In `KnowledgeEntityUpdate` (line 23-29), add `category`:

```python
class KnowledgeEntityUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    status: Optional[str] = None
    source_url: Optional[str] = None
    enrichment_data: Optional[Dict[str, Any]] = None
```

In `CollectionSummary` (line 58-64), add `by_category`:

```python
class CollectionSummary(BaseModel):
    """Summary of entities collected by a task."""
    task_id: uuid.UUID
    total_entities: int
    by_status: Dict[str, int]
    by_type: Dict[str, int]
    by_category: Dict[str, int]
    sources: List[str]
```

**Step 2: Commit**

```bash
git add apps/api/app/schemas/knowledge_entity.py
git commit -m "feat: add category field to knowledge entity schemas"
```

---

## Task 4: Knowledge Service — Add category filter

**Files:**
- Modify: `apps/api/app/services/knowledge.py`

**Step 1: Update `create_entity` to include category (line 12-29)**

Replace the `create_entity` function body to include `category`:

```python
def create_entity(db: Session, entity_in: KnowledgeEntityCreate, tenant_id: uuid.UUID) -> KnowledgeEntity:
    """Create a knowledge entity."""
    entity = KnowledgeEntity(
        tenant_id=tenant_id,
        entity_type=entity_in.entity_type,
        category=entity_in.category,
        name=entity_in.name,
        attributes=entity_in.attributes,
        confidence=entity_in.confidence or 1.0,
        source_agent_id=entity_in.source_agent_id,
        status=entity_in.status or "draft",
        collection_task_id=entity_in.collection_task_id,
        source_url=entity_in.source_url,
        enrichment_data=entity_in.enrichment_data,
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity
```

**Step 2: Update `get_entities` to accept category filter (line 40-57)**

```python
def get_entities(
    db: Session,
    tenant_id: uuid.UUID,
    entity_type: str = None,
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    task_id: uuid.UUID = None,
    category: str = None,
) -> List[KnowledgeEntity]:
    """List entities with optional filters."""
    query = db.query(KnowledgeEntity).filter(KnowledgeEntity.tenant_id == tenant_id)
    if entity_type:
        query = query.filter(KnowledgeEntity.entity_type == entity_type)
    if status:
        query = query.filter(KnowledgeEntity.status == status)
    if task_id:
        query = query.filter(KnowledgeEntity.collection_task_id == task_id)
    if category:
        query = query.filter(KnowledgeEntity.category == category)
    return query.order_by(KnowledgeEntity.created_at.desc()).offset(skip).limit(limit).all()
```

**Step 3: Update `bulk_create_entities` to include category (line 133-144)**

In the `KnowledgeEntity(...)` constructor inside `bulk_create_entities`, add:

```python
        entity = KnowledgeEntity(
            tenant_id=tenant_id,
            entity_type=entity_in.entity_type,
            category=entity_in.category,
            name=entity_in.name,
            ...
        )
```

**Step 4: Update `get_collection_summary` to include `by_category` (line 155-178)**

Add `by_category` dict:

```python
def get_collection_summary(db: Session, task_id: uuid.UUID, tenant_id: uuid.UUID) -> Dict[str, Any]:
    """Get summary of entities collected by a task."""
    entities = db.query(KnowledgeEntity).filter(
        KnowledgeEntity.tenant_id == tenant_id,
        KnowledgeEntity.collection_task_id == task_id,
    ).all()

    by_status: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    sources = set()

    for e in entities:
        by_status[e.status or "draft"] = by_status.get(e.status or "draft", 0) + 1
        by_type[e.entity_type] = by_type.get(e.entity_type, 0) + 1
        cat = e.category or "uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1
        if e.source_url:
            sources.add(e.source_url)

    return {
        "task_id": task_id,
        "total_entities": len(entities),
        "by_status": by_status,
        "by_type": by_type,
        "by_category": by_category,
        "sources": list(sources),
    }
```

**Step 5: Commit**

```bash
git add apps/api/app/services/knowledge.py
git commit -m "feat: add category filter to knowledge service"
```

---

## Task 5: API Route — Add category query param

**Files:**
- Modify: `apps/api/app/api/v1/knowledge.py` (line 30-44)

**Step 1: Add `category` param to `list_entities` endpoint**

```python
@router.get("/entities", response_model=List[KnowledgeEntity])
def list_entities(
    entity_type: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    task_id: Optional[uuid.UUID] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List entities with optional filters."""
    return service.get_entities(
        db, current_user.tenant_id, entity_type, skip, limit,
        status=status, task_id=task_id, category=category,
    )
```

**Step 2: Add `category` param to `search_entities` endpoint (line 47-55)**

```python
@router.get("/entities/search", response_model=List[KnowledgeEntity])
def search_entities(
    q: str,
    entity_type: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Search entities by name."""
    return service.search_entities(db, current_user.tenant_id, q, entity_type)
```

Note: category filter in search_entities service can be added later — the query param is exposed now for forward compat.

**Step 3: Commit**

```bash
git add apps/api/app/api/v1/knowledge.py
git commit -m "feat: add category query param to knowledge API"
```

---

## Task 6: Frontend — Category filter + Signal badges + "Memory" rebrand

**Files:**
- Modify: `apps/web/src/pages/MemoryPage.js`
- Modify: `apps/web/src/components/Layout.js` (one line — sidebar label)

**Step 1: Update Layout.js sidebar label**

In `apps/web/src/components/Layout.js`, find line 68:
```javascript
{ path: '/memory', icon: DatabaseFill, label: 'Knowledge', description: 'Knowledge graph entities and relations' },
```

Change to:
```javascript
{ path: '/memory', icon: DatabaseFill, label: 'Memory', description: 'Entities, signals, and relations' },
```

**Step 2: Rewrite MemoryPage.js**

Replace the full contents of `apps/web/src/pages/MemoryPage.js` with the updated version that includes:

1. **"Memory" rebrand**: Page title → "Memory", tab title → "Entities" (not "Knowledge Graph")
2. **Category filter**: New dropdown with categories: lead, contact, investor, accelerator, signal, organization, person
3. **Dynamic type sub-filter**: Shows entity_types from actual data, not a hardcoded list
4. **Signal badges**: Amber/warning color for signal category entities
5. **Category badge colors**: lead=success, contact=info, investor=purple, accelerator=cyan, signal=warning, organization=secondary, person=secondary

Key changes to `MemoryPage.js`:

a. Add `categoryFilter` state:
```javascript
const [categoryFilter, setCategoryFilter] = useState('');
```

b. Add `categoryFilter` to `useEffect` deps and `loadEntities`:
```javascript
useEffect(() => {
    loadEntities();
  }, [entityType, statusFilter, categoryFilter]);

const loadEntities = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (entityType) params.append('entity_type', entityType);
      if (statusFilter) params.append('status', statusFilter);
      if (categoryFilter) params.append('category', categoryFilter);
      params.append('limit', '100');
      const res = await api.get(`/knowledge/entities?${params.toString()}`);
      setEntities(res.data || []);
    } catch (error) {
      console.error('Failed to load entities:', error);
    } finally {
      setLoading(false);
    }
  };
```

c. Replace hardcoded `entityTypes` array with categories:
```javascript
const categories = ['lead', 'contact', 'investor', 'accelerator', 'signal', 'organization', 'person'];
```

d. Replace first dropdown (Type) with Category, move Type to second dropdown (dynamic from data):
```jsx
<Col md={3}>
  <Form.Select
    value={categoryFilter}
    onChange={(e) => setCategoryFilter(e.target.value)}
    className="border-secondary border-opacity-50"
  >
    <option value="">All Categories</option>
    {categories.map(cat => (
      <option key={cat} value={cat}>{cat.charAt(0).toUpperCase() + cat.slice(1)}</option>
    ))}
  </Form.Select>
</Col>
<Col md={3}>
  <Form.Select
    value={entityType}
    onChange={(e) => setEntityType(e.target.value)}
    className="border-secondary border-opacity-50"
  >
    <option value="">All Types</option>
    {[...new Set(entities.map(e => e.entity_type))].sort().map(type => (
      <option key={type} value={type}>{type}</option>
    ))}
  </Form.Select>
</Col>
```

e. Update page title and tab:
```jsx
<h2 className="fw-bold mb-1">Memory</h2>
<p className="text-soft mb-0">Entities, signals, and relations</p>
```

```jsx
<Tabs defaultActiveKey="entities" className="mb-4 custom-tabs">
  <Tab eventKey="entities" title="Entities">
```

f. Add Category column to table + category-aware badge colors:
```jsx
<th>Category</th>
```

```jsx
<td>
  <Badge
    bg={
      entity.category === 'lead' ? 'success' :
      entity.category === 'contact' ? 'info' :
      entity.category === 'investor' ? 'primary' :
      entity.category === 'accelerator' ? 'info' :
      entity.category === 'signal' ? 'warning' :
      'secondary'
    }
    className="bg-opacity-25 border border-secondary text-uppercase"
    style={{ fontSize: '0.7rem' }}
  >
    {entity.category || 'uncategorized'}
  </Badge>
</td>
```

Update empty state `colSpan` to `"8"` (was `"7"`).

**Step 3: Commit**

```bash
git add apps/web/src/pages/MemoryPage.js apps/web/src/components/Layout.js
git commit -m "feat: rebrand Knowledge Graph to Memory, add category filter and signal badges"
```

---

## Task 7: ADK knowledge_graph.py — Add `category` param to `create_entity`

**Files:**
- Modify: `apps/adk-server/services/knowledge_graph.py` (lines 53-109)

**Step 1: Add `category` parameter to `create_entity` method**

Update the method signature (line 53-62):
```python
    async def create_entity(
        self,
        name: str,
        entity_type: str,
        tenant_id: str,
        properties: dict = None,
        description: str = None,
        aliases: list = None,
        confidence: float = 1.0,
        category: str = None,
    ) -> dict:
```

**Step 2: Add `category` to both INSERT SQL statements**

For the pgvector branch (line 72-88):
```sql
INSERT INTO knowledge_entities
(id, tenant_id, name, entity_type, category, description, properties, aliases, confidence, embedding, created_at, updated_at)
VALUES (:id, :tenant_id, :name, :entity_type, :category, :description, :properties, :aliases, :confidence, :embedding, NOW(), NOW())
```

Add `"category": category` to the params dict.

For the no-pgvector branch (line 90-106):
```sql
INSERT INTO knowledge_entities
(id, tenant_id, name, entity_type, category, description, properties, aliases, confidence, created_at, updated_at)
VALUES (:id, :tenant_id, :name, :entity_type, :category, :description, :properties, :aliases, :confidence, NOW(), NOW())
```

Add `"category": category` to the params dict.

**Step 3: Update return value to include category**

```python
return {"id": entity_id, "name": name, "entity_type": entity_type, "category": category}
```

**Step 4: Update `find_entities` to include category in SELECT (line 111-168)**

In both the pgvector and fallback SQL queries, add `category` to the SELECT list:
```sql
SELECT id, name, entity_type, category, description, confidence, ...
```

**Step 5: Update `get_entity` to include category in SELECT (line 177-183)**

```sql
SELECT id, tenant_id, name, entity_type, category, description,
       properties, aliases, confidence, created_at, updated_at
FROM knowledge_entities
WHERE id = :entity_id
```

**Step 6: Commit**

```bash
git add apps/adk-server/services/knowledge_graph.py
git commit -m "feat: add category param to ADK knowledge graph create_entity"
```

---

## Task 8: ADK knowledge_tools.py — Add `category` param to `create_entity` tool

**Files:**
- Modify: `apps/adk-server/tools/knowledge_tools.py` (find the `create_entity` function wrapper)

**Step 1: Find and update the `create_entity` tool function**

Look for the `async def create_entity(...)` function in `tools/knowledge_tools.py`. Add `category: str = None` parameter and pass it through:

```python
async def create_entity(
    name: str,
    entity_type: str,
    tenant_id: str,
    properties: dict = None,
    description: str = None,
    aliases: list = None,
    confidence: float = 1.0,
    category: str = None,
) -> dict:
    """Create a new entity in the knowledge graph.

    Args:
        name: Entity name.
        entity_type: Specific type (e.g. ai_company, cto, vc_fund, job_posting).
        tenant_id: Tenant ID (use 'auto' if unknown).
        properties: Structured properties dict.
        description: Text description for semantic search.
        aliases: Alternative names list.
        confidence: Confidence score 0-1.
        category: High-level category: lead, contact, investor, accelerator, signal, organization, person.
    """
    service = get_knowledge_service()
    resolved_tenant = await _resolve_tenant_id(tenant_id)
    return await service.create_entity(
        name=name,
        entity_type=entity_type,
        tenant_id=resolved_tenant,
        properties=properties,
        description=description,
        aliases=aliases,
        confidence=confidence,
        category=category,
    )
```

**Step 2: Commit**

```bash
git add apps/adk-server/tools/knowledge_tools.py
git commit -m "feat: add category param to create_entity ADK tool"
```

---

## Task 9: ADK knowledge_manager.py — Taxonomy-aware instructions

**Files:**
- Modify: `apps/adk-server/agentprovision_supervisor/knowledge_manager.py` (lines 32-61, the `instruction` string)

**Step 1: Replace the instruction string**

```python
    instruction="""You are a memory and knowledge management specialist who maintains the organizational knowledge graph.

IMPORTANT: For the tenant_id parameter in all tools, use the value from the session state.
The tenant_id is available in the session state as state["tenant_id"].
If you cannot access the session state, use "auto" as tenant_id and the system will resolve it.

Your capabilities:
- Create and update entities with proper CATEGORY and TYPE classification
- Establish relationships between entities
- Search for relevant knowledge using semantic search
- Answer questions by traversing the knowledge graph
- Record observations and detect buying signals

## Entity Taxonomy

When creating entities, ALWAYS set both `category` and `entity_type`:

| Category | When to use | Example entity_types |
|---|---|---|
| lead | Companies that might buy a product/service | ai_company, enterprise, startup, saas_platform |
| contact | Decision makers and key people at companies | cto, vp_engineering, ceo, head_of_ai, founder |
| investor | VCs, angels, funding sources | vc_fund, angel_investor, corporate_vc |
| accelerator | Programs, incubators, startup programs | accelerator, incubator, startup_program |
| signal | Buying signals and market intelligence | job_posting, hiring_signal, tech_adoption, funding_round, news_mention |
| organization | Generic companies (when not a lead) | company, nonprofit, government |
| person | Generic people (when not a contact) | employee, researcher |

The `category` is the high-level bucket. The `entity_type` is the specific granular type — use any descriptive string.

## Signal Entities

Signals are entities with `category='signal'`. When you detect buying signals, create them as signal entities and link them to the source company:

Signal properties (stored in `properties` JSON):
- signal_type: hiring_signal, tech_adoption, funding_round, news_mention
- signal_strength: high, medium, low
- signal_source: linkedin, website, news, job_board
- signal_detail: description of the signal
- detected_at: ISO date string
- source_url: URL where signal was found

After creating a signal entity, create a relation from the source company to the signal:
- relation_type: "has_signal"
- strength: 0.5-1.0 based on signal_strength

## Relationship Types

- Business: purchased, works_at, manages, partners_with, competes_with
- Hierarchy: subsidiary_of, division_of, invested_in
- Signals: has_signal, indicates_interest, hiring_for
- Data: derived_from, depends_on, contains

Guidelines:
1. Before creating entities, search for existing ones to avoid duplicates
2. Always set the correct category based on context
3. Always record the source and confidence of knowledge
4. Link related entities to build a connected graph
5. Use semantic search to find relevant context
6. Track entity history for important changes
""",
```

**Step 2: Commit**

```bash
git add apps/adk-server/agentprovision_supervisor/knowledge_manager.py
git commit -m "feat: update knowledge_manager instructions with entity taxonomy and signal detection"
```

---

## Task 10: ADK web_researcher.py — Signal detection instructions

**Files:**
- Modify: `apps/adk-server/agentprovision_supervisor/web_researcher.py` (lines 135-157, the `instruction` string)

**Step 1: Replace the instruction string**

```python
    instruction="""You are a web research specialist focused on gathering intelligence from the internet.

Your capabilities:
- Scrape any public webpage to extract content, links, and metadata
- Search the web for companies, people, job postings, news, and market signals
- Extract structured data from web pages using CSS selectors
- Research companies and their key contacts for lead generation

Guidelines:
1. Start with search_and_scrape for broad research queries
2. Use scrape_webpage for known URLs or to dive deeper into specific pages
3. Use scrape_structured_data when you know the page structure and need specific fields
4. Always summarize findings clearly - include company names, URLs, key contacts, and relevant data
5. When you find valuable entities (companies, people, technologies), delegate to knowledge_manager to store them
6. Be methodical: search first, then scrape the most promising results for details
7. Respect rate limits - don't scrape too many pages in rapid succession

## Entity Categorization

When delegating to knowledge_manager, always specify the correct category:
- Companies interested in AI/orchestration/agents → category: "lead"
- Executives/decision makers → category: "contact"
- VCs or investors → category: "investor"
- Accelerator programs → category: "accelerator"
- Generic companies → category: "organization"
- Generic people → category: "person"

## Signal Detection — ALWAYS DO THIS

When scraping any company or job board page, ALWAYS look for buying signals and ask knowledge_manager to store them:

1. **Hiring signals**: Job titles mentioning AI, ML, platform engineering, orchestration, automation, agents
   - entity_type: "hiring_signal"
   - signal_strength: high if senior role or multiple postings, medium if single posting
2. **Tech stack signals**: Mentions of LangChain, OpenAI, Anthropic, competing orchestration tools
   - entity_type: "tech_adoption"
   - signal_strength: high if actively using, medium if evaluating
3. **Funding signals**: Recent raises, investor mentions, Series A/B/C
   - entity_type: "funding_round"
   - signal_strength: high if recent (<6 months)
4. **News signals**: Product launches, partnerships, expansions, acquisitions
   - entity_type: "news_mention"
   - signal_strength: varies

For each signal, tell knowledge_manager to create it with category="signal" and link it to the source company with relation_type="has_signal".

When researching leads:
1. Search for companies or job postings matching the criteria
2. Scrape company websites for contact information and details
3. Extract structured data like company size, location, technologies used
4. ALWAYS check for buying signals on every page you scrape
5. Summarize your findings with actionable intelligence
""",
```

**Step 2: Commit**

```bash
git add apps/adk-server/agentprovision_supervisor/web_researcher.py
git commit -m "feat: add signal detection and entity categorization to web_researcher instructions"
```

---

## Task 11: ADK supervisor agent.py — Signal-aware routing

**Files:**
- Modify: `apps/adk-server/agentprovision_supervisor/agent.py` (lines 19-41, the `instruction` string)

**Step 1: Update supervisor instructions**

```python
    instruction="""You are the AgentProvision AI supervisor - an intelligent orchestrator for data analysis, research, and memory management.

You coordinate a team of specialist agents:
- data_analyst: For data queries, SQL execution, statistical analysis, and generating insights from datasets
- report_generator: For creating reports, visualizations, and formatted outputs
- knowledge_manager: For managing organizational memory — storing entities (leads, contacts, investors, signals), relationships, and retrieving relevant context
- web_researcher: For web scraping, internet research, lead generation, and gathering market intelligence. Always detects buying signals.

Your responsibilities:
1. Understand user requests and route them to the appropriate specialist
2. For complex tasks, coordinate multiple specialists in sequence
3. Maintain conversation context and ensure continuity
4. Always be helpful, accurate, and concise

Routing guidelines:
- Data/analytics questions → data_analyst
- Reports/charts/formatted outputs → report_generator
- Memory, stored knowledge, entity lookup → knowledge_manager
- Web research, scraping, lead generation, market intelligence → web_researcher
- Research + store results → web_researcher first, then knowledge_manager
- "Find signals" or "detect buying intent" → web_researcher (it auto-detects signals and stores them via knowledge_manager)
- For ambiguous requests, ask clarifying questions
- Always explain what you're doing before delegating

Entity categories in memory:
- lead: Companies that might buy products/services
- contact: Decision makers at companies
- investor: VCs, angels, funding sources
- accelerator: Programs, incubators
- signal: Buying signals (hiring, tech adoption, funding, news)
- organization: Generic companies
- person: Generic people
""",
```

**Step 2: Commit**

```bash
git add apps/adk-server/agentprovision_supervisor/agent.py
git commit -m "feat: update supervisor routing with entity taxonomy and signal awareness"
```

---

## Task 12: Apply migration on production + Deploy

**Step 1: Apply migration on Cloud SQL**

```bash
kubectl exec -it deploy/agentprovision-api -n prod -- python -c "
from app.db.session import engine
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text(\"ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS category VARCHAR(50)\"))
    conn.execute(text(\"UPDATE knowledge_entities SET category = 'lead' WHERE entity_type IN ('organization', 'company', 'prospect', 'ai_company', 'enterprise', 'startup', 'saas_platform') AND category IS NULL\"))
    conn.execute(text(\"UPDATE knowledge_entities SET category = 'contact' WHERE entity_type IN ('person', 'cto', 'vp_engineering', 'ceo', 'head_of_ai', 'founder') AND category IS NULL\"))
    conn.execute(text(\"UPDATE knowledge_entities SET category = 'organization' WHERE category IS NULL\"))
    conn.execute(text(\"CREATE INDEX IF NOT EXISTS idx_knowledge_entities_category ON knowledge_entities (category)\"))
    conn.commit()
    print('Migration applied successfully')
"
```

**Step 2: Push to main and deploy**

```bash
git push origin main
```

This triggers the web, api, and worker workflows. Then deploy ADK separately:

```bash
gh workflow run adk-deploy.yaml -f deploy=true -f environment=prod
```

**Step 3: Verify**

- Check `https://agentprovision.com/memory` — should show "Memory" title, Category filter dropdown
- Check API: `curl -H "Authorization: Bearer $TOKEN" https://api.agentprovision.com/api/v1/knowledge/entities?category=lead`
- Check ADK: Send "research AI companies and find buying signals" via chat
