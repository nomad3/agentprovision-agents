# Integral + AgentProvision Integration Design

**Date:** 2026-03-30
**Status:** Approved
**Scope:** New tenant onboarding, agent skills, MCP connectivity, Jenkins/Nexus tools, on-premise deployment

## Overview

Integrate Integral's existing SRE Control Plane (51 MCP tools, ChromaDB knowledge base, 455 servers across 6 datacenters) with AgentProvision's orchestration layer. Deploy AgentProvision on-premise inside Integral's private network. Create three specialized agents orchestrated by Luna, with new Jenkins and Nexus MCP tools built in the SRE project.

## Architecture

### Deployment Topology

On-premise deployment inside Integral's private network (e.g., mvfxiadp45 or dedicated host):

```
Integral Private Network
├── AgentProvision Stack (Docker Compose)
│   ├── api (FastAPI, port 8001)
│   ├── web (React, port 8002)
│   ├── db (PostgreSQL + pgvector, port 8003)
│   ├── mcp-tools (FastMCP, port 8087) — unchanged, no new tools here
│   ├── code-worker (Claude Code CLI via Temporal)
│   ├── temporal (port 7233)
│   └── ollama (Qwen scoring, port 11434)
│
├── Integral SRE Stack (already running)
│   ├── control-plane-api (port 8080) ← MCP connector target
│   ├── control-plane-web (port 5173)
│   └── ChromaDB (321K+ docs knowledge base)
│
├── Jenkins Instances (internal)
│   ├── nyjenkin.integral.com (NY4)
│   ├── ldnjenkin.integral.com (LD4)
│   ├── sgjenkin.integral.com (SG)
│   ├── tyojenkin.integral.com (TY3)
│   └── uatjenkin.integral.com (UAT)
│
└── Nexus Registry
    ├── nexus.sca.dc.integral.net:8081 (push)
    └── nexus.integral.com:8081 (pull)
```

### MCP Connectivity (Hybrid Approach)

- **SRE tools (51 existing + 14 new Jenkins/Nexus):** Built natively in `infra-control-plane-center`. AgentProvision connects via `MCPServerConnector` (HTTP transport, internal network).
- **AgentProvision FastMCP (81 tools):** Unchanged. No new tools added here.
- **Discovery:** AgentProvision's `MCPServerConnector.discover_tools()` sends JSON-RPC `tools/list` to SRE server, automatically discovers all 65 tools.

### Networking

Both stacks on shared Docker network or host networking. SRE MCP server reachable at `http://control-plane-api:8080` (shared network) or `http://localhost:8080` (host networking). All traffic stays inside private network.

- Claude Code CLI requires outbound internet (Anthropic API).
- Ollama runs fully local — no outbound needed.

## Agent Hierarchy

Tenant: **Integral** — AgentKit type: `hierarchy`, Luna as supervisor.

```
Luna (Supervisor / Entry Point)
├── integral-sre (Technical Support)
├── integral-devops (Release Operations)
└── integral-business-support (Operations Intelligence)
```

All agents are **skill definitions** (skill.md files), not hardcoded logic. The CLI orchestrator (Claude Code / Codex CLI / Gemini CLI) reads the skill prompt and has access to the MCP tools via the session's MCP config.

### Agent Skill Definitions

#### 1. integral-sre (Technical Support)

**File:** `apps/api/app/skills/native/agents/integral-sre/skill.md`
**Platform affinity:** `claude_code` (fallback: `gemini_cli`)
**MCP tools:** All 65 SRE tools via remote connector
**Role:** Infrastructure monitoring, alert investigation, incident triage, SSH operations, runbook execution
**Personality:** Technical, concise, SRE vocabulary
**Autonomy:** Full for read-only ops, supervised for SSH commands

#### 2. integral-devops (Release Operations)

**File:** `apps/api/app/skills/native/agents/integral-devops/skill.md`
**Platform affinity:** `claude_code`
**MCP tools:** Jenkins + Nexus tools (subset of 65 SRE tools via remote connector)
**Role:** CI/CD pipeline management, build triggering, deployment orchestration, artifact management, release checklists
**Personality:** Process-oriented, safety-conscious, confirms before destructive actions
**Autonomy:** Supervised (builds require confirmation before trigger)

#### 3. integral-business-support (Operations Intelligence)

**File:** `apps/api/app/skills/native/agents/integral-business-support/skill.md`
**Platform affinity:** `claude_code` (fallback: `codex_cli`)
**MCP tools:** All 65 SRE tools via remote connector (full read access)
**Role:** Transaction tracing, alert translation, system health for non-technical users, self-service troubleshooting
**Personality:** Business-friendly, forex domain language, translates technical data into business impact, no jargon
**Autonomy:** Full (all read-only)

**Special capability — Forex Transaction Trace:**

The agent follows this trace path when investigating failed/delayed transactions:

1. **Client → FIX Session** — `check_fix_session` — Is the FIX session connected? Any reconnects?
2. **FIX → Matching Engine** — `check_latency_metrics` — Latency between client and matching engine?
3. **Matching → LP** — `check_lp_status` — Is the Liquidity Provider reachable? Quoting?
4. **LP → Execution** — `query_opentsdb` — FXCloudWatch execution metrics, fill rates, rejects?
5. **Execution → Settlement** — `check_server_health` + `correlate_alerts` — Settlement service health, any related alerts?

At each step, the agent translates findings into business language:
> "Transaction delayed at step 3 — Liquidity Provider CityFX is showing 340ms latency (normally 12ms), likely causing the fill delay."

### Agent Routing

Additions to `agent_router.py` keyword detection:

| Intent keywords | Routes to |
|---|---|
| `build`, `deploy`, `release`, `pipeline`, `jenkins`, `nexus`, `artifact`, `promote` | integral-devops |
| `server`, `ssh`, `prometheus`, `alert triage`, `runbook`, `haproxy`, `infrastructure` | integral-sre |
| `transaction`, `failed trade`, `delayed`, `FIX session`, `LP`, `trace`, `business impact`, `health check`, `client`, `settlement` | integral-business-support |
| General / unclear | Luna decides from context |

These keywords only activate when the tenant has matching agent skills configured.

## Jenkins & Nexus MCP Tools (SRE Project)

**Location:** `infra-control-plane-center` — new handler files following existing patterns.

### New Files in SRE Project

- `src/integral_mcp_server/handlers/jenkins.py` — 8 tools
- `src/integral_mcp_server/handlers/nexus.py` — 6 tools
- Tool definitions added to `src/integral_mcp_server/legacy_tools.py`
- Handler routing added to `src/integral_mcp_server/mcp_server.py`

### Authentication

Configured in SRE server's `.env`:

```bash
JENKINS_API_USER=<service-account>
JENKINS_API_TOKEN=<api-token-from-ldap-user>
JENKINS_URLS_NY4=http://nyjenkin.integral.com
JENKINS_URLS_LD4=http://ldnjenkin.integral.com
JENKINS_URLS_SG=http://sgjenkin.integral.com
JENKINS_URLS_TY3=http://tyojenkin.integral.com
JENKINS_URLS_UAT=http://uatjenkin.integral.com
NEXUS_URL=nexus.sca.dc.integral.net:8081
NEXUS_API_USER=<service-account>
NEXUS_API_TOKEN=<token>
```

### Jenkins Tools (8)

| Tool | HTTP | Endpoint | Description |
|---|---|---|---|
| `list_jenkins_jobs` | GET | `/api/json` | List jobs with status, folder navigation |
| `get_jenkins_job_status` | GET | `/job/{name}/api/json` | Last build result, duration, health |
| `trigger_jenkins_build` | POST | `/job/{name}/build` | Trigger with parameters, returns queue URL |
| `get_jenkins_build_log` | GET | `/job/{name}/{build}/consoleText` | Console output, tail support for large logs |
| `get_jenkins_build_artifacts` | GET | `/job/{name}/{build}/api/json` | List artifacts with download URLs |
| `abort_jenkins_build` | POST | `/job/{name}/{build}/stop` | Cancel running build |
| `list_jenkins_pipelines` | GET | `/api/json?tree=jobs[...]` | Multibranch pipeline views, nested folders |
| `get_jenkins_queue` | GET | `/queue/api/json` | Queued builds, wait reasons |

All Jenkins tools accept a `region` parameter (NY4, LD4, SG, TY3, UAT) that resolves to the correct Jenkins URL from env config.

### Nexus Tools (6)

| Tool | HTTP | Endpoint | Description |
|---|---|---|---|
| `search_nexus_artifacts` | GET | `/service/rest/v1/search` | Search by name, group, version, format |
| `get_nexus_artifact_info` | GET | `/service/rest/v1/components/{id}` | Metadata, checksums, upload date, size |
| `list_nexus_repositories` | GET | `/service/rest/v1/repositories` | All repos with type, format, health |
| `get_nexus_component_versions` | GET | `/service/rest/v1/search?name={name}` | All versions, sorted by date |
| `promote_nexus_artifact` | POST | `/service/rest/v1/staging/move` | Move from snapshots to releases |
| `check_nexus_health` | GET | `/service/rest/v1/status` | Storage, repo health, blob store stats |

## AgentProvision Platform Changes

### What Changes

1. **3 agent skill files** — `apps/api/app/skills/native/agents/integral-{sre,devops,business-support}/skill.md`
2. **Agent router keywords** — `apps/api/app/services/agent_router.py` — add intent detection for devops/sre/business-support
3. **CLI session MCP config** — `apps/api/app/services/cli_session_manager.py` — pull tenant's `MCPServerConnector` entries and inject into CLI's MCP config so the CLI can call SRE tools directly
4. **One-time seed script** — `scripts/seed_integral_tenant.py` — creates tenant, admin user, AgentKit, MCPServerConnector, integration credentials. Run once and discard.

### What Does NOT Change

- FastMCP server (`mcp-tools/`) — untouched
- Database schema — no new tables or migrations
- Web frontend — existing agent/chat UI works as-is
- Code worker — same CLI execution path
- Temporal workflows — existing `ChatCliWorkflow` handles orchestration

### Seed Script Creates

- Tenant: "Integral"
- Admin user: configurable email/password
- TenantFeatures: `default_cli_platform: "claude_code"`
- AgentKit: Luna supervisor, `kit_type: "hierarchy"`, 3 agent skills linked
- MCPServerConnector: `name: "integral-sre"`, `server_url: "http://control-plane-api:8080"`, `transport: "streamable-http"`, `auth_type: "none"` (internal network)
- 3 Agent records with skills attached

## On-Premise Deployment Considerations

- Replace Cloudflare Tunnel with internal DNS/reverse proxy
- Ollama needs GPU-capable host or CPU fallback (Qwen models are small)
- Claude Code CLI needs outbound internet for Anthropic API
- All other traffic stays inside private network

### Deferred (Phase 2)

- SSO/LDAP integration for AgentProvision login
- High availability / multi-node deployment
- Monitoring AgentProvision via Integral's existing Prometheus
- Dynamic Workflows for complex release orchestration (multi-agent)

## Implementation Scope

### SRE Project (`infra-control-plane-center`)
- 2 new handler files (jenkins.py, nexus.py)
- 14 new tool definitions in legacy_tools.py
- Handler routing in mcp_server.py
- Environment variable additions

### AgentProvision Project (`servicetsunami-agents`)
- 3 skill.md files
- Agent router keyword updates
- CLI session manager MCP config injection
- One-time seed script
