# Platform Security Audit Report

**Date:** 2026-04-17  
**Auditor:** AgentProvision Security Audit  
**Status:** Completed  
**Scope:** Containers, Dependencies, Network Configuration, Orchestration, and Access Control.

## 1. Executive Summary

The AgentProvision platform demonstrates a strong security baseline, particularly in its containerization strategy and infrastructure-as-code. All core services (`api`, `code-worker`, `mcp-server`) run as non-root users and utilize multi-stage builds to minimize attack surfaces. However, several critical risks were identified in the development configuration (`docker-compose.yml`), outdated frontend dependencies, and permissive network settings in non-production environments.

## 2. Container Security Audit

### Findings:
*   **Non-Root Execution (PASS):** All primary services (`apps/api`, `apps/code-worker`, `apps/mcp-server`) explicitly create and use non-root users (`appuser`, `codeworker`, `mcpuser`).
*   **Minimal Base Images (PASS):** Most containers use `python:3.11-slim`, reducing the number of pre-installed vulnerabilities.
*   **Health Checks (PASS):** Production Dockerfiles include functional health checks using `curl`, ensuring orchestration tools can detect and restart compromised or failing instances.
*   **Secrets Exposure (RISK):** `apps/mcp-server/Dockerfile` copies an `.env.example` to `.env` inside the image. While it's an example, this pattern can lead to accidental inclusion of real secrets if not carefully managed.

### Recommendations:
1.  **Remove `.env` from images:** Do not copy or create `.env` files during build time. Always inject secrets via Kubernetes ExternalSecrets or Environment Variables at runtime.
2.  **Scan Images:** Integrate `trivy` or `snyk` into the CI/CD pipeline (`.github/workflows/`) to scan for OS-level vulnerabilities in base images.

## 3. Dependency Audit

### Findings:
*   **Python (STABLE):** Core backend dependencies (`fastapi`, `pydantic`, `SQLAlchemy`) are relatively modern. `bcrypt<4` is pinned, which is safe but should be monitored.
*   **Frontend (OUTDATED):** `apps/web/package.json` contains several outdated or potentially vulnerable packages:
    *   `react-scripts: 5.0.1` (known vulnerabilities in underlying `webpack` and `ajv` versions).
    *   `axios: ^1.12.2` (many newer security releases available).
    *   `bootstrap: ^5.3.8` (stable, but keep updated).
*   **CLI Providers (DYNAMIC):** The `code-worker` installs CLIs directly from `npm -g`. This ensures latest features but introduces non-deterministic builds if versions aren't pinned.

### Recommendations:
1.  **Update Axios:** Move to `axios: ^1.7.0` or higher to resolve known SSRF and ReDoS vulnerabilities.
2.  **Migrate from React Scripts:** Consider moving to `Vite` for the frontend build system to reduce the massive dependency tree and vulnerability surface of `react-scripts`.
3.  **Pin CLI Versions:** Pin `@github/copilot`, `@anthropic-ai/claude-code`, and `@openai/codex` to specific versions in the Dockerfile to prevent supply-chain attacks.

## 4. Network & Infrastructure Security

### Findings:
*   **Kubernetes Network Policies (PASS):** The platform includes `default-deny-ingress` policies for `prod` and `database` namespaces, which is a best-in-class security posture.
*   **Docker Compose Defaults (CRITICAL):**
    *   `POSTGRES_PASSWORD=postgres` is used in `docker-compose.yml`.
    *   `API_INTERNAL_KEY=dev_mcp_key` is hardcoded.
    *   Databases and Temporal are exposed on host ports (`8003`, `7233`), making them accessible to other machines on the local network.
*   **CORS (VERIFY):** The API allows `CORS_EXTRA_ORIGINS`. Ensure this is tightly scoped in production.

### Recommendations:
1.  **Tighten Local Ports:** In `docker-compose.yml`, change port mappings to `127.0.0.1:8003:5432` to ensure services are only accessible from the local host.
2.  **Rotate Internal Keys:** Replace `dev_mcp_key` with a high-entropy secret in all environments.
3.  **External Secrets:** Ensure `externalsecret.yaml` templates are correctly pulling from a secure provider (Vault/AWS SM) and not just environment variables.

## 5. Agent Orchestration Security (CLI)

### Findings:
*   **Code-Worker Sandbox (PARTIAL):** The `code-worker` runs as a non-root user and operates in a `/workspace` volume. However, it has `dangerously-skip-permissions` flags for some CLIs (e.g., Claude Code).
*   **Token Management (PASS):** Tokens are fetched at runtime via internal API calls and injected as environment variables, which is more secure than persisting them on disk long-term.
*   **Session Isolation (IMPROVED):** `claude_code` uses `--no-session-persistence` to avoid leaking conversation history in JSONL files within the container.

### Recommendations:
1.  **Restrict Workspace:** Ensure the `/workspace` mount is strictly limited to the task directory and does not have access to the `code-worker` source code or config files.
2.  **Audit Logs:** Implement granular logging for all `copilot`, `claude`, and `codex` subprocess calls to track tool usage (especially shell commands).

---
**Conclusion:** The platform is architecturally sound but requires a cleanup of development-time "convenience" settings (weak passwords, open ports) and an update to the frontend dependency tree to meet enterprise security standards.
