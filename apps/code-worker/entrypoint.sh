#!/usr/bin/env bash
set -euo pipefail

# Strip trailing whitespace/newlines from secrets (K8s secret mounts can add them)
GITHUB_TOKEN="$(echo -n "${GITHUB_TOKEN}" | tr -d '[:space:]')"

# Mark /workspace as safe (ownership may differ across pod restarts)
git config --global --add safe.directory /workspace

# Repo URL is parameterized so the rename (servicetsunami-agents →
# agentprovision-agents) can be applied to all in-repo references
# BEFORE the GitHub repository itself is renamed. The default falls
# back to the current GitHub slug `servicetsunami-agents` so the
# worker keeps booting during the transition; once the repo is
# renamed on GitHub, GitHub's auto-redirect keeps the old slug
# working for ~3 months, and operators can override
# GIT_REPO_URL in compose/Helm to point at the new slug directly.
GIT_REPO_URL="${GIT_REPO_URL:-https://${GITHUB_TOKEN}@github.com/nomad3/servicetsunami-agents.git}"

echo "[code-worker] Setting up repository (branch: ${GIT_BRANCH:-main})..."
if [ -d /workspace/.git ]; then
    # Verify repo is valid; if not, remove and re-clone
    if cd /workspace && git rev-parse --git-dir >/dev/null 2>&1; then
        echo "[code-worker] Updating existing repo..."
        git fetch origin && git checkout "${GIT_BRANCH:-main}" && git reset --hard "origin/${GIT_BRANCH:-main}"
    else
        echo "[code-worker] Removing corrupted repo..."
        rm -rf /workspace/.git /workspace/*
        git clone --branch "${GIT_BRANCH:-main}" "${GIT_REPO_URL}" /workspace
    fi
else
    git clone --branch "${GIT_BRANCH:-main}" "${GIT_REPO_URL}" /workspace
fi

# Configure git identity for commits
cd /workspace
git config user.email "code-worker@agentprovision.com"
git config user.name "AgentProvision Code Worker"

# Configure gh CLI
echo -n "${GITHUB_TOKEN}" | gh auth login --with-token 2>/dev/null || true

# Start OpenCode server in background (local Gemma 4 via host Ollama)
# Keeps warm so _execute_opencode_chat() gets ~3s responses instead of ~90s cold starts
OPENCODE_PORT="${OPENCODE_PORT:-8200}"
echo "[code-worker] Starting OpenCode server on port ${OPENCODE_PORT}..."

# Write opencode config for the server.
#
# mcp servers — without this block, OpenCode comes up with ZERO MCP tools
# registered, even though apps/mcp-server is running on port 8086 with all
# 156 AgentProvision tools (find_entities, search_knowledge, recall_memory,
# etc.). Before the platform-routing flip that started defaulting Luna to
# OpenCode, the same chat path went through Claude Code which wrote its
# own .claude.json with the mcpServers block from
# `cli_session_manager._build_mcp_config()`. OpenCode never got the same
# treatment — the persistent-server commit (7e5cd727) only wired the
# Ollama provider. Result: every Luna chat through WhatsApp lost
# find_entities/search_knowledge/recall_memory access without anyone
# noticing because Gmail/Calendar still resolved via the user's external
# Claude.ai connectors, so the symptom looked like "MCP works but
# AgentProvision tools are gone".
#
# Tenant scoping: per-tool tenant_id is injected by the prompt prefix in
# cli_executors/opencode.py (`Always pass tenant_id in ALL MCP tool calls`),
# so the static config only needs the X-Internal-Key header. Each MCP
# tool call already takes tenant_id as an argument.
MCP_TOOLS_URL_DEFAULT="http://mcp-tools:8086/sse"
mkdir -p /home/codeworker/.config/opencode
cat > /home/codeworker/opencode.json <<OCEOF
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama",
      "options": {
        "baseURL": "${OPENCODE_OLLAMA_URL:-http://host.docker.internal:11434/v1}"
      },
      "models": {
        "${OPENCODE_MODEL:-gemma4}": {
          "name": "${OPENCODE_MODEL:-gemma4}"
        }
      }
    }
  },
  "model": "ollama/${OPENCODE_MODEL:-gemma4}",
  "mcp": {
    "agentprovision": {
      "type": "remote",
      "url": "${MCP_TOOLS_URL:-${MCP_TOOLS_URL_DEFAULT}}",
      "enabled": true,
      "headers": {
        "X-Internal-Key": "${MCP_API_KEY:-dev_mcp_key}"
      }
    }
  }
}
OCEOF

cd /home/codeworker
# Try to start OpenCode server — non-fatal if it fails
(opencode serve --port "${OPENCODE_PORT}" >>/tmp/opencode-server.log 2>&1) &
OPENCODE_PID=$!
echo "[code-worker] OpenCode server PID: ${OPENCODE_PID}"
# Give it a moment to start
sleep 3
if kill -0 "${OPENCODE_PID}" 2>/dev/null; then
    echo "[code-worker] OpenCode server started successfully"
else
    echo "[code-worker] WARNING: OpenCode server failed to start (will use fallback)"
fi

echo "[code-worker] Starting Temporal worker..."
cd /app
exec python -m worker
