# AgentProvision + MCP PostgreSQL Integration Guide

**Purpose**: This document outlines the AgentProvision-side integration with the MCP Server's PostgreSQL connector.

**Context**: The PostgreSQL connector is being built in `../dentalerp/mcp-server`. This document focuses on what needs to change in AgentProvision to use it.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                  AgentProvision                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Frontend (React)                                   │     │
│  │  • DatasetsPage                                    │     │
│  │  • NotebooksPage                                   │     │
│  │  • DataPipelinesPage                               │     │
│  │  • AgentsPage                                      │     │
│  └──────────────────┬─────────────────────────────────┘     │
│                     │ HTTP                                   │
│  ┌──────────────────▼─────────────────────────────────┐     │
│  │ Backend (FastAPI)                                  │     │
│  │  ┌──────────────────────────────────────────┐     │     │
│  │  │ Services Layer                           │     │     │
│  │  │  • datasets.py                           │     │     │
│  │  │  • notebook.py                           │     │     │
│  │  │  • data_pipeline.py                      │     │     │
│  │  │  • agents.py                             │     │     │
│  │  │  • vector_stores.py                      │     │     │
│  │  │  • mcp_client.py (NEW) ←──────────────┐  │     │     │
│  │  └──────────────────────────────────────────┘  │  │     │
│  │                                                  │  │     │
│  │  ┌──────────────────────────────────────────┐  │  │     │
│  │  │ PostgreSQL                               │  │  │     │
│  │  │  • Stores metadata                       │  │  │     │
│  │  │  • Tracks PostgreSQL resources           │  │  │     │
│  │  └──────────────────────────────────────────┘  │  │     │
│  └──────────────────────────────────────────────────┘  │     │
└────────────────────────────────────────────────────────┼─────┘
                                                         │
                                                         │ HTTPS
                                                         │
                    ┌────────────────────────────────────▼─────┐
                    │         MCP Server (Port 8085)           │
                    │  ┌────────────────────────────────────┐  │
                    │  │ AgentProvision Module               │  │
                    │  │  /agentprovision/v1/*              │  │
                    │  │  ├─ /postgres/datasets            │  │
                    │  │  ├─ /postgres/notebooks           │  │
                    │  │  ├─ /postgres/jobs                │  │
                    │  │  ├─ /postgres/serving-endpoints   │  │
                    │  │  └─ /postgres/vector-indexes      │  │
                    │  └────────────────────────────────────┘  │
                    │  ┌────────────────────────────────────┐  │
                    │  │ PostgreSQL Connector                │  │
                    │  │  (Being built in other session)     │  │
                    │  └────────────────────────────────────┘  │
                    └──────────────────┬───────────────────────┘
                                       │
                                       │ PostgreSQL REST API
                                       │
                            ┌──────────▼──────────┐
                            │   PostgreSQL        │
                            │  Unity Catalog      │
                            │  • Notebooks        │
                            │  • Delta Tables     │
                            │  • Jobs             │
                            │  • Model Serving    │
                            │  • Vector Search    │
                            └─────────────────────┘
```

---

## What's Been Created (AgentProvision Side)

### ✅ Completed

1. **MCP Client Service** (`apps/api/app/services/mcp_client.py`)
   - HTTP client for MCP server
   - Methods for all PostgreSQL operations:
     - Catalogs: `create_tenant_catalog()`, `get_catalog_status()`
     - Datasets: `create_dataset()`, `upload_dataset_file()`, `query_dataset()`
     - Notebooks: `create_notebook()`, `execute_notebook()`, `get_notebook_run_status()`
     - Jobs: `create_job()`, `run_job()`, `get_job_run_status()`
     - Model Serving: `deploy_model()`, `invoke_model()`
     - Vector Search: `create_vector_index()`, `search_vectors()`

2. **Configuration Updates**
   - Added `MCP_SERVER_URL`, `MCP_API_KEY`, `MCP_ENABLED` to settings
   - Updated `.env` file with MCP configuration
   - Feature flag for gradual rollout

3. **Logger Utility** (`apps/api/app/utils/logger.py`)
   - Consistent logging across services

---

## What Needs to Be Updated (Next Steps)

### 1. Dataset Service Integration

**File**: `apps/api/app/services/datasets.py`

**Current State**:
- Stores Parquet files locally
- Uses pandas for processing
- No integration with PostgreSQL

**Required Changes**:

```python
# Hybrid approach - keep local storage as fallback

from app.services.mcp_client import get_mcp_client
from app.core.config import settings

async def ingest_tabular_to_postgres(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    file: UploadFile,
    name: str,
    description: str | None = None,
) -> Dataset:
    """
    Ingest file to PostgreSQL Delta Lake via MCP

    Flow:
    1. Read file locally (pandas)
    2. Upload to PostgreSQL via MCP
    3. Store metadata in PostgreSQL
    4. Keep local Parquet as backup
    """
    # Read file
    df = _load_dataframe(file)

    # Upload to PostgreSQL if enabled
    postgres_table = None
    if settings.MCP_ENABLED:
        mcp = get_mcp_client()
        try:
            # Convert DataFrame to bytes
            parquet_bytes = df.to_parquet(index=False)

            # Upload via MCP
            result = await mcp.upload_dataset_file(
                tenant_id=str(tenant_id),
                dataset_name=name,
                file_content=parquet_bytes,
                file_format="parquet"
            )
            postgres_table = result.get("table_path")
        except MCPClientError as e:
            logger.error(f"PostgreSQL upload failed: {e}, falling back to local storage")

    # Always persist locally as backup
    dataset = _persist_dataframe(
        db,
        tenant_id=tenant_id,
        df=df,
        name=name,
        description=description,
        source_type="excel_upload",
        file_name=file.filename,
    )

    # Store PostgreSQL reference if available
    if postgres_table:
        dataset.metadata_ = dataset.metadata_ or {}
        dataset.metadata_["postgres_table"] = postgres_table
        db.commit()

    return dataset
```

**Database Schema Update**:
Add `metadata_` JSON column to `datasets` table to store PostgreSQL references.

### 2. Notebook Service Integration

**File**: `apps/api/app/services/notebook.py`

**Current State**:
- Only stores metadata
- No actual execution

**Required Changes**:

```python
from app.services.mcp_client import get_mcp_client

async def create_postgres_notebook(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    item_in: NotebookCreate
) -> Notebook:
    """
    Create notebook in PostgreSQL and store metadata locally
    """
    # Create in PostgreSQL
    db_item = Notebook(**item_in.dict(), tenant_id=tenant_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)

    # Create in PostgreSQL if enabled
    if settings.MCP_ENABLED:
        mcp = get_mcp_client()
        try:
            result = await mcp.create_notebook(
                tenant_id=str(tenant_id),
                notebook_name=item_in.name,
                language="python",
                content=item_in.content.get("source", "") if item_in.content else ""
            )

            # Store PostgreSQL workspace path
            db_item.metadata_ = {
                "postgres_path": result.get("path"),
                "postgres_id": result.get("object_id")
            }
            db.commit()
        except MCPClientError as e:
            logger.error(f"PostgreSQL notebook creation failed: {e}")

    return db_item

async def execute_notebook(
    db: Session,
    *,
    notebook_id: uuid.UUID,
    tenant_id: uuid.UUID,
    parameters: dict | None = None
) -> dict:
    """Execute notebook in PostgreSQL"""
    notebook = db.query(Notebook).filter(Notebook.id == notebook_id).first()
    if not notebook or notebook.tenant_id != tenant_id:
        raise ValueError("Notebook not found")

    if not settings.MCP_ENABLED:
        raise ValueError("PostgreSQL integration not enabled")

    mcp = get_mcp_client()
    postgres_path = notebook.metadata_.get("postgres_path")

    result = await mcp.execute_notebook(
        tenant_id=str(tenant_id),
        notebook_path=postgres_path,
        parameters=parameters or {}
    )

    return {
        "run_id": result.get("run_id"),
        "status": "PENDING",
        "message": "Notebook execution started"
    }
```

### 3. Data Pipeline Service Integration

**File**: `apps/api/app/services/data_pipeline.py`

**Current State**:
- Only CRUD operations
- No execution

**Required Changes**:

```python
async def create_postgres_job(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    pipeline_in: DataPipelineCreate
) -> DataPipeline:
    """
    Create data pipeline as PostgreSQL Job
    """
    # Create in PostgreSQL
    db_item = DataPipeline(**pipeline_in.dict(), tenant_id=tenant_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)

    # Create PostgreSQL Job if enabled
    if settings.MCP_ENABLED:
        mcp = get_mcp_client()

        # Convert pipeline config to PostgreSQL job tasks
        tasks = _convert_to_postgres_tasks(pipeline_in.config)

        try:
            result = await mcp.create_job(
                tenant_id=str(tenant_id),
                job_name=pipeline_in.name,
                tasks=tasks,
                schedule=pipeline_in.schedule
            )

            db_item.metadata_ = {
                "postgres_job_id": result.get("job_id"),
                "job_url": result.get("job_url")
            }
            db.commit()
        except MCPClientError as e:
            logger.error(f"PostgreSQL job creation failed: {e}")

    return db_item

async def run_pipeline(
    db: Session,
    *,
    pipeline_id: uuid.UUID,
    tenant_id: uuid.UUID
) -> dict:
    """Trigger pipeline execution"""
    pipeline = db.query(DataPipeline).filter(DataPipeline.id == pipeline_id).first()
    if not pipeline or pipeline.tenant_id != tenant_id:
        raise ValueError("Pipeline not found")

    if not settings.MCP_ENABLED:
        raise ValueError("PostgreSQL integration not enabled")

    mcp = get_mcp_client()
    job_id = pipeline.metadata_.get("postgres_job_id")

    result = await mcp.run_job(
        tenant_id=str(tenant_id),
        job_id=job_id
    )

    return {
        "run_id": result.get("run_id"),
        "status": "RUNNING",
        "message": "Pipeline execution started"
    }
```

### 4. Agent Service Updates

**File**: `apps/api/app/services/agents.py`

**Required Changes**:

```python
async def deploy_agent_to_postgres(
    db: Session,
    *,
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID
) -> dict:
    """
    Deploy agent as PostgreSQL model serving endpoint
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent or agent.tenant_id != tenant_id:
        raise ValueError("Agent not found")

    if not settings.MCP_ENABLED:
        raise ValueError("PostgreSQL integration not enabled")

    mcp = get_mcp_client()

    # Deploy to PostgreSQL Model Serving
    result = await mcp.deploy_model(
        tenant_id=str(tenant_id),
        model_name=agent.name.lower().replace(" ", "_"),
        model_version="1",  # From MLflow registry
        endpoint_name=f"agent_{agent.id}",
        workload_size="Small"
    )

    # Update agent metadata
    agent.metadata_ = agent.metadata_ or {}
    agent.metadata_["serving_endpoint"] = result.get("endpoint_name")
    agent.metadata_["endpoint_url"] = result.get("endpoint_url")
    db.commit()

    return result
```

### 5. Vector Store Service Updates

**File**: `apps/api/app/services/vector_stores.py`

**Required Changes**:

```python
async def create_postgres_vector_index(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    vector_store_in: VectorStoreCreate
) -> VectorStore:
    """
    Create vector search index in PostgreSQL
    """
    # Create in PostgreSQL
    db_item = VectorStore(**vector_store_in.dict(), tenant_id=tenant_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)

    # Create in PostgreSQL if enabled
    if settings.MCP_ENABLED:
        mcp = get_mcp_client()

        try:
            result = await mcp.create_vector_index(
                tenant_id=str(tenant_id),
                index_name=vector_store_in.name,
                source_table=vector_store_in.config.get("source_table"),
                embedding_dimension=vector_store_in.config.get("dimension", 1536),
                embedding_column="embedding"
            )

            db_item.metadata_ = {
                "postgres_index_name": result.get("index_name"),
                "index_url": result.get("index_url")
            }
            db.commit()
        except MCPClientError as e:
            logger.error(f"PostgreSQL vector index creation failed: {e}")

    return db_item
```

---

## Database Migration Required

### Add `metadata_` Column to All Tables

```sql
-- Migration script
ALTER TABLE datasets ADD COLUMN metadata_ JSONB;
ALTER TABLE notebooks ADD COLUMN metadata_ JSONB;
ALTER TABLE data_pipelines ADD COLUMN metadata_ JSONB;
ALTER TABLE agents ADD COLUMN metadata_ JSONB;
ALTER TABLE vector_stores ADD COLUMN metadata_ JSONB;

-- Create indexes for better query performance
CREATE INDEX idx_datasets_metadata ON datasets USING GIN (metadata_);
CREATE INDEX idx_notebooks_metadata ON notebooks USING GIN (metadata_);
CREATE INDEX idx_data_pipelines_metadata ON data_pipelines USING GIN (metadata_);
CREATE INDEX idx_agents_metadata ON agents USING GIN (metadata_);
CREATE INDEX idx_vector_stores_metadata ON vector_stores USING GIN (metadata_);
```

---

## Frontend Updates Needed

### 1. Datasets Page

**File**: `apps/web/src/pages/DatasetsPage.js`

**Required Changes**:
- Add "PostgreSQL Status" column showing sync status
- Add "Query in PostgreSQL" button for datasets with PostgreSQL tables
- Show PostgreSQL table path in metadata
- Add execution status for running queries

### 2. Notebooks Page

**File**: `apps/web/src/pages/NotebooksPage.js`

**Required Changes**:
- Add "Execute" button to run notebooks in PostgreSQL
- Show execution status (Running, Completed, Failed)
- Add link to PostgreSQL workspace
- Display execution results

### 3. Data Pipelines Page

**File**: `apps/web/src/pages/DataPipelinesPage.js`

**Required Changes**:
- Add "Run Pipeline" button
- Show job run history from PostgreSQL
- Display run status (Pending, Running, Succeeded, Failed)
- Add link to PostgreSQL job UI

### 4. Agents Page

**File**: `apps/web/src/pages/AgentsPage.js`

**Required Changes**:
- Add "Deploy to PostgreSQL" button
- Show serving endpoint status
- Add "Test Endpoint" functionality
- Display endpoint URL for API calls

---

## API Endpoints to Add

### PostgreSQL Status Endpoint

```python
# apps/api/app/api/v1/postgres.py

from fastapi import APIRouter, Depends
from app.services.mcp_client import get_mcp_client
from app.api.deps import get_current_user

router = APIRouter()

@router.get("/postgres/status")
async def get_postgres_status(
    current_user: User = Depends(get_current_user)
):
    """Get PostgreSQL integration status for current tenant"""
    mcp = get_mcp_client()

    try:
        catalog_status = await mcp.get_catalog_status(
            tenant_id=str(current_user.tenant_id)
        )
        health = await mcp.health_check()

        return {
            "enabled": settings.MCP_ENABLED,
            "mcp_healthy": health.get("status") == "healthy",
            "catalog_exists": catalog_status.get("exists"),
            "catalog_name": catalog_status.get("catalog_name")
        }
    except Exception as e:
        return {
            "enabled": settings.MCP_ENABLED,
            "mcp_healthy": False,
            "error": str(e)
        }

@router.post("/postgres/initialize")
async def initialize_postgres_for_tenant(
    current_user: User = Depends(get_current_user)
):
    """Initialize PostgreSQL resources for tenant"""
    mcp = get_mcp_client()

    catalog_name = f"agentprovision_{current_user.tenant_id}"
    result = await mcp.create_tenant_catalog(
        tenant_id=str(current_user.tenant_id),
        catalog_name=catalog_name
    )

    return {
        "message": "PostgreSQL catalog created successfully",
        "catalog_name": result.get("catalog_name")
    }
```

---

## Testing Strategy

### Unit Tests

```python
# tests/test_mcp_client.py

import pytest
from app.services.mcp_client import MCPClient, MCPClientError

@pytest.mark.asyncio
async def test_mcp_client_health_check():
    """Test MCP server health check"""
    client = MCPClient()
    result = await client.health_check()
    assert result["status"] == "healthy"

@pytest.mark.asyncio
async def test_create_dataset():
    """Test dataset creation via MCP"""
    client = MCPClient()
    result = await client.create_dataset(
        tenant_id="test-tenant",
        dataset_name="test_dataset",
        schema=[{"name": "id", "type": "integer"}],
        data=[{"id": 1}, {"id": 2}]
    )
    assert "table_path" in result
```

### Integration Tests

```python
# tests/test_postgres_integration.py

@pytest.mark.integration
async def test_end_to_end_dataset_flow():
    """Test full dataset ingestion to PostgreSQL"""
    # 1. Upload file to AgentProvision
    # 2. Verify it's pushed to PostgreSQL via MCP
    # 3. Query the data
    # 4. Verify results match
    pass
```

---

## Deployment Checklist

- [ ] MCP server running on port 8085
- [ ] PostgreSQL workspace configured
- [ ] MCP_SERVER_URL and MCP_API_KEY set in `.env`
- [ ] Database migration executed (add `metadata_` columns)
- [ ] AgentProvision API restarted
- [ ] Frontend updated with new features
- [ ] Integration tests passing
- [ ] Health check endpoint returns healthy status

---

## Rollout Plan

### Phase 1: Datasets (Week 1)
- Deploy MCP client
- Update dataset service
- Add PostgreSQL status UI
- Test with sample datasets

### Phase 2: Notebooks (Week 2)
- Update notebook service
- Add execution endpoints
- Build notebook execution UI
- Test end-to-end flows

### Phase 3: Pipelines & Agents (Week 3-4)
- Update data pipeline service
- Deploy agent serving
- Add vector search
- Full integration testing

### Phase 4: Production (Week 5)
- Performance optimization
- Monitoring setup
- User documentation
- Production deployment

---

## Monitoring & Observability

### Metrics to Track

```python
# Add to each service

from prometheus_client import Counter, Histogram

mcp_requests_total = Counter(
    'mcp_requests_total',
    'Total MCP API requests',
    ['operation', 'status']
)

mcp_request_duration = Histogram(
    'mcp_request_duration_seconds',
    'MCP request duration',
    ['operation']
)
```

### Logging

All MCP interactions should be logged:
- Request details (operation, tenant)
- Response time
- Errors with full context
- PostgreSQL resource IDs

---

## Next Steps

1. **Immediate**: Wait for PostgreSQL connector completion in MCP server
2. **Test MCP Client**: Once MCP endpoints are ready, test `mcp_client.py`
3. **Update Services**: Implement hybrid approach in dataset, notebook, pipeline services
4. **Database Migration**: Add `metadata_` columns
5. **Frontend Updates**: Add PostgreSQL status indicators
6. **Integration Testing**: End-to-end workflow validation

---

## Questions for MCP Server Team

1. What's the expected response format for each endpoint?
2. How are errors returned (status codes, error messages)?
3. Is authentication handled via Bearer token?
4. What's the rate limit for PostgreSQL operations?
5. How should we handle long-running operations (notebooks, jobs)?

---

**Document Owner**: AgentProvision Platform Team
**Last Updated**: October 30, 2025
**Status**: Integration in Progress
