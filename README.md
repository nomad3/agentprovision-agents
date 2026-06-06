<h1 align="center">AgentProvision</h1>

<p align="center"><strong>The orchestration layer for AI agents — with emotional intelligence and teamwork.</strong></p>

```
    +---------------------------------------------------------------+
    |  Live          agentprovision.com                             |
    |  Orchestrates  Claude Code | Codex CLI | Gemini CLI |         |
    |                GitHub Copilot CLI | OpenCode                  |
    |  Viewports     Alpha Control Center (web /dashboard)          |
    |                Luna desktop (Tauri 2.0)  ·  alpha CLI         |
    |                WhatsApp  ·  Microsoft Teams                   |
    |  Substrate     Memory · Emotion · Teamwork · Trust            |
    |  Capabilities  90+ MCP tools · skill library · 35 workflows   |
    |                RL auto-scoring on every reply                 |
    +---------------------------------------------------------------+
```

<p align="center">
AgentProvision is a <b>memory-first, multi-tenant</b> platform that orchestrates the AI coding CLIs you already pay for — Claude Code, Codex, Gemini CLI, GitHub Copilot CLI — into a <b>network of agents</b> that remember, collaborate, and stay accountable. One brain, many viewports: web, terminal, desktop, WhatsApp. Each tenant runs on their own subscription — <b>zero API credits</b>. Self-hosted, Kubernetes-native, deployed today on Rancher Desktop behind a Cloudflare tunnel.
</p>

> **The thesis:** raw AI CLIs are powerful but stateless and solitary. AgentProvision adds the two things they lack — **emotional intelligence** (agents that remember you and read the room) and **teamwork** (agents that collaborate instead of working alone) — on top of an **orchestration layer** that routes work to whichever CLI fits best. The user-facing surface is the **Alpha Control Center** at `/dashboard` (a VSCode-style IDE shell), and the **Alpha CLI is the kernel** — every feature flows through it. Weekly digests live in [`docs/changelog/`](docs/changelog/); the architecture source of truth is [`CLAUDE.md`](CLAUDE.md).

---

## Core features

### Emotional intelligence + teamwork — what raw CLIs lack

| Capability | What it means | How (the engines underneath) |
|---|---|---|
| **Emotional intelligence** | agents that **remember you and read the room** | **Memory** — knowledge graph (entities, relations, observations) + pgvector recall (768-dim nomic-embed), **pre-loaded** into every turn so the agent knows you over time, no recall tool needed. **Emotion** — PAD affect tracked per conversation episode; Luna's tone and presence adapt, with an emotion-reactive avatar in the desktop client. |
| **Teamwork** | agents that **work as a team, not a tool** | A2A coalitions collaborate on a shared **Blackboard** through phased workflows (`incident_investigation`, `plan_verify`, `propose_critique_revise`, …) — agents hand off, critique, and revise each other's work. |
| **Accountability** | honest, governed, and **always learning** | Every reply auto-scored by a local Gemma 4 council (6 dimensions) and logged as an RL experience; a multi-provider review council (Claude · Codex · Gemma) adjudicates side-effecting actions; full agent governance via the ALM platform. |

### Orchestration — don't build agents, route to them

- **Multi-CLI runtime** — routes each task to **Claude Code, Codex, Gemini CLI, or GitHub Copilot CLI** (plus local OpenCode/Gemma for the free tier), with **autodetect + quota-fallback chaining** and a per-tenant default. Runs in an isolated `code-worker` pod via Temporal; creates branches and PRs with full traceability.
- **Alpha CLI is the kernel** — frontend → `alpha <verb>` (kernel) → thin internal API → MCP tools / memory / RL. The web `/dashboard`, Tauri, WhatsApp, and the `alpha` binary are **viewports, not implementations**. If a feature can't be expressed as `alpha <verb>`, the design is wrong. ([`docs/architecture/alpha_cli_kernel.md`](docs/architecture/alpha_cli_kernel.md))
- **Deterministic agent router** (zero LLM cost) maps channels/intents to skills before any model is touched.
- **Temporal** durable workflows across orchestration, code, and business task queues.

### Platform capabilities

- **Agent Lifecycle Management (ALM)** — ownership, status (draft→staging→production→deprecated), versioning + rollback, compliance audit log, hourly performance snapshots, Redis capability registry, RBAC, external-agent adapters (OpenAI Assistants, MCP, webhooks). ([`docs/plans/2026-04-18-agent-lifecycle-management-platform-plan.md`](docs/plans/2026-04-18-agent-lifecycle-management-platform-plan.md))
- **Dynamic Workflows** — JSON-defined workflows interpreted at runtime by one executor; ReactFlow visual builder; **35 native templates**; step types incl. `cli_execute`, `human_approval`, `internal_api`. ([`docs/plans/2026-04-03-dynamic-workflows-visual-builder-design.md`](docs/plans/2026-04-03-dynamic-workflows-visual-builder-design.md))
- **Skills Marketplace v2** — file-based library (`_bundled/` + `_tenant/<uuid>/`), Claude-Code-format `SKILL.md`, four engines (python/shell/markdown/tool), pgvector auto-trigger, audited to `library_revisions`.
- **90+ MCP tools** (FastMCP over SSE) — ads, analytics, calendar, connectors, data, devices, drive, email, github, jira, knowledge, reports, sales, shell, skills, webhooks, and more. Auth via `X-Internal-Key` + `X-Tenant-Id`.
- **Knowledge graph + vector search** — lead scoring, entity extraction, semantic search, memory-activity audit log.
- **Proactive monitors** — Inbox Monitor (Gmail/Calendar triage), Competitor Monitor (ad libraries + web): long-running per-tenant Temporal workflows.
- **Multi-tenant** — every model is `tenant_id`-scoped; JWT-secured; per-tenant branding, feature flags, and a Fernet-encrypted integration credential vault.

---

## Viewports

### Alpha Control Center — web `/dashboard`

A VSCode/Cursor-style IDE shell (`apps/web/src/pages/DashboardControlCenter.js`) — conversation-first, laid out like an editor.

```
┌──────────────────────────────────────────────────────────────────────┐
│ TitleBar · session · ⚡ A2A · ⌘K · Pro/Simple · user ▾               │
├────────────┬─────────────────────────────────────┬───────────────────┤
│ Chats │    │ EditorArea (1..4 chat groups)       │ AgentActivityPanel│
│ Files      │ side-by-side splits; focused group  │ live v2 SSE feed  │
├────────────┴─────────────────────────────────────┴───────────────────┤
│  TerminalCard — auto-opens on cli_subprocess_stream; tab per CLI      │
└──────────────────────────────────────────────────────────────────────┘
```

Left card toggles **Chats ↔ Files** (workspace tree, tenant + platform scopes). Up to 4 editor groups, each its own session. Inline CLI picker, ⌘K palette, ⚡ A2A trigger, single shared SSE via `SessionEventsContext`, live terminal rendering the full CLI transcript. Full doc: [`docs/architecture/dashboard.md`](docs/architecture/dashboard.md).

**Workspace persistence** — every tenant gets a durable filesystem subtree (`/var/agentprovision/workspaces/<tenant_id>/`) mounted into both `api` and `code-worker`. Memory, plans, and cloned repos survive restarts, rebuilds, and deploys. Kernel verbs: `alpha workspace tree | read | clone`. ([`docs/architecture/workspace.md`](docs/architecture/workspace.md))

### Luna — native desktop client

A native Tauri 2.0 macOS menu-bar app (`apps/luna-client`): system tray, `Cmd+Shift+Space` command palette, SSE-streamed chat, emotion-reactive `LunaAvatar`, episodic memory panel, screenshot capture, trust-gated local actions, and a `Cmd+Shift+L` **Spatial HUD** (transparent Three.js knowledge nebula + MediaPipe hand tracking). PWA fallback; auto-updates via GitHub Releases.

```bash
cd apps/luna-client && npm install
VITE_API_BASE_URL=http://localhost:8000 npm run tauri dev      # dev (hot reload)
```

### `alpha` — terminal client

Terminal-native counterpart to Luna — same backend, agents, and skills, but scriptable (`--json`), CI-friendly, with OS-keychain tokens. Orchestrates the leaf CLIs rather than competing with them: durable runs (terminal-close-safe), fanout/consensus, cost attribution, team RBAC, A2A coalitions, memory-aware sessions, governance policies.

```bash
curl -fsSL https://agentprovision.com/install.sh | sh
alpha login                                       # token in keychain
alpha status --runtimes                           # auth + preflight every CLI runtime
alpha chat send "what shipped this week?"         # streaming reply
alpha workflow run incident_investigation --json  # dispatch a dynamic workflow
```

Full reference: [`docs/cli/README.md`](docs/cli/README.md) · roadmap: [`docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`](docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md).

### Channels

WhatsApp (Neonize — durable validated sessions that survive restarts without a QR re-pair, plus live typing presence) and Microsoft Teams (Graph + `TeamsMonitorWorkflow`) hit the **same agents** as web and terminal. Every channel is a viewport onto one orchestrator.

---

## Architecture

```
Internet ─▶ Cloudflare Tunnel ─▶ agentprovision.com (web + API) · luna.agentprovision.com

┌─ Channels:  Web /dashboard · Luna Desktop · alpha CLI · WhatsApp · Teams ──────────┐
└──────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─ FastAPI backend ─────────────────────────────────────────────────────────────────┐
│  Agent Router (0 LLM) · Session Manager · Memory (recall/record/ingest)            │
│  Auto Quality Scorer (Gemma 4, 6-dim → RL) · ALM · A2A Blackboard + CoalitionWF    │
└──────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─ Temporal workers ────────────────────────────────────────────────────────────────┐
│  code queue:  Claude Code │ Codex │ Gemini │ Copilot  (isolated code-worker pod)   │
│  orchestration queue:  monitors · coalitions · dynamic workflows · snapshots       │
└──────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
   MCP tools (FastMCP, 90+) · PostgreSQL + pgvector · Redis · Ollama (Gemma 4, host GPU)
   Rust gRPC: embedding-service (:50051) · memory-core (:50052)
```

**Flow:** Chat → Agent Router → Memory Recall (pre-loaded context) → Temporal → code-worker (CLI fleet) → MCP tools → response → async entity/commitment extraction. Every response auto-scored by a local Gemma 4 council; all scores logged as RL experiences. **Performance** (2026-04-10 baseline): API ~80 ms, chat p50 ~5.5 s.

Full architecture, models, services, and dev commands: [`CLAUDE.md`](CLAUDE.md).

---

## Quick start

```bash
# 1. Secrets (all three required — no defaults). Generate: python -c "import secrets; print(secrets.token_hex(32))"
#    Set SECRET_KEY, API_INTERNAL_KEY, MCP_API_KEY in apps/api/.env

# 2. Start the full stack (docker compose — primary local runtime)
docker compose up -d --build
# Apply DB migrations — see apps/api/migrations/README.md

# Web:    http://localhost:8002   (or agentprovision.com via tunnel)
# API:    http://localhost:8000/api/v1/
# Luna:   http://localhost:8009
# Demo:   test@example.com / DemoPass123!   (local/dev only)
```

**Connect your CLI:** Integrations → connect Claude Code / Codex / Gemini / Copilot (each uses *your* subscription). Then chat via web, WhatsApp, Luna, or `alpha chat repl` — every channel reaches the same agents, and every reply is auto-scored for RL.

Production deploy: [`docs/KUBERNETES_DEPLOYMENT.md`](docs/KUBERNETES_DEPLOYMENT.md) · local K8s: `./scripts/deploy_k8s_local.sh`.

---

## Stack

FastAPI · React 18 · Tauri 2.0 (Rust) · Three.js + Framer Motion · PostgreSQL + pgvector · Temporal · Redis · FastMCP · Ollama (Gemma 4) · Rust gRPC (embedding + memory-core) · Neonize (WhatsApp) · Cloudflare Tunnel · Docker Compose (local) / Helm on Rancher Desktop (prod-path) · nomic-embed-text-v1.5.

## Documentation

| Where | What |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **Source of truth** — full architecture, models, services, dev commands, patterns |
| [`docs/architecture/alpha_cli_kernel.md`](docs/architecture/alpha_cli_kernel.md) | "Every feature through Alpha CLI" — principle, examples, anti-patterns |
| [`docs/architecture/dashboard.md`](docs/architecture/dashboard.md) | Alpha Control Center `/dashboard` — IDE shell, panes, height chain |
| [`docs/architecture/workspace.md`](docs/architecture/workspace.md) | Durable per-tenant workspace volume |
| [`docs/changelog/`](docs/changelog/) | Weekly digests of shipped features |
| [`docs/plans/`](docs/plans/) | Design docs + implementation plans (dated, per feature) |
| [`docs/report/`](docs/report/) | Security audits, pentest verifications, health reports |
| [`docs/cli/README.md`](docs/cli/README.md) | `alpha` CLI reference |

---

*Orchestrates Claude Code · Codex · Gemini CLI · GitHub Copilot CLI. Built on FastAPI · React · Tauri · MCP · Temporal · Ollama · pgvector · Neonize · Cloudflare.*
