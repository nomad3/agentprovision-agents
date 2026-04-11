# Code Worker: Claude Code Integration Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the 5-agent ADK dev team (architect → coder → tester → dev_ops → user_agent) with a single `code_agent` that delegates coding tasks to Claude Code CLI running in an isolated Kubernetes pod, communicating via Temporal workflows.

**Architecture:** A dedicated code worker pod runs Claude Code CLI authenticated via Claude Pro/Max subscription token. The ADK `code_agent` starts a `CodeTaskWorkflow` on a `agentprovision-code` Temporal queue. Claude Code handles the full development cycle autonomously — reads code, implements, tests, commits to a feature branch, and creates a PR. The user reviews and merges.

**Tech Stack:** Claude Code CLI (Node.js), Python 3.11 (Temporal worker), Temporal, Kubernetes, Helm, GitHub Actions.

---

## Architecture Diagram

```
User (chat/WhatsApp)
  → Root Supervisor (ADK)
    → code_agent (ADK leaf agent)
      → starts CodeTaskWorkflow (Temporal, queue: agentprovision-code)
        → code-worker pod picks up task
          → git pull origin main
          → git checkout -b code/task-<short-id>
          → claude -p "<task description>" --output-format json --allowedTools "Edit,Write,Bash,Read,Glob,Grep"
          → git push origin code/task-<short-id>
          → gh pr create --title "..." --body "..."
        → returns {pr_url, summary, branch, files_changed}
      → code_agent reports PR URL + summary to user
```

## Components

### 1. Code Worker Pod (`apps/code-worker/`)

**Dockerfile:**
- Base: `python:3.11-slim`
- Install: Node.js 20 LTS (for Claude Code), git, gh CLI
- Install: `npm install -g @anthropic-ai/claude-code`
- Install: Python deps (temporalio, pydantic)
- Entrypoint: `python -m worker`

**Startup sequence:**
1. `git clone https://<GITHUB_TOKEN>@github.com/nomad3/agentprovision-agents.git /workspace`
2. Start Temporal worker on `agentprovision-code` queue
3. Per-task: fetch tenant's Claude session token via internal API → `claude setup-token` → execute

**Worker code (`apps/code-worker/worker.py`):**
- Temporal worker with one workflow + one activity
- `CodeTaskWorkflow`: receives task description, tenant_id, optional context
- `execute_code_task` activity:
  1. `cd /workspace && git fetch origin && git checkout main && git pull`
  2. `git checkout -b code/task-<uuid[:8]>`
  3. Run Claude Code: `claude -p "<task>" --output-format json --allowedTools "Edit,Write,Bash,Read,Glob,Grep"`
  4. `git push origin code/task-<id>`
  5. `gh pr create --title "<title>" --body "<summary>"`
  6. Return `{pr_url, summary, branch, files_changed, claude_output}`

**Timeouts:**
- Activity timeout: 15 minutes (Claude Code sessions can be long)
- Heartbeat: every 60 seconds
- Retry: 1 retry on failure

### 2. ADK code_agent (replaces 5 agents)

**File:** `apps/adk-server/agentprovision_supervisor/code_agent.py`

Single leaf agent with one tool: `start_code_task(task_description: str) -> dict`

The tool:
1. Calls the API's `/api/v1/code-tasks` endpoint (or starts Temporal workflow directly)
2. Waits for completion (polls or uses Temporal query)
3. Returns the result (PR URL, summary)

**Instructions:** Tell the user what's happening ("I'm starting a dev task for X, Claude Code will implement it and create a PR"). Report back with the PR URL when done.

### 3. Root Supervisor Update

**File:** `apps/adk-server/agentprovision_supervisor/agent.py`

- Remove `code_agent` import, replace with `code_agent`
- Update routing: "code_agent" handles all code/tool/feature requests
- Update `sub_agents` list

### 4. Temporal Integration

**Queue:** `agentprovision-code` (new dedicated queue)

**Workflow:** `CodeTaskWorkflow`
- Input: `CodeTaskInput(task_description: str, tenant_id: str, context: Optional[str])`
- Single activity: `execute_code_task`
- Shows up in Workflows Executions page

**No changes to existing workers** — the code worker is its own separate Temporal worker process.

### 5. Authentication & Secrets

**Per-tenant tokens (from Integrations page):**
- Claude session token → stored encrypted in `integration_credentials` table via credential vault
- Code worker fetches at runtime: `GET /api/v1/oauth/internal/token/claude_code?tenant_id=...`
- Each tenant provides their own Claude Pro/Max subscription token

**GCP Secret Manager (infrastructure only):**
- `agentprovision-github-token` — already exists (for git clone + push + gh CLI)
- `agentprovision-api-internal-key` — already exists (for code worker → API auth)

**ExternalSecrets in Helm values:**
```yaml
externalSecret:
  data:
    - secretKey: GITHUB_TOKEN
      remoteRef:
        key: agentprovision-github-token
    - secretKey: API_INTERNAL_KEY
      remoteRef:
        key: agentprovision-api-internal-key
```

**Token refresh:** Claude subscription tokens last weeks. User pastes a new one in the Integrations page when expired. The card shows connection status (connected/expired).

### 6. Git Flow

1. Claude Code creates branch: `code/task-<uuid[:8]>`
2. Commits with descriptive messages
3. Pushes branch to origin
4. Creates PR via `gh pr create`
5. CI runs on the branch (existing workflows)
6. User reviews and merges to main
7. Deploy triggers on merge (existing CI/CD)

### 7. Helm Values (`helm/values/agentprovision-code-worker.yaml`)

Follows the worker pattern (no HTTP service, no probes):
```yaml
nameOverride: "agentprovision-code-worker"
container:
  command: ["python", "-m", "worker"]
replicaCount: 1
resources:
  requests: {cpu: 200m, memory: 512Mi}
  limits: {cpu: 1000m, memory: 2Gi}  # Claude Code needs more memory
livenessProbe: {enabled: false}
readinessProbe: {enabled: false}
service: {type: ClusterIP, port: 80}
```

No Cloud SQL proxy needed (code worker doesn't access the database).

### 8. GitHub Actions (`code-worker-deploy.yaml`)

Follows the ADK deploy pattern:
- Triggers on push to `apps/code-worker/**`, `helm/values/agentprovision-code-worker.yaml`
- Builds Docker image → pushes to GCR → deploys via Helm
- Image: `gcr.io/ai-agency-479516/agentprovision-code-worker`

### 9. Integrations Page — Claude Code Card

Claude Code appears on the Integrations page as a token-paste integration (like Slack/Notion, not OAuth).

**Backend — `SKILL_CREDENTIAL_SCHEMAS` in `skill_configs.py`:**
```python
"claude_code": {
    "display_name": "Claude Code",
    "description": "Autonomous coding agent — implements features, fixes bugs, creates PRs",
    "icon": "FaTerminal",
    "credentials": [
        {"key": "session_token", "label": "Session Token", "type": "password", "required": True,
         "help": "Run 'claude setup-token' in your terminal, then paste the token here"},
    ],
},
```

**Frontend — `IntegrationsPanel.js`:**
- Add `FaTerminal` to `ICON_MAP`
- Add `claude_code: '#D97706'` to `SKILL_COLORS` (amber, matches Claude branding)
- The existing credential form rendering handles the rest — user clicks the card, expands, pastes token, saves

**Token flow:**
1. User runs `claude setup-token` locally (or copies from browser session)
2. Pastes the session token in the Integrations page Claude Code card
3. Token is encrypted via `credential_vault.store_credential()` and stored in `integration_credentials` table
4. Code worker activity fetches the token at runtime via internal API: `GET /api/v1/oauth/internal/token/claude_code?tenant_id=...`
5. Code worker runs `claude setup-token` with the fetched token before each task

**Multi-tenant:** Each tenant provides their own Claude subscription token. The code worker fetches the correct token per `tenant_id` at task execution time, not at pod startup.

**This changes the authentication model:**
- ~~GCP Secret Manager for `CLAUDE_SESSION_TOKEN`~~ — no longer needed
- Token comes from the integration_credentials table via the internal API
- Code worker only needs `API_INTERNAL_KEY` to call the token endpoint
- Helm values simplified: no `agentprovision-claude-session-token` external secret

## Prerequisite: Consolidate skill_config → integration_config

The codebase has a partial rename from the old `skill_config`/`skill_credential` naming to `integration_config`/`integration_credential`. Both models exist, causing duplication and confusion. Consolidate fully before building the Claude Code integration.

**Remove (old naming):**
- `apps/api/app/models/skill_config.py` → use `integration_config.py` only
- `apps/api/app/models/skill_credential.py` → use `integration_credential.py` only
- `apps/api/app/api/v1/skill_configs.py` → merge registry + endpoints into `integration_configs.py`
- `apps/api/app/services/skill_configs.py` → merge into integration service
- `apps/web/src/components/SkillsConfigPanel.js` → already replaced by `IntegrationsPanel.js`
- `apps/web/src/services/skillConfigService.js` → already replaced by `integrationConfigService.js`

**Update all imports:**
- `credential_vault.py` — imports `SkillCredential` → `IntegrationCredential`
- `oauth.py` — imports `SkillConfig`, `SkillCredential` → integration equivalents
- `SKILL_CREDENTIAL_SCHEMAS` constant → rename to `INTEGRATION_REGISTRY` and move into `integration_configs.py`
- All route registrations in `routes.py`

**Keep DB table names as-is** — migration 040 already renamed the tables to `integration_configs` and `integration_credentials`. No new migration needed.

## What Gets Removed

- `apps/api/app/models/skill_config.py` (replaced by `integration_config.py`)
- `apps/api/app/models/skill_credential.py` (replaced by `integration_credential.py`)
- `apps/api/app/api/v1/skill_configs.py` (merged into `integration_configs.py`)
- `apps/api/app/services/skill_configs.py` (merged into integration service)
- `apps/web/src/components/SkillsConfigPanel.js` (replaced by `IntegrationsPanel.js`)
- `apps/web/src/services/skillConfigService.js` (replaced by `integrationConfigService.js`)
- `apps/adk-server/agentprovision_supervisor/architect.py`
- `apps/adk-server/agentprovision_supervisor/coder.py`
- `apps/adk-server/agentprovision_supervisor/tester.py`
- `apps/adk-server/agentprovision_supervisor/dev_ops.py`
- `apps/adk-server/agentprovision_supervisor/user_agent.py`
- `apps/adk-server/agentprovision_supervisor/code_agent.py`
- Imports/references from `__init__.py` and `agent.py`

## What Stays

- `tools/shell_tools.py` — still used by other agents (Luna, etc.)
- `tools/shell_tools.deploy_changes()` — could be useful for hotfixes
- All other teams unchanged

## Security Boundaries

| Component | Has Access To | Does NOT Have Access To |
|-----------|---------------|------------------------|
| Code worker | Git repo, GitHub token, API internal key (to fetch Claude token per-task) | DB, encryption keys, OAuth tokens, customer data |
| ADK service | DB (read), all agent tools | Git push (removed with dev_ops) |
| Orchestration worker | DB, encryption keys, Gmail/Calendar tokens | Git repo, Claude Code |

## File Structure

```
apps/code-worker/
├── Dockerfile
├── requirements.txt        # temporalio, pydantic
├── worker.py               # Temporal worker + activities
├── workflows.py            # CodeTaskWorkflow definition
└── entrypoint.sh           # git clone + claude setup-token + start worker
```

## Verification

1. Deploy code worker pod, verify it starts and connects to Temporal
2. Send a dev task via WhatsApp/chat: "Add a health check endpoint to the MCP server"
3. Verify Claude Code runs, creates branch, opens PR
4. Check PR in GitHub — should have proper commits, tests
5. Check Workflows page — CodeTaskWorkflow should appear with status
6. Merge PR — verify CI/CD deploys normally
