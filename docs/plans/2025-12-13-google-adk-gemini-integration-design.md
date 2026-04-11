# Google ADK + Gemini Integration Design

**Date:** 2025-12-13
**Status:** Approved
**Author:** AI Assistant + Human Review

## Overview

Full migration from Claude/Anthropic to Google Agent Development Kit (ADK) with native Gemini 2.5 Flash support. This replaces the existing custom LLM layer, chat services, tool executor, and orchestration with ADK's built-in capabilities.

## Decisions Summary

| Decision | Choice |
|----------|--------|
| LLM | Gemini 2.5 Flash (native ADK) |
| Framework | Google ADK (full replacement) |
| Feature scope | Full parity in one phase |
| Memory | Hybrid: ADK session + Vertex Vector + PostgreSQL KG |
| Vector store | Vertex AI Vector Search |
| Embeddings | text-embedding-005 (768 dims) |
| Data operations | PostgreSQL via MCP server (all queries) |
| API exposure | ADK API server (separate service) |
| Deployment | New Helm service `agentprovision-adk` |
| Auth | Shared JWT validation |
| Knowledge Graph | Extended schema with 30 entity types, 30 relation types |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         GKE Cluster                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────┐ │
│  │ agentprovision- │    │ agentprovision- │    │    mcp-     │ │
│  │      web        │    │      api        │    │   server    │ │
│  │   (React SPA)   │    │   (FastAPI)     │    │ (PostgreSQL)│ │
│  └────────┬────────┘    └────────┬────────┘    └──────┬──────┘ │
│           │                      │                     │        │
│           │              ┌───────┴───────┐             │        │
│           │              │ Auth, Users,  │             │        │
│           │              │ Datasets,     │             │        │
│           │              │ Tenants       │             │        │
│           │              └───────────────┘             │        │
│           │                                            │        │
│           │    ┌─────────────────────────────┐        │        │
│           └───►│    agentprovision-adk       │◄───────┘        │
│                │    (ADK API Server)         │                  │
│                │                             │                  │
│                │  • Gemini 2.5 Flash         │                  │
│                │  • Multi-agent teams        │                  │
│                │  • Tool execution           │                  │
│                │  • Shared JWT auth          │                  │
│                └──────────────┬──────────────┘                  │
│                               │                                 │
│         ┌─────────────────────┼─────────────────────┐          │
│         ▼                     ▼                     ▼          │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────┐    │
│  │ PostgreSQL  │    │  Vertex AI      │    │ PostgreSQL  │    │
│  │ (metadata)  │    │  Vector Search  │    │ Unity       │    │
│  │             │    │  (RAG)          │    │ Catalog     │    │
│  └─────────────┘    └─────────────────┘    └─────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Key changes:**
- New `agentprovision-adk` service handles all agent/chat operations
- Frontend calls ADK server directly for chat, FastAPI for datasets/auth
- ADK connects to PostgreSQL via MCP server for all data operations
- Vertex AI Vector Search for RAG embeddings (text-embedding-005)
- Hybrid memory: ADK session for hot, PostgreSQL for long-term

---

## ADK Agent Structure

### Agent Mapping

Current `AgentKit` model maps directly to ADK agents:

```python
# Current AgentKit config (stored in PostgreSQL)
{
    "primary_objective": "Analyze sales data and provide insights",
    "triggers": ["analyze", "report", "summarize"],
    "metrics": ["revenue", "conversion_rate"],
    "constraints": ["Only query datasets user has access to"],
    "tool_bindings": [{"tool_id": "...", "alias": "sql_query"}],
    "playbook": [{"name": "step1", "agent_action": "query data"}]
}

# Becomes ADK Agent definition
from google.adk.agents import Agent

sales_analyst = Agent(
    name="sales_analyst",
    model="gemini-2.5-flash",
    instruction="""You are a sales data analyst.
    Primary objective: Analyze sales data and provide insights.
    Metrics to track: revenue, conversion_rate.
    Constraints: Only query datasets user has access to.""",
    tools=[postgres_query, data_summary, calculate],
)
```

### Multi-Agent Teams

Current `AgentGroup` becomes ADK hierarchies:

```python
# Supervisor agent with sub-agents
data_team = Agent(
    name="data_team_supervisor",
    model="gemini-2.5-flash",
    instruction="Coordinate data analysis tasks across specialists.",
    sub_agents=[sales_analyst, marketing_analyst, finance_analyst],
)
```

ADK handles delegation automatically based on agent instructions and capabilities.

---

## AI-First Tool Implementation

### Data Discovery Tools
```python
@tool
def discover_datasets(tenant_id: str, search_query: str = "") -> list:
    """Find available datasets matching criteria."""

@tool
def get_dataset_schema(dataset_id: str) -> dict:
    """Get detailed schema with column types, nullability, sample values."""

@tool
def get_dataset_statistics(dataset_id: str) -> dict:
    """Get statistical profile: distributions, correlations, anomalies."""

@tool
def get_data_lineage(dataset_id: str) -> dict:
    """Trace data origin, transformations, downstream dependencies."""
```

### Data Querying Tools
```python
@tool
def query_sql(sql: str, explanation: str, limit: int = 1000) -> dict:
    """Execute SQL on PostgreSQL Unity Catalog."""

@tool
def query_natural_language(question: str, dataset_ids: list) -> dict:
    """Convert natural language to SQL and execute."""

@tool
def query_timeseries(
    dataset_id: str,
    metric_column: str,
    time_column: str,
    aggregation: str = "sum",
    granularity: str = "day"
) -> dict:
    """Specialized time-series analysis with automatic bucketing."""
```

### Data Transformation Tools
```python
@tool
def create_derived_dataset(
    source_dataset_id: str,
    transformations: list,
    output_name: str
) -> dict:
    """Create new dataset from transformations."""

@tool
def enrich_dataset(
    dataset_id: str,
    enrichment_type: str,  # sentiment, classification, embedding, anomaly_score
    config: dict
) -> dict:
    """Add AI-derived columns to dataset."""
```

### RAG & Knowledge Tools
```python
@tool
def search_knowledge(
    query: str,
    tenant_id: str,
    top_k: int = 5,
    filters: dict = None
) -> list:
    """Semantic search across knowledge base using Vertex AI Vector Search."""

@tool
def store_knowledge(content: str, metadata: dict, tenant_id: str) -> str:
    """Add new knowledge to vector store with text-embedding-005."""

@tool
def get_related_knowledge(entity_id: str, relation_types: list = None) -> dict:
    """Traverse knowledge graph for related entities."""
```

### Analytics & Insights Tools
```python
@tool
def calculate(expression: str) -> float:
    """Evaluate mathematical expression safely."""

@tool
def generate_insights(dataset_id: str, focus_areas: list = None) -> dict:
    """Auto-generate insights from dataset."""

@tool
def compare_periods(
    dataset_id: str,
    metric: str,
    period1: dict,
    period2: dict
) -> dict:
    """Compare metrics across time periods with statistical significance."""

@tool
def forecast(
    dataset_id: str,
    target_column: str,
    time_column: str,
    horizon: int = 30
) -> dict:
    """Generate time-series forecast with confidence intervals."""
```

### Reporting Tools
```python
@tool
def generate_report(
    title: str,
    sections: list,
    format: str = "markdown"
) -> dict:
    """Generate structured report from analysis results."""

@tool
def create_visualization(
    data: dict,
    chart_type: str,  # bar, line, pie, scatter, heatmap, funnel, sankey
    config: dict
) -> dict:
    """Create chart specification for frontend rendering."""
```

### Action & Workflow Tools
```python
@tool
def schedule_pipeline(
    pipeline_config: dict,
    schedule: str,
    notifications: list = None
) -> str:
    """Schedule recurring data pipeline execution."""

@tool
def trigger_alert(
    alert_type: str,
    message: str,
    recipients: list,
    severity: str = "info"
) -> bool:
    """Send notification to users or external systems."""

@tool
def export_data(
    dataset_id: str,
    format: str,
    destination: dict
) -> str:
    """Export dataset to external destination (S3, GCS, email, webhook)."""
```

---

## Memory Architecture

### Three-Tier Hybrid Memory

```
┌─────────────────────────────────────────────────────────────────┐
│                      MEMORY ARCHITECTURE                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              HOT MEMORY (ADK Session)                    │   │
│  │                                                          │   │
│  │  • Current conversation context                          │   │
│  │  • Last 10 messages                                      │   │
│  │  • Active tool results                                   │   │
│  │  • In-memory, per-session                                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            │                                    │
│                            ▼ (summarize & persist)              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           SEMANTIC MEMORY (Vertex AI Vector Search)      │   │
│  │                                                          │   │
│  │  • Conversation summaries (text-embedding-005)           │   │
│  │  • Document chunks for RAG                               │   │
│  │  • Agent learnings & experiences                         │   │
│  │  • Indexed by tenant_id, agent_id, timestamp             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            │                                    │
│                            ▼ (extracted facts)                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           KNOWLEDGE GRAPH (PostgreSQL)                   │   │
│  │                                                          │   │
│  │  • KnowledgeEntity: customers, products, concepts        │   │
│  │  • KnowledgeRelation: relationships between entities     │   │
│  │  • Structured facts extracted from conversations         │   │
│  │  • Cross-session, cross-agent shared knowledge           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Hybrid Memory Service

```python
class HybridMemoryService:
    def __init__(self):
        self.embedding_model = TextEmbeddingModel.from_pretrained("text-embedding-005")
        self.vector_index = aiplatform.MatchingEngineIndex("projects/.../indexes/...")

    async def before_agent_response(self, session: Session, user_message: str):
        """Inject relevant memories before agent thinks."""
        # 1. Semantic search for relevant past context
        embedding = self.embedding_model.get_embeddings([user_message])[0].values
        similar_memories = await self.vector_index.find_neighbors(embedding, top_k=5)

        # 2. Query knowledge graph for relevant entities
        entities = await self.get_related_entities(user_message)

        # 3. Inject into session state
        session.state["relevant_memories"] = similar_memories
        session.state["relevant_entities"] = entities

    async def after_agent_response(self, session: Session, response: str):
        """Persist learnings after agent responds."""
        # 1. If session getting long, summarize and store
        if len(session.messages) > 10:
            summary = await self.summarize_conversation(session)
            await self.store_to_vector(summary, session.tenant_id)

        # 2. Extract and store knowledge entities
        entities = await self.extract_entities(response)
        await self.store_to_knowledge_graph(entities)
```

---

## Enhanced Knowledge Graph

### Entity Types

| Category | Entity Types |
|----------|--------------|
| **Business** | customer, product, organization, person, location, event, transaction, campaign, contract, project |
| **Data** | dataset, table, column, query, report, dashboard, metric, pipeline, data_source, schema |
| **AI** | agent, agent_kit, tool, workflow, insight, prediction, anomaly, pattern, recommendation, alert |

### Relationship Types

| Category | Relationship Types |
|----------|-------------------|
| **Business** | purchased, works_at, manages, reports_to, partners_with, competes_with, located_in, participated_in, owns, influences |
| **Data** | derived_from, joins_with, references, feeds_into, aggregates, transforms, depends_on, contains, measures, schedules |
| **AI** | discovered, predicted, recommended, triggered, generated, validated, learned_from, contradicts, confirms, supersedes |

### PostgreSQL Schema

```sql
-- Core entity table with vector embedding
CREATE TABLE knowledge_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),

    -- Identity
    name VARCHAR(500) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    aliases TEXT[],
    description TEXT,

    -- Flexible properties
    properties JSONB DEFAULT '{}',

    -- AI Metadata
    confidence FLOAT DEFAULT 1.0,
    importance FLOAT DEFAULT 0.5,
    embedding VECTOR(768),  -- pgvector for local search

    -- Provenance
    source_type VARCHAR(50),  -- 'conversation', 'dataset', 'document', 'api', 'manual'
    source_id UUID,
    discovered_by_agent_id UUID REFERENCES agents(id),
    extraction_method VARCHAR(50),  -- 'llm', 'ner', 'rule', 'user'
    verified BOOLEAN DEFAULT FALSE,
    verified_by UUID REFERENCES users(id),

    -- Temporal
    valid_from TIMESTAMP,
    valid_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_accessed_at TIMESTAMP,
    access_count INTEGER DEFAULT 0
);

-- Relationships with rich metadata
CREATE TABLE knowledge_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),

    -- Endpoints
    source_entity_id UUID NOT NULL REFERENCES knowledge_entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES knowledge_entities(id) ON DELETE CASCADE,
    relation_type VARCHAR(100) NOT NULL,

    -- Relation properties
    strength FLOAT DEFAULT 1.0,
    confidence FLOAT DEFAULT 1.0,
    properties JSONB DEFAULT '{}',
    evidence TEXT,

    -- Directionality
    bidirectional BOOLEAN DEFAULT FALSE,

    -- Provenance
    discovered_by_agent_id UUID REFERENCES agents(id),
    source_conversation_id UUID,
    extraction_method VARCHAR(50),

    -- Temporal
    valid_from TIMESTAMP,
    valid_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Entity history for versioning
CREATE TABLE knowledge_entity_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES knowledge_entities(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    properties_snapshot JSONB,
    changed_by UUID,
    change_reason TEXT,
    changed_at TIMESTAMP DEFAULT NOW()
);

-- Observations: raw facts before entity extraction
CREATE TABLE knowledge_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),

    -- Content
    observation_text TEXT NOT NULL,
    observation_type VARCHAR(50),  -- 'fact', 'opinion', 'question', 'hypothesis'
    embedding VECTOR(768),

    -- Source
    source_type VARCHAR(50) NOT NULL,
    source_id UUID,
    conversation_id UUID,
    message_id UUID,

    -- Processing status
    processed BOOLEAN DEFAULT FALSE,
    extracted_entity_ids UUID[],

    -- Metadata
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_entities_tenant_type ON knowledge_entities(tenant_id, entity_type);
CREATE INDEX idx_entities_embedding ON knowledge_entities USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_entities_name_search ON knowledge_entities USING gin(to_tsvector('english', name || ' ' || COALESCE(description, '')));
CREATE INDEX idx_relations_source ON knowledge_relations(source_entity_id);
CREATE INDEX idx_relations_target ON knowledge_relations(target_entity_id);
CREATE INDEX idx_relations_type ON knowledge_relations(tenant_id, relation_type);
CREATE INDEX idx_observations_unprocessed ON knowledge_observations(tenant_id) WHERE NOT processed;
```

### Knowledge Graph Tools

```python
# Entity Operations
@tool
def create_entity(name, entity_type, properties=None, description=None, aliases=None, confidence=1.0) -> dict
@tool
def find_entities(query, entity_types=None, limit=10, min_confidence=0.5) -> list
@tool
def get_entity(entity_id, include_relations=True) -> dict
@tool
def update_entity(entity_id, updates, reason=None) -> dict
@tool
def merge_entities(primary_entity_id, duplicate_entity_ids, reason) -> dict

# Relationship Operations
@tool
def create_relation(source_entity_id, target_entity_id, relation_type, properties=None, strength=1.0, evidence=None, bidirectional=False) -> dict
@tool
def find_relations(entity_id=None, relation_types=None, direction="both", min_strength=0.0) -> list
@tool
def get_path(source_entity_id, target_entity_id, max_depth=4, relation_types=None) -> list

# Graph Traversal
@tool
def get_neighborhood(entity_id, depth=2, relation_types=None, entity_types=None) -> dict
@tool
def find_clusters(entity_type=None, min_cluster_size=3) -> list
@tool
def get_central_entities(entity_type=None, centrality_type="degree", limit=10) -> list

# Knowledge Extraction
@tool
def extract_entities_from_text(text, entity_types=None, auto_create=False) -> list
@tool
def extract_relations_from_text(text, known_entities=None, auto_create=False) -> list
@tool
def record_observation(observation_text, observation_type="fact", source_type="conversation") -> str
@tool
def process_observations(limit=100) -> dict

# Knowledge Queries
@tool
def query_knowledge_graph(cypher_like_query) -> list
@tool
def ask_knowledge_graph(natural_language_question) -> dict
@tool
def get_entity_timeline(entity_id, include_relations=True) -> list

# Knowledge Maintenance
@tool
def validate_knowledge(entity_id=None, auto_fix=False) -> dict
@tool
def suggest_relations(entity_id, limit=5) -> list
@tool
def deprecate_knowledge(entity_id=None, relation_id=None, reason=None) -> bool
```

---

## ADK Service Structure

### Directory Layout

```
apps/
├── api/                    # Existing FastAPI (auth, datasets, tenants)
├── web/                    # Existing React frontend
├── mcp-server/             # Existing PostgreSQL connector
└── adk-server/             # NEW - Google ADK agent service
    ├── Dockerfile
    ├── requirements.txt
    ├── pyproject.toml
    ├── agent.py            # Root agent definition (ADK entry point)
    ├── agents/
    │   ├── __init__.py
    │   ├── data_analyst.py
    │   ├── report_generator.py
    │   ├── knowledge_manager.py
    │   └── supervisor.py
    ├── tools/
    │   ├── __init__.py
    │   ├── data_tools.py
    │   ├── knowledge_tools.py
    │   ├── analytics_tools.py
    │   └── action_tools.py
    ├── memory/
    │   ├── __init__.py
    │   ├── hybrid_memory.py
    │   └── vertex_vector.py
    ├── services/
    │   ├── __init__.py
    │   ├── knowledge_graph.py
    │   ├── postgres_client.py
    │   └── auth.py          # JWT validation (shared SECRET_KEY)
    ├── models/
    │   ├── __init__.py
    │   └── schemas.py       # Pydantic models for API
    └── config/
        ├── __init__.py
        └── settings.py      # Environment config
```

### Root Agent (`agent.py`)

```python
from google.adk.agents import Agent
from agents.data_analyst import data_analyst
from agents.report_generator import report_generator
from agents.knowledge_manager import knowledge_manager

root_agent = Agent(
    name="agentprovision_supervisor",
    model="gemini-2.5-flash",
    instruction="""You are the AgentProvision AI supervisor.

    You coordinate a team of specialist agents:
    - data_analyst: For data queries, analysis, and insights
    - report_generator: For creating reports and visualizations
    - knowledge_manager: For managing organizational knowledge

    Route user requests to the appropriate specialist.
    For complex tasks, coordinate multiple specialists.
    Always maintain context from the knowledge graph.
    """,
    sub_agents=[data_analyst, report_generator, knowledge_manager],
)
```

### Requirements

```
google-adk>=1.21.0
google-cloud-aiplatform>=1.50.0
vertexai>=1.50.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
httpx>=0.27.0
python-jose>=3.3.0
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
pgvector>=0.2.0
```

### Helm Values (`helm/values/agentprovision-adk.yaml`)

```yaml
nameOverride: "agentprovision-adk"
fullnameOverride: "agentprovision-adk"

image:
  repository: gcr.io/ai-agency-479516/agentprovision-adk
  tag: latest
  pullPolicy: IfNotPresent

replicaCount: 1

container:
  port: 8080
  command: ["adk", "api_server", "--port", "8080"]

serviceAccount:
  create: true
  annotations:
    iam.gke.io/gcp-service-account: dev-backend-app@ai-agency-479516.iam.gserviceaccount.com

resources:
  requests:
    cpu: 200m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi

service:
  type: ClusterIP
  port: 80
  targetPort: 8080

configMap:
  enabled: true
  data:
    GOOGLE_GENAI_USE_VERTEXAI: "TRUE"
    ADK_MODEL: "gemini-2.5-flash"
    MCP_SERVER_URL: "http://mcp-server:8000"
    DATABASE_HOST: "localhost"
    DATABASE_PORT: "5432"
    DATABASE_NAME: "agentprovision"

externalSecret:
  enabled: true
  refreshInterval: 1m
  secretStoreRef:
    name: gcpsm-secret-store
    kind: SecretStore
  target:
    name: agentprovision-adk-secret
    creationPolicy: Owner
  data:
    - secretKey: SECRET_KEY
      remoteRef:
        key: agentprovision-secret-key
    - secretKey: DATABASE_URL
      remoteRef:
        key: agentprovision-database-url
    - secretKey: GOOGLE_API_KEY
      remoteRef:
        key: agentprovision-google-api-key
    - secretKey: MCP_API_KEY
      remoteRef:
        key: agentprovision-mcp-api-key

extraContainers:
  - name: cloud-sql-proxy
    image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.8.0
    args:
      - "--private-ip"
      - "--structured-logs"
      - "--port=5432"
      - "ai-agency-479516:us-central1:dev-postgres-instance"
```

---

## Ingress & Frontend Integration

### Updated Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: agentprovision-ingress
  namespace: prod
  annotations:
    kubernetes.io/ingress.class: gce
    networking.gke.io/managed-certificates: agentprovision-cert
spec:
  rules:
    - host: "agentprovision.com"
      http:
        paths:
          - path: /adk
            pathType: Prefix
            backend:
              service:
                name: agentprovision-adk
                port:
                  number: 80
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: agentprovision-api
                port:
                  number: 80
          - path: /
            pathType: Prefix
            backend:
              service:
                name: agentprovision-web
                port:
                  number: 80
```

### Frontend API Changes

```javascript
// apps/web/src/services/api.js
const API_BASE = '/api/v1';
const ADK_BASE = '/adk';

export const agentApi = {
  createSession: (agentId, datasetId) =>
    axios.post(`${ADK_BASE}/apps/agentprovision_supervisor/users/${userId}/sessions`, {
      state: { agent_id: agentId, dataset_id: datasetId }
    }),

  sendMessage: (sessionId, message) =>
    axios.post(`${ADK_BASE}/run`, {
      app_name: 'agentprovision_supervisor',
      user_id: userId,
      session_id: sessionId,
      new_message: { role: 'user', parts: [{ text: message }] }
    }),

  streamMessage: (sessionId, message) =>
    axios.post(`${ADK_BASE}/run_sse`, {
      app_name: 'agentprovision_supervisor',
      user_id: userId,
      session_id: sessionId,
      new_message: { role: 'user', parts: [{ text: message }] }
    }),
};
```

---

## Legacy Cleanup

### Services to DELETE

```
apps/api/app/services/
├── llm.py
├── llm/
│   ├── router.py
│   ├── provider_factory.py
│   └── service.py
├── chat.py
├── enhanced_chat.py
├── tool_executor.py
├── context_manager.py
└── orchestration/
    └── task_dispatcher.py
```

### Models to DELETE

```
apps/api/app/models/
├── llm_provider.py
├── llm_model.py
├── llm_config.py
├── agent_task.py
├── agent_message.py
└── agent_relationship.py
```

### Models to KEEP

```
apps/api/app/models/
├── agent.py              # Maps to ADK Agent definitions
├── agent_kit.py          # Templates for ADK agents
├── agent_group.py        # Maps to ADK multi-agent teams
├── agent_skill.py        # Long-term skill tracking
├── agent_memory.py       # Long-term memory storage
├── knowledge_entity.py   # Knowledge graph (enhanced)
├── knowledge_relation.py # Knowledge graph (enhanced)
├── tenant.py             # Unchanged
├── user.py               # Unchanged
├── dataset.py            # Unchanged
├── data_source.py        # Unchanged
├── data_pipeline.py      # Unchanged
└── chat.py               # Keep for session metadata sync
```

### API Routes to DEPRECATE

```
apps/api/app/api/v1/
├── chat.py           # Move to ADK
├── agent_tasks.py    # ADK handles tasks
├── llm.py            # ADK handles LLM config
└── memories.py       # Move to ADK tools
```

### Frontend Pages to UPDATE

```
apps/web/src/pages/
├── ChatPage.js       # Update to use ADK endpoints
├── AgentsPage.js     # Update to sync with ADK agents
└── AgentKitsPage.js  # Keep, creates ADK agent configs
```

---

## Implementation Order

1. **Infrastructure Setup**
   - Create `apps/adk-server/` directory structure
   - Add Helm values for ADK service
   - Update Ingress with `/adk` route
   - Add GCP Secret Manager entries for `GOOGLE_API_KEY`
   - Create Vertex AI Vector Search index

2. **Core ADK Service**
   - Implement root agent with supervisor pattern
   - Create specialist agents (data_analyst, report_generator, knowledge_manager)
   - Implement JWT auth middleware
   - Add PostgreSQL client (MCP server integration)

3. **Tools Implementation**
   - Data discovery tools
   - Data querying tools (SQL, natural language)
   - Analytics tools (insights, forecast)
   - Knowledge graph tools
   - Reporting tools
   - Action tools

4. **Memory & RAG**
   - Implement hybrid memory service
   - Vertex AI Vector Search integration
   - Knowledge graph enhancement (new schema)
   - Entity extraction pipeline

5. **Frontend Migration**
   - Update ChatPage to use ADK endpoints
   - Add streaming support
   - Update AgentsPage for ADK sync

6. **Legacy Cleanup**
   - Remove deprecated services
   - Remove deprecated models
   - Update API routes
   - Clean up unused frontend code

7. **Testing & Validation**
   - E2E tests for ADK endpoints
   - Tool execution tests
   - Multi-agent coordination tests
   - Memory persistence tests

---

## Sources

- [Google ADK Python GitHub](https://github.com/google/adk-python)
- [Google ADK Documentation](https://google.github.io/adk-docs/)
- [ADK PyPI Package](https://pypi.org/project/google-adk/)
- [ADK Models & Authentication](https://google.github.io/adk-docs/agents/models/)
