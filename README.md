<h1 align="center">ServiceTsunami</h1>

<p align="center"><strong>AI Agent Orchestration Platform</strong></p>

<p align="center">
  <a href="https://servicetsunami.com"><img src="https://img.shields.io/badge/live-servicetsunami.com-00d2ff?style=flat-square" alt="Production"></a>
  <a href="#"><img src="https://img.shields.io/badge/agents-25-blueviolet?style=flat-square" alt="25 Agents"></a>
  <a href="#"><img src="https://img.shields.io/badge/LLM-Anthropic%20%7C%20Gemini%20%7C%20100%2B-ff6b6b?style=flat-square" alt="Multi-LLM"></a>
  <a href="#"><img src="https://img.shields.io/badge/skills-92%2B%20GWS-green?style=flat-square" alt="Skill Marketplace"></a>
  <a href="#"><img src="https://img.shields.io/badge/embeddings-local%20(nomic)-orange?style=flat-square" alt="Local Embeddings"></a>
  <a href="#"><img src="https://img.shields.io/badge/deploy-GKE%20%2B%20Helm-4285F4?style=flat-square" alt="Kubernetes"></a>
</p>

<p align="center">
  Multi-tenant AI agent platform with 25 specialized agents, LLM-agnostic execution, WhatsApp-native assistant, skill marketplace with GitHub import, local vector embeddings, and durable workflow orchestration.
</p>

---

## What Makes It Different

- **LLM-Agnostic** — Switch between Anthropic Claude, Google Gemini, or 100+ providers per-tenant. Credentials encrypted with Fernet vault. ADK `before_model_callback` + LiteLLM for zero-downtime provider switching.

- **Local Embeddings** — `nomic-embed-text-v1.5` (768-dim) runs locally via sentence-transformers. No API key. No cost. Used across knowledge graph, chat, memory, RL, skills, and email attachments.

- **Skill Marketplace** — Three-tier system (native/community/custom) with GitHub import. Drop a `SKILL.md` in a repo and import it. Supports GWS (92 Google Workspace skills), Claude Code superpowers, or any markdown-based skill format. Semantic auto-trigger matching via pgvector.

- **WhatsApp-Native AI** — Luna, a business co-pilot accessible via WhatsApp. Reads Gmail, manages calendar, tracks competitors, scores leads, runs SQL, downloads email attachments, and maintains a persistent knowledge graph. Typing indicator stays active throughout long processing.

- **25 Specialized Agents** — Hierarchical multi-team architecture. Root supervisor routes to 5 teams, each with sub-agents. Personal assistant, code agent (Claude Code CLI), data team, sales team, marketing intelligence, deal pipeline, and industry verticals (HealthPets, Remedia).

- **Autonomous Code Agent** — Claude Code CLI in a dedicated Kubernetes pod. Creates feature branches, implements code, opens PRs with full traceability. Uses tenant's OAuth subscription, not API credits.

---

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │  React SPA (Ocean Theme, i18n)       │
                    │  Chat  Agents  Skills  Integrations  │
                    └──────────────┬───────────────────────┘
                                   │
┌──────────────────────────────────▼───────────────────────────────────┐
│  FastAPI (Python 3.11)                                               │
│  Multi-tenant JWT  ·  Fernet Vault  ·  Embedding Service (local)    │
│  Skill Manager  ·  Knowledge Graph  ·  WhatsApp Service             │
└──────┬──────────────────┬──────────────────┬───────────────┬────────┘
       │                  │                  │               │
┌──────▼──────┐   ┌───────▼───────┐  ┌──────▼──────┐ ┌──────▼──────┐
│  ADK Server │   │  MCP Server   │  │  Temporal   │ │ Code Worker │
│  25 Agents  │   │  Databricks   │  │  Workflows  │ │ Claude Code │
│  LiteLLM    │   │  Unity Catalog│  │  4 Queues   │ │ CLI in K8s  │
│  Nomic Embed│   │  9 MCP Tools  │  │  10+ Flows  │ │ Auto PRs    │
└─────────────┘   └───────────────┘  └─────────────┘ └─────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **AI Agents** | Google ADK, LiteLLM, Anthropic Claude, Google Gemini |
| **Embeddings** | nomic-embed-text-v1.5 (768-dim, local, sentence-transformers) |
| **Vector Search** | pgvector (cosine similarity) |
| **Backend** | FastAPI, Python 3.11, SQLAlchemy, Pydantic |
| **Frontend** | React 18, Bootstrap 5, i18next |
| **Workflows** | Temporal (4 task queues, 10+ durable workflows) |
| **Messaging** | WhatsApp via Neonize (whatsmeow Go backend) |
| **Security** | JWT multi-tenant, Fernet-encrypted credential vault |
| **Data** | PostgreSQL, Databricks Unity Catalog (Bronze/Silver/Gold) |
| **Skills** | Markdown-based skill files, GitHub import, semantic matching |
| **Infrastructure** | GKE, Helm, GitHub Actions, Docker Compose |

---

## Key Features

### Multi-LLM Provider Switching

Tenants choose their LLM provider from the integration registry. API reads encrypted credentials from the vault and passes `llm_config` to ADK via `state_delta`. The `before_model_callback` overrides `agent.model` per-request — agents stay as singletons.

```
Tenant Settings → Integration Registry → Fernet Vault → state_delta → ADK Callback → LiteLLM → Provider API
```

Supported: Anthropic, Gemini, OpenAI, DeepSeek, Mistral, Groq, Bedrock, Ollama, and 100+ via LiteLLM.

### Skill Marketplace with GitHub Import

```bash
# Import all 92 Google Workspace skills
POST /api/v1/skills/library/import-github
{"repo_url": "https://github.com/googleworkspace/cli/tree/main/skills"}

# Import a single skill
{"repo_url": "https://github.com/googleworkspace/cli/tree/main/skills/gws-gmail-triage"}
```

Three tiers: **Native** (bundled, read-only) | **Community** (GitHub imports) | **Custom** (per-tenant, versioned). Supports `SKILL.md` and `skill.md` formats. External formats (GWS, superpowers) auto-normalized on import.

### 25-Agent Hierarchical Teams

| Team | Agents | Capabilities |
|------|--------|-------------|
| **Personal Assistant** | Luna | WhatsApp co-pilot, Gmail, Calendar, Jira, knowledge graph, attachment download |
| **Code Agent** | Claude Code CLI | Feature branches, PRs, autonomous coding in K8s pod |
| **Data Team** | Data Analyst, Report Generator, Knowledge Manager | SQL, analytics, Excel reports, entity CRUD |
| **Sales Team** | Sales Agent, Customer Support | Deal management, lead scoring, follow-ups |
| **Marketing Team** | Web Researcher, Marketing Analyst, Knowledge Manager | Ad campaigns (Meta/Google/TikTok), competitor monitoring |
| **Prospecting** | Prospect Researcher, Scorer, Outreach | Discovery, qualification, outreach |
| **Deal Team** | Deal Analyst, Researcher, Outreach Specialist | M&A pipeline workflows |
| **Industry** | Vet Supervisor, Cardiac Analyst, Billing Agent | HealthPets mobile cardiology |

### Durable Workflows (Temporal)

- **Inbox Monitor** — Proactive Gmail + Calendar monitoring with LLM triage and knowledge extraction
- **Competitor Monitor** — Scheduled competitor tracking via website scraping and ad library analysis
- **Deal Pipeline** — Discover, Score, Research, Outreach, Advance, Sync (6-step)
- **Code Task** — Claude Code CLI execution in isolated pod with PR creation
- **Knowledge Extraction** — LLM-powered entity/relation extraction from conversations
- **Dataset Sync** — Databricks Unity Catalog (Bronze/Silver/Gold medallion)

### Knowledge Graph + Vector Search

Entities, relations, observations, and history stored in PostgreSQL with pgvector semantic search. Email attachments, chat messages, memory activities, and skills are embedded for cross-content recall.

---

## Quick Start

```bash
# Clone and start
git clone https://github.com/nomad3/servicetsunami-agents.git
cd servicetsunami-agents

# Start all services
DB_PORT=8003 API_PORT=8001 WEB_PORT=8002 docker-compose up --build

# Access
# Web:      http://localhost:8002
# API:      http://localhost:8001
# ADK:      http://localhost:8085
# Temporal: http://localhost:8233

# Demo login: test@example.com / password
```

### Environment Setup

```bash
# apps/api/.env — required
ENCRYPTION_KEY=<fernet-key>           # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ANTHROPIC_API_KEY=sk-ant-xxx          # Or configure via LLM Settings UI
GOOGLE_CLIENT_ID=xxx                  # For Gmail/Calendar OAuth
GOOGLE_CLIENT_SECRET=xxx

# root .env — optional overrides
ANTHROPIC_API_KEY=sk-ant-xxx          # Passed to ADK container
```

---

## Production Deployment

Deploys exclusively via **Kubernetes (GKE)** using Helm charts and GitHub Actions.

```bash
gh workflow run deploy-all.yaml -f environment=prod     # Full stack
gh workflow run adk-deploy.yaml -f environment=prod     # ADK only
kubectl rollout status deployment/servicetsunami-api -n prod
```

```
GKE Gateway → prod namespace
  ├── servicetsunami-web        (React SPA)
  ├── servicetsunami-api        (FastAPI + embedding model)
  ├── servicetsunami-worker     (Temporal workers)
  ├── servicetsunami-adk        (25 agents + LiteLLM)
  ├── servicetsunami-code-worker (Claude Code CLI pod)
  ├── mcp-server                (Databricks integration)
  ├── temporal + temporal-web
  └── Cloud SQL (PostgreSQL + pgvector)
```

---

## Contributing

1. Branch from `main`: `feature/your-feature`
2. Follow patterns in `CLAUDE.md`
3. Conventional commits: `feat:`, `fix:`, `chore:`
4. Open a Pull Request

---

*Built with Google ADK  ·  LiteLLM  ·  Anthropic Claude  ·  Temporal  ·  pgvector  ·  Neonize  ·  sentence-transformers  ·  FastAPI  ·  React*
