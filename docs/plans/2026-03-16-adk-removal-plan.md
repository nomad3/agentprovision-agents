# ADK Removal Plan

> Remove the Google ADK server from AgentProvision. All agent execution now runs via CLI orchestration (Claude Code CLI → MCP tools). ADK is fully redundant.

**Date:** 2026-03-16
**Status:** Ready to execute
**Prerequisite:** CLI orchestration verified end-to-end with 77 MCP tools

---

## Current State

- **CLI orchestrator**: Working. Luna on Claude Code CLI via Temporal → code-worker
- **MCP tools server**: 77 tools (knowledge, email, calendar, jira, github, data, ads, competitor, monitor, sales, reports, connectors, shell, analytics, skills)
- **ADK server**: Still running but unused when `cli_orchestrator_enabled = true`
- **Feature flag**: `cli_orchestrator_enabled` per tenant (default false)

## What Gets Removed

```
apps/adk-server/                          # ENTIRE directory
├── agentprovision_supervisor/            # 25 agent Python files
│   ├── agent.py                         # Root supervisor
│   ├── personal_assistant.py            # Luna (replaced by skill.md)
│   ├── code_agent.py                    # Replaced by native Claude Code
│   └── ... (22 more agent files)
├── tools/                               # 21 tool files (replaced by MCP)
├── config/
│   ├── model_callback.py               # LiteLLM callback (not needed)
│   └── settings.py
├── memory/
│   └── vertex_vector.py                # Replaced by MCP knowledge tools
├── server.py                           # ADK FastAPI server
├── Dockerfile
└── requirements.txt
```

Also remove from:
- `docker-compose.yml`: `adk-server` service
- `helm/values/adk.yaml`: Helm chart values
- `.github/workflows/adk-deploy.yaml`: CI/CD workflow
- `apps/api/app/services/adk_client.py`: ADK HTTP client
- `apps/api/app/services/chat.py`: ADK fallback path (the else branch)

## What Stays

- `apps/api/` — FastAPI backend (chat service, auth, models, RL, etc.)
- `apps/code-worker/` — Claude Code CLI execution via Temporal
- `apps/mcp-server/` — MCP tools server (77 tools)
- `apps/web/` — React frontend
- `apps/api/app/skills/` — Skill marketplace (agents are skills now)
- Everything in PostgreSQL (knowledge graph, RL, credentials, sessions)

## Execution Steps

### Step 1: Enable CLI orchestrator for ALL tenants (default true)

```sql
ALTER TABLE tenant_features ALTER COLUMN cli_orchestrator_enabled SET DEFAULT TRUE;
UPDATE tenant_features SET cli_orchestrator_enabled = TRUE;
```

Update model: `cli_orchestrator_enabled = Column(Boolean, default=True)`

### Step 2: Remove ADK fallback from chat.py

In `apps/api/app/services/chat.py`, remove the entire ADK path:
- Delete the `# --- Existing ADK path ---` section
- Delete `from app.services.adk_client import ...`
- Delete the ADK client construction, session management, context overflow guards
- The CLI path becomes the ONLY path

### Step 3: Remove ADK client

Delete `apps/api/app/services/adk_client.py`

### Step 4: Remove ADK from docker-compose

Remove the `adk-server` service from `docker-compose.yml`

### Step 5: Remove ADK from Helm

Remove `helm/values/adk.yaml` or disable the deployment

### Step 6: Remove ADK CI/CD

Remove or disable `.github/workflows/adk-deploy.yaml`

### Step 7: Archive ADK server code

```bash
# Move to archive (don't delete history)
git rm -r apps/adk-server/
git commit -m "chore: remove ADK server — replaced by CLI orchestration + MCP tools"
```

### Step 8: Clean up imports and references

Search for any remaining references to ADK:
```bash
grep -r "adk" apps/api/ --include="*.py" -l
grep -r "ADK" apps/api/ --include="*.py" -l
grep -r "adk-server" . --include="*.yaml" --include="*.yml" -l
```

Fix or remove any found references.

### Step 9: Update documentation

- CLAUDE.md: Remove ADK sections, update architecture
- README.md: Already updated for CLI orchestration
- Design docs: Mark ADK-related docs as historical

### Step 10: Production deployment

1. Deploy CLI orchestrator + MCP tools to GKE
2. Enable `cli_orchestrator_enabled = true` for all tenants
3. Monitor for errors (Temporal workflows, MCP tool failures)
4. Scale down ADK pods to 0
5. Wait 1 week for validation
6. Remove ADK deployment entirely

## Rollback

If issues arise after removal:
1. Re-enable ADK deployment (Helm rollback)
2. Set `cli_orchestrator_enabled = false` for affected tenants
3. Chat service falls through to... nothing (ADK code deleted)

**Better rollback**: Keep ADK code in a `legacy/adk-server` branch for 30 days. If needed, cherry-pick it back.

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| MCP tool has a bug ADK didn't | All 77 tools tested. MCP tools use same internal APIs. |
| CLI timeout on heavy tasks | Extended to 30 min. Temporal retries. |
| Session persistence issues | Auto-retry without --resume on failure. |
| Token refresh failures | Fixed: propagate refresh_token to all sibling configs. |
| Image support | Saved to session dir + Read tool. Works. |

## Timeline

- **Day 1**: Steps 1-4 (enable CLI, remove ADK from docker-compose)
- **Day 2**: Steps 5-6 (Helm, CI/CD)
- **Day 3**: Step 7 (archive code)
- **Day 4-5**: Steps 8-9 (cleanup, docs)
- **Week 2**: Step 10 (production deployment)
