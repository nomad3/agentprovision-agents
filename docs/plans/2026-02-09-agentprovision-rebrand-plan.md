# AgentProvision Rebrand Plan

## Context
Rebrand the entire AgentProvision monorepo to **AgentProvision** (agentprovision.com). The product is pivoting to "The AI-powered operating system for roll-ups" targeting: ERP/finance, hyper-local AI ads, M&A pipeline, HR/compliance, banking/spend, insurance/RCM, private credit, exit/liquidity hub. DNS for agentprovision.com already points to the same public IP as agentprovision.com.

## Approach
Full find-replace across all code, infra, and config. Rewrite marketing copy for roll-up positioning. Skip logo/favicon assets (user will replace later).

## Replacement Map
| Old | New |
|-----|-----|
| `AgentProvision` | `AgentProvision` |
| `agentprovision` | `agentprovision` |
| `AGENTPROVISION` | `AGENTPROVISION` |
| `agentprovision.com` | `agentprovision.com` |
| `demo@agentprovision.ai` | `demo@agentprovision.com` |
| `devops@agentprovision.com` | `devops@agentprovision.com` |
| `agentprovision_supervisor` (dir) | `agentprovision_supervisor` |
| `AgentProvisionAPI` (class) | `AgentProvisionAPI` |
| `hide_agentprovision_branding` | `hide_agentprovision_branding` |
| `agentprovision.lang` | `agentprovision.lang` |

## Execution Steps

### Step 1: Rename files and directories (git mv)
- `apps/adk-server/agentprovision_supervisor/` → `agentprovision_supervisor/`
- `helm/values/agentprovision-api.yaml` → `agentprovision-api.yaml`
- `helm/values/agentprovision-web.yaml` → `agentprovision-web.yaml`
- `helm/values/agentprovision-worker.yaml` → `agentprovision-worker.yaml`
- `helm/values/agentprovision-adk.yaml` → `agentprovision-adk.yaml`
- `.github/workflows/agentprovision-api.yaml` → `agentprovision-api.yaml`
- `.github/workflows/agentprovision-web.yaml` → `agentprovision-web.yaml`
- `.github/workflows/agentprovision-worker.yaml` → `agentprovision-worker.yaml`
- `agentprovision.code-workspace` → `agentprovision.code-workspace`

### Step 2: Batch find-replace across all source files
Run parallel agents to update all 140+ files, grouped by area:
- **Agent A**: Backend Python (`apps/api/`, `apps/adk-server/`, `apps/mcp-server/`)
- **Agent B**: Frontend (`apps/web/`), root configs, scripts, docker-compose, env files
- **Agent C**: Infrastructure (`helm/`, `kubernetes/`, `.github/workflows/`, `infra/terraform/`)
- **Agent D**: Documentation (`CLAUDE.md`, `README.md`, `docs/`, other *.md files)

### Step 3: Rewrite marketing copy
- `apps/web/src/i18n/locales/en/landing.json` — full rewrite for roll-up positioning
- `apps/web/src/i18n/locales/en/common.json` — brand name, copyright
- `apps/web/src/i18n/locales/es/common.json` — brand name, copyright
- `apps/web/src/i18n/locales/es/landing.json` — translate new roll-up copy
- `apps/web/public/index.html` — page title
- `apps/web/public/manifest.json` — app name

### Step 4: Update Kubernetes managed certificate for new domain
- `kubernetes/gateway/managed-certificate.yaml` — add agentprovision.com domains
- `kubernetes/ingress.yaml` — update hosts to agentprovision.com

### Step 5: Verification
- `grep -rI "agentprovision" . --exclude-dir={.git,node_modules,__pycache__}` should return 0 results
- `helm template` each service chart to verify rendering
- Review critical files: ingress, managed-cert, workflow triggers, ADK imports, MCP endpoints

## Critical Files (most impactful)
- `apps/adk-server/agentprovision_supervisor/agent.py` — ADK supervisor definition
- `apps/mcp-server/src/server.py` — MCP endpoints with `/agentprovision/v1/` prefix
- `kubernetes/ingress.yaml` — production traffic routing (14 references)
- `helm/values/agentprovision-api.yaml` — primary Helm values pattern
- `.github/workflows/agentprovision-api.yaml` — CI/CD image builds and deploys
- `apps/web/src/i18n/locales/en/landing.json` — marketing copy rewrite

## GCP Resources (user handles separately)
After code changes, user needs to:
- Create new GCP secrets with `agentprovision-*` prefix (copy values from `agentprovision-*`)
- Create `agentprovision-worker` service account
- Rename database: `ALTER DATABASE agentprovision RENAME TO agentprovision;`
- Build and push new container images via updated workflows
