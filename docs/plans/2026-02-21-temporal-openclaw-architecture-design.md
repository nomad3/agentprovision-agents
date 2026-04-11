# Temporal Workflows & OpenClaw Integration Architecture

**Date:** 2026-02-21
**Status:** Implemented and deployed to production

## Overview

AgentProvision uses Temporal for durable workflow execution across three domains: agent task orchestration, OpenClaw instance provisioning, and data pipeline sync. Each tenant gets an isolated OpenClaw instance (deployed via Helm) for 50+ skill integrations. The SkillRouter service bridges the API layer to OpenClaw via a WebSocket gateway protocol.

---

## Temporal Infrastructure

### Workers

| Worker | Task Queue | File | Workflows | Activities |
|--------|-----------|------|-----------|------------|
| **Orchestration** | `agentprovision-orchestration` | `apps/api/app/workers/orchestration_worker.py` | TaskExecutionWorkflow, OpenClawProvisionWorkflow | dispatch_task, recall_memory, execute_task, persist_entities, evaluate_task, generate_openclaw_values, helm_install_openclaw, wait_pod_ready, health_check_openclaw, register_instance |
| **PostgreSQL** | `agentprovision-postgres` | `apps/api/app/workers/postgres_worker.py` | DatasetSyncWorkflow, KnowledgeExtractionWorkflow, AgentKitExecutionWorkflow, DataSourceSyncWorkflow, ScheduledSyncWorkflow | sync_to_bronze, transform_to_silver, update_dataset_metadata, extract_knowledge_from_session, execute_agent_kit_activity, extract_from_connector, load_to_bronze, load_to_silver, update_sync_metadata |
| **Scheduler** | N/A (event-driven) | `apps/api/app/workers/scheduler_worker.py` | Triggers ScheduledSyncWorkflow | Polls every 60s, supports cron + interval schedules |

### Temporal Connection

- Address: `settings.TEMPORAL_ADDRESS` (default: `temporal:7233`, prod via env var)
- Namespace: `settings.TEMPORAL_NAMESPACE` (default: `default`)
- Temporal UI accessible at `:8233` in development

---

## Workflow Catalog

### 1. TaskExecutionWorkflow

**Purpose:** Durable 5-step pipeline for executing agent tasks through the orchestration engine.

**File:** `apps/api/app/workflows/task_execution.py`
**Activities:** `apps/api/app/workflows/activities/task_execution.py`
**Queue:** `agentprovision-orchestration`
**Workflow ID pattern:** Not directly triggered via API (used internally)

```
Step 1: dispatch_task       (2min timeout)  → Find best agent via TaskDispatcher
Step 2: recall_memory       (1min timeout)  → Load relevant agent memories (importance >= 0.3, limit 5)
Step 3: execute_task        (10min timeout) → Run task via ADK client
Step 4: persist_entities    (5min timeout)  → Extract entities to knowledge graph
Step 5: evaluate_task       (2min timeout)  → Score results, store memory, update skills
```

**Execution Trace:** Each step writes an `ExecutionTrace` record with `step_type` and `step_order` (1-5). Frontend displays these in `TaskTimeline` component.

**Retry Policy:** 3 attempts, 30s initial interval, 2.0 backoff coefficient.

### 2. OpenClawProvisionWorkflow

**Purpose:** Provision an isolated OpenClaw instance per tenant via Helm chart deployment.

**File:** `apps/api/app/workflows/openclaw_provision.py`
**Activities:** `apps/api/app/workflows/activities/openclaw_provision.py`
**Queue:** `agentprovision-orchestration`
**Workflow ID patterns:** `provision-openclaw-{instance_id}`, `upgrade-openclaw-{instance_id}-{timestamp}`

```
Step 1: generate_openclaw_values  (1min timeout)  → Render per-tenant Helm values YAML
Step 2: helm_install_openclaw     (7min timeout)  → Run helm upgrade --install
Step 3: wait_pod_ready            (6min timeout)  → Poll kubectl until pod Running + Ready
Step 4: health_check_openclaw     (2min timeout)  → HTTP health check on port 18789
Step 5: register_instance         (1min timeout)  → Update TenantInstance DB record
```

**Resource Defaults:** CPU 250m/1000m, Memory 512Mi/2Gi.
**Namespace:** `prod` (hardcoded).
**Release naming:** `openclaw-{tenant_id[:8]}`.
**Internal URL:** `http://{release_name}.prod.svc.cluster.local:18789`.

**Triggered by:**
- `POST /api/v1/instances/` (create) - workflow ID: `provision-openclaw-{id}`
- `POST /api/v1/instances/{id}/upgrade` - workflow ID: `upgrade-openclaw-{id}-{timestamp}`

### 3. DatasetSyncWorkflow

**Purpose:** Sync datasets to PostgreSQL Unity Catalog through Bronze/Silver layers.

**File:** `apps/api/app/workflows/dataset_sync.py`
**Activities:** `apps/api/app/workflows/activities/postgres_sync.py`
**Queue:** `agentprovision-postgres`

```
Step 1: sync_to_bronze         (5min timeout)  → Upload via MCP server or direct PostgreSQL
Step 2: transform_to_silver    (10min timeout) → CTAS from Bronze table
Step 3: update_dataset_metadata (1min timeout) → Mark sync_status="synced" in DB
```

### 4. DataSourceSyncWorkflow + ScheduledSyncWorkflow

**Purpose:** Extract data from external connectors and load into PostgreSQL layers.

**File:** `apps/api/app/workflows/data_source_sync.py`
**Activities:** `apps/api/app/workflows/activities/connectors/extract.py`
**Queue:** `agentprovision-postgres`

```
DataSourceSyncWorkflow:
  Step 1: extract_from_connector → Supports Snowflake, PostgreSQL, BigQuery (full/incremental)
  Step 2: load_to_bronze         → Stage to Bronze layer
  Step 3: load_to_silver         → Transform to Silver layer
  Step 4: update_sync_metadata   → Update connector watermark

ScheduledSyncWorkflow:
  For each table in sync config → start child DataSourceSyncWorkflow
```

**Triggered by:**
- `POST /api/v1/data-pipelines/{id}/execute` (connector type)
- Scheduler worker (cron/interval triggers)

### 5. KnowledgeExtractionWorkflow

**Purpose:** Extract entities from chat session transcripts using LLM.

**File:** `apps/api/app/workflows/knowledge_extraction.py`
**Activities:** `apps/api/app/workflows/activities/knowledge_extraction.py`
**Queue:** `agentprovision-postgres`
**Workflow ID pattern:** `knowledge-extraction-{session_id}`

```
Step 1: extract_knowledge_from_session → LLM entity extraction with deduplication
```

**Triggered by:**
- `POST /api/v1/integrations/import/chatgpt`
- `POST /api/v1/integrations/import/claude`

### 6. AgentKitExecutionWorkflow

**Purpose:** Execute agent kit task bundles.

**File:** `apps/api/app/workflows/agent_kit_execution.py`
**Activities:** `apps/api/app/workflows/activities/agent_kit_execution.py`
**Queue:** `agentprovision-postgres`
**Workflow ID pattern:** `pipeline-{pipeline_id}-{run_id}`

**Triggered by:**
- `POST /api/v1/data-pipelines/{id}/execute` (agent_kit type)

---

## OpenClaw Integration Architecture

### Instance Lifecycle

```
                    POST /instances/
                          │
                          ▼
              ┌───────────────────────┐
              │   DB: provisioning    │
              └─────────┬─────────────┘
                        │
                        ▼
              OpenClawProvisionWorkflow
              (Temporal, ~5 steps)
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
         DB: running         DB: error
              │
    ┌─────────┼─────────┬─────────────┐
    ▼         ▼         ▼             ▼
  /stop    /restart   /upgrade    DELETE /
    │         │         │             │
    ▼         ▼         ▼             ▼
kubectl    kubectl   Temporal     helm uninstall
scale 0    rollout   workflow     + PVC cleanup
    │      restart      │         + DB delete
    ▼         │         ▼
DB: stopped   │    DB: upgrading
    │         │         │
    ▼         ▼         ▼
  /start   DB: running  DB: running
    │
    ▼
kubectl
scale 1
    │
    ▼
DB: running
```

### Instance API Endpoints

| Endpoint | Method | Action | Implementation |
|----------|--------|--------|----------------|
| `GET /instances/` | GET | List tenant instances | DB query |
| `POST /instances/` | POST | Deploy new instance | DB create + Temporal workflow |
| `GET /instances/{id}` | GET | Get instance details | DB query |
| `POST /instances/{id}/stop` | POST | Stop instance | `kubectl scale --replicas=0` |
| `POST /instances/{id}/start` | POST | Start instance | `kubectl scale --replicas=1` |
| `POST /instances/{id}/restart` | POST | Restart instance | `kubectl rollout restart` |
| `POST /instances/{id}/upgrade` | POST | Upgrade instance | DB update + Temporal workflow |
| `DELETE /instances/{id}` | DELETE | Destroy instance | `helm uninstall` + PVC cleanup + DB delete |
| `GET /instances/{id}/logs` | GET | Get pod logs | `kubectl logs --tail=N` |

**File:** `apps/api/app/api/v1/instances.py`

### OpenClaw Gateway Protocol (WebSocket)

OpenClaw uses a WebSocket-only protocol on port `18789`. HTTP POST returns 405.

**Connection Flow:**

```
API Server                              OpenClaw Gateway
    │                                        │
    ├──── ws://openclaw:18789 ──────────────►│
    │                                        │
    │◄──── connect.challenge {nonce} ────────┤
    │                                        │
    ├──── connect {auth:{token}, device} ───►│
    │                                        │
    │◄──── hello-ok ─────────────────────────┤
    │                                        │
    ├──── sessions_send {skill, payload} ───►│
    │                                        │
    │◄──── res {data} or event {payload} ────┤
    │                                        │
```

**Authentication:**
- Token: `OPENCLAW_GATEWAY_TOKEN` from k8s secret `openclaw-secrets`
- Challenge-response: Server sends nonce, client responds with token + device ID
- Frame format: `{type: "req", id: "<unique>", method: "connect", params: {auth: {token: "..."}, device: {nonce: "..."}}}`

**Skill Execution:**
- Method: `sessions_send`
- Payload includes: skill name, input data, decrypted credentials, LLM config
- Response: Wait for matching `{type: "res", id: "<exec-id>"}` or event frame
- Timeout: 60 seconds for response, 90 seconds overall

**Implementation:** `apps/api/app/services/orchestration/skill_router.py` (`_call_openclaw()`)

### Skills Gateway (SkillRouter)

The `SkillRouter` service orchestrates skill execution through the tenant's OpenClaw instance.

**File:** `apps/api/app/services/orchestration/skill_router.py`

**Execution Flow:**

```
POST /api/v1/skills/execute
         │
         ▼
    SkillRouter.execute_skill()
         │
    ┌────┴────────────────────────┐
    │ 1. Resolve instance         │  DB: TenantInstance (status=running)
    │ 2. Circuit breaker check    │  Module-level state (3 failures / 5min window)
    │ 3. Validate SkillConfig     │  DB: SkillConfig (enabled, approval gate)
    │ 4. Decrypt credentials      │  CredentialVault (Fernet decryption)
    │ 5. Resolve LLM model        │  LLMRouter (per-skill or tenant default)
    │ 6. Call OpenClaw (WebSocket) │  Challenge-response + sessions_send
    │ 7. Log ExecutionTrace        │  DB: execution_traces
    └─────────────────────────────┘
```

**Circuit Breaker:**
- Threshold: 3 failures
- Window: 5 minutes
- Cooldown: 2 minutes
- Scope: per instance ID (module-level shared state)

**API Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /api/v1/skills/execute` | POST | Execute a skill through tenant's OpenClaw |
| `GET /api/v1/skills/health` | GET | Health check (HTTP + WebSocket verification) |

**File:** `apps/api/app/api/v1/skills.py`

### Health Probe

The health check verifies both HTTP and WebSocket connectivity to the OpenClaw instance.

**Backend (`SkillRouter.health_check()`):**
1. HTTP check: `GET` to internal URL (status < 400 = ok)
2. WebSocket check: Connect and verify `connect.challenge` event received
3. Returns: `{healthy: bool, http_ok: bool, ws_ok: bool, status: "healthy"|"http_only"|"unreachable"}`

**Frontend (`OpenClawInstanceCard.js`):**
- On page load, if DB status is "running", calls `GET /api/v1/skills/health`
- Displays:
  - Green "Live" badge when `healthy: true`
  - Red "Unreachable" badge when `healthy: false`
  - Spinner while checking

---

## Frontend Integration

### Task Execution Visualization

**Page:** `apps/web/src/pages/TaskConsolePage.js` (route: `/task-console`)
**Timeline Component:** `apps/web/src/components/TaskTimeline.js`
**Service:** `apps/web/src/services/taskService.js`

**Features:**
- Two-column layout: task list (left) + task detail (right)
- 5-second polling interval for real-time updates
- Execution trace timeline with step icons and duration badges
- Approval workflow: approve/reject for `waiting_input` tasks

**Task Status Flow:**
```
queued → thinking → executing → waiting_input → completed/failed
                                     │
                              approve/reject
```

**API Calls:**
- `GET /api/v1/agent-tasks/` - List tasks (with status filter)
- `GET /api/v1/agent-tasks/{id}` - Task detail
- `GET /api/v1/agent-tasks/{id}/trace` - Execution trace steps
- `POST /api/v1/agent-tasks/{id}/approve` - Approve waiting task
- `POST /api/v1/agent-tasks/{id}/reject` - Reject waiting task

### OpenClaw Instance Management

**Component:** `apps/web/src/components/OpenClawInstanceCard.js` (on `/integrations`)
**Service:** `apps/web/src/services/instanceService.js`

**Features:**
- Deploy, stop, start, restart, destroy lifecycle controls
- Live health badge (calls `/api/v1/skills/health` when running)
- Version, uptime, namespace, CPU, memory display
- Polling during transient states (provisioning/upgrading/destroying)

**Status States:**
```
(none) → provisioning → running ⟷ stopped
                  │         │
              upgrading   error
                  │
              destroying → (deleted)
```

### Skills Configuration

**Component:** `apps/web/src/components/SkillsConfigPanel.js` (on `/integrations`)
**Service:** `apps/web/src/services/skillService.js`

**Features:**
- 50+ skill cards with toggle, credential forms, and test button
- Per-skill credential management (encrypted via CredentialVault)
- Test button sends `POST /api/v1/skills/execute` with test payload
- Skill registry defines available skills with icons and credential fields

### Data Pipelines

**Page:** `apps/web/src/pages/DataPipelinesPage.js` (route: `/data-pipelines`)

**Features:**
- Manual pipeline execution via `POST /api/v1/data-pipelines/{id}/execute`
- Pipeline run history display (status, duration, error details)
- Triggers DatasetSyncWorkflow, DataSourceSyncWorkflow, or AgentKitExecutionWorkflow via Temporal

---

## Execution Trace System

### Model

**File:** `apps/api/app/models/execution_trace.py`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `task_id` | UUID | FK to `agent_tasks.id` |
| `tenant_id` | UUID | FK to `tenants.id` |
| `step_type` | String | dispatched, memory_recall, executing, entity_persist, skill_call, completed, failed |
| `step_order` | Integer | Sequential step number |
| `agent_id` | UUID | FK to `agents.id` (nullable) |
| `details` | JSON | Step-specific data |
| `duration_ms` | Integer | Step execution time |
| `created_at` | DateTime | Timestamp |

### Service

**File:** `apps/api/app/services/execution_traces.py`

- `create_trace(db, trace_in, tenant_id)` - Insert trace record
- `get_traces_by_task(db, task_id, tenant_id)` - Ordered by step_order
- `get_traces_by_tenant(db, tenant_id, skip, limit)` - Ordered by created_at DESC

### API

**Endpoint:** `GET /api/v1/agent-tasks/{task_id}/trace`
**File:** `apps/api/app/api/v1/agent_tasks.py`

Returns all `ExecutionTrace` records for a task, rendered by `TaskTimeline` component in the frontend.

---

## Kubernetes Deployment

### Helm Values

**API service:** `helm/values/agentprovision-api.yaml`
- `TEMPORAL_ADDRESS: temporal:7233` (env var)
- `OPENCLAW_GATEWAY_TOKEN` from `openclaw-secrets` k8s secret
- `ADK_BASE_URL: http://agentprovision-adk` (configMap)

**Worker:** Deployed as separate pod with same image, runs `orchestration_worker.py` and `postgres_worker.py`.

### Secrets

| Secret Name | Key | Used By |
|-------------|-----|---------|
| `openclaw-secrets` | `OPENCLAW_GATEWAY_TOKEN` | API → SkillRouter → OpenClaw WebSocket auth |
| `agentprovision-api-secret` | `SECRET_KEY`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `ENCRYPTION_KEY` | API service |

### Services

| K8s Service | Port | Used For |
|-------------|------|----------|
| `temporal` | 7233 | Temporal server gRPC |
| `openclaw` | 18789 | OpenClaw WebSocket gateway |
| `agentprovision-api` | 8000 | FastAPI backend |
| `agentprovision-adk` | 8080 | ADK server |

---

## File Reference

### Workflow Definitions
- `apps/api/app/workflows/task_execution.py` - TaskExecutionWorkflow
- `apps/api/app/workflows/openclaw_provision.py` - OpenClawProvisionWorkflow
- `apps/api/app/workflows/dataset_sync.py` - DatasetSyncWorkflow
- `apps/api/app/workflows/data_source_sync.py` - DataSourceSyncWorkflow, ScheduledSyncWorkflow
- `apps/api/app/workflows/knowledge_extraction.py` - KnowledgeExtractionWorkflow
- `apps/api/app/workflows/agent_kit_execution.py` - AgentKitExecutionWorkflow

### Activity Implementations
- `apps/api/app/workflows/activities/task_execution.py` - 5 task execution activities
- `apps/api/app/workflows/activities/openclaw_provision.py` - 5 provisioning activities
- `apps/api/app/workflows/activities/postgres_sync.py` - 3 dataset sync activities
- `apps/api/app/workflows/activities/knowledge_extraction.py` - 1 extraction activity
- `apps/api/app/workflows/activities/agent_kit_execution.py` - 1 kit execution activity
- `apps/api/app/workflows/activities/connectors/extract.py` - 4 connector activities

### Workers
- `apps/api/app/workers/orchestration_worker.py` - Orchestration queue worker
- `apps/api/app/workers/postgres_worker.py` - PostgreSQL queue worker
- `apps/api/app/workers/scheduler_worker.py` - Scheduled pipeline trigger

### API Routes
- `apps/api/app/api/v1/instances.py` - Instance lifecycle (9 endpoints)
- `apps/api/app/api/v1/skills.py` - Skill execution + health (2 endpoints)
- `apps/api/app/api/v1/agent_tasks.py` - Task CRUD + trace query
- `apps/api/app/api/v1/data_pipelines.py` - Pipeline execution trigger
- `apps/api/app/api/v1/integrations.py` - Knowledge extraction trigger

### Services
- `apps/api/app/services/orchestration/skill_router.py` - SkillRouter (WebSocket, circuit breaker)
- `apps/api/app/services/orchestration/credential_vault.py` - Fernet encryption
- `apps/api/app/services/orchestration/task_dispatcher.py` - Agent selection
- `apps/api/app/services/tenant_instances.py` - Instance CRUD
- `apps/api/app/services/execution_traces.py` - Trace CRUD

### Frontend
- `apps/web/src/pages/TaskConsolePage.js` - Task execution monitor
- `apps/web/src/pages/IntegrationsPage.js` - OpenClaw + Skills page
- `apps/web/src/components/TaskTimeline.js` - Execution trace timeline
- `apps/web/src/components/OpenClawInstanceCard.js` - Instance lifecycle card with health probe
- `apps/web/src/components/SkillsConfigPanel.js` - Skill configuration with test button
- `apps/web/src/services/taskService.js` - Task API client
- `apps/web/src/services/instanceService.js` - Instance API client
- `apps/web/src/services/skillService.js` - Skill API client

### Configuration
- `apps/api/app/core/config.py` - Settings (TEMPORAL_ADDRESS, OPENCLAW_GATEWAY_TOKEN, etc.)
- `helm/values/agentprovision-api.yaml` - K8s deployment config
