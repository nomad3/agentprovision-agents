#!/usr/bin/env bash
# Local deploy script — updated to use Kubernetes (Rancher Desktop)
# Replaces the old docker-compose deployment

set -e
cd "$(dirname "$0")/.."

echo "[deploy] Pulling latest from main..."
git pull origin main

echo "[deploy] Starting Kubernetes deployment via deploy_k8s_local.sh..."
bash scripts/deploy_k8s_local.sh

echo "[deploy] Done!"
