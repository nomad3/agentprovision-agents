#!/bin/bash
# Local deploy script — pulls latest code and rebuilds changed services
# Called after Luna merges a PR

set -e
cd "$(dirname "$0")/.."

echo "[deploy] Pulling latest from main..."
git pull origin main

echo "[deploy] Detecting changed services..."
CHANGED=$(git diff HEAD~1 --name-only 2>/dev/null || echo "")

REBUILD=""
if echo "$CHANGED" | grep -q "apps/web/"; then
  REBUILD="$REBUILD web"
fi
if echo "$CHANGED" | grep -q "apps/api/"; then
  REBUILD="$REBUILD api"
fi
if echo "$CHANGED" | grep -q "apps/mcp-server/"; then
  REBUILD="$REBUILD mcp-tools mcp-server"
fi
if echo "$CHANGED" | grep -q "apps/code-worker/"; then
  REBUILD="$REBUILD code-worker"
fi

if [ -z "$REBUILD" ]; then
  echo "[deploy] No service changes detected. Restarting API only."
  docker-compose restart api
else
  echo "[deploy] Rebuilding:$REBUILD"
  DB_PORT=8003 API_PORT=8001 WEB_PORT=8002 docker-compose up -d --build $REBUILD
fi

echo "[deploy] Done!"
