# Enterprise Agentic Orchestration Engine — Design Document

**Date:** 2025-02-13
**Status:** Approved
**Scope:** Temporal-backed orchestration, in-platform traceability, managed OpenClaw instances, credential vault, LLM-agnostic skills, language abstraction

---

## 1. Problem Statement

AgentProvision has the data models for enterprise agent orchestration (AgentTask, AgentRelationship, AgentSkill, AgentMemory, AgentMessage, AgentGroup) but no execution logic. Only ~5-8% of platform operations use Temporal. The UI is PE/roll-up specific and needs to be industry-agnostic. OpenClaw provides 50+ external service integrations but lacks enterprise controls.

### Goals

1. Wire all existing agent models into Temporal-backed durable execution
2. Build in-platform traceability (no Temporal UI dependency)
3. Deploy managed, fully isolated OpenClaw instances per tenant via Helm
4. Secure credential vault for per-tenant skill API keys/tokens
5. LLM-agnostic skill execution with per-tenant/per-skill model selection
6. Abstract PE-specific language to generic enterprise terms

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    AGENTPROVISION PLATFORM                        │
│                                                                  │
│  ┌─ Frontend ─────────────────────────────────────────────────┐ │
│  │ Operations Command Center  │  Task Execution Console       │ │
│  │ Integrations Hub                                           │ │
│  │  ├─ Connectors (Snowflake, Postgres, S3, ...)             │ │
│  │  ├─ OpenClaw Instance Manager (deploy/stop/upgrade/logs)  │ │
│  │  └─ Skills Config (enable/approve/LLM/credentials)        │ │
│  │ Agent Fleet  │  LLM Settings  │  Organizations             │ │
│  └────────────────────────┬───────────────────────────────────┘ │
│                           │ REST API                            │
│  ┌─ API Layer ────────────▼───────────────────────────────────┐ │
│  │ /agent-tasks     → Create tasks, view traces               │ │
│  │ /instances       → Manage tenant OpenClaw instances         │ │
│  │ /skill-configs   → Per-tenant skill enable/approve/LLM     │ │
│  │ /skill-creds     → Encrypted credential management         │ │
│  │ /connectors      → Existing connector management           │ │
│  │ /llm-configs     → Multi-LLM provider management           │ │
│  └────────────────────────┬───────────────────────────────────┘ │
│                           │                                     │
│  ┌─ Orchestration Engine ─▼───────────────────────────────────┐ │
│  │                    TEMPORAL                                 │ │
│  │  TaskExecutionWorkflow      (agent task execution)          │ │
│  │  OpenClawProvisionWorkflow  (deploy/upgrade/destroy)        │ │
│  │  DatasetSyncWorkflow        (existing)                      │ │
│  │  ConnectorSyncWorkflow      (existing)                      │ │
│  │  KnowledgeExtractionWorkflow (existing)                     │ │
│  └───────┬──────────────┬──────────────┬──────────────────────┘ │
│          │              │              │                         │
│     ┌────▼────┐   ┌────▼────────┐   ┌────▼────┐               │
│     │   ADK   │   │  Per-Tenant │   │  MCP    │               │
│     │ Multi-  │   │  OpenClaw   │   │ Server  │               │
│     │ LLM     │   │  Instances  │   │ Data    │               │
│     └─────────┘   │ (Helm)      │   └─────────┘               │
│                    │ 🦞 tenant-A │                              │
│                    │ 🦞 tenant-B │                              │
│                    │ 🦞 tenant-C │                              │
│                    └─────────────┘                              │
│                                                                  │
│  ┌─ Cross-Cutting ────────────────────────────────────────────┐ │
│  │ ExecutionTrace   │  AgentMemory   │  SkillCredential       │ │
│  │ AgentMessage     │  SkillConfig   │  TenantInstance        │ │
│  │ LLM Router       │  Multi-tenant isolation                 │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Orchestration Engine (Temporal)

### 3.1 TaskExecutionWorkflow

Every `AgentTask` triggers a durable Temporal workflow with 5 activities:

```
AgentTask created (status: queued)
  │
  ├─ 1. dispatch_activity
  │     TaskDispatcher.find_best_agent()
  │     Match capabilities, skills, relationships, trust_level
  │     Status → "thinking"
  │
  ├─ 2. recall_memory_activity
  │     MemoryService.get_relevant_memories()
  │     Load agent memories by task context (limit=5, min_importance=0.3)
  │     Inject into execution context
  │
  ├─ 3. execute_activity
  │     Route to execution backend:
  │     ├─ ADK: AI reasoning, data analysis
  │     ├─ OpenClaw: External service actions (via tenant's instance)
  │     └─ MCP: Data operations (PostgreSQL)
  │     Status → "executing"
  │     Log AgentMessages for each step
  │
  ├─ 4. evaluate_activity
  │     Calculate confidence score
  │     Store output in task.output
  │     Update AgentSkill proficiency + success_rate
  │     Create AgentMemory from experience
  │     Track tokens_used + cost
  │     Status → "completed" or "failed"
  │
  └─ 5. delegate_activity (conditional)
        If task requires delegation:
        Create child AgentTask (parent_task_id set)
        Start child TaskExecutionWorkflow
        Parent status → "delegated"
        Wait for child, aggregate results
```

### 3.2 Configuration

- **Task queue:** `agentprovision-orchestration` (new, separate from `agentprovision-postgres`)
- **Worker:** `orchestration_worker.py` (new file alongside existing `postgres_worker.py`)
- **Retry policy:** 3 attempts, exponential backoff (initial 30s, max 5min)
- **Timeouts:** 10 minutes per task, 30 minutes for delegated chains
- **Approval gate:** If `requires_approval=true`, workflow signals and waits for human approval via Temporal signal

### 3.3 Approval Workflow

When a task or skill requires human approval:

1. Workflow sends a Temporal signal: `approval_requested`
2. API updates task status → `waiting_input`
3. Frontend shows approval notification in Task Execution Console
4. Human clicks [Approve] or [Reject]
5. API sends Temporal signal: `approval_response` with decision
6. Workflow resumes or fails based on decision

---

## 4. In-Platform Traceability

### 4.1 ExecutionTrace Model (new)

```python
class ExecutionTrace(Base):
    __tablename__ = "execution_traces"

    id              # UUID PK
    task_id         # FK → agent_tasks
    tenant_id       # FK → tenants
    step_type       # "dispatched", "memory_recall", "executing", "skill_call",
                    # "delegated", "approval_requested", "approval_granted",
                    # "completed", "failed"
    step_order      # Integer (sequential within task)
    agent_id        # FK → agents, nullable (which agent performed this step)
    details         # JSON: step-specific data
                    #   dispatched: {agent_name, skill_match_score, capabilities_matched}
                    #   executing: {backend: "adk"|"openclaw"|"mcp", tool_called, input, output}
                    #   skill_call: {skill_name, action, approved_by, credentials_used: "bot_token:****a3f2"}
                    #   completed: {confidence, tokens_used, cost, llm_model}
    duration_ms     # Integer
    created_at      # DateTime
```

### 4.2 Task Execution Console (new page)

Frontend page showing:

1. **Active Tasks list** — filterable by status, agent, priority
2. **Task Detail view** — execution timeline, agent messages, output, metrics
3. **Live updates** — poll every 2s for in-progress tasks (or SSE later)

### 4.3 API Endpoints (new)

```
GET  /api/v1/agent-tasks                    # List with filters (status, agent, priority)
GET  /api/v1/agent-tasks/{id}               # Task detail
GET  /api/v1/agent-tasks/{id}/trace         # Execution timeline (List[ExecutionTrace])
GET  /api/v1/agent-tasks/{id}/messages      # Inter-agent messages
POST /api/v1/agent-tasks/{id}/approve       # Human approval
POST /api/v1/agent-tasks/{id}/reject        # Human rejection
POST /api/v1/agent-tasks                    # Create task (triggers workflow)
```

---

## 5. Managed OpenClaw Instances

### 5.1 Per-Tenant Isolation

Each tenant gets a fully isolated OpenClaw instance deployed via the existing Helm chart from `../openclaw-k8s/helm/openclaw/`. Each Helm release creates:

- **Deployment** — 1 replica, `openclaw/openclaw:{version}` image
- **Service** — ClusterIP on port 18789 (internal only)
- **PVC** — 10Gi at `/root/.openclaw` for config, memory, workspace, sessions
- **Secret** — tenant's API keys (Anthropic, OpenAI, Gemini, GitHub, etc.)
- **NetworkPolicy** — only accepts connections from `agentprovision-api` pods

Instance naming: `openclaw-{tenant_short_id}` (first 8 chars of tenant UUID)
Service URL: `ws://openclaw-{tenant_short_id}:18789` (cluster-internal)

### 5.2 TenantInstance Model (new)

```python
class TenantInstance(Base):
    __tablename__ = "tenant_instances"

    id              # UUID PK
    tenant_id       # FK → tenants
    instance_type   # "openclaw" (extensible for future instance types)
    version         # "2026.2.1" (OpenClaw version)
    status          # "provisioning", "running", "stopped", "upgrading", "error", "destroying"
    internal_url    # "ws://openclaw-c024fddd:18789"
    helm_release    # "openclaw-c024fddd" (Helm release name)
    k8s_namespace   # "prod"
    resource_config # JSON: {cpu_request, cpu_limit, memory_request, memory_limit, storage}
    health          # JSON: {last_check, healthy, uptime, cpu_pct, memory_pct}
    error           # String, nullable
    created_at
    updated_at
```

### 5.3 OpenClawProvisionWorkflow (Temporal)

```
Tenant clicks [Deploy OpenClaw Instance]
  │
  ├─ 1. generate_values_activity
  │     Generate per-tenant values.yaml override:
  │       release name: openclaw-{tenant_short_id}
  │       secrets: tenant's encrypted API keys (decrypted at runtime)
  │       resources: from tenant's resource tier config
  │     Create TenantInstance record (status: provisioning)
  │
  ├─ 2. helm_install_activity
  │     Execute: helm upgrade --install openclaw-{tenant_short_id}
  │              ../openclaw-k8s/helm/openclaw/
  │              -f /tmp/{tenant_short_id}-values.yaml
  │              -n prod
  │     Uses Kubernetes Python client or subprocess
  │
  ├─ 3. wait_ready_activity
  │     Poll pod readiness (kubectl get pod -l app=openclaw-{tenant_short_id})
  │     Timeout: 5 minutes
  │     Retry on not-ready
  │
  ├─ 4. health_check_activity
  │     Verify OpenClaw gateway responds on port 18789
  │     Test WebSocket connectivity from API pod
  │
  └─ 5. register_activity
        Update TenantInstance:
          status → "running"
          internal_url → "ws://openclaw-{tenant_short_id}:18789"
          health → initial health snapshot
```

### 5.4 Lifecycle Management

| UI Action | Backend |
|---|---|
| **Deploy** | `OpenClawProvisionWorkflow` → `helm upgrade --install` |
| **Stop** | `helm upgrade` with `replicas: 0` (keeps PVC) |
| **Start** | `helm upgrade` with `replicas: 1` |
| **Restart** | `kubectl rollout restart deployment/openclaw-{id}` |
| **Upgrade** | `helm upgrade` with new image tag, rolling update |
| **Destroy** | `helm uninstall openclaw-{id}` + delete PVC |
| **Logs** | Stream via K8s API → shown in UI modal |
| **Health** | Background job polls every 60s, updates `health` JSON |

### 5.5 Instance Management UI

Added to Integrations Hub page:

- **Not deployed:** CTA card with [Deploy OpenClaw Instance] button
- **Deployed:** Status card showing version, uptime, resource usage, with [Skills Config] [Restart] [Upgrade] [Logs] [Stop] [Destroy] actions
- **Provisioning:** Progress indicator with Temporal workflow status

### 5.6 OpenClaw Config Template

Per-tenant `config.json` generated from template:

```json
{
  "gateway": {
    "mode": "local",
    "bind": "lan",
    "port": 18789,
    "auth": {
      "mode": "token",
      "token": "{{ generated_gateway_token }}"
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "{{ tenant_default_llm }}"
      },
      "maxConcurrent": 4,
      "subagents": { "maxConcurrent": 8 }
    }
  },
  "skills": {
    "entries": {}
  }
}
```

Skills and credentials are injected at runtime per-request by the Skill Router, NOT baked into the config. The config only has the gateway token and default LLM model.

---

## 6. Credential Vault

### 6.1 SkillCredential Model (new)

```python
class SkillCredential(Base):
    __tablename__ = "skill_credentials"

    id              # UUID PK
    tenant_id       # FK → tenants
    skill_config_id # FK → skill_configs
    credential_key  # "bot_token", "signing_secret", "pat", "oauth_token"
    encrypted_value # AES-256 encrypted, never returned in API responses
    credential_type # "api_key", "oauth_token", "bot_token", "pat", "secret"
    status          # "active", "expired", "revoked"
    expires_at      # DateTime, nullable
    last_used_at    # DateTime, nullable
    created_at
    updated_at
```

### 6.2 Encryption

- **At rest:** AES-256-GCM encryption using a master key from GCP Secret Manager
- **In transit:** HTTPS only, credentials never in URL params
- **API responses:** Never return raw values, only `last_4` chars + status
- **In OpenClaw pod:** Credentials injected per-request via WebSocket, never persisted on disk
- **Revocation:** Tenant clicks [Revoke], status → "revoked", all future requests fail immediately

### 6.3 Skill Credential Registry

Each skill defines what credentials it needs:

```python
SKILL_CREDENTIAL_SCHEMAS = {
    "slack": [
        {"key": "bot_token", "type": "bot_token", "required": True, "label": "Bot Token", "placeholder": "xoxb-..."},
        {"key": "signing_secret", "type": "secret", "required": False, "label": "Signing Secret"},
    ],
    "gmail": [
        {"key": "oauth_token", "type": "oauth_token", "required": True, "label": "Gmail Account", "auth_flow": "oauth"},
    ],
    "github": [
        {"key": "pat", "type": "pat", "required": True, "label": "Personal Access Token", "placeholder": "ghp_...", "scopes": ["repo", "issues"]},
    ],
    "whatsapp": [
        {"key": "api_key", "type": "api_key", "required": True, "label": "WhatsApp Business API Key"},
        {"key": "phone_number_id", "type": "api_key", "required": True, "label": "Phone Number ID"},
    ],
    "telegram": [
        {"key": "bot_token", "type": "bot_token", "required": True, "label": "Bot Token", "placeholder": "123456:ABC-..."},
    ],
    "notion": [
        {"key": "api_key", "type": "api_key", "required": True, "label": "Integration Token", "placeholder": "ntn_..."},
    ],
    # ... extensible for all 50+ OpenClaw skills
}
```

Frontend renders credential forms dynamically from this registry (same pattern as existing `CONNECTOR_FIELDS`).

### 6.4 OpenClaw Instance Secrets

The Helm chart's Secret template already supports these env vars:
- `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY` — for LLM access
- `GITHUB_TOKEN`, `NOTION_API_KEY` — for skill access
- `OPENCLAW_GATEWAY_TOKEN` — for authenticating API → OpenClaw WebSocket calls

For tenant provisioning, the `generate_values_activity` populates these from the tenant's `SkillCredential` records (decrypted at deploy time, base64-encoded into Helm values). When credentials are updated in the UI, the workflow runs a `helm upgrade` to rotate the secret.

For per-request credential injection (skills not baked into the pod), the Skill Router decrypts and passes credentials as runtime parameters in the WebSocket message.

---

## 7. Skills Gateway

### 7.1 SkillConfig Model (new)

```python
class SkillConfig(Base):
    __tablename__ = "skill_configs"

    id                # UUID PK
    tenant_id         # FK → tenants
    instance_id       # FK → tenant_instances (which OpenClaw pod)
    skill_name        # "slack", "gmail", "github", "whatsapp", "telegram", "notion", etc.
    enabled           # Boolean
    requires_approval # Boolean (human-in-the-loop gate)
    rate_limit        # JSON: {"max_actions": 10, "per_seconds": 3600}
    allowed_scopes    # JSON: {"channels": ["#general"], "repos": ["org/repo"]}
    llm_config_id     # FK → llm_configs, nullable (specific LLM for this skill)
    created_at
    updated_at

    # Relationships
    credentials → List[SkillCredential]
    instance → TenantInstance
```

### 7.2 Skill Router

The Skill Router sits between the orchestration engine and execution backends:

```
Agent needs external skill
  │
  ├─ 1. Resolve tenant's OpenClaw instance
  │     TenantInstance.query(tenant_id, instance_type="openclaw", status="running")
  │     → internal_url: ws://openclaw-{id}:18789
  │
  ├─ 2. Check SkillConfig
  │     Enabled? Rate limit not exceeded? Scopes allowed?
  │
  ├─ 3. Check approval requirement
  │     If requires_approval → task status → "waiting_input"
  │     Wait for human signal via Temporal
  │
  ├─ 4. Load LLM config
  │     SkillConfig.llm_config_id → specific model
  │     OR fall through to LLMRouter.select_model() (tenant defaults)
  │
  ├─ 5. Load credentials
  │     Decrypt SkillCredential for this tenant + skill
  │     Never log raw values
  │
  ├─ 6. Execute via OpenClaw WebSocket
  │     Authenticate with OPENCLAW_GATEWAY_TOKEN
  │     Send: {skill, action, params, credentials}
  │     Receive: result
  │
  └─ 7. Log to ExecutionTrace
        skill_name, action, result, llm_model, tokens, cost, duration
        credentials_used: "bot_token:****a3f2" (masked)
```

### 7.3 Skills Config UI

Added as a panel within the Integrations Hub when OpenClaw instance is running:

- List of available skills with enable/disable toggle
- Per-skill: credentials form, approval toggle, rate limit, scope restrictions, LLM selection
- Audit log showing recent skill executions per tenant

---

## 8. LLM-Agnostic Execution

### 8.1 Per-Skill LLM Selection

Each `SkillConfig` can optionally reference an `llm_config_id`. If set, that skill uses the specific LLM. If null, the existing `LLMRouter` selects based on task type and tenant defaults.

### 8.2 Existing LLM Router Integration

The existing `LLMRouter` at `apps/api/app/services/llm/router.py` already supports:
- Multiple providers (Anthropic, OpenAI, DeepSeek, Mistral, Google)
- Per-tenant configuration
- Cost/speed/quality priority routing
- Fallback models

No changes needed to the router itself — we just wire `SkillConfig.llm_config_id` into the execution chain.

### 8.3 ADK LLM Flexibility

The ADK server currently hardcodes Gemini 2.5 Flash. Future iteration: pass the tenant's preferred LLM as an environment variable or runtime parameter to ADK. For MVP, ADK keeps using Gemini.

---

## 9. Language Abstraction

Direct string replacements in ~9 files. No architectural change needed.

### 9.1 Terminology Mapping

| Current (PE-specific) | New (Generic) |
|---|---|
| "The AI-Powered Operating System for Roll-Ups" | "The AI-Powered Operations Platform" |
| "Acquire. Integrate. Scale. Repeat." | "Connect. Automate. Scale. Repeat." |
| "Portfolio Command Center" | "Operations Command Center" |
| "Roll-Up Operator" / "roll-up" | (removed, no replacement needed) |
| "Portfolio Overview" | "Analytics Overview" |
| "Portfolio Entities" | "Organizations" |
| "Entity Data" | "Business Data" |
| "Entity Integrations" | "System Integrations" |
| "ENTITY DATA" (nav section) | "DATA" |
| "PORTFOLIO ADMIN" (nav section) | "ADMIN" |
| "Cross-entity metrics" | "Cross-business metrics" |
| "Portfolio KPI Dashboard" | "KPI Dashboard" |
| "Due Diligence Summary" | "Business Health Assessment" |
| "M&A Pipeline" | "Growth Pipeline" |
| "portfolio companies & entities" | "organizations & business units" |
| "Entity P&L Statement" | "P&L Statement" (already generic) |
| "Consolidated Balance Sheet" | (keep — already generic) |
| "Entity Comparison" | "Business Unit Comparison" |
| "Pre-built agent playbooks for roll-up operations" | "Pre-built agent playbooks for business automation" |

### 9.2 Files to Update

1. `apps/web/src/components/Layout.js` — nav labels, section headers
2. `apps/web/src/pages/DashboardPage.js` — hero text, stat cards, descriptions
3. `apps/web/src/pages/NotebooksPage.js` — report template names/descriptions
4. `apps/web/src/pages/HomePage.js` — quick actions, activity items, tips
5. `apps/web/src/pages/TenantsPage.js` — page title, descriptions, definitions
6. `apps/web/src/components/QuickStartSection.js` — step copy
7. `apps/web/public/locales/en/landing.json` — all landing page copy
8. `apps/web/public/locales/en/common.json` — sidebar terms
9. `apps/web/public/locales/es/landing.json` — Spanish translations (mirror changes)

---

## 10. New Models Summary

| Model | Table | Purpose |
|---|---|---|
| `ExecutionTrace` | `execution_traces` | Step-by-step audit trail for task execution |
| `TenantInstance` | `tenant_instances` | Managed OpenClaw pod lifecycle per tenant |
| `SkillConfig` | `skill_configs` | Per-tenant skill enable/approve/rate-limit/LLM |
| `SkillCredential` | `skill_credentials` | AES-256 encrypted API keys/tokens per skill |

### Existing Models Wired In (no schema changes)

| Model | What Changes |
|---|---|
| `AgentTask` | Now triggers `TaskExecutionWorkflow` on creation |
| `AgentMessage` | Written by execution activities for inter-agent comms |
| `AgentMemory` | Recalled before execution, stored after completion |
| `AgentSkill` | Proficiency/success_rate updated after each task |
| `AgentRelationship` | Consulted by `TaskDispatcher` for delegation routing |
| `AgentGroup` | Strategy/escalation_rules read by workflow |

---

## 11. New Files Summary

### Backend (apps/api/)

```
app/models/
  execution_trace.py          # ExecutionTrace model
  tenant_instance.py          # TenantInstance model
  skill_config.py             # SkillConfig model
  skill_credential.py         # SkillCredential model

app/schemas/
  execution_trace.py          # Trace schemas
  tenant_instance.py          # Instance schemas
  skill_config.py             # SkillConfig + SkillCredential schemas

app/services/
  orchestration/
    skill_router.py           # Route skills to OpenClaw, check config, inject creds
    credential_vault.py       # AES-256 encrypt/decrypt, GCP Secret Manager key
  instance_manager.py         # TenantInstance CRUD + Helm operations

app/workflows/
  task_execution.py           # TaskExecutionWorkflow
  openclaw_provision.py       # OpenClawProvisionWorkflow
  activities/
    task_execution.py         # dispatch, recall_memory, execute, evaluate, delegate
    openclaw_provision.py     # generate_values, helm_install, wait_ready, health_check, register

app/workers/
  orchestration_worker.py     # New Temporal worker for orchestration task queue

app/api/v1/
  task_execution.py           # Task + trace + approval endpoints
  instances.py                # Instance management endpoints
  skill_configs.py            # Skill config + credential endpoints
```

### Frontend (apps/web/)

```
src/pages/
  TaskConsolePage.js          # Task Execution Console (new page)

src/components/
  OpenClawInstanceCard.js     # Instance status/management card
  SkillsConfigPanel.js        # Skills enable/config/credentials panel
  TaskTimeline.js             # Execution trace timeline component

src/services/
  taskService.js              # API client for task/trace endpoints
  instanceService.js          # API client for instance management
  skillConfigService.js       # API client for skill config/credentials
```

### Helm

```
helm/values/agentprovision-orchestration-worker.yaml  # New worker Helm values
```

### Infrastructure

The OpenClaw Helm chart at `../openclaw-k8s/helm/openclaw/` is used as-is. Per-tenant deployments are created by the `OpenClawProvisionWorkflow` generating per-tenant values and running `helm upgrade --install`.

Additional Helm template needed:
```
helm/charts/microservice/templates/networkpolicy.yaml  # Template for OpenClaw pod isolation
```

---

## 12. MVP Scope (Build First)

### Phase 1: Core Orchestration Engine
1. `ExecutionTrace` model + migration
2. `TaskExecutionWorkflow` + 5 activities
3. `orchestration_worker.py` registered with Temporal
4. Task API endpoints (create, list, detail, trace)
5. Task Execution Console page (frontend)

### Phase 2: Managed OpenClaw Instances
6. `TenantInstance` model + migration
7. `OpenClawProvisionWorkflow` + Helm integration
8. Instance management API endpoints
9. Instance management UI in Integrations Hub
10. NetworkPolicy template for pod isolation

### Phase 3: Skills Gateway + Credentials
11. `SkillConfig` + `SkillCredential` models + migration
12. Skill Router service
13. Credential vault (AES-256 encrypt/decrypt)
14. Skill config API endpoints
15. Skills Config panel UI with credential forms

### Phase 4: LLM Integration + Language
16. Wire `SkillConfig.llm_config_id` into Skill Router
17. Language abstraction (~9 files, string replacements)
18. Update i18n files (en + es)

### Iterate After MVP
- Auto-scaling (scale to 0 when idle, wake on demand)
- Approval workflows (human-in-the-loop via Temporal signals)
- Memory integration into execution pipeline
- Skill proficiency learning loop
- Rate limiting enforcement
- OpenClaw version pinning per tenant
- Skill marketplace (browse/install skills from UI)
- Credential expiration monitoring + notifications
- SSE/WebSocket live updates for Task Console

---

## 13. Execution Flow (Complete)

```
AgentTask: "Send Q4 summary to #finance channel on Slack"
  │
  ▼
TaskExecutionWorkflow (Temporal, queue: agentprovision-orchestration)
  │
  ├─ 1. DISPATCH
  │     TaskDispatcher.find_best_agent(capabilities=["data_analysis", "slack"])
  │     → data_analyst (skill_match: 0.92)
  │     ExecutionTrace: {step: "dispatched", agent: "data_analyst", score: 0.92}
  │
  ├─ 2. MEMORY RECALL
  │     MemoryService.get_relevant_memories(agent_id, context="Q4 revenue")
  │     → 3 memories loaded (Q3 analysis, revenue schema, Slack channel prefs)
  │     ExecutionTrace: {step: "memory_recall", memories_loaded: 3}
  │
  ├─ 3. EXECUTE (ADK)
  │     Generate Q4 summary via ADK supervisor → data_analyst sub-agent
  │     LLM: tenant's configured provider
  │     ExecutionTrace: {step: "executing", backend: "adk", tool: "sql_query", tokens: 450}
  │
  ├─ 4. SKILL CHECK
  │     SkillConfig: slack enabled? ✓ | requires_approval? YES
  │     Task status → "waiting_input"
  │     ExecutionTrace: {step: "approval_requested", skill: "slack", action: "send_message"}
  │
  ├─ 5. HUMAN APPROVAL
  │     Admin approves in Task Console
  │     ExecutionTrace: {step: "approval_granted", approved_by: "admin@company.com"}
  │
  ├─ 6. CREDENTIAL LOAD
  │     SkillCredential: decrypt bot_token for tenant
  │     Scope check: #finance in allowed_channels? ✓
  │     Rate limit: 3/10 used this hour ✓
  │
  ├─ 7. OPENCLAW EXECUTE
  │     Resolve TenantInstance: ws://openclaw-c024fddd:18789
  │     Auth with OPENCLAW_GATEWAY_TOKEN
  │     Send: {skill: "slack", action: "send_message", channel: "#finance", text: "Q4 Summary..."}
  │     Credentials injected at runtime, wiped after use
  │     ExecutionTrace: {step: "skill_call", skill: "slack", action: "send_message", duration_ms: 1200}
  │
  ├─ 8. EVALUATE
  │     confidence: 0.87
  │     Update AgentSkill("slack"): times_used++, success_rate recalculated
  │     Create AgentMemory: "Successfully sent Q4 summary to #finance"
  │     ExecutionTrace: {step: "completed", confidence: 0.87, tokens: 450, cost: 0.003}
  │
  └─ DONE: Task status → "completed"
```

---

## 14. Security Model

| Concern | Approach |
|---|---|
| Tenant isolation (OpenClaw pods) | Separate Helm release per tenant + K8s NetworkPolicy |
| Credential storage | AES-256-GCM encryption at rest, GCP Secret Manager master key |
| Credential exposure | Never in API responses, logs, or OpenClaw pod disk. Injected per-request. |
| Cross-tenant access | `tenant_id` FK on all models + query filtering |
| OpenClaw authentication | Per-instance `OPENCLAW_GATEWAY_TOKEN` for WebSocket auth |
| Skill access control | `SkillConfig.enabled` + `allowed_scopes` + `requires_approval` |
| Rate limiting | `SkillConfig.rate_limit` enforced by Skill Router |
| Audit trail | `ExecutionTrace` records every action with masked credentials |
| Pod network access | NetworkPolicy restricts ingress to `agentprovision-api` pods only |
