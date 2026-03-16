<h1 align="center">ServiceTsunami</h1>

<p align="center"><strong>AI Agent Orchestration Platform</strong></p>

<p align="center">
  <a href="https://servicetsunami.com"><img src="https://img.shields.io/badge/live-servicetsunami.com-00d2ff?style=flat-square" alt="Production"></a>
  <a href="#"><img src="https://img.shields.io/badge/CLI_Agents-Claude%20%7C%20Gemini%20%7C%20Codex-blueviolet?style=flat-square" alt="CLI Agents"></a>
  <a href="#"><img src="https://img.shields.io/badge/MCP_Tools-19_tools-ff6b6b?style=flat-square" alt="MCP Tools"></a>
  <a href="#"><img src="https://img.shields.io/badge/skills-92%2B%20marketplace-green?style=flat-square" alt="Skill Marketplace"></a>
  <a href="#"><img src="https://img.shields.io/badge/embeddings-local%20(nomic)-orange?style=flat-square" alt="Local Embeddings"></a>
  <a href="#"><img src="https://img.shields.io/badge/deploy-GKE%20%2B%20Helm-4285F4?style=flat-square" alt="Kubernetes"></a>
</p>

<p align="center">
  Orchestration layer on top of existing AI agent platforms. Routes tasks to Claude Code CLI, Gemini CLI, or Codex CLI — each running on the tenant's own subscription. Multi-tenant, WhatsApp-native, with a shared knowledge graph, MCP tool server, skill marketplace, and RL-driven routing.
</p>

---

## What Makes It Different

- **Orchestrate, don't build agents** — Instead of custom LLM agents, we route to existing CLI platforms (Claude Code, Gemini CLI, Codex). They handle context windows, memory, and tool calling. We handle routing, multi-tenancy, integrations, and learning.

- **Zero API credits** — Tenants connect their own subscriptions (Claude Pro/Max, ChatGPT Plus, Google AI Pro) via one-click OAuth. Agents run on subscription plans, not per-token API billing.

- **MCP Tool Server** — 19 tools (email, calendar, knowledge graph, Jira, data, ads) served via Anthropic's MCP protocol (FastMCP). Any MCP-compatible CLI agent connects instantly.

- **Tool & Skill Marketplace** — Three-tier system (native/community/custom) with GitHub import for both agent skills and MCP tools. Import from `googleworkspace/cli` (92 skills), `modelcontextprotocol/servers`, or any repo with SKILL.md/tool.md files.

- **WhatsApp-Native AI** — Luna, a business co-pilot on WhatsApp. Reads Gmail, manages calendar, tracks competitors, scores leads, downloads attachments, and builds a persistent knowledge graph. Typing indicator stays active throughout processing.

- **RL-Driven Routing** — The platform learns which CLI agent performs best per task type. Starts with deterministic routing (tenant default + agent affinity), converges via user feedback (thumbs up/down) to optimal platform selection.

- **Local Embeddings** — `nomic-embed-text-v1.5` (768-dim) runs locally. No API key. No cost. Powers knowledge graph search, memory recall, skill matching, and email attachment indexing.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Channels: WhatsApp (Neonize) · Web Chat · API                   │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│  FastAPI Backend                                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────────────────┐ │
│  │ Chat Service  │ │ Agent Router │ │ Session Manager           │ │
│  │ (entry point) │ │ (RL + tenant │ │ (skill → CLAUDE.md,       │ │
│  │              │ │  default)    │ │  MCP config, lifecycle)   │ │
│  └──────┬───────┘ └──────┬───────┘ └───────────────────────────┘ │
│         └────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│  Temporal (servicetsunami-code queue)                              │
│  ┌─────────────────┐ ┌─────────────────┐ ┌────────────────────┐  │
│  │ Claude Code CLI  │ │ Gemini CLI      │ │ Codex CLI          │  │
│  │ (subscription)   │ │ (free/Pro)      │ │ (ChatGPT plan)     │  │
│  └────────┬─────────┘ └────────┬────────┘ └─────────┬──────────┘  │
│           └────────────────────┼────────────────────┘             │
│                                │                                  │
│                    ┌───────────▼───────────┐                      │
│                    │  MCP Tool Server       │                      │
│                    │  (FastMCP, 19 tools)   │                      │
│                    │  Email · Calendar ·    │                      │
│                    │  Knowledge · Jira ·    │                      │
│                    │  Data · Ads · Reports  │                      │
│                    └───────────────────────┘                      │
└───────────────────────────────────────────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
      ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
      │ PostgreSQL │ │  Gmail    │ │  Jira     │
      │ + pgvector │ │  Calendar │ │  GitHub   │
      │ Knowledge  │ │  OAuth    │ │  Ads      │
      │ Graph, RL  │ │           │ │           │
      └───────────┘ └───────────┘ └───────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Agent Platforms** | Claude Code CLI, Gemini CLI, Codex CLI |
| **Tool Protocol** | MCP (FastMCP, Streamable HTTP, 19 tools) |
| **Orchestration** | Temporal (durable workflows, retries, timeouts) |
| **Agent Definitions** | Skill Marketplace (SKILL.md → CLAUDE.md/GEMINI.md/CODEX.md) |
| **Routing** | Python + RL policy (zero LLM cost) |
| **Embeddings** | nomic-embed-text-v1.5 (768-dim, local, sentence-transformers) |
| **Vector Search** | pgvector (cosine similarity) |
| **Backend** | FastAPI, Python 3.11, SQLAlchemy, Pydantic |
| **Frontend** | React 18, Bootstrap 5, i18next, Ocean Theme |
| **Messaging** | WhatsApp via Neonize (whatsmeow Go backend) |
| **Security** | JWT multi-tenant, Fernet-encrypted credential vault |
| **Data** | PostgreSQL, Databricks Unity Catalog |
| **Infrastructure** | GKE, Helm, GitHub Actions, Docker Compose |

---

## Key Features

### CLI Agent Orchestration

Each agent is a skill in the marketplace. The orchestrator generates platform-specific instruction files, connects to MCP tools, and dispatches via Temporal:

```
User message → Agent Router (Python, zero LLM cost)
  → Load agent skill (e.g., Luna)
  → Generate CLAUDE.md + MCP config
  → Dispatch to code-worker via Temporal
  → claude -p "message" --mcp-config mcp.json --allowedTools mcp__*
  → CLI uses MCP tools (email, calendar, knowledge graph)
  → Response flows back to chat/WhatsApp
```

Supported platforms: Claude Code (subscription), Gemini CLI (free/Pro), Codex CLI (ChatGPT plan). Each tenant connects their own subscription via OAuth — zero API credits.

### MCP Tool Server

19 tools served via Anthropic's MCP protocol (FastMCP):

| Category | Tools |
|----------|-------|
| **Email** | search_emails, read_email, send_email, download_attachment, deep_scan_emails, list_connected_accounts |
| **Calendar** | list_calendar_events, create_calendar_event |
| **Knowledge Graph** | create/find/update entity, merge, create/find relations, get_neighborhood, record_observation, get_entity_timeline, search_knowledge, ask_knowledge_graph |

Tools follow the same three-tier marketplace as skills — import from GitHub, create custom per-tenant, or use built-in.

### Skill & Agent Marketplace

```bash
# Import 92 Google Workspace skills
POST /api/v1/skills/library/import-github
{"repo_url": "https://github.com/googleworkspace/cli/tree/main/skills"}

# Import MCP tools from community
POST /api/v1/tools/import-github
{"repo_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/slack"}
```

Three tiers: **Native** (bundled) | **Community** (GitHub imports) | **Custom** (per-tenant, versioned). Agents are skills with `engine: agent` and `platform_affinity: claude_code|gemini_cli|codex_cli`.

### RL-Driven Learning

Every chat interaction logs RL experiences (agent_selection, tool_selection, response_generation). User feedback (thumbs up/down) propagates rewards. The Learning page shows decision point performance, activity feed, and platform comparison.

### WhatsApp-Native Assistant (Luna)

Luna runs as a Claude Code CLI session via WhatsApp. Persistent typing indicator (refreshes every 4s), bulk email scanning in Python (no LLM per email), automatic entity extraction from every interaction, and document processing (PDF/Excel/CSV extracted locally, embedded for search).

### Knowledge Graph + Vector Search

Entities, relations, observations, and history in PostgreSQL with pgvector semantic search (768-dim, nomic-embed). Email attachments, chat messages, memory activities, and skills embedded for cross-content recall.

---

## Quick Start

```bash
git clone https://github.com/nomad3/servicetsunami-agents.git
cd servicetsunami-agents

# Start all services
DB_PORT=8003 API_PORT=8001 WEB_PORT=8002 docker-compose up --build

# Access
# Web:         http://localhost:8002
# API:         http://localhost:8001
# MCP Tools:   http://localhost:8087
# Temporal UI: http://localhost:8233

# Demo login: test@example.com / password
```

### Connect Your Agent

1. Go to **Integrations** → click **Claude Code** → run `claude setup-token` → paste token
2. Go to **Settings** → enable **CLI Orchestrator**
3. Chat via web or WhatsApp — Luna responds via your Claude subscription

### Environment Setup

```bash
# apps/api/.env — required
ENCRYPTION_KEY=<fernet-key>           # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
GOOGLE_CLIENT_ID=xxx                  # For Gmail/Calendar OAuth
GOOGLE_CLIENT_SECRET=xxx

# No ANTHROPIC_API_KEY needed — uses subscription via CLI
```

---

## Production Deployment

Deploys via **Kubernetes (GKE)** using Helm charts and GitHub Actions.

```
GKE Gateway → prod namespace
  ├── servicetsunami-web        (React SPA)
  ├── servicetsunami-api        (FastAPI + embedding model)
  ├── servicetsunami-worker     (Temporal workers)
  ├── servicetsunami-code-worker (Claude Code / Gemini / Codex CLI)
  ├── mcp-tools                 (FastMCP server, 19 tools)
  ├── mcp-server                (Databricks integration)
  ├── temporal + temporal-web
  └── Cloud SQL (PostgreSQL + pgvector)
```

---

## Design Documents

- `docs/plans/2026-03-15-cli-orchestration-pivot-design.md` — Full architecture spec for CLI orchestration
- `docs/plans/2026-03-15-cli-orchestration-pivot-plan.md` — Phase 1 implementation plan (10 tasks)
- `docs/plans/2026-03-13-multi-model-abstraction-layer-design.md` — Multi-LLM provider switching

---

## Contributing

1. Branch from `main`: `feature/your-feature`
2. Follow patterns in `CLAUDE.md`
3. Conventional commits: `feat:`, `fix:`, `chore:`
4. Open a Pull Request

---

*Built with Claude Code CLI · Gemini CLI · Codex CLI · MCP (FastMCP) · Temporal · pgvector · Neonize · sentence-transformers · FastAPI · React*
