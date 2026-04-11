# Automations & Temporal Orchestration - Implementation Plan

## Current State Analysis

### ✅ What's Already Implemented

**Backend (API):**
- `DatasetSyncWorkflow` - Syncs datasets to PostgreSQL (Bronze → Silver)
- `KnowledgeExtractionWorkflow` - Extracts knowledge from chat sessions
- `AgentKitExecutionWorkflow` - Executes agent kit workflows
- Temporal Worker (`postgres_worker.py`) - Running and connected
- Connector CRUD API (`/api/v1/connectors/`)
- Data Pipeline CRUD API and execute endpoint

**Frontend:**
- `DataPipelinesPage.js` - Full page with create/delete/execute automations
- `ConnectorsPage.js` - Basic stub only (needs implementation)

### ❌ What's Missing

1. **Connector Types & Integration**
   - No actual connector type implementations (Snowflake, PostgreSQL, S3, etc.)
   - No OAuth/credential management
   - No test connection functionality
   - Frontend ConnectorsPage is just a stub

2. **Data Source Sync Workflows**
   - DatasetSync only works for PostgreSQL
   - Need general sync workflow for any connector type
   - No incremental sync (only full refresh)
   - No sync scheduling

3. **Automation Execution**
   - Pipeline execute() doesn't trigger Temporal workflows
   - No actual scheduling (cron/interval)
   - No execution history tracking
   - No run status monitoring

4. **Frontend**
   - ConnectorsPage is empty
   - No connector configuration wizard
   - No sync status visibility
   - No execution logs viewer

---

## Implementation Plan

### Phase 1: Connector Types & Configuration (Priority: HIGH)

#### 1.1 Update Connector Model with Type
```python
# app/models/connector.py - Add connector_type field
connector_type = Column(String, index=True)  # snowflake, postgres, mysql, s3, gcs, api
status = Column(String, default="pending")  # pending, active, error
last_test_at = Column(DateTime, nullable=True)
```

#### 1.2 Create Connector Type Schemas
- Snowflake: account, user, password, warehouse, database, schema
- PostgreSQL: host, port, database, user, password, ssl_mode
- MySQL: host, port, database, user, password
- S3: bucket, region, access_key, secret_key, prefix
- GCS: bucket, project_id (uses Workload Identity)
- REST API: base_url, auth_type, api_key/oauth settings

#### 1.3 Backend Service for Connection Testing
```python
# app/services/connector_test.py
async def test_connector(connector_type: str, config: dict) -> dict:
    """Test connector configuration returns {success, message, metadata}"""
```

#### 1.4 Frontend ConnectorsPage Implementation
- List all connectors with status badges
- Create connector wizard with type selection
- Configuration form per connector type
- Test connection button
- Edit/Delete actions

### Phase 2: Data Sync Workflows (Priority: HIGH)

#### 2.1 Create Generic DataSourceSyncWorkflow
```python
# app/workflows/data_source_sync.py
@workflow.defn
class DataSourceSyncWorkflow:
    """
    Generic workflow for syncing any data source to datalake

    Steps:
    1. Connect to source
    2. Extract data (full or incremental)
    3. Upload to staging (S3/GCS)
    4. Sync to PostgreSQL (Bronze/Silver)
    5. Update metadata
    """
```

#### 2.2 Create Activities per Connector Type
```python
# app/workflows/activities/connectors/
- snowflake_extract.py
- postgres_extract.py
- s3_extract.py
- api_extract.py
```

#### 2.3 Incremental Sync Support
- Track last sync timestamp
- Support watermark columns (e.g., updated_at)
- Support change data capture where available

### Phase 3: Automation Scheduling (Priority: MEDIUM)

#### 3.1 Update DataPipeline Model
```python
# app/models/data_pipeline.py - Add scheduling fields
schedule_type = Column(String)  # cron, interval, manual
cron_expression = Column(String, nullable=True)  # "0 8 * * MON"
interval_seconds = Column(Integer, nullable=True)
is_active = Column(Boolean, default=True)
last_run_at = Column(DateTime, nullable=True)
last_run_status = Column(String, nullable=True)
next_run_at = Column(DateTime, nullable=True)
```

#### 3.2 Create Scheduler Worker
```python
# app/workers/scheduler_worker.py
"""
Long-running worker that:
1. Checks for due automations every minute
2. Triggers Temporal workflows for matching schedules
3. Updates next_run_at after execution
"""
```

#### 3.3 Pipeline Execution History
```python
# app/models/pipeline_run.py
class PipelineRun(Base):
    pipeline_id = Column(UUID, ForeignKey("data_pipelines.id"))
    workflow_id = Column(String)  # Temporal workflow ID
    status = Column(String)  # pending, running, completed, failed
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error = Column(Text, nullable=True)
    output = Column(JSON, nullable=True)
```

### Phase 4: Frontend Enhancements (Priority: MEDIUM)

#### 4.1 Connector Configuration Wizard
- Step 1: Select connector type
- Step 2: Enter credentials
- Step 3: Test connection
- Step 4: Review and save

#### 4.2 Sync Status Dashboard
- Real-time sync status
- Last sync time, row counts
- Error alerts

#### 4.3 Execution History Viewer
- List of runs per pipeline
- Duration, status, logs
- Re-run button

---

## Immediate Next Steps (Today)

### Step 1: Implement ConnectorsPage Frontend
Create a functional connectors page with:
- List view with status
- Create modal with type selection
- Basic credential configuration

### Step 2: Add Connector Types
Update the backend connector model with:
- connector_type field
- status field
- Basic validation per type

### Step 3: Wire Pipeline Execute to Temporal
Update `dataPipelineService.execute()` to:
- Start a Temporal workflow
- Return workflow ID
- Track execution

---

## Files to Create/Modify

### New Files:
- `apps/api/app/services/connector_test.py` - Connection testing
- `apps/api/app/workflows/data_source_sync.py` - Generic sync workflow
- `apps/api/app/workflows/activities/connectors/` - Per-type activities
- `apps/api/app/models/pipeline_run.py` - Execution history

### Modify:
- `apps/api/app/models/connector.py` - Add type, status fields
- `apps/api/app/schemas/connector.py` - Add type-specific schemas
- `apps/api/app/api/v1/data_pipelines.py` - Wire to Temporal
- `apps/web/src/pages/ConnectorsPage.js` - Full implementation

---

## Date Created
December 18, 2025
