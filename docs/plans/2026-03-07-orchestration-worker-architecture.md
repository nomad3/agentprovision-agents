# Orchestration Worker Architecture

**Date**: 2026-03-07
**Status**: Deployed (prod)

## What It Is

The orchestration worker (`servicetsunami-orchestration-worker`) is a Temporal worker pod that processes workflows from the `servicetsunami-orchestration` task queue. It shares the same API codebase (`servicetsunami-api` Docker image) but runs a different entrypoint: `python -m app.workers.orchestration_worker`.

## Why It Exists

Previously, all Temporal workflows ran on a single worker (`servicetsunami-worker`) using the `servicetsunami-databricks` queue. When we added the Inbox Monitor and other orchestration workflows that need access to Google OAuth tokens, the Anthropic API, and encrypted credentials, we needed a dedicated worker with the right secrets and permissions.

**Key difference**: The databricks worker handles data pipeline workflows (dataset sync, knowledge extraction). The orchestration worker handles real-time business workflows that interact with external services (Gmail, Calendar, WhatsApp).

## Workflows It Runs

| Workflow | Description |
|----------|-------------|
| `TaskExecutionWorkflow` | End-to-end agent task execution with memory recall + entity extraction |
| `ChannelHealthMonitorWorkflow` | Long-running monitor for WhatsApp connection health |
| `FollowUpWorkflow` | Delayed follow-up actions (WhatsApp, pipeline stage, reminders) |
| `InboxMonitorWorkflow` | Proactive Gmail + Calendar monitoring with LLM triage |
| `AutoActionWorkflow` | Memory-triggered automated actions via ADK agents |

## Helm Configuration

**File**: `helm/values/servicetsunami-orchestration-worker.yaml`

Key configuration:
- **Image**: Same as API (`gcr.io/ai-agency-479516/servicetsunami-api`)
- **Command**: `python -m app.workers.orchestration_worker`
- **Replicas**: 1
- **Probes**: Disabled (worker doesn't serve HTTP)
- **Cloud SQL Proxy**: Sidecar for database access
- **Service Account**: `dev-backend-app@` GSA via Workload Identity

### Required Secrets (ExternalSecret)
- `DATABASE_URL` — PostgreSQL connection
- `MCP_API_KEY` — MCP server auth
- `API_INTERNAL_KEY` — Internal API auth
- `ENCRYPTION_KEY` — Credential vault (Fernet)
- `ANTHROPIC_API_KEY` — LLM for triage/extraction
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — OAuth token refresh

### ConfigMap
- `TEMPORAL_NAMESPACE`: "default"
- `LLM_MODEL`: "claude-3-haiku-20240307" (for triage)
- `HCA_API_URL`: Marketing backend URL
- `HCA_SERVICE_KEY`: Marketing backend auth

## Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│  Temporal Server (:7233)                         │
│  ┌──────────────────────┐  ┌──────────────────┐ │
│  │ servicetsunami-       │  │ servicetsunami-  │ │
│  │ orchestration queue   │  │ databricks queue  │ │
│  └──────────┬───────────┘  └────────┬─────────┘ │
└─────────────┼──────────────────────┼────────────┘
              │                      │
   ┌──────────▼──────────┐  ┌───────▼──────────┐
   │ orchestration-worker │  │ databricks-worker │
   │                      │  │                   │
   │ • TaskExecution      │  │ • DatasetSync     │
   │ • ChannelHealth      │  │ • KnowledgeExtr.  │
   │ • FollowUp           │  │ • AgentKitExec.   │
   │ • InboxMonitor       │  │ • DataSourceSync  │
   │ • AutoAction         │  │                   │
   │                      │  │                   │
   │ Needs: Gmail, Cal,   │  │ Needs: MCP,       │
   │ Anthropic, Encrypt.  │  │ Databricks        │
   └──────────────────────┘  └───────────────────┘
```

## Entrypoint

**File**: `apps/api/app/workers/orchestration_worker.py`

Registers all workflow classes and their activity functions, then starts polling the `servicetsunami-orchestration` task queue.

## Monitoring

```bash
# Check pod status
kubectl get pods -n prod | grep orchestration

# View logs
kubectl logs -n prod -l app=servicetsunami-orchestration-worker -c microservice --tail=100

# Check Temporal workflows
# Visit temporal-web at https://temporal.servicetsunami.com
```
