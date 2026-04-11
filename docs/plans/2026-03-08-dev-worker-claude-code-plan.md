# Code Worker: Claude Code Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the 5-agent ADK dev team with a single `code_agent` that delegates to Claude Code CLI via Temporal workflows in a dedicated K8s pod, and add Claude Code as a token-paste integration on the Integrations page.

**Architecture:** Dedicated code-worker pod runs Claude Code CLI, authenticated per-tenant via session tokens stored in the Integrations page. The ADK `code_agent` starts a `CodeTaskWorkflow` on Temporal. Claude Code handles the full dev cycle autonomously — reads code, implements, tests, commits, creates a PR.

**Tech Stack:** Claude Code CLI (Node.js), Python 3.11 (Temporal worker), Temporal, Kubernetes, Helm, GitHub Actions.

---

## Task 1: Remove old skill_config/skill_credential code — Update credential_vault

The `credential_vault.py` imports `SkillCredential` but should use `IntegrationCredential`. The vault creates rows in `skill_credentials` table, but integration endpoints query `integration_credentials` table — a mismatch.

**Files:**
- Modify: `apps/api/app/services/orchestration/credential_vault.py`

**Step 1: Update credential_vault imports and model usage**

Change the import from `SkillCredential` to `IntegrationCredential`, and update all references:

In `apps/api/app/services/orchestration/credential_vault.py`:
- Line 18: `from app.models.skill_credential import SkillCredential` → `from app.models.integration_credential import IntegrationCredential`
- Line 74: `credential = SkillCredential(` → `credential = IntegrationCredential(`
- Line 77: `skill_config_id=skill_config_id,` → `integration_config_id=skill_config_id,`
- Lines 113-120: `db.query(SkillCredential).filter(SkillCredential.id == ...)` → `db.query(IntegrationCredential).filter(IntegrationCredential.id == ...)`
- Lines 165-173: Same query replacement for `retrieve_credentials_for_skill`
  - `SkillCredential.skill_config_id` → `IntegrationCredential.integration_config_id`
- Lines 218-225: Same replacement for `revoke_credential`

Also rename parameter `skill_config_id` → `integration_config_id` in function signatures for `store_credential` and `retrieve_credentials_for_skill`.

**Step 2: Verify no other files break**

Run: `grep -r "from app.services.orchestration.credential_vault import" apps/api/`

Update callers that pass `skill_config_id=` to pass `integration_config_id=` (both `skill_configs.py` and `integration_configs.py` endpoints call `store_credential`).

**Step 3: Commit**

```bash
git add apps/api/app/services/orchestration/credential_vault.py
git commit -m "refactor: migrate credential_vault from SkillCredential to IntegrationCredential"
```

---

## Task 2: Remove old skill_config/skill_credential code — Update oauth.py

`oauth.py` uses `SkillConfig` and `SkillCredential` for OAuth token storage. Switch to `IntegrationConfig` and `IntegrationCredential`.

**Files:**
- Modify: `apps/api/app/api/v1/oauth.py`

**Step 1: Update imports**

In `apps/api/app/api/v1/oauth.py`:
- Line 28: `from app.models.skill_config import SkillConfig` → `from app.models.integration_config import IntegrationConfig`
- Line 29: `from app.models.skill_credential import SkillCredential` → `from app.models.integration_credential import IntegrationCredential`

**Step 2: Replace all model references**

Throughout the file, replace:
- `SkillConfig` → `IntegrationConfig` (all occurrences — queries at lines 384-402, 527-538, 586-593, 657-664)
- `SkillCredential` → `IntegrationCredential` (all occurrences — queries at lines 170-179, 431-440, 542-550, 600-609)
- `SkillCredential.skill_config_id` → `IntegrationCredential.integration_config_id`
- `SkillConfig.account_email` → `IntegrationConfig.account_email` (etc.)

Update `store_credential` calls to use `integration_config_id=` parameter name.

**Step 3: Commit**

```bash
git add apps/api/app/api/v1/oauth.py
git commit -m "refactor: migrate oauth.py from SkillConfig/SkillCredential to IntegrationConfig/IntegrationCredential"
```

---

## Task 3: Remove old skill_config/skill_credential code — Delete old files

Remove the old models, service, route, and schema that are now fully replaced by the integration equivalents.

**Files:**
- Delete: `apps/api/app/models/skill_config.py`
- Delete: `apps/api/app/models/skill_credential.py`
- Delete: `apps/api/app/services/skill_configs.py`
- Delete: `apps/api/app/api/v1/skill_configs.py`
- Delete: `apps/api/app/schemas/skill_config.py`
- Modify: `apps/api/app/models/__init__.py`
- Modify: `apps/api/app/schemas/__init__.py`
- Modify: `apps/api/app/api/v1/routes.py`

**Step 1: Update models/__init__.py**

Remove lines:
```python
from .skill_config import SkillConfig
from .skill_credential import SkillCredential
```
Remove from `__all__`: `"SkillConfig", "SkillCredential"`

**Step 2: Update schemas/__init__.py**

Remove line:
```python
from . import skill_config
```
Remove from `__all__`: `"skill_config"`

**Step 3: Update routes.py**

Remove import: `skill_configs,`
Remove line: `router.include_router(skill_configs.router, prefix="/skill-configs", tags=["skill-configs"])`

**Step 4: Delete old files**

```bash
rm apps/api/app/models/skill_config.py
rm apps/api/app/models/skill_credential.py
rm apps/api/app/services/skill_configs.py
rm apps/api/app/api/v1/skill_configs.py
rm apps/api/app/schemas/skill_config.py
```

**Step 5: Verify no dangling imports**

Run: `grep -r "skill_config\|SkillConfig\|skill_credential\|SkillCredential" apps/api/app/ --include="*.py" | grep -v __pycache__ | grep -v ".pyc"`

Fix any remaining references.

**Step 6: Commit**

```bash
git add -A apps/api/app/models/skill_config.py apps/api/app/models/skill_credential.py \
  apps/api/app/services/skill_configs.py apps/api/app/api/v1/skill_configs.py \
  apps/api/app/schemas/skill_config.py apps/api/app/models/__init__.py \
  apps/api/app/schemas/__init__.py apps/api/app/api/v1/routes.py
git commit -m "refactor: remove old skill_config/skill_credential code, fully replaced by integration_config"
```

---

## Task 4: Add Claude Code to integration registry + frontend

Add Claude Code as a token-paste integration card on the Integrations page.

**Files:**
- Modify: `apps/api/app/api/v1/integration_configs.py`
- Modify: `apps/web/src/components/IntegrationsPanel.js`

**Step 1: Add Claude Code entry to INTEGRATION_CREDENTIAL_SCHEMAS**

In `apps/api/app/api/v1/integration_configs.py`, add to `INTEGRATION_CREDENTIAL_SCHEMAS` dict after the `"linear"` entry:

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

**Step 2: Update frontend IntegrationsPanel.js**

In `apps/web/src/components/IntegrationsPanel.js`:

Add `FaTerminal` to the react-icons import (line 36 area):
```javascript
import { ..., FaTerminal } from 'react-icons/fa';
```

Add to `ICON_MAP` (line 44 area):
```javascript
  FaTerminal: FaTerminal,
```

Add to `SKILL_COLORS` (line 57 area):
```javascript
  claude_code: '#D97706',
```

**Step 3: Commit**

```bash
git add apps/api/app/api/v1/integration_configs.py apps/web/src/components/IntegrationsPanel.js
git commit -m "feat: add Claude Code integration card to Integrations page"
```

---

## Task 5: Create code-worker — Python Temporal worker

Create the code-worker application that runs as a Temporal worker, picks up dev tasks, and executes Claude Code CLI.

**Files:**
- Create: `apps/code-worker/worker.py`
- Create: `apps/code-worker/workflows.py`
- Create: `apps/code-worker/requirements.txt`

**Step 1: Create requirements.txt**

`apps/code-worker/requirements.txt`:
```
temporalio>=1.4.0
pydantic>=2.0.0
httpx>=0.25.0
```

**Step 2: Create workflows.py**

`apps/code-worker/workflows.py`:
```python
"""Temporal workflow and activities for Claude Code dev tasks."""

import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import httpx
from temporalio import activity, workflow

logger = logging.getLogger(__name__)

WORKSPACE = "/workspace"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_INTERNAL_KEY = os.environ.get("API_INTERNAL_KEY", "")
API_BASE_URL = os.environ.get("API_BASE_URL", "http://agentprovision-api:8000")


@dataclass
class CodeTaskInput:
    task_description: str
    tenant_id: str
    context: Optional[str] = None


@dataclass
class CodeTaskResult:
    pr_url: str
    summary: str
    branch: str
    files_changed: list[str]
    claude_output: str
    success: bool
    error: Optional[str] = None


def _run(cmd: str, cwd: str = WORKSPACE, timeout: int = 600) -> str:
    """Run a shell command and return stdout. Raises on failure."""
    logger.info("Running: %s", cmd)
    result = subprocess.run(
        cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        logger.error("Command failed: %s\nstderr: %s", cmd, result.stderr)
        raise RuntimeError(f"Command failed: {cmd}\n{result.stderr}")
    return result.stdout.strip()


def _fetch_claude_token(tenant_id: str) -> str:
    """Fetch the Claude Code session token from the API's internal endpoint."""
    url = f"{API_BASE_URL}/api/v1/oauth/internal/token/claude_code"
    headers = {"X-Internal-Key": API_INTERNAL_KEY}
    params = {"tenant_id": tenant_id}

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    token = data.get("session_token")
    if not token:
        raise RuntimeError(f"No session_token in response: {data}")
    return token


@activity.defn
async def execute_code_task(task_input: CodeTaskInput) -> CodeTaskResult:
    """Execute a dev task using Claude Code CLI."""
    branch_id = uuid.uuid4().hex[:8]
    branch_name = f"code/task-{branch_id}"

    try:
        # 1. Fetch tenant's Claude Code session token
        activity.heartbeat("Fetching Claude token...")
        token = _fetch_claude_token(task_input.tenant_id)

        # 2. Set up Claude authentication
        activity.heartbeat("Setting up Claude authentication...")
        _run(f'echo "{token}" | claude setup-token', timeout=30)

        # 3. Pull latest code
        activity.heartbeat("Pulling latest code...")
        _run("git fetch origin && git checkout main && git pull origin main")

        # 4. Create feature branch
        activity.heartbeat("Creating feature branch...")
        _run(f"git checkout -b {branch_name}")

        # 5. Build the prompt
        prompt = task_input.task_description
        if task_input.context:
            prompt = f"{task_input.context}\n\n{prompt}"

        # 6. Run Claude Code
        activity.heartbeat("Running Claude Code...")
        claude_cmd = (
            f'claude -p "{prompt}" '
            f'--output-format json '
            f'--allowedTools "Edit,Write,Bash,Read,Glob,Grep"'
        )
        claude_output = _run(claude_cmd, timeout=600)

        # Parse Claude output
        try:
            claude_data = json.loads(claude_output)
        except json.JSONDecodeError:
            claude_data = {"raw": claude_output}

        # 7. Check if there are any changes to commit
        status = _run("git status --porcelain")
        if not status:
            return CodeTaskResult(
                pr_url="",
                summary="No changes were made by Claude Code.",
                branch=branch_name,
                files_changed=[],
                claude_output=claude_output[:5000],
                success=True,
            )

        # 8. Stage and push
        activity.heartbeat("Pushing changes...")
        _run("git add -A")
        _run(f'git push origin {branch_name}')

        # 9. Get changed files
        files_changed = _run("git diff --name-only main").split("\n")
        files_changed = [f for f in files_changed if f]

        # 10. Create PR
        activity.heartbeat("Creating PR...")
        pr_title = task_input.task_description[:70]
        pr_body = f"## Summary\\n\\nAutonomously implemented by Claude Code.\\n\\n## Task\\n\\n{task_input.task_description}\\n\\n---\\n\\nFiles changed: {len(files_changed)}"
        pr_output = _run(
            f'gh pr create --title "{pr_title}" --body "{pr_body}" --head {branch_name} --base main'
        )

        # Extract PR URL from gh output
        pr_url = pr_output.strip().split("\n")[-1]

        summary = claude_data.get("result", claude_output[:2000]) if isinstance(claude_data, dict) else claude_output[:2000]

        return CodeTaskResult(
            pr_url=pr_url,
            summary=str(summary)[:2000],
            branch=branch_name,
            files_changed=files_changed,
            claude_output=claude_output[:5000],
            success=True,
        )

    except Exception as e:
        logger.exception("Dev task failed: %s", e)
        # Clean up: switch back to main
        try:
            _run("git checkout main", timeout=10)
        except Exception:
            pass

        return CodeTaskResult(
            pr_url="",
            summary="",
            branch=branch_name,
            files_changed=[],
            claude_output="",
            success=False,
            error=str(e),
        )


@workflow.defn
class CodeTaskWorkflow:
    """Temporal workflow for executing a dev task via Claude Code CLI."""

    @workflow.run
    async def run(self, task_input: CodeTaskInput) -> CodeTaskResult:
        return await workflow.execute_activity(
            execute_code_task,
            task_input,
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(seconds=120),
        )
```

**Step 3: Create worker.py**

`apps/code-worker/worker.py`:
```python
"""Temporal worker for dev tasks — runs Claude Code CLI."""

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from workflows import CodeTaskWorkflow, execute_code_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233")
TASK_QUEUE = "agentprovision-code"


async def main():
    logger.info("Connecting to Temporal at %s", TEMPORAL_ADDRESS)
    client = await Client.connect(TEMPORAL_ADDRESS)

    logger.info("Starting code worker on queue '%s'", TASK_QUEUE)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CodeTaskWorkflow],
        activities=[execute_code_task],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 4: Commit**

```bash
git add apps/code-worker/
git commit -m "feat: create code-worker Temporal worker with Claude Code CLI integration"
```

---

## Task 6: Create code-worker — Dockerfile and entrypoint

**Files:**
- Create: `apps/code-worker/Dockerfile`
- Create: `apps/code-worker/entrypoint.sh`

**Step 1: Create Dockerfile**

`apps/code-worker/Dockerfile`:
```dockerfile
FROM python:3.11-slim

# Install system deps: git, gh CLI, Node.js 20 LTS
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl gnupg ca-certificates && \
    # Node.js 20
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    # GitHub CLI
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
        gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y gh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Python deps
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user
RUN useradd -m -u 1000 devworker && \
    mkdir -p /workspace && chown devworker:devworker /workspace && \
    mkdir -p /home/devworker/.config && chown -R devworker:devworker /home/devworker
USER devworker

ENTRYPOINT ["/app/entrypoint.sh"]
```

**Step 2: Create entrypoint.sh**

`apps/code-worker/entrypoint.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

echo "[code-worker] Cloning repository..."
if [ ! -d /workspace/.git ]; then
    git clone "https://${GITHUB_TOKEN}@github.com/nomad3/agentprovision-agents.git" /workspace
else
    cd /workspace && git fetch origin && git checkout main && git pull origin main
fi

# Configure git identity for commits
cd /workspace
git config user.email "code-worker@agentprovision.com"
git config user.name "AgentProvision Code Worker"

# Configure gh CLI
echo "${GITHUB_TOKEN}" | gh auth login --with-token 2>/dev/null || true

echo "[code-worker] Starting Temporal worker..."
exec python -m worker
```

**Step 3: Make entrypoint executable**

```bash
chmod +x apps/code-worker/entrypoint.sh
```

**Step 4: Commit**

```bash
git add apps/code-worker/Dockerfile apps/code-worker/entrypoint.sh
git commit -m "feat: add Dockerfile and entrypoint for code-worker"
```

---

## Task 7: Create Helm values for code-worker

**Files:**
- Create: `helm/values/agentprovision-code-worker.yaml`

**Step 1: Create Helm values file**

`helm/values/agentprovision-code-worker.yaml`:
```yaml
# AgentProvision Code Worker - Claude Code CLI Temporal Worker
nameOverride: "agentprovision-code-worker"
fullnameOverride: "agentprovision-code-worker"

image:
  repository: gcr.io/ai-agency-479516/agentprovision-code-worker
  tag: latest
  pullPolicy: IfNotPresent

replicaCount: 1

container:
  port: 8000
  command:
    - /app/entrypoint.sh

# Service account with Workload Identity
serviceAccount:
  create: true
  annotations:
    iam.gke.io/gcp-service-account: dev-backend-app@ai-agency-479516.iam.gserviceaccount.com

# Pod security — relaxed for git + Claude Code CLI
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000

securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL

# Resources — Claude Code needs more memory than typical workers
resources:
  requests:
    cpu: 200m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 2Gi

# Disable HTTP probes — worker doesn't serve HTTP
livenessProbe:
  enabled: false

readinessProbe:
  enabled: false

# Service not needed for worker
service:
  type: ClusterIP
  port: 80
  targetPort: 8000

# ConfigMap with non-sensitive configuration
configMap:
  enabled: true
  data:
    TEMPORAL_NAMESPACE: "default"
    API_BASE_URL: "http://agentprovision-api:8000"

# External Secrets — GitHub token + API internal key only (no DB access)
externalSecret:
  enabled: true
  refreshInterval: 1m
  secretStoreRef:
    name: gcpsm-secret-store
    kind: SecretStore
  target:
    name: agentprovision-code-worker-secret
    creationPolicy: Owner
  data:
    - secretKey: GITHUB_TOKEN
      remoteRef:
        key: agentprovision-github-token
    - secretKey: API_INTERNAL_KEY
      remoteRef:
        key: agentprovision-api-internal-key

# Additional environment variables
env:
  - name: TEMPORAL_ADDRESS
    value: "temporal:7233"

# No autoscaling — single instance
autoscaling:
  enabled: false

# Writable dirs for git + Claude Code
tmpDirs:
  - /tmp
  - /workspace
  - /home/devworker

# Init container to wait for Temporal
initContainers:
  - name: wait-for-temporal
    image: busybox:1.36
    command: ['sh', '-c', 'echo "Waiting for Temporal..."; sleep 15']
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop:
          - ALL

# No Cloud SQL proxy — code worker doesn't access the database
# No HTTPRoute — internal service only
httpRoute:
  enabled: false
```

**Step 2: Commit**

```bash
git add helm/values/agentprovision-code-worker.yaml
git commit -m "feat: add Helm values for code-worker deployment"
```

---

## Task 8: Create GitHub Actions workflow for code-worker deploy

**Files:**
- Create: `.github/workflows/code-worker-deploy.yaml`

**Step 1: Create the workflow**

`.github/workflows/code-worker-deploy.yaml`:
```yaml
name: Code Worker Deploy

on:
  push:
    branches:
      - main
    paths:
      - 'apps/code-worker/**'
      - 'helm/values/agentprovision-code-worker.yaml'
      - '.github/workflows/code-worker-deploy.yaml'
  workflow_dispatch:

env:
  GCP_PROJECT: ${{ vars.GCP_PROJECT }}
  GKE_CLUSTER: ${{ vars.GKE_CLUSTER }}
  GKE_ZONE: ${{ vars.GKE_ZONE }}
  IMAGE_NAME: gcr.io/${{ vars.GCP_PROJECT }}/agentprovision-code-worker
  NAMESPACE: prod
  HELM_RELEASE: agentprovision-code-worker
  HELM_CHART: ./helm/charts/microservice

jobs:
  build-and-deploy:
    name: Build and Deploy Code Worker
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
          docker build -t ${{ env.IMAGE_NAME }}:${{ github.sha }} apps/code-worker/
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
            --values helm/values/agentprovision-code-worker.yaml \
            --set image.tag=${{ github.sha }} \
            --wait \
            --timeout 10m

      - name: Verify deployment
        run: |
          kubectl rollout status deployment/${{ env.HELM_RELEASE }} -n ${{ env.NAMESPACE }}
          kubectl get pods -n ${{ env.NAMESPACE }} -l app.kubernetes.io/name=agentprovision-code-worker
```

**Step 2: Commit**

```bash
git add .github/workflows/code-worker-deploy.yaml
git commit -m "ci: add GitHub Actions workflow for code-worker deploy"
```

---

## Task 9: Create ADK code_agent — single agent with Temporal tool

Replace the 5-agent dev team with a single `code_agent` leaf agent that starts a `CodeTaskWorkflow` via Temporal.

**Files:**
- Create: `apps/adk-server/agentprovision_supervisor/code_agent.py`
- Create: `apps/adk-server/tools/code_tools.py`

**Step 1: Create code_tools.py**

`apps/adk-server/tools/code_tools.py`:
```python
"""Tools for the code_agent — starts dev tasks via Temporal workflows."""

import asyncio
import logging
import os
import uuid

from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233")
TASK_QUEUE = "agentprovision-code"


async def _start_code_workflow(task_description: str, tenant_id: str, context: str = "") -> dict:
    """Start a CodeTaskWorkflow on Temporal and wait for the result."""
    from temporalio.client import Client

    client = await Client.connect(TEMPORAL_ADDRESS)

    workflow_id = f"code-task-{uuid.uuid4().hex[:8]}"

    # Import the dataclass for input
    from dataclasses import dataclass

    # We send a dict since the workflow is in a separate worker
    handle = await client.start_workflow(
        "CodeTaskWorkflow",
        arg={
            "task_description": task_description,
            "tenant_id": tenant_id,
            "context": context,
        },
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    logger.info("Started CodeTaskWorkflow %s for tenant %s", workflow_id, tenant_id)

    # Wait for completion (up to 15 min)
    result = await handle.result()

    return {
        "workflow_id": workflow_id,
        "pr_url": result.get("pr_url", ""),
        "summary": result.get("summary", ""),
        "branch": result.get("branch", ""),
        "files_changed": result.get("files_changed", []),
        "success": result.get("success", False),
        "error": result.get("error"),
    }


def start_code_task(task_description: str, tenant_id: str, context: str = "") -> dict:
    """Start an autonomous dev task. Claude Code will implement the task, create a branch, and open a PR.

    Args:
        task_description: What to build or fix. Be specific.
        tenant_id: The tenant ID (from session state).
        context: Optional additional context about the codebase or requirements.

    Returns:
        dict with pr_url, summary, branch, files_changed, success, error.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(asyncio.run, _start_code_workflow(task_description, tenant_id, context)).result()
        else:
            result = loop.run_until_complete(_start_code_workflow(task_description, tenant_id, context))
    except RuntimeError:
        result = asyncio.run(_start_code_workflow(task_description, tenant_id, context))

    return result


start_code_task_tool = FunctionTool(start_code_task)
```

**Step 2: Create code_agent.py**

`apps/adk-server/agentprovision_supervisor/code_agent.py`:
```python
"""Code Agent — autonomous coding agent powered by Claude Code CLI.

Replaces the old 5-agent dev team (architect → coder → tester → dev_ops → user_agent).
Delegates coding tasks to Claude Code running in an isolated code-worker pod via Temporal.
"""
from google.adk.agents import Agent
from tools.code_tools import start_code_task_tool
from config.settings import settings

code_agent = Agent(
    name="code_agent",
    model=settings.adk_model,
    instruction="""You are the Code Agent — an autonomous coding agent powered by Claude Code.

When a user asks you to build, fix, or modify code, you delegate the task to Claude Code running in an isolated environment. Claude Code handles the full development cycle autonomously: reads the codebase, implements changes, runs tests, commits, and creates a pull request.

## How it works:
1. User describes what they want built/fixed
2. You call `start_code_task` with the description
3. Claude Code implements it autonomously in an isolated pod
4. A PR is created on GitHub
5. You report back with the PR URL and summary

## Guidelines:
- Always tell the user what's happening: "I'm starting a dev task for X. Claude Code will implement it and create a PR."
- Be specific in the task_description — include file paths, expected behavior, edge cases
- If the user's request is vague, ask clarifying questions BEFORE starting the task
- When the result comes back, summarize what was done and provide the PR link
- If the task fails, explain the error and suggest next steps

## What to include in task_description:
- What to build or fix (specific behavior)
- Which files/areas of the codebase to modify
- Any constraints or patterns to follow
- Expected test coverage

## You have ONE tool:
- `start_code_task(task_description, tenant_id, context)` — starts an autonomous dev task
""",
    tools=[start_code_task_tool],
)
```

**Step 3: Commit**

```bash
git add apps/adk-server/tools/code_tools.py apps/adk-server/agentprovision_supervisor/code_agent.py
git commit -m "feat: create code_agent with Temporal-based Claude Code tool"
```

---

## Task 10: Update root supervisor and remove old dev team agents

Replace `code_agent` with `code_agent` in the root supervisor, update `__init__.py`, and remove old agent files.

**Files:**
- Modify: `apps/adk-server/agentprovision_supervisor/agent.py`
- Modify: `apps/adk-server/agentprovision_supervisor/__init__.py`
- Delete: `apps/adk-server/agentprovision_supervisor/architect.py`
- Delete: `apps/adk-server/agentprovision_supervisor/coder.py`
- Delete: `apps/adk-server/agentprovision_supervisor/tester.py`
- Delete: `apps/adk-server/agentprovision_supervisor/dev_ops.py`
- Delete: `apps/adk-server/agentprovision_supervisor/user_agent.py`
- Delete: `apps/adk-server/agentprovision_supervisor/code_agent.py`

**Step 1: Update agent.py (root supervisor)**

In `apps/adk-server/agentprovision_supervisor/agent.py`:

Replace line 9: `from .code_agent import code_agent` → `from .code_agent import code_agent`

In the instruction string, replace the code_agent section:
```
- **code_agent**: Full development cycle (architect -> coder -> tester -> dev_ops -> user_agent). For code modifications, new tools/agents/connectors, shell commands, deployments, and infrastructure.
```
With:
```
- **code_agent**: Autonomous coding agent powered by Claude Code. Implements features, fixes bugs, creates PRs automatically. For code modifications, new features, bug fixes, refactoring.
```

Update code_agent routing guidelines to:
```
### code_agent:
- Code modifications, new features, bug fixes
- "Create a tool/connector/agent for X"
- "Add a feature", "fix a bug", "refactor X"
- Infrastructure changes, configuration updates
```

Remove shell command / deployment mentions (code_agent creates PRs, doesn't deploy directly).

In `sub_agents` list (line 107): replace `code_agent` with `code_agent`.

**Step 2: Update __init__.py**

In `apps/adk-server/agentprovision_supervisor/__init__.py`:

Remove imports:
```python
from .architect import architect
from .coder import coder
from .tester import tester
from .dev_ops import dev_ops
from .user_agent import user_agent
from .code_agent import code_agent
```

Add import:
```python
from .code_agent import code_agent
```

Update `__all__`:
- Remove: `"code_agent"`, `"architect"`, `"coder"`, `"tester"`, `"dev_ops"`, `"user_agent"`
- Add: `"code_agent"`

**Step 3: Delete old agent files**

```bash
rm apps/adk-server/agentprovision_supervisor/architect.py
rm apps/adk-server/agentprovision_supervisor/coder.py
rm apps/adk-server/agentprovision_supervisor/tester.py
rm apps/adk-server/agentprovision_supervisor/dev_ops.py
rm apps/adk-server/agentprovision_supervisor/user_agent.py
rm apps/adk-server/agentprovision_supervisor/code_agent.py
```

**Step 4: Commit**

```bash
git add apps/adk-server/agentprovision_supervisor/
git commit -m "feat: replace 5-agent dev team with single code_agent using Claude Code"
```

---

## Task 11: Add internal token endpoint for claude_code

The code worker needs to fetch the tenant's Claude Code session token via the internal API. The existing `/oauth/internal/token/{skill_name}` endpoint works for OAuth tokens but needs to also handle manual credential tokens.

**Files:**
- Modify: `apps/api/app/api/v1/oauth.py`

**Step 1: Update get_skill_token to handle manual credentials**

The existing endpoint at line 636 queries `IntegrationConfig` (after Task 2) and calls `retrieve_credentials_for_skill`. This already works for non-OAuth skills — it returns all active credentials as `{key: value}`.

For `claude_code`, the endpoint will return `{"session_token": "<decrypted value>"}` which is exactly what the code worker expects.

Verify the endpoint works by checking the query flow:
1. `IntegrationConfig` where `skill_name='claude_code'` and `enabled=True` → finds the config
2. `retrieve_credentials_for_skill(db, config.id, tenant_id)` → returns `{"session_token": "<value>"}`

The only change needed: the endpoint currently checks `creds.get("oauth_token")` and raises 404 if missing. For manual credentials like claude_code, there's no `oauth_token` — there's a `session_token`. Update the check:

```python
    # For OAuth integrations, require oauth_token; for manual, require any credential
    provider = _skill_to_provider(skill_name)
    if provider and not creds.get("oauth_token"):
        raise HTTPException(status_code=404, detail="No active OAuth token found")
    elif not provider and not creds:
        raise HTTPException(status_code=404, detail=f"No active credentials for '{skill_name}'")
```

Also skip the Google token refresh logic for non-OAuth skills.

**Step 2: Commit**

```bash
git add apps/api/app/api/v1/oauth.py
git commit -m "fix: support manual credential tokens in internal token endpoint"
```

---

## Task 12: Update CLAUDE.md and verify

Update project documentation to reflect the new architecture.

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md agent architecture section**

In the Multi-Agent Orchestration section, replace:
```
- **Dev Team**: Self-modifying team with a strict 5-step cycle (**Architect** → **Coder** → **Tester** → **DevOps** → **User Agent**). Agents have shell access and can autonomously modify code, run tests, and deploy via git.
```
With:
```
- **Code Agent**: Autonomous coding agent powered by Claude Code CLI. Delegates tasks to a dedicated code-worker pod via Temporal. Creates feature branches and PRs automatically.
```

Add to the Temporal workflows section:
```
- `agentprovision-code`: `CodeTaskWorkflow` (Claude Code CLI execution in isolated pod).
```

Add to the What Gets Removed section (or "Architecture" section):
```
- `apps/code-worker/`: Dedicated Temporal worker for Claude Code CLI
```

**Step 2: Verify all imports work**

Run: `cd apps/api && python -c "from app.models import *; print('Models OK')"`
Run: `cd apps/adk-server && python -c "from agentprovision_supervisor import root_agent; print('ADK OK')"`

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with code-worker architecture"
```

---

## Verification

1. API starts without import errors (models, routes, schemas)
2. Integration registry endpoint returns `claude_code` entry
3. IntegrationsPanel renders Claude Code card with token-paste form
4. ADK server starts with `code_agent` in root supervisor
5. No references to `SkillConfig` or `SkillCredential` remain in app code
6. Code worker Docker image builds successfully
7. GitHub Actions workflow triggers on push to `apps/code-worker/**`
