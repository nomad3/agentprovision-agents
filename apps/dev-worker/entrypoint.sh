#!/usr/bin/env bash
set -euo pipefail

# Strip trailing whitespace/newlines from secrets (K8s secret mounts can add them)
GITHUB_TOKEN="$(echo -n "${GITHUB_TOKEN}" | tr -d '[:space:]')"

# Mark /workspace as safe (ownership may differ across pod restarts)
git config --global --add safe.directory /workspace

echo "[dev-worker] Setting up repository..."
if [ -d /workspace/.git ]; then
    # Verify repo is valid; if not, remove and re-clone
    if cd /workspace && git rev-parse --git-dir >/dev/null 2>&1; then
        echo "[dev-worker] Updating existing repo..."
        git fetch origin && git checkout main && git reset --hard origin/main
    else
        echo "[dev-worker] Removing corrupted repo..."
        rm -rf /workspace/.git /workspace/*
        git clone "https://${GITHUB_TOKEN}@github.com/nomad3/servicetsunami-agents.git" /workspace
    fi
else
    git clone "https://${GITHUB_TOKEN}@github.com/nomad3/servicetsunami-agents.git" /workspace
fi

# Configure git identity for commits
cd /workspace
git config user.email "dev-worker@servicetsunami.com"
git config user.name "ServiceTsunami Dev Worker"

# Configure gh CLI
echo -n "${GITHUB_TOKEN}" | gh auth login --with-token 2>/dev/null || true

echo "[dev-worker] Starting Temporal worker..."
exec python -m worker
