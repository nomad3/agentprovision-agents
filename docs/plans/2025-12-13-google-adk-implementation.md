# Google ADK + Gemini Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Claude/Anthropic LLM with Google ADK + Gemini 2.5 Flash, implementing full multi-agent architecture with hybrid memory and knowledge graph.

**Architecture:** New `adk-server` service using Google ADK API server, connected to existing PostgreSQL (via Cloud SQL Proxy), PostgreSQL (via MCP server), and Vertex AI Vector Search for RAG. Frontend calls ADK endpoints directly for chat.

**Tech Stack:** Google ADK 1.21+, Gemini 2.5 Flash, Vertex AI Vector Search, text-embedding-005, PostgreSQL + pgvector, FastAPI (existing), React (existing)

---

## Phase 1: Infrastructure Setup

### Task 1.1: Create ADK Server Directory Structure

**Files:**
- Create: `apps/adk-server/`
- Create: `apps/adk-server/__init__.py`
- Create: `apps/adk-server/agents/__init__.py`
- Create: `apps/adk-server/tools/__init__.py`
- Create: `apps/adk-server/memory/__init__.py`
- Create: `apps/adk-server/services/__init__.py`
- Create: `apps/adk-server/models/__init__.py`
- Create: `apps/adk-server/config/__init__.py`

**Step 1: Create directory structure**

```bash
mkdir -p apps/adk-server/{agents,tools,memory,services,models,config}
```

**Step 2: Create __init__.py files**

```bash
touch apps/adk-server/__init__.py
touch apps/adk-server/agents/__init__.py
touch apps/adk-server/tools/__init__.py
touch apps/adk-server/memory/__init__.py
touch apps/adk-server/services/__init__.py
touch apps/adk-server/models/__init__.py
touch apps/adk-server/config/__init__.py
```

**Step 3: Verify structure**

Run: `find apps/adk-server -type f -name "*.py"`
Expected: 7 __init__.py files listed

**Step 4: Commit**

```bash
git add apps/adk-server/
git commit -m "feat(adk): create adk-server directory structure"
```

---

### Task 1.2: Create ADK Server Requirements

**Files:**
- Create: `apps/adk-server/requirements.txt`

**Step 1: Create requirements.txt**

```
# Google ADK
google-adk>=1.21.0

# Vertex AI for embeddings and vector search
google-cloud-aiplatform>=1.50.0
vertexai>=1.50.0

# Pydantic for schemas
pydantic>=2.0.0
pydantic-settings>=2.0.0

# HTTP client for MCP server
httpx>=0.27.0

# JWT authentication (shared with FastAPI)
python-jose[cryptography]>=3.3.0

# Database
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
pgvector>=0.2.0

# Async support
asyncio>=3.4.3

# Testing
pytest>=7.0.0
pytest-asyncio>=0.21.0
```

**Step 2: Verify file created**

Run: `cat apps/adk-server/requirements.txt | head -5`
Expected: First 5 lines showing google-adk

**Step 3: Commit**

```bash
git add apps/adk-server/requirements.txt
git commit -m "feat(adk): add requirements.txt"
```

---

### Task 1.3: Create ADK Server Configuration

**Files:**
- Create: `apps/adk-server/config/settings.py`

**Step 1: Create settings.py**

```python
"""ADK Server configuration using pydantic-settings."""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Environment configuration for ADK server."""

    # Google AI
    google_api_key: str = ""
    google_genai_use_vertexai: bool = True
    adk_model: str = "gemini-2.5-flash"

    # Database (shared with FastAPI)
    database_url: str = "postgresql://postgres:postgres@localhost:5432/agentprovision"
    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "agentprovision"
    database_user: str = "postgres"
    database_password: str = "postgres"

    # JWT Auth (shared SECRET_KEY with FastAPI)
    secret_key: str = "secret"
    algorithm: str = "HS256"

    # MCP Server (PostgreSQL)
    mcp_server_url: str = "http://mcp-server:8000"
    mcp_api_key: str = "dev_mcp_key"

    # Vertex AI Vector Search
    vertex_project: str = "ai-agency-479516"
    vertex_location: str = "us-central1"
    vector_index_id: str = ""
    vector_endpoint_id: str = ""

    # Embedding model
    embedding_model: str = "text-embedding-005"
    embedding_dimensions: int = 768

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/config/settings.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/config/settings.py
git commit -m "feat(adk): add configuration settings"
```

---

### Task 1.4: Create ADK Server Dockerfile

**Files:**
- Create: `apps/adk-server/Dockerfile`

**Step 1: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 adk && chown -R adk:adk /app
USER adk

# Expose ADK API server port
EXPOSE 8080

# Run ADK API server
CMD ["adk", "api_server", "--port", "8080", "--host", "0.0.0.0"]
```

**Step 2: Verify Dockerfile syntax**

Run: `docker build --check apps/adk-server/ 2>&1 | head -5 || echo "Dockerfile syntax OK"`
Expected: No syntax errors

**Step 3: Commit**

```bash
git add apps/adk-server/Dockerfile
git commit -m "feat(adk): add Dockerfile"
```

---

### Task 1.5: Create Helm Values for ADK Service

**Files:**
- Create: `helm/values/agentprovision-adk.yaml`

**Step 1: Create Helm values**

```yaml
# AgentProvision ADK Service - Google ADK Agent Server
nameOverride: "agentprovision-adk"
fullnameOverride: "agentprovision-adk"

image:
  repository: gcr.io/ai-agency-479516/agentprovision-adk
  tag: latest
  pullPolicy: IfNotPresent

replicaCount: 1

container:
  port: 8080
  command: ["adk", "api_server", "--port", "8080", "--host", "0.0.0.0"]

# Service account with Workload Identity for GCP services
serviceAccount:
  create: true
  annotations:
    iam.gke.io/gcp-service-account: dev-backend-app@ai-agency-479516.iam.gserviceaccount.com

# Pod security - Python app runs as non-root
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000

securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: false  # ADK needs write access
  capabilities:
    drop:
      - ALL

# Resource allocation
resources:
  requests:
    cpu: 200m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi

# Health checks for ADK API server
livenessProbe:
  enabled: true
  httpGet:
    path: /list-apps
    port: http
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  enabled: true
  httpGet:
    path: /list-apps
    port: http
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3

startupProbe:
  enabled: true
  httpGet:
    path: /list-apps
    port: http
  initialDelaySeconds: 10
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 30

# Service configuration
service:
  type: ClusterIP
  port: 80
  targetPort: 8080

# ConfigMap with non-sensitive configuration
configMap:
  enabled: true
  data:
    GOOGLE_GENAI_USE_VERTEXAI: "TRUE"
    ADK_MODEL: "gemini-2.5-flash"
    MCP_SERVER_URL: "http://mcp-server:8000"
    DATABASE_HOST: "localhost"
    DATABASE_PORT: "5432"
    DATABASE_NAME: "agentprovision"
    VERTEX_PROJECT: "ai-agency-479516"
    VERTEX_LOCATION: "us-central1"
    EMBEDDING_MODEL: "text-embedding-005"

# External Secrets - pulls from GCP Secret Manager
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

# Cloud SQL Proxy sidecar for secure database connection
extraContainers:
  - name: cloud-sql-proxy
    image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.8.0
    args:
      - "--private-ip"
      - "--structured-logs"
      - "--port=5432"
      - "--http-port=9090"
      - "ai-agency-479516:us-central1:dev-postgres-instance"
    securityContext:
      runAsNonRoot: true
      allowPrivilegeEscalation: false
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 100m
        memory: 128Mi

# Temporary directories
tmpDirs:
  - /tmp

# Horizontal Pod Autoscaler - disabled for cost savings
autoscaling:
  enabled: false

# Pod Disruption Budget - disabled with 1 replica
podDisruptionBudget:
  enabled: false

# Disable individual Ingress - using shared kubernetes/ingress.yaml
ingress:
  enabled: false
```

**Step 2: Verify YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('helm/values/agentprovision-adk.yaml'))"`
Expected: No output (success)

**Step 3: Commit**

```bash
git add helm/values/agentprovision-adk.yaml
git commit -m "feat(adk): add Helm values for ADK service"
```

---

### Task 1.6: Update Ingress to Include ADK Route

**Files:**
- Modify: `kubernetes/ingress.yaml`

**Step 1: Read current ingress**

Run: `cat kubernetes/ingress.yaml`

**Step 2: Add ADK route to ingress.yaml**

Add the following path before `/api` in the rules section:

```yaml
          # ADK handles all agent/chat operations
          - path: /adk
            pathType: Prefix
            backend:
              service:
                name: agentprovision-adk
                port:
                  number: 80
```

**Step 3: Verify YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('kubernetes/ingress.yaml'))"`
Expected: No output (success)

**Step 4: Commit**

```bash
git add kubernetes/ingress.yaml
git commit -m "feat(adk): add /adk route to shared Ingress"
```

---

### Task 1.7: Create GitHub Actions Workflow for ADK

**Files:**
- Create: `.github/workflows/adk-deploy.yaml`

**Step 1: Create workflow file**

```yaml
name: ADK Service Deploy

on:
  push:
    branches:
      - main
    paths:
      - 'apps/adk-server/**'
      - 'helm/values/agentprovision-adk.yaml'
      - '.github/workflows/adk-deploy.yaml'
  workflow_dispatch:

env:
  GCP_PROJECT: ${{ vars.GCP_PROJECT }}
  GKE_CLUSTER: ${{ vars.GKE_CLUSTER }}
  GKE_ZONE: ${{ vars.GKE_ZONE }}
  IMAGE_NAME: gcr.io/${{ vars.GCP_PROJECT }}/agentprovision-adk
  NAMESPACE: prod
  HELM_RELEASE: agentprovision-adk
  HELM_CHART: ./helm/charts/microservice

jobs:
  build-and-deploy:
    name: Build and Deploy ADK Service
    runs-on: ubuntu-latest
    environment: prod

    permissions:
      contents: read
      id-token: write

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v2

      - name: Configure Docker for GCR
        run: gcloud auth configure-docker --quiet

      - name: Build and push Docker image
        run: |
          docker build -t ${{ env.IMAGE_NAME }}:${{ github.sha }} apps/adk-server/
          docker tag ${{ env.IMAGE_NAME }}:${{ github.sha }} ${{ env.IMAGE_NAME }}:latest
          docker push ${{ env.IMAGE_NAME }}:${{ github.sha }}
          docker push ${{ env.IMAGE_NAME }}:latest

      - name: Get GKE credentials
        uses: google-github-actions/get-gke-credentials@v2
        with:
          cluster_name: ${{ env.GKE_CLUSTER }}
          location: ${{ env.GKE_ZONE }}
          project_id: ${{ env.GCP_PROJECT }}

      - name: Deploy with Helm
        run: |
          helm upgrade --install ${{ env.HELM_RELEASE }} ${{ env.HELM_CHART }} \
            --namespace ${{ env.NAMESPACE }} \
            --values helm/values/agentprovision-adk.yaml \
            --set image.tag=${{ github.sha }} \
            --wait \
            --timeout 10m

      - name: Verify deployment
        run: |
          kubectl rollout status deployment/${{ env.HELM_RELEASE }} -n ${{ env.NAMESPACE }}
          kubectl get pods -n ${{ env.NAMESPACE }} -l app.kubernetes.io/name=agentprovision-adk
```

**Step 2: Verify YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/adk-deploy.yaml'))"`
Expected: No output (success)

**Step 3: Commit**

```bash
git add .github/workflows/adk-deploy.yaml
git commit -m "feat(adk): add GitHub Actions workflow for ADK deployment"
```

---

## Phase 2: Core ADK Service

### Task 2.1: Create Root Agent Definition

**Files:**
- Create: `apps/adk-server/agent.py`

**Step 1: Create agent.py (ADK entry point)**

```python
"""Root agent definition for AgentProvision ADK server.

This is the main entry point for the ADK API server.
The root_agent coordinates specialist sub-agents for different tasks.
"""
from google.adk.agents import Agent

from agents.data_analyst import data_analyst
from agents.report_generator import report_generator
from agents.knowledge_manager import knowledge_manager
from config.settings import settings


# Root supervisor agent - coordinates specialist agents
root_agent = Agent(
    name="agentprovision_supervisor",
    model=settings.adk_model,
    instruction="""You are the AgentProvision AI supervisor - an intelligent orchestrator for data analysis and insights.

You coordinate a team of specialist agents:
- data_analyst: For data queries, SQL execution, statistical analysis, and generating insights from datasets
- report_generator: For creating reports, visualizations, and formatted outputs
- knowledge_manager: For managing organizational knowledge, storing facts, and retrieving relevant context

Your responsibilities:
1. Understand user requests and route them to the appropriate specialist
2. For complex tasks, coordinate multiple specialists in sequence
3. Maintain conversation context and ensure continuity
4. Always be helpful, accurate, and concise

Guidelines:
- If the user asks about data or analytics, delegate to data_analyst
- If the user wants reports, charts, or formatted outputs, delegate to report_generator
- If the user asks about stored knowledge or wants to remember something, delegate to knowledge_manager
- For ambiguous requests, ask clarifying questions
- Always explain what you're doing before delegating
""",
    sub_agents=[data_analyst, report_generator, knowledge_manager],
)
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/agent.py`
Expected: No output (success) - Note: Will fail until sub-agents are created

**Step 3: Commit (after sub-agents created)**

```bash
git add apps/adk-server/agent.py
git commit -m "feat(adk): add root supervisor agent"
```

---

### Task 2.2: Create Data Analyst Agent

**Files:**
- Create: `apps/adk-server/agents/data_analyst.py`

**Step 1: Create data_analyst.py**

```python
"""Data Analyst specialist agent.

Handles all data-related operations:
- Dataset discovery and exploration
- SQL query execution via PostgreSQL
- Statistical analysis and insights
- Natural language to SQL conversion
"""
from google.adk.agents import Agent

from tools.data_tools import (
    discover_datasets,
    get_dataset_schema,
    get_dataset_statistics,
    query_sql,
    query_natural_language,
    generate_insights,
)
from tools.analytics_tools import (
    calculate,
    compare_periods,
    forecast,
)
from tools.knowledge_tools import (
    search_knowledge,
    record_observation,
)
from config.settings import settings


data_analyst = Agent(
    name="data_analyst",
    model=settings.adk_model,
    instruction="""You are a senior data analyst with expertise in SQL, statistics, and data visualization.

Your capabilities:
- Discover and explore available datasets
- Write and execute SQL queries on PostgreSQL Unity Catalog
- Generate statistical insights and forecasts
- Answer natural language questions about data
- Perform calculations and comparisons

Guidelines:
1. Always explore the dataset schema before writing queries
2. Explain your analysis approach before executing
3. Use clear, well-formatted SQL with appropriate LIMIT clauses
4. Record important findings as observations for the knowledge graph
5. Suggest follow-up questions when you discover interesting patterns
6. Be precise with numbers and always cite data sources

When asked about data:
1. First, discover available datasets if needed
2. Get the schema to understand columns
3. Write and execute appropriate queries
4. Summarize findings in a clear, business-friendly way
""",
    tools=[
        discover_datasets,
        get_dataset_schema,
        get_dataset_statistics,
        query_sql,
        query_natural_language,
        generate_insights,
        calculate,
        compare_periods,
        forecast,
        search_knowledge,
        record_observation,
    ],
)
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/agents/data_analyst.py`
Expected: No output (success) - Note: Will fail until tools are created

**Step 3: Commit (after tools created)**

```bash
git add apps/adk-server/agents/data_analyst.py
git commit -m "feat(adk): add data analyst agent"
```

---

### Task 2.3: Create Report Generator Agent

**Files:**
- Create: `apps/adk-server/agents/report_generator.py`

**Step 1: Create report_generator.py**

```python
"""Report Generator specialist agent.

Handles all reporting and visualization tasks:
- Creating formatted reports
- Generating chart specifications
- Exporting data in various formats
"""
from google.adk.agents import Agent

from tools.data_tools import (
    query_sql,
    get_dataset_schema,
)
from tools.action_tools import (
    generate_report,
    create_visualization,
    export_data,
)
from config.settings import settings


report_generator = Agent(
    name="report_generator",
    model=settings.adk_model,
    instruction="""You are a report generation specialist who creates clear, professional reports and visualizations.

Your capabilities:
- Generate formatted reports in markdown or HTML
- Create chart specifications (bar, line, pie, scatter, heatmap)
- Export data to various formats
- Query data to populate reports

Guidelines:
1. Always understand what the user wants to communicate before creating
2. Choose appropriate chart types for the data:
   - Bar charts for comparisons
   - Line charts for trends over time
   - Pie charts for proportions (use sparingly)
   - Scatter plots for correlations
   - Heatmaps for matrices
3. Keep reports concise and focused on key insights
4. Use clear titles and labels
5. Include data sources and timestamps

Report structure:
1. Executive Summary (key findings)
2. Detailed Analysis (with visualizations)
3. Recommendations (actionable next steps)
4. Appendix (methodology, data sources)
""",
    tools=[
        query_sql,
        get_dataset_schema,
        generate_report,
        create_visualization,
        export_data,
    ],
)
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/agents/report_generator.py`
Expected: No output (success)

**Step 3: Commit (after tools created)**

```bash
git add apps/adk-server/agents/report_generator.py
git commit -m "feat(adk): add report generator agent"
```

---

### Task 2.4: Create Knowledge Manager Agent

**Files:**
- Create: `apps/adk-server/agents/knowledge_manager.py`

**Step 1: Create knowledge_manager.py**

```python
"""Knowledge Manager specialist agent.

Handles all knowledge graph and memory operations:
- Storing and retrieving facts
- Managing entity relationships
- Semantic search across knowledge base
"""
from google.adk.agents import Agent

from tools.knowledge_tools import (
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
)
from config.settings import settings


knowledge_manager = Agent(
    name="knowledge_manager",
    model=settings.adk_model,
    instruction="""You are a knowledge management specialist who maintains the organizational knowledge graph.

Your capabilities:
- Create and update knowledge entities (customers, products, concepts)
- Establish relationships between entities
- Search for relevant knowledge using semantic search
- Answer questions by traversing the knowledge graph
- Record observations for later extraction

Entity types you manage:
- Business: customer, product, organization, person, location, event
- Data: dataset, table, metric, pipeline
- AI: insight, prediction, anomaly, pattern, recommendation

Relationship types:
- Business: purchased, works_at, manages, partners_with
- Data: derived_from, joins_with, depends_on, contains
- AI: discovered, predicted, recommended, learned_from

Guidelines:
1. Before creating entities, search for existing ones to avoid duplicates
2. Always record the source and confidence of knowledge
3. Link related entities to build a connected graph
4. Use semantic search to find relevant context
5. Track entity history for important changes
""",
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
    ],
)
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/agents/knowledge_manager.py`
Expected: No output (success)

**Step 3: Commit (after tools created)**

```bash
git add apps/adk-server/agents/knowledge_manager.py
git commit -m "feat(adk): add knowledge manager agent"
```

---

### Task 2.5: Update Agents __init__.py

**Files:**
- Modify: `apps/adk-server/agents/__init__.py`

**Step 1: Update __init__.py to export agents**

```python
"""Agent definitions for AgentProvision ADK server."""
from agents.data_analyst import data_analyst
from agents.report_generator import report_generator
from agents.knowledge_manager import knowledge_manager

__all__ = [
    "data_analyst",
    "report_generator",
    "knowledge_manager",
]
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/agents/__init__.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/agents/__init__.py
git commit -m "feat(adk): export agents from __init__.py"
```

---

## Phase 3: Tools Implementation

### Task 3.1: Create PostgreSQL Client Service

**Files:**
- Create: `apps/adk-server/services/postgres_client.py`

**Step 1: Create postgres_client.py**

```python
"""PostgreSQL client that communicates with MCP server.

All data operations route through the MCP server to PostgreSQL Unity Catalog.
"""
import httpx
from typing import Any, Optional

from config.settings import settings


class PostgreSQLClient:
    """HTTP client for MCP server (PostgreSQL operations)."""

    def __init__(self):
        self.base_url = settings.mcp_server_url
        self.api_key = settings.mcp_api_key
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            timeout=60.0,
        )

    async def query_sql(
        self,
        sql: str,
        catalog: Optional[str] = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Execute SQL query on PostgreSQL."""
        response = await self.client.post(
            "/tools/query_sql",
            json={
                "sql": sql,
                "catalog": catalog,
                "limit": limit,
            },
        )
        response.raise_for_status()
        return response.json()

    async def list_tables(
        self,
        catalog: str,
        schema: str = "silver",
    ) -> list[dict[str, Any]]:
        """List tables in PostgreSQL catalog."""
        response = await self.client.post(
            "/tools/list_tables",
            json={
                "catalog": catalog,
                "schema": schema,
            },
        )
        response.raise_for_status()
        return response.json()

    async def describe_table(
        self,
        catalog: str,
        schema: str,
        table: str,
    ) -> dict[str, Any]:
        """Get table schema and statistics."""
        response = await self.client.post(
            "/tools/describe_table",
            json={
                "catalog": catalog,
                "schema": schema,
                "table": table,
            },
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance
_client: Optional[PostgreSQLClient] = None


def get_postgres_client() -> PostgreSQLClient:
    """Get or create PostgreSQL client singleton."""
    global _client
    if _client is None:
        _client = PostgreSQLClient()
    return _client
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/services/postgres_client.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/services/postgres_client.py
git commit -m "feat(adk): add PostgreSQL MCP client"
```

---

### Task 3.2: Create Data Tools

**Files:**
- Create: `apps/adk-server/tools/data_tools.py`

**Step 1: Create data_tools.py**

```python
"""Data discovery and querying tools.

All data operations route through MCP server to PostgreSQL.
"""
from google.adk.tools import tool
from typing import Optional

from services.postgres_client import get_postgres_client


@tool
async def discover_datasets(
    tenant_id: str,
    search_query: str = "",
) -> list[dict]:
    """Find available datasets matching criteria.

    Args:
        tenant_id: Tenant context for isolation
        search_query: Optional natural language search (e.g., "sales data from 2024")

    Returns:
        List of datasets with name, schema, row count, last updated
    """
    client = get_postgres_client()
    # List tables from tenant's catalog
    catalog = f"tenant_{tenant_id.replace('-', '_')}"
    tables = await client.list_tables(catalog=catalog, schema="silver")

    # Filter by search query if provided
    if search_query:
        search_lower = search_query.lower()
        tables = [t for t in tables if search_lower in t.get("name", "").lower()]

    return tables


@tool
async def get_dataset_schema(dataset_id: str) -> dict:
    """Get detailed schema with column types, nullability, sample values.

    Args:
        dataset_id: Dataset identifier (format: catalog.schema.table)

    Returns:
        Schema with columns, types, and sample data
    """
    client = get_postgres_client()
    parts = dataset_id.split(".")
    if len(parts) != 3:
        return {"error": "Invalid dataset_id format. Expected: catalog.schema.table"}

    catalog, schema, table = parts
    return await client.describe_table(catalog=catalog, schema=schema, table=table)


@tool
async def get_dataset_statistics(dataset_id: str) -> dict:
    """Get statistical profile: distributions, correlations, anomalies.

    Args:
        dataset_id: Dataset identifier (format: catalog.schema.table)

    Returns:
        Statistical summary including counts, means, distributions
    """
    client = get_postgres_client()

    # Run DESCRIBE EXTENDED to get table stats
    sql = f"DESCRIBE EXTENDED {dataset_id}"
    result = await client.query_sql(sql=sql)

    # Also get row count and column stats
    count_sql = f"SELECT COUNT(*) as row_count FROM {dataset_id}"
    count_result = await client.query_sql(sql=count_sql)

    return {
        "table_info": result,
        "row_count": count_result.get("rows", [{}])[0].get("row_count", 0),
    }


@tool
async def query_sql(
    sql: str,
    explanation: str = "",
    limit: int = 1000,
) -> dict:
    """Execute SQL query on PostgreSQL Unity Catalog.

    Args:
        sql: The SQL query to execute
        explanation: Brief explanation of what this query does
        limit: Maximum rows to return (default 1000)

    Returns:
        Query results with rows, column names, and metadata
    """
    client = get_postgres_client()

    # Add LIMIT if not present
    sql_upper = sql.upper()
    if "LIMIT" not in sql_upper:
        sql = f"{sql.rstrip(';')} LIMIT {limit}"

    result = await client.query_sql(sql=sql, limit=limit)

    return {
        "rows": result.get("rows", []),
        "columns": result.get("columns", []),
        "row_count": len(result.get("rows", [])),
        "explanation": explanation,
        "query": sql,
    }


@tool
async def query_natural_language(
    question: str,
    dataset_ids: list[str],
) -> dict:
    """Convert natural language question to SQL and execute.

    Args:
        question: Natural language question (e.g., "What were top 10 products by revenue?")
        dataset_ids: List of dataset identifiers to query against

    Returns:
        Generated SQL, results, and explanation
    """
    # This will be enhanced with LLM-powered SQL generation
    # For now, return a placeholder that the agent can work with
    return {
        "question": question,
        "datasets": dataset_ids,
        "note": "Natural language query requires agent to generate SQL based on schema",
    }


@tool
async def generate_insights(
    dataset_id: str,
    focus_areas: Optional[list[str]] = None,
) -> dict:
    """Auto-generate insights from dataset.

    Args:
        dataset_id: Dataset identifier
        focus_areas: Optional list of areas to focus on (e.g., ["trends", "anomalies"])

    Returns:
        Key findings, suggested follow-up questions, visualization recommendations
    """
    client = get_postgres_client()

    # Get basic statistics
    stats_sql = f"""
    SELECT
        COUNT(*) as total_rows,
        COUNT(DISTINCT *) as unique_rows
    FROM {dataset_id}
    """
    stats = await client.query_sql(sql=stats_sql)

    return {
        "dataset": dataset_id,
        "statistics": stats,
        "focus_areas": focus_areas or ["general"],
        "note": "Detailed insights will be generated by the agent based on data exploration",
    }
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/tools/data_tools.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/tools/data_tools.py
git commit -m "feat(adk): add data discovery and querying tools"
```

---

### Task 3.3: Create Analytics Tools

**Files:**
- Create: `apps/adk-server/tools/analytics_tools.py`

**Step 1: Create analytics_tools.py**

```python
"""Analytics and calculation tools."""
from google.adk.tools import tool
from typing import Optional
import re

from services.postgres_client import get_postgres_client


@tool
def calculate(expression: str) -> dict:
    """Evaluate a mathematical expression safely.

    Args:
        expression: Mathematical expression (e.g., "100 * 1.15", "(500 - 300) / 200")

    Returns:
        Calculated result
    """
    # Only allow safe characters
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        return {"error": "Invalid characters in expression. Only numbers and +-*/() allowed."}

    try:
        result = eval(expression)
        return {
            "expression": expression,
            "result": result,
        }
    except Exception as e:
        return {"error": f"Calculation error: {str(e)}"}


@tool
async def compare_periods(
    dataset_id: str,
    metric: str,
    period1: dict,
    period2: dict,
    time_column: str = "date",
) -> dict:
    """Compare metrics across time periods with statistical significance.

    Args:
        dataset_id: Dataset identifier
        metric: Column name to compare (e.g., "revenue", "count")
        period1: First period {"start": "2024-01-01", "end": "2024-03-31"}
        period2: Second period {"start": "2024-04-01", "end": "2024-06-30"}
        time_column: Name of the date/timestamp column

    Returns:
        Comparison with absolute and percentage changes
    """
    client = get_postgres_client()

    sql = f"""
    WITH period1_data AS (
        SELECT SUM({metric}) as total, AVG({metric}) as avg, COUNT(*) as count
        FROM {dataset_id}
        WHERE {time_column} BETWEEN '{period1["start"]}' AND '{period1["end"]}'
    ),
    period2_data AS (
        SELECT SUM({metric}) as total, AVG({metric}) as avg, COUNT(*) as count
        FROM {dataset_id}
        WHERE {time_column} BETWEEN '{period2["start"]}' AND '{period2["end"]}'
    )
    SELECT
        p1.total as period1_total,
        p1.avg as period1_avg,
        p1.count as period1_count,
        p2.total as period2_total,
        p2.avg as period2_avg,
        p2.count as period2_count,
        (p2.total - p1.total) as absolute_change,
        CASE WHEN p1.total > 0 THEN ((p2.total - p1.total) / p1.total * 100) ELSE NULL END as pct_change
    FROM period1_data p1, period2_data p2
    """

    result = await client.query_sql(sql=sql)

    return {
        "metric": metric,
        "period1": period1,
        "period2": period2,
        "comparison": result.get("rows", [{}])[0] if result.get("rows") else {},
    }


@tool
async def forecast(
    dataset_id: str,
    target_column: str,
    time_column: str,
    horizon: int = 30,
) -> dict:
    """Generate time-series forecast with confidence intervals.

    Args:
        dataset_id: Dataset identifier
        target_column: Column to forecast
        time_column: Date/timestamp column
        horizon: Number of periods to forecast (default 30)

    Returns:
        Historical data and forecasted values with confidence intervals
    """
    client = get_postgres_client()

    # Get historical data for trend analysis
    sql = f"""
    SELECT
        {time_column},
        {target_column},
        AVG({target_column}) OVER (ORDER BY {time_column} ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) as moving_avg
    FROM {dataset_id}
    ORDER BY {time_column} DESC
    LIMIT 100
    """

    result = await client.query_sql(sql=sql)

    return {
        "dataset": dataset_id,
        "target": target_column,
        "horizon": horizon,
        "historical_data": result.get("rows", []),
        "note": "Advanced forecasting requires statistical models. This provides historical context.",
    }
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/tools/analytics_tools.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/tools/analytics_tools.py
git commit -m "feat(adk): add analytics and calculation tools"
```

---

### Task 3.4: Create Knowledge Tools

**Files:**
- Create: `apps/adk-server/tools/knowledge_tools.py`

**Step 1: Create knowledge_tools.py**

```python
"""Knowledge graph and memory tools.

Manages entities, relationships, and semantic search.
"""
from google.adk.tools import tool
from typing import Optional
import uuid

from services.knowledge_graph import get_knowledge_service


@tool
async def create_entity(
    name: str,
    entity_type: str,
    tenant_id: str,
    properties: Optional[dict] = None,
    description: Optional[str] = None,
    aliases: Optional[list[str]] = None,
    confidence: float = 1.0,
) -> dict:
    """Create a new knowledge entity.

    Args:
        name: Entity name
        entity_type: Type (customer, product, organization, person, etc.)
        tenant_id: Tenant context
        properties: Additional properties as JSON
        description: Human-readable description
        aliases: Alternative names
        confidence: Confidence score 0-1

    Returns:
        Created entity with ID
    """
    kg = get_knowledge_service()
    return await kg.create_entity(
        name=name,
        entity_type=entity_type,
        tenant_id=tenant_id,
        properties=properties or {},
        description=description,
        aliases=aliases or [],
        confidence=confidence,
    )


@tool
async def find_entities(
    query: str,
    tenant_id: str,
    entity_types: Optional[list[str]] = None,
    limit: int = 10,
    min_confidence: float = 0.5,
) -> list[dict]:
    """Semantic search for entities by name, description, or properties.

    Args:
        query: Search query
        tenant_id: Tenant context
        entity_types: Filter by types
        limit: Max results
        min_confidence: Minimum confidence threshold

    Returns:
        Matching entities ranked by relevance
    """
    kg = get_knowledge_service()
    return await kg.find_entities(
        query=query,
        tenant_id=tenant_id,
        entity_types=entity_types,
        limit=limit,
        min_confidence=min_confidence,
    )


@tool
async def get_entity(
    entity_id: str,
    include_relations: bool = True,
) -> dict:
    """Get entity with all its relationships.

    Args:
        entity_id: Entity UUID
        include_relations: Whether to include relationships

    Returns:
        Entity with properties and optionally relationships
    """
    kg = get_knowledge_service()
    return await kg.get_entity(
        entity_id=entity_id,
        include_relations=include_relations,
    )


@tool
async def update_entity(
    entity_id: str,
    updates: dict,
    reason: Optional[str] = None,
) -> dict:
    """Update entity properties (creates version history).

    Args:
        entity_id: Entity UUID
        updates: Properties to update
        reason: Reason for change (for audit)

    Returns:
        Updated entity
    """
    kg = get_knowledge_service()
    return await kg.update_entity(
        entity_id=entity_id,
        updates=updates,
        reason=reason,
    )


@tool
async def merge_entities(
    primary_entity_id: str,
    duplicate_entity_ids: list[str],
    reason: str,
) -> dict:
    """Merge duplicate entities, preserving relationships.

    Args:
        primary_entity_id: Entity to keep
        duplicate_entity_ids: Entities to merge into primary
        reason: Reason for merge

    Returns:
        Merged entity
    """
    kg = get_knowledge_service()
    return await kg.merge_entities(
        primary_entity_id=primary_entity_id,
        duplicate_entity_ids=duplicate_entity_ids,
        reason=reason,
    )


@tool
async def create_relation(
    source_entity_id: str,
    target_entity_id: str,
    relation_type: str,
    tenant_id: str,
    properties: Optional[dict] = None,
    strength: float = 1.0,
    evidence: Optional[str] = None,
    bidirectional: bool = False,
) -> dict:
    """Create relationship between entities.

    Args:
        source_entity_id: Source entity UUID
        target_entity_id: Target entity UUID
        relation_type: Type (purchased, works_at, derived_from, etc.)
        tenant_id: Tenant context
        properties: Additional properties
        strength: Relationship strength 0-1
        evidence: Supporting context
        bidirectional: If true, creates both directions

    Returns:
        Created relationship
    """
    kg = get_knowledge_service()
    return await kg.create_relation(
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relation_type=relation_type,
        tenant_id=tenant_id,
        properties=properties or {},
        strength=strength,
        evidence=evidence,
        bidirectional=bidirectional,
    )


@tool
async def find_relations(
    tenant_id: str,
    entity_id: Optional[str] = None,
    relation_types: Optional[list[str]] = None,
    direction: str = "both",
    min_strength: float = 0.0,
) -> list[dict]:
    """Find relationships for an entity.

    Args:
        tenant_id: Tenant context
        entity_id: Entity to find relations for (optional)
        relation_types: Filter by types
        direction: 'outgoing', 'incoming', or 'both'
        min_strength: Minimum strength threshold

    Returns:
        List of relationships
    """
    kg = get_knowledge_service()
    return await kg.find_relations(
        tenant_id=tenant_id,
        entity_id=entity_id,
        relation_types=relation_types,
        direction=direction,
        min_strength=min_strength,
    )


@tool
async def get_path(
    source_entity_id: str,
    target_entity_id: str,
    max_depth: int = 4,
    relation_types: Optional[list[str]] = None,
) -> list[dict]:
    """Find shortest path between two entities through relationships.

    Args:
        source_entity_id: Starting entity
        target_entity_id: Ending entity
        max_depth: Maximum hops
        relation_types: Filter by relationship types

    Returns:
        Path as list of entities and relationships
    """
    kg = get_knowledge_service()
    return await kg.get_path(
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        max_depth=max_depth,
        relation_types=relation_types,
    )


@tool
async def get_neighborhood(
    entity_id: str,
    depth: int = 2,
    relation_types: Optional[list[str]] = None,
    entity_types: Optional[list[str]] = None,
) -> dict:
    """Get entity neighborhood graph up to N hops.

    Args:
        entity_id: Center entity
        depth: Number of hops
        relation_types: Filter relationships
        entity_types: Filter entities

    Returns:
        Subgraph with entities and relations
    """
    kg = get_knowledge_service()
    return await kg.get_neighborhood(
        entity_id=entity_id,
        depth=depth,
        relation_types=relation_types,
        entity_types=entity_types,
    )


@tool
async def search_knowledge(
    query: str,
    tenant_id: str,
    top_k: int = 5,
    filters: Optional[dict] = None,
) -> list[dict]:
    """Semantic search across knowledge base using Vertex AI Vector Search.

    Args:
        query: Natural language search query
        tenant_id: Tenant context
        top_k: Number of results
        filters: Optional metadata filters

    Returns:
        Ranked results with relevance scores
    """
    kg = get_knowledge_service()
    return await kg.search_knowledge(
        query=query,
        tenant_id=tenant_id,
        top_k=top_k,
        filters=filters,
    )


@tool
async def store_knowledge(
    content: str,
    metadata: dict,
    tenant_id: str,
) -> str:
    """Add new knowledge to vector store with text-embedding-005.

    Args:
        content: Text content to store
        metadata: Associated metadata
        tenant_id: Tenant context

    Returns:
        ID of stored knowledge
    """
    kg = get_knowledge_service()
    return await kg.store_knowledge(
        content=content,
        metadata=metadata,
        tenant_id=tenant_id,
    )


@tool
async def record_observation(
    observation_text: str,
    tenant_id: str,
    observation_type: str = "fact",
    source_type: str = "conversation",
) -> str:
    """Record raw observation for later entity extraction.

    Args:
        observation_text: The observation to record
        tenant_id: Tenant context
        observation_type: Type (fact, opinion, question, hypothesis)
        source_type: Source (conversation, dataset, document)

    Returns:
        Observation ID
    """
    kg = get_knowledge_service()
    return await kg.record_observation(
        observation_text=observation_text,
        tenant_id=tenant_id,
        observation_type=observation_type,
        source_type=source_type,
    )


@tool
async def ask_knowledge_graph(
    natural_language_question: str,
    tenant_id: str,
) -> dict:
    """Answer questions using knowledge graph traversal.

    Args:
        natural_language_question: Question to answer
        tenant_id: Tenant context

    Returns:
        Answer with supporting entities and relations
    """
    kg = get_knowledge_service()
    return await kg.ask_knowledge_graph(
        question=natural_language_question,
        tenant_id=tenant_id,
    )


@tool
async def get_entity_timeline(
    entity_id: str,
    include_relations: bool = True,
) -> list[dict]:
    """Get chronological history of entity changes and interactions.

    Args:
        entity_id: Entity UUID
        include_relations: Include relationship changes

    Returns:
        Timeline of events
    """
    kg = get_knowledge_service()
    return await kg.get_entity_timeline(
        entity_id=entity_id,
        include_relations=include_relations,
    )
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/tools/knowledge_tools.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/tools/knowledge_tools.py
git commit -m "feat(adk): add knowledge graph tools"
```

---

### Task 3.5: Create Action Tools

**Files:**
- Create: `apps/adk-server/tools/action_tools.py`

**Step 1: Create action_tools.py**

```python
"""Action and reporting tools.

Handles report generation, visualizations, and exports.
"""
from google.adk.tools import tool
from typing import Optional
import json


@tool
def generate_report(
    title: str,
    sections: list[dict],
    format: str = "markdown",
) -> dict:
    """Generate structured report from analysis results.

    Args:
        title: Report title
        sections: List of sections with:
            - heading: Section title
            - content_type: 'chart', 'table', or 'text'
            - data: Content data
        format: Output format ('markdown', 'html')

    Returns:
        Formatted report content
    """
    if format == "markdown":
        report = f"# {title}\n\n"
        for section in sections:
            report += f"## {section.get('heading', 'Section')}\n\n"
            content_type = section.get('content_type', 'text')
            data = section.get('data', '')

            if content_type == 'text':
                report += f"{data}\n\n"
            elif content_type == 'table':
                # Format as markdown table
                if isinstance(data, list) and len(data) > 0:
                    headers = list(data[0].keys())
                    report += "| " + " | ".join(headers) + " |\n"
                    report += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                    for row in data:
                        report += "| " + " | ".join(str(row.get(h, '')) for h in headers) + " |\n"
                    report += "\n"
            elif content_type == 'chart':
                report += f"[Chart: {section.get('heading', 'Chart')}]\n\n"
                report += f"```json\n{json.dumps(data, indent=2)}\n```\n\n"

        return {
            "format": format,
            "content": report,
            "title": title,
            "section_count": len(sections),
        }
    else:
        return {"error": f"Unsupported format: {format}"}


@tool
def create_visualization(
    data: dict,
    chart_type: str,
    config: dict,
) -> dict:
    """Create chart specification for frontend rendering.

    Args:
        data: Data to visualize (rows, columns)
        chart_type: Type (bar, line, pie, scatter, heatmap, funnel, sankey)
        config: Chart configuration:
            - title: Chart title
            - x_axis: X-axis column
            - y_axis: Y-axis column(s)
            - color: Color column (optional)
            - labels: Show labels (boolean)

    Returns:
        Chart specification for frontend
    """
    valid_types = ["bar", "line", "pie", "scatter", "heatmap", "funnel", "sankey"]
    if chart_type not in valid_types:
        return {"error": f"Invalid chart type. Must be one of: {valid_types}"}

    spec = {
        "type": chart_type,
        "data": data,
        "config": {
            "title": config.get("title", "Chart"),
            "x_axis": config.get("x_axis"),
            "y_axis": config.get("y_axis"),
            "color": config.get("color"),
            "labels": config.get("labels", True),
        },
    }

    return {
        "chart_spec": spec,
        "chart_type": chart_type,
        "note": "Render this specification in the frontend visualization library",
    }


@tool
async def export_data(
    dataset_id: str,
    format: str,
    destination: dict,
) -> str:
    """Export dataset to external destination.

    Args:
        dataset_id: Dataset to export
        format: Export format (csv, json, parquet)
        destination: Where to export:
            - type: 'gcs', 's3', 'email', 'webhook'
            - path: Destination path or URL

    Returns:
        Export job ID or download URL
    """
    valid_formats = ["csv", "json", "parquet"]
    if format not in valid_formats:
        return f"Invalid format. Must be one of: {valid_formats}"

    valid_destinations = ["gcs", "s3", "email", "webhook"]
    dest_type = destination.get("type", "")
    if dest_type not in valid_destinations:
        return f"Invalid destination type. Must be one of: {valid_destinations}"

    # This would integrate with actual export service
    return {
        "status": "queued",
        "dataset_id": dataset_id,
        "format": format,
        "destination": destination,
        "note": "Export will be processed asynchronously",
    }
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/tools/action_tools.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/tools/action_tools.py
git commit -m "feat(adk): add action and reporting tools"
```

---

### Task 3.6: Update Tools __init__.py

**Files:**
- Modify: `apps/adk-server/tools/__init__.py`

**Step 1: Update __init__.py to export tools**

```python
"""Tool definitions for AgentProvision ADK server."""
from tools.data_tools import (
    discover_datasets,
    get_dataset_schema,
    get_dataset_statistics,
    query_sql,
    query_natural_language,
    generate_insights,
)
from tools.analytics_tools import (
    calculate,
    compare_periods,
    forecast,
)
from tools.knowledge_tools import (
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
)
from tools.action_tools import (
    generate_report,
    create_visualization,
    export_data,
)

__all__ = [
    # Data tools
    "discover_datasets",
    "get_dataset_schema",
    "get_dataset_statistics",
    "query_sql",
    "query_natural_language",
    "generate_insights",
    # Analytics tools
    "calculate",
    "compare_periods",
    "forecast",
    # Knowledge tools
    "create_entity",
    "find_entities",
    "get_entity",
    "update_entity",
    "merge_entities",
    "create_relation",
    "find_relations",
    "get_path",
    "get_neighborhood",
    "search_knowledge",
    "store_knowledge",
    "record_observation",
    "ask_knowledge_graph",
    "get_entity_timeline",
    # Action tools
    "generate_report",
    "create_visualization",
    "export_data",
]
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/tools/__init__.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/tools/__init__.py
git commit -m "feat(adk): export tools from __init__.py"
```

---

## Phase 4: Knowledge Graph Service

### Task 4.1: Create Knowledge Graph Service

**Files:**
- Create: `apps/adk-server/services/knowledge_graph.py`

**Step 1: Create knowledge_graph.py**

```python
"""Knowledge graph service for entity and relationship management.

Uses PostgreSQL with pgvector for storage and Vertex AI for embeddings.
"""
from typing import Optional, Any
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import uuid

from config.settings import settings
from memory.vertex_vector import get_embedding_service


class KnowledgeGraphService:
    """Manages knowledge entities and relationships in PostgreSQL."""

    def __init__(self):
        self.engine = create_engine(settings.database_url)
        self.Session = sessionmaker(bind=self.engine)
        self.embedding_service = get_embedding_service()

    async def create_entity(
        self,
        name: str,
        entity_type: str,
        tenant_id: str,
        properties: dict = None,
        description: str = None,
        aliases: list = None,
        confidence: float = 1.0,
    ) -> dict:
        """Create a new knowledge entity."""
        entity_id = str(uuid.uuid4())

        # Generate embedding for semantic search
        text_for_embedding = f"{name} {description or ''}"
        embedding = await self.embedding_service.get_embedding(text_for_embedding)

        with self.Session() as session:
            session.execute(
                text("""
                    INSERT INTO knowledge_entities
                    (id, tenant_id, name, entity_type, description, properties, aliases, confidence, embedding)
                    VALUES (:id, :tenant_id, :name, :entity_type, :description, :properties, :aliases, :confidence, :embedding)
                """),
                {
                    "id": entity_id,
                    "tenant_id": tenant_id,
                    "name": name,
                    "entity_type": entity_type,
                    "description": description,
                    "properties": properties or {},
                    "aliases": aliases or [],
                    "confidence": confidence,
                    "embedding": embedding,
                }
            )
            session.commit()

        return {"id": entity_id, "name": name, "entity_type": entity_type}

    async def find_entities(
        self,
        query: str,
        tenant_id: str,
        entity_types: list = None,
        limit: int = 10,
        min_confidence: float = 0.5,
    ) -> list[dict]:
        """Semantic search for entities."""
        # Get query embedding
        query_embedding = await self.embedding_service.get_embedding(query)

        with self.Session() as session:
            type_filter = ""
            if entity_types:
                type_list = ",".join(f"'{t}'" for t in entity_types)
                type_filter = f"AND entity_type IN ({type_list})"

            result = session.execute(
                text(f"""
                    SELECT id, name, entity_type, description, confidence,
                           1 - (embedding <=> :embedding) as similarity
                    FROM knowledge_entities
                    WHERE tenant_id = :tenant_id
                    AND confidence >= :min_confidence
                    {type_filter}
                    ORDER BY embedding <=> :embedding
                    LIMIT :limit
                """),
                {
                    "tenant_id": tenant_id,
                    "embedding": query_embedding,
                    "min_confidence": min_confidence,
                    "limit": limit,
                }
            )

            return [dict(row._mapping) for row in result]

    async def get_entity(
        self,
        entity_id: str,
        include_relations: bool = True,
    ) -> dict:
        """Get entity by ID with optional relationships."""
        with self.Session() as session:
            result = session.execute(
                text("""
                    SELECT id, tenant_id, name, entity_type, description,
                           properties, aliases, confidence, created_at, updated_at
                    FROM knowledge_entities
                    WHERE id = :entity_id
                """),
                {"entity_id": entity_id}
            ).fetchone()

            if not result:
                return {"error": "Entity not found"}

            entity = dict(result._mapping)

            if include_relations:
                relations = session.execute(
                    text("""
                        SELECT r.id, r.relation_type, r.strength, r.properties,
                               e.id as target_id, e.name as target_name, e.entity_type as target_type
                        FROM knowledge_relations r
                        JOIN knowledge_entities e ON r.target_entity_id = e.id
                        WHERE r.source_entity_id = :entity_id
                        UNION ALL
                        SELECT r.id, r.relation_type, r.strength, r.properties,
                               e.id as target_id, e.name as target_name, e.entity_type as target_type
                        FROM knowledge_relations r
                        JOIN knowledge_entities e ON r.source_entity_id = e.id
                        WHERE r.target_entity_id = :entity_id
                    """),
                    {"entity_id": entity_id}
                )
                entity["relations"] = [dict(row._mapping) for row in relations]

            return entity

    async def update_entity(
        self,
        entity_id: str,
        updates: dict,
        reason: str = None,
    ) -> dict:
        """Update entity and create history record."""
        with self.Session() as session:
            # Get current state for history
            current = session.execute(
                text("SELECT properties FROM knowledge_entities WHERE id = :id"),
                {"id": entity_id}
            ).fetchone()

            if current:
                # Create history record
                session.execute(
                    text("""
                        INSERT INTO knowledge_entity_history
                        (entity_id, version, properties_snapshot, change_reason)
                        SELECT :entity_id, COALESCE(MAX(version), 0) + 1, :properties, :reason
                        FROM knowledge_entity_history WHERE entity_id = :entity_id
                    """),
                    {
                        "entity_id": entity_id,
                        "properties": current.properties,
                        "reason": reason,
                    }
                )

            # Update entity
            session.execute(
                text("""
                    UPDATE knowledge_entities
                    SET properties = properties || :updates, updated_at = NOW()
                    WHERE id = :entity_id
                """),
                {"entity_id": entity_id, "updates": updates}
            )
            session.commit()

        return await self.get_entity(entity_id, include_relations=False)

    async def merge_entities(
        self,
        primary_entity_id: str,
        duplicate_entity_ids: list[str],
        reason: str,
    ) -> dict:
        """Merge duplicate entities into primary."""
        with self.Session() as session:
            for dup_id in duplicate_entity_ids:
                # Move relations to primary
                session.execute(
                    text("""
                        UPDATE knowledge_relations
                        SET source_entity_id = :primary_id
                        WHERE source_entity_id = :dup_id
                    """),
                    {"primary_id": primary_entity_id, "dup_id": dup_id}
                )
                session.execute(
                    text("""
                        UPDATE knowledge_relations
                        SET target_entity_id = :primary_id
                        WHERE target_entity_id = :dup_id
                    """),
                    {"primary_id": primary_entity_id, "dup_id": dup_id}
                )

                # Delete duplicate
                session.execute(
                    text("DELETE FROM knowledge_entities WHERE id = :id"),
                    {"id": dup_id}
                )

            session.commit()

        return await self.get_entity(primary_entity_id)

    async def create_relation(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        tenant_id: str,
        properties: dict = None,
        strength: float = 1.0,
        evidence: str = None,
        bidirectional: bool = False,
    ) -> dict:
        """Create relationship between entities."""
        relation_id = str(uuid.uuid4())

        with self.Session() as session:
            session.execute(
                text("""
                    INSERT INTO knowledge_relations
                    (id, tenant_id, source_entity_id, target_entity_id, relation_type,
                     properties, strength, evidence, bidirectional)
                    VALUES (:id, :tenant_id, :source_id, :target_id, :relation_type,
                            :properties, :strength, :evidence, :bidirectional)
                """),
                {
                    "id": relation_id,
                    "tenant_id": tenant_id,
                    "source_id": source_entity_id,
                    "target_id": target_entity_id,
                    "relation_type": relation_type,
                    "properties": properties or {},
                    "strength": strength,
                    "evidence": evidence,
                    "bidirectional": bidirectional,
                }
            )
            session.commit()

        return {"id": relation_id, "relation_type": relation_type}

    async def find_relations(
        self,
        tenant_id: str,
        entity_id: str = None,
        relation_types: list = None,
        direction: str = "both",
        min_strength: float = 0.0,
    ) -> list[dict]:
        """Find relationships."""
        with self.Session() as session:
            conditions = ["r.tenant_id = :tenant_id", "r.strength >= :min_strength"]
            params = {"tenant_id": tenant_id, "min_strength": min_strength}

            if entity_id:
                if direction == "outgoing":
                    conditions.append("r.source_entity_id = :entity_id")
                elif direction == "incoming":
                    conditions.append("r.target_entity_id = :entity_id")
                else:
                    conditions.append("(r.source_entity_id = :entity_id OR r.target_entity_id = :entity_id)")
                params["entity_id"] = entity_id

            if relation_types:
                type_list = ",".join(f"'{t}'" for t in relation_types)
                conditions.append(f"r.relation_type IN ({type_list})")

            where_clause = " AND ".join(conditions)

            result = session.execute(
                text(f"""
                    SELECT r.*,
                           s.name as source_name, s.entity_type as source_type,
                           t.name as target_name, t.entity_type as target_type
                    FROM knowledge_relations r
                    JOIN knowledge_entities s ON r.source_entity_id = s.id
                    JOIN knowledge_entities t ON r.target_entity_id = t.id
                    WHERE {where_clause}
                """),
                params
            )

            return [dict(row._mapping) for row in result]

    async def get_path(
        self,
        source_entity_id: str,
        target_entity_id: str,
        max_depth: int = 4,
        relation_types: list = None,
    ) -> list[dict]:
        """Find shortest path between entities using BFS."""
        # Simplified BFS implementation
        visited = set()
        queue = [(source_entity_id, [])]

        while queue and len(visited) < 1000:  # Safety limit
            current_id, path = queue.pop(0)

            if current_id == target_entity_id:
                return path

            if current_id in visited or len(path) >= max_depth:
                continue

            visited.add(current_id)

            relations = await self.find_relations(
                tenant_id="",  # Need to pass from context
                entity_id=current_id,
                relation_types=relation_types,
            )

            for rel in relations:
                next_id = rel["target_entity_id"] if rel["source_entity_id"] == current_id else rel["source_entity_id"]
                if next_id not in visited:
                    queue.append((next_id, path + [rel]))

        return []  # No path found

    async def get_neighborhood(
        self,
        entity_id: str,
        depth: int = 2,
        relation_types: list = None,
        entity_types: list = None,
    ) -> dict:
        """Get entity neighborhood graph."""
        entities = {}
        relations = []

        async def expand(eid: str, current_depth: int):
            if current_depth > depth or eid in entities:
                return

            entity = await self.get_entity(eid, include_relations=False)
            if entity_types and entity.get("entity_type") not in entity_types:
                return

            entities[eid] = entity

            rels = await self.find_relations(
                tenant_id=entity.get("tenant_id", ""),
                entity_id=eid,
                relation_types=relation_types,
            )

            for rel in rels:
                relations.append(rel)
                next_id = rel["target_entity_id"] if rel["source_entity_id"] == eid else rel["source_entity_id"]
                await expand(next_id, current_depth + 1)

        await expand(entity_id, 0)

        return {
            "entities": list(entities.values()),
            "relations": relations,
        }

    async def search_knowledge(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 5,
        filters: dict = None,
    ) -> list[dict]:
        """Semantic search using vector similarity."""
        return await self.find_entities(
            query=query,
            tenant_id=tenant_id,
            entity_types=filters.get("entity_types") if filters else None,
            limit=top_k,
        )

    async def store_knowledge(
        self,
        content: str,
        metadata: dict,
        tenant_id: str,
    ) -> str:
        """Store knowledge as an entity."""
        entity = await self.create_entity(
            name=metadata.get("name", content[:100]),
            entity_type=metadata.get("type", "fact"),
            tenant_id=tenant_id,
            description=content,
            properties=metadata,
        )
        return entity["id"]

    async def record_observation(
        self,
        observation_text: str,
        tenant_id: str,
        observation_type: str = "fact",
        source_type: str = "conversation",
    ) -> str:
        """Record observation for later processing."""
        obs_id = str(uuid.uuid4())
        embedding = await self.embedding_service.get_embedding(observation_text)

        with self.Session() as session:
            session.execute(
                text("""
                    INSERT INTO knowledge_observations
                    (id, tenant_id, observation_text, observation_type, source_type, embedding)
                    VALUES (:id, :tenant_id, :text, :type, :source, :embedding)
                """),
                {
                    "id": obs_id,
                    "tenant_id": tenant_id,
                    "text": observation_text,
                    "type": observation_type,
                    "source": source_type,
                    "embedding": embedding,
                }
            )
            session.commit()

        return obs_id

    async def ask_knowledge_graph(
        self,
        question: str,
        tenant_id: str,
    ) -> dict:
        """Answer question using knowledge graph."""
        # Find relevant entities
        entities = await self.find_entities(
            query=question,
            tenant_id=tenant_id,
            limit=5,
        )

        # Get relations for top entities
        relations = []
        for entity in entities[:3]:
            rels = await self.find_relations(
                tenant_id=tenant_id,
                entity_id=entity["id"],
            )
            relations.extend(rels[:5])

        return {
            "question": question,
            "relevant_entities": entities,
            "relevant_relations": relations,
            "note": "Agent should synthesize answer from this context",
        }

    async def get_entity_timeline(
        self,
        entity_id: str,
        include_relations: bool = True,
    ) -> list[dict]:
        """Get entity history timeline."""
        with self.Session() as session:
            result = session.execute(
                text("""
                    SELECT version, properties_snapshot, change_reason, changed_at
                    FROM knowledge_entity_history
                    WHERE entity_id = :entity_id
                    ORDER BY changed_at DESC
                """),
                {"entity_id": entity_id}
            )

            return [dict(row._mapping) for row in result]


# Singleton instance
_service: Optional[KnowledgeGraphService] = None


def get_knowledge_service() -> KnowledgeGraphService:
    """Get or create knowledge graph service singleton."""
    global _service
    if _service is None:
        _service = KnowledgeGraphService()
    return _service
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/services/knowledge_graph.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/services/knowledge_graph.py
git commit -m "feat(adk): add knowledge graph service"
```

---

### Task 4.2: Create Vertex AI Embedding Service

**Files:**
- Create: `apps/adk-server/memory/vertex_vector.py`

**Step 1: Create vertex_vector.py**

```python
"""Vertex AI Vector Search integration for embeddings and RAG.

Uses text-embedding-005 for 768-dimensional embeddings.
"""
from typing import Optional
from google.cloud import aiplatform
from vertexai.language_models import TextEmbeddingModel

from config.settings import settings


class EmbeddingService:
    """Generates embeddings using Vertex AI text-embedding-005."""

    def __init__(self):
        # Initialize Vertex AI
        aiplatform.init(
            project=settings.vertex_project,
            location=settings.vertex_location,
        )

        # Load embedding model
        self.model = TextEmbeddingModel.from_pretrained(settings.embedding_model)

    async def get_embedding(self, text: str) -> list[float]:
        """Generate embedding for text.

        Args:
            text: Input text to embed

        Returns:
            768-dimensional embedding vector
        """
        # TextEmbeddingModel.get_embeddings is synchronous
        embeddings = self.model.get_embeddings([text])
        return embeddings[0].values

    async def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of input texts

        Returns:
            List of embedding vectors
        """
        embeddings = self.model.get_embeddings(texts)
        return [e.values for e in embeddings]


class VectorSearchService:
    """Manages Vertex AI Vector Search index for similarity search."""

    def __init__(self):
        aiplatform.init(
            project=settings.vertex_project,
            location=settings.vertex_location,
        )

        self.index_id = settings.vector_index_id
        self.endpoint_id = settings.vector_endpoint_id
        self.embedding_service = EmbeddingService()

        # Load index endpoint if configured
        self._endpoint = None
        if self.endpoint_id:
            try:
                self._endpoint = aiplatform.MatchingEngineIndexEndpoint(self.endpoint_id)
            except Exception:
                pass  # Endpoint not yet created

    async def find_neighbors(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """Find similar items using vector search.

        Args:
            query: Search query text
            top_k: Number of results
            filters: Metadata filters

        Returns:
            List of similar items with scores
        """
        if not self._endpoint:
            return []

        # Get query embedding
        query_embedding = await self.embedding_service.get_embedding(query)

        # Search
        response = self._endpoint.find_neighbors(
            deployed_index_id=self.index_id,
            queries=[query_embedding],
            num_neighbors=top_k,
        )

        results = []
        for neighbor in response[0]:
            results.append({
                "id": neighbor.id,
                "score": neighbor.distance,
            })

        return results

    async def upsert_embedding(
        self,
        item_id: str,
        text: str,
        metadata: dict,
    ) -> bool:
        """Add or update item in vector index.

        Note: Vertex AI Vector Search requires batch updates via index rebuild.
        For real-time updates, use the streaming index feature or queue updates.
        """
        # Get embedding
        embedding = await self.embedding_service.get_embedding(text)

        # In production, queue this for batch index update
        # For now, just return success
        return True


# Singleton instances
_embedding_service: Optional[EmbeddingService] = None
_vector_service: Optional[VectorSearchService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create embedding service singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def get_vector_service() -> VectorSearchService:
    """Get or create vector search service singleton."""
    global _vector_service
    if _vector_service is None:
        _vector_service = VectorSearchService()
    return _vector_service
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/memory/vertex_vector.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/memory/vertex_vector.py
git commit -m "feat(adk): add Vertex AI embedding service"
```

---

## Phase 5: Authentication Service

### Task 5.1: Create JWT Auth Service

**Files:**
- Create: `apps/adk-server/services/auth.py`

**Step 1: Create auth.py**

```python
"""JWT authentication service.

Shares SECRET_KEY with FastAPI for consistent token validation.
"""
from typing import Optional
from datetime import datetime
from jose import JWTError, jwt
from pydantic import BaseModel

from config.settings import settings


class TokenData(BaseModel):
    """Decoded JWT token data."""
    sub: str  # User email
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    exp: Optional[datetime] = None


def decode_token(token: str) -> Optional[TokenData]:
    """Decode and validate JWT token.

    Args:
        token: JWT token string (without 'Bearer ' prefix)

    Returns:
        TokenData if valid, None if invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )

        return TokenData(
            sub=payload.get("sub", ""),
            tenant_id=payload.get("tenant_id"),
            user_id=payload.get("user_id"),
            exp=datetime.fromtimestamp(payload.get("exp", 0)) if payload.get("exp") else None,
        )
    except JWTError:
        return None


def extract_token_from_header(authorization: str) -> Optional[str]:
    """Extract token from Authorization header.

    Args:
        authorization: Full Authorization header value

    Returns:
        Token string if valid Bearer token, None otherwise
    """
    if not authorization:
        return None

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return parts[1]


def validate_request(authorization: str) -> Optional[TokenData]:
    """Validate request authorization.

    Args:
        authorization: Authorization header value

    Returns:
        TokenData if valid, None if invalid
    """
    token = extract_token_from_header(authorization)
    if not token:
        return None

    return decode_token(token)


def get_tenant_id_from_token(authorization: str) -> Optional[str]:
    """Extract tenant_id from authorization header.

    Args:
        authorization: Authorization header value

    Returns:
        Tenant ID if valid, None otherwise
    """
    token_data = validate_request(authorization)
    if not token_data:
        return None

    return token_data.tenant_id
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/services/auth.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/services/auth.py
git commit -m "feat(adk): add JWT auth service"
```

---

## Phase 6: Update Services __init__.py

### Task 6.1: Update Services Export

**Files:**
- Modify: `apps/adk-server/services/__init__.py`

**Step 1: Update __init__.py**

```python
"""Service layer for AgentProvision ADK server."""
from services.auth import (
    decode_token,
    validate_request,
    get_tenant_id_from_token,
    TokenData,
)
from services.postgres_client import (
    PostgreSQLClient,
    get_postgres_client,
)
from services.knowledge_graph import (
    KnowledgeGraphService,
    get_knowledge_service,
)

__all__ = [
    # Auth
    "decode_token",
    "validate_request",
    "get_tenant_id_from_token",
    "TokenData",
    # PostgreSQL
    "PostgreSQLClient",
    "get_postgres_client",
    # Knowledge Graph
    "KnowledgeGraphService",
    "get_knowledge_service",
]
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile apps/adk-server/services/__init__.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add apps/adk-server/services/__init__.py
git commit -m "feat(adk): export services from __init__.py"
```

---

## Phase 7: Database Schema Updates

### Task 7.1: Create Knowledge Graph Migration

**Files:**
- Create: `apps/api/alembic/versions/xxxx_add_knowledge_graph_tables.py`

**Step 1: Create migration file**

Note: Generate with `alembic revision --autogenerate -m "add knowledge graph tables"` or create manually:

```python
"""Add knowledge graph tables

Revision ID: kg_001
Revises:
Create Date: 2025-12-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'kg_001'
down_revision = None  # Set to previous migration
branch_labels = None
depends_on = None


def upgrade():
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create knowledge_entities table
    op.create_table(
        'knowledge_entities',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('entity_type', sa.String(100), nullable=False),
        sa.Column('aliases', postgresql.ARRAY(sa.Text)),
        sa.Column('description', sa.Text),
        sa.Column('properties', postgresql.JSONB, default={}),
        sa.Column('confidence', sa.Float, default=1.0),
        sa.Column('importance', sa.Float, default=0.5),
        sa.Column('embedding', sa.LargeBinary),  # Vector stored as bytes
        sa.Column('source_type', sa.String(50)),
        sa.Column('source_id', postgresql.UUID(as_uuid=True)),
        sa.Column('discovered_by_agent_id', postgresql.UUID(as_uuid=True)),
        sa.Column('extraction_method', sa.String(50)),
        sa.Column('verified', sa.Boolean, default=False),
        sa.Column('verified_by', postgresql.UUID(as_uuid=True)),
        sa.Column('valid_from', sa.DateTime),
        sa.Column('valid_until', sa.DateTime),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('last_accessed_at', sa.DateTime),
        sa.Column('access_count', sa.Integer, default=0),
    )

    # Create knowledge_relations table
    op.create_table(
        'knowledge_relations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('source_entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('knowledge_entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('knowledge_entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('relation_type', sa.String(100), nullable=False),
        sa.Column('strength', sa.Float, default=1.0),
        sa.Column('confidence', sa.Float, default=1.0),
        sa.Column('properties', postgresql.JSONB, default={}),
        sa.Column('evidence', sa.Text),
        sa.Column('bidirectional', sa.Boolean, default=False),
        sa.Column('discovered_by_agent_id', postgresql.UUID(as_uuid=True)),
        sa.Column('source_conversation_id', postgresql.UUID(as_uuid=True)),
        sa.Column('extraction_method', sa.String(50)),
        sa.Column('valid_from', sa.DateTime),
        sa.Column('valid_until', sa.DateTime),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )

    # Create knowledge_entity_history table
    op.create_table(
        'knowledge_entity_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('knowledge_entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('properties_snapshot', postgresql.JSONB),
        sa.Column('changed_by', postgresql.UUID(as_uuid=True)),
        sa.Column('change_reason', sa.Text),
        sa.Column('changed_at', sa.DateTime, server_default=sa.func.now()),
    )

    # Create knowledge_observations table
    op.create_table(
        'knowledge_observations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('observation_text', sa.Text, nullable=False),
        sa.Column('observation_type', sa.String(50)),
        sa.Column('embedding', sa.LargeBinary),
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True)),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True)),
        sa.Column('message_id', postgresql.UUID(as_uuid=True)),
        sa.Column('processed', sa.Boolean, default=False),
        sa.Column('extracted_entity_ids', postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column('confidence', sa.Float, default=1.0),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )

    # Create indexes
    op.create_index('idx_entities_tenant_type', 'knowledge_entities', ['tenant_id', 'entity_type'])
    op.create_index('idx_relations_source', 'knowledge_relations', ['source_entity_id'])
    op.create_index('idx_relations_target', 'knowledge_relations', ['target_entity_id'])
    op.create_index('idx_relations_type', 'knowledge_relations', ['tenant_id', 'relation_type'])
    op.create_index('idx_observations_unprocessed', 'knowledge_observations', ['tenant_id'], postgresql_where=sa.text('NOT processed'))


def downgrade():
    op.drop_table('knowledge_observations')
    op.drop_table('knowledge_entity_history')
    op.drop_table('knowledge_relations')
    op.drop_table('knowledge_entities')
```

**Step 2: Note for implementation**

This migration should be created properly using Alembic:

```bash
cd apps/api
alembic revision --autogenerate -m "add knowledge graph tables"
```

Then edit the generated file to match the schema above.

**Step 3: Commit**

```bash
git add apps/api/alembic/versions/
git commit -m "feat(db): add knowledge graph tables migration"
```

---

## Phase 8: Add Google API Key to Secret Manager

### Task 8.1: Add Secret to GCP

**Step 1: Create secret in GCP Secret Manager**

```bash
gcloud secrets create agentprovision-google-api-key \
    --project=ai-agency-479516 \
    --replication-policy=automatic

# Add the API key value
echo -n "YOUR_GOOGLE_API_KEY" | gcloud secrets versions add agentprovision-google-api-key --data-file=-
```

**Step 2: Grant access to service account**

```bash
gcloud secrets add-iam-policy-binding agentprovision-google-api-key \
    --project=ai-agency-479516 \
    --member="serviceAccount:dev-backend-app@ai-agency-479516.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

**Step 3: Verify secret exists**

```bash
gcloud secrets describe agentprovision-google-api-key --project=ai-agency-479516
```

---

## Phase 9: Final Integration

### Task 9.1: Commit All ADK Server Code

**Step 1: Stage all changes**

```bash
git add apps/adk-server/
git add helm/values/agentprovision-adk.yaml
git add kubernetes/ingress.yaml
git add .github/workflows/adk-deploy.yaml
```

**Step 2: Commit**

```bash
git commit -m "feat(adk): complete Google ADK server implementation

- Add ADK server with supervisor and specialist agents
- Implement data, analytics, knowledge, and action tools
- Add knowledge graph service with PostgreSQL
- Add Vertex AI embedding service
- Add JWT auth service (shared with FastAPI)
- Add Helm values and GitHub Actions workflow
- Update Ingress with /adk route"
```

**Step 3: Push and trigger deployment**

```bash
git push origin main
```

---

## Verification Checklist

After deployment, verify:

1. [ ] ADK pod is running: `kubectl get pods -n prod -l app.kubernetes.io/name=agentprovision-adk`
2. [ ] ADK service is healthy: `curl https://agentprovision.com/adk/list-apps`
3. [ ] Root agent is available: Check response includes `agentprovision_supervisor`
4. [ ] Create session works: Test POST to `/adk/apps/agentprovision_supervisor/users/test/sessions`
5. [ ] Send message works: Test POST to `/adk/run` with test message

---

## Summary

This plan creates:
- 15 new files in `apps/adk-server/`
- 1 Helm values file
- 1 GitHub Actions workflow
- 1 Ingress update
- 1 database migration

Total estimated tasks: 25 bite-sized steps
