#!/usr/bin/env bash
# Run an end-to-end demo workflow using the seeded demo credentials.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

API_BASE=${API_BASE:-"http://localhost:8000/api/v1"}
TEMPORAL_ADDRESS=${TEMPORAL_ADDRESS:-"localhost:7233"}
TEMPORAL_NAMESPACE=${TEMPORAL_NAMESPACE:-"default"}
DEMO_EMAIL=${DEMO_EMAIL:-"test@example.com"}
DEMO_PASSWORD=${DEMO_PASSWORD:-"password"}
DATASET_NAME=${DATASET_NAME:-"Workflow Demo"}
TASK_QUEUE=${TASK_QUEUE:-"agentprovision-lifeops"}
WORKFLOW_TYPE=${WORKFLOW_TYPE:-"MorningRoutineWorkflow"}
SKIP_WORKFLOW=${SKIP_WORKFLOW:-"false"}
DESCRIBE=${DESCRIBE:-"false"}

log() {
  echo "[run_demo] $1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd jq
require_cmd python3

log "Authenticating demo user $DEMO_EMAIL..."
LOGIN_RESPONSE=$(curl -sS -w "\n%{http_code}" -X POST "$API_BASE/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$DEMO_EMAIL&password=$DEMO_PASSWORD")
LOGIN_BODY=$(echo "$LOGIN_RESPONSE" | head -n -1)
LOGIN_STATUS=$(echo "$LOGIN_RESPONSE" | tail -n1)
TOKEN=$(echo "$LOGIN_BODY" | jq -r '.access_token')

if [[ "$LOGIN_STATUS" != "200" || "$TOKEN" == "null" || -z "$TOKEN" ]]; then
  echo "Failed to obtain access token (status $LOGIN_STATUS). Response: $LOGIN_BODY" >&2
  exit 1
fi
log "Access token acquired."

read -r -d '' DATASET_PAYLOAD <<EOF_JSON
{
  "name": "${DATASET_NAME}",
  "description": "Synthetic dataset ingested via run_demo_workflow.sh",
  "records": [
    {"date": "2024-10-01", "metric": "energy", "value": 78},
    {"date": "2024-10-02", "metric": "energy", "value": 82},
    {"date": "2024-10-03", "metric": "energy", "value": 76}
  ]
}
EOF_JSON

log "Ingesting synthetic dataset $DATASET_NAME..."
DATASET_RESPONSE=$(curl -sS -w "\n%{http_code}" -X POST "$API_BASE/datasets/ingest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$DATASET_PAYLOAD")
DATASET_BODY=$(echo "$DATASET_RESPONSE" | head -n -1)
DATASET_STATUS=$(echo "$DATASET_RESPONSE" | tail -n1)
DATASET_ID=$(echo "$DATASET_BODY" | jq -r '.id')
TENANT_ID=$(echo "$DATASET_BODY" | jq -r '.tenant_id')

if [[ "$DATASET_STATUS" != "201" || "$DATASET_ID" == "null" || -z "$DATASET_ID" ]]; then
  echo "Dataset ingestion failed (status $DATASET_STATUS). Response: $DATASET_BODY" >&2
  exit 1
fi

log "Dataset created (id=$DATASET_ID) for tenant $TENANT_ID."

if [[ "$SKIP_WORKFLOW" == "true" ]]; then
  log "SKIP_WORKFLOW=true; exiting after dataset creation."
  exit 0
fi

log "Starting $WORKFLOW_TYPE on Temporal ($TEMPORAL_ADDRESS) using task queue $TASK_QUEUE..."
WORKFLOW_OUTPUT=$(env \
  TEMPORAL_ADDRESS="$TEMPORAL_ADDRESS" \
  TEMPORAL_NAMESPACE="$TEMPORAL_NAMESPACE" \
  DATASET_ID="$DATASET_ID" \
  TENANT_ID="$TENANT_ID" \
  WORKFLOW_TYPE="$WORKFLOW_TYPE" \
  TASK_QUEUE="$TASK_QUEUE" \
  python3 <<'PY'
import asyncio
import json
import os
import uuid
from app.services import workflows

async def main():
    tenant_uuid = uuid.UUID(os.environ["TENANT_ID"])
    result = await workflows.start_workflow(
        workflow_type=os.environ["WORKFLOW_TYPE"],
        tenant_id=tenant_uuid,
        task_queue=os.environ["TASK_QUEUE"],
        arguments={"dataset_id": os.environ["DATASET_ID"]},
        memo={"source": "shell_demo"},
    )
    return {"workflow_id": result.id, "run_id": result.first_execution_run_id}

print(json.dumps(asyncio.run(main())))
PY
)

WORKFLOW_ID=$(echo "$WORKFLOW_OUTPUT" | jq -r '.workflow_id')
RUN_ID=$(echo "$WORKFLOW_OUTPUT" | jq -r '.run_id')

if [[ "$WORKFLOW_ID" == "null" || -z "$WORKFLOW_ID" ]]; then
  echo "Workflow start failed: $WORKFLOW_OUTPUT" >&2
  exit 1
fi

log "Workflow dispatched (workflow_id=$WORKFLOW_ID run_id=$RUN_ID)."

if [[ "$DESCRIBE" == "true" ]]; then
  log "Fetching workflow description from Temporal..."
  DESCRIPTION=$(env \
    TEMPORAL_ADDRESS="$TEMPORAL_ADDRESS" \
    TEMPORAL_NAMESPACE="$TEMPORAL_NAMESPACE" \
    WORKFLOW_ID="$WORKFLOW_ID" \
    RUN_ID="$RUN_ID" \
    python3 <<'PY'
import asyncio
import json
import os
from app.services import workflows

async def main():
    return await workflows.describe_workflow(
        workflow_id=os.environ["WORKFLOW_ID"],
        run_id=os.environ.get("RUN_ID") or None,
    )

print(json.dumps(asyncio.run(main())))
PY
  )
  echo "$DESCRIPTION" | jq .
fi

log "Demo workflow complete. Verify results in Temporal Web UI and application UI."
