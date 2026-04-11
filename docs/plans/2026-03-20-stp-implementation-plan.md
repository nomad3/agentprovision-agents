# STP Implementation Plan — From Orchestration Layer to Distributed Agent Network

> Master plan covering Gemini CLI integration, Wolfpoint.ai rebrand, and the full AgentProvision Protocol (STP) build-out — incorporating all recent code changes as foundation.

**Date:** 2026-03-20
**Status:** Plan
**Author:** Simon Aguilera + Luna (Claude Opus 4.6)

---

## Current State (What's Already Built)

### Last 72 Hours of Shipping

| Commit | Feature | STP Relevance |
|--------|---------|---------------|
| `f715092` | Local ML inference — Ollama + auto-quality scorer | **Quality Engine** — auto-scores every response, feeds RL without manual ratings |
| `d2b38c4` | Knowledge backfill + local ML training plan | **Knowledge Foundation** — roadmap to 700+ entities, 4K+ observations |
| `8d1e400` | Codex CLI integration | **Multi-CLI** — 2nd CLI platform live (Claude Code + Codex) |
| `a78c1d2` | Full RL & memory distributed system (12 tasks) | **RL Core** — semantic recall, entity history, observations, quality tracking, consolidation workflows |
| `af0a95b` | Git history tracking + PR rewards | **Delayed Rewards** — RL learns from PR merge outcomes |
| `fcc01db` | MCP server connectors | **Tool Network** — nodes can connect external MCP servers |
| `1e82523` | Universal webhook connectors | **Event Mesh** — inbound/outbound webhooks for inter-node events |

### Existing Infrastructure That Transfers to STP

| Component | Status | STP Role |
|-----------|--------|----------|
| CLI Session Manager (`cli_session_manager.py`) | ✅ Platform-agnostic | Becomes Agent Runner on each node |
| Agent Router (`agent_router.py`) | ✅ RL-powered routing | Becomes RL Task Router |
| 81 MCP tools (FastMCP, port 8087) | ✅ Running | Ships with every node |
| Skill marketplace (70+ skills) | ✅ 3-tier system | Seeds Agent Registry |
| RL experience system | ✅ Full pipeline | Becomes Quality Scoring Engine |
| Temporal workflows (4 queues) | ✅ Durable execution | Distributed task execution backbone |
| OAuth credential vault (Fernet) | ✅ Encrypted | Stays local per node — never shared |
| Knowledge graph + pgvector | ✅ Per-tenant | Pull-on-demand for remote nodes |
| Embedding service (nomic-embed-text) | ✅ Local, no API key | Runs on every node |
| Auto-quality scorer (Ollama) | ✅ Local ML | Zero-cost quality signals on every node |
| Helm charts | ✅ K8s-ready | Adapt for K3s multi-node |
| Cloudflare Tunnel | ✅ Single origin | Expand to multi-origin failover |

---

## Phase 0: Gemini CLI Integration (Week 1)

> **Goal:** Third CLI platform live. All three target platforms operational.

### Prerequisites
- Design doc exists: `2026-03-15-cli-orchestration-pivot-design.md`
- CLI session manager already platform-agnostic
- Codex integration pattern established (auth flow → credential vault → Temporal activity)

### Tasks

#### 0.1 — Gemini CLI Auth Flow
**Files:** New `apps/api/app/api/v1/gemini_auth.py`
- API endpoint `POST /api/v1/integrations/gemini-cli/configure`
- Accept Google API key (free tier) or OAuth token
- Store via credential vault (`integration_name="gemini_cli"`)
- Test endpoint to verify key validity

#### 0.2 — Gemini CLI Execution Activity
**Files:** `apps/code-worker/workflows.py`
- Add `_execute_gemini_chat()` method to `ChatCliWorkflow`
- Command: `gemini --prompt "{message}"` with MCP config
- Environment: `GOOGLE_API_KEY` or `GEMINI_API_KEY` from vault
- Handle Gemini-specific output format (parse response)

#### 0.3 — CLI Session Manager Update
**Files:** `apps/api/app/services/cli_session_manager.py`
- Add `"gemini_cli"` to `SUPPORTED_CLI_PLATFORMS`
- Add Gemini-specific credential fetching in `_get_cli_platform_credentials()`
- Generate Gemini-compatible MCP config (if format differs)

#### 0.4 — Agent Router Gemini Support
**Files:** `apps/api/app/services/agent_router.py`
- Remove `# Future: gemini_cli` placeholder
- Add Gemini to platform selection logic
- Route data/analytics tasks to Gemini (cost-sensitive, bulk ops)

#### 0.5 — Frontend Integration Card
**Files:** `apps/web/src/components/IntegrationsPanel.js`
- Add Gemini CLI card with API key input
- Show connection status + test button
- Match existing Codex card pattern

#### 0.6 — Code Worker Dockerfile
**Files:** `apps/code-worker/Dockerfile`
- Install Gemini CLI binary
- Verify `gemini --version` in build

**Deliverable:** All 3 CLI platforms (Claude Code, Codex, Gemini CLI) operational end-to-end.

---

## Phase 1: Wolfpoint.ai Rebrand (Week 1-2, parallel with Phase 0)

> **Goal:** Platform identity transitions from AgentProvision to Wolfpoint.ai.

### Tasks

#### 1.1 — Domain & Tunnel Configuration
- Add `wolfpoint.ai` to Cloudflare Tunnel config
- Keep `agentprovision.com` as redirect/alias during transition
- Update DNS records

#### 1.2 — Frontend Rebrand
**Files:** `apps/web/src/`
- Replace AgentProvision logo/branding with Wolfpoint wolf + wave identity
- Update `<title>`, favicon, meta tags
- Update marketing landing page copy
- Apply to both light and dark mode variants

#### 1.3 — Backend References
**Files:** Various
- Update API response headers/branding
- Update email templates (sender name, footer)
- Update WhatsApp business profile name
- PR body templates in code-worker

#### 1.4 — Documentation & CLAUDE.md
- Update CLAUDE.md project overview
- Update README references
- Keep old domain references in comments for redirect mapping

#### 1.5 — CI/CD & Infrastructure
- Update GitHub Actions workflow names/descriptions
- Update Helm chart metadata
- Update Cloudflare Tunnel routes

**Deliverable:** `wolfpoint.ai` serves the platform. `agentprovision.com` redirects.

---

## Phase 2: STP Foundation — Node Daemon + Agent Packages (Weeks 2-4)

> **Goal:** First multi-node deployment. Your MacBook + gaming laptops run as a cluster with automatic failover.

### 2.1 — Node Daemon MVP

#### 2.1.1 — Daemon Core
**New directory:** `apps/node-daemon/`
**Language:** Python first (fast iteration), rewrite to Go/Rust in Phase 4

```
apps/node-daemon/
├── daemon.py              # Main loop: register → heartbeat → accept tasks
├── capability_probe.py    # Detect OS, RAM, GPU, CLI tools, LLM subscriptions
├── agent_runner.py        # Download agent package → set up CLI session → execute
├── metric_reporter.py     # Execution time, success rate, resource usage
├── config.yaml            # Operator settings
├── requirements.txt
└── Dockerfile
```

**daemon.py responsibilities:**
- Register with Registry Service on startup (POST `/api/v1/nodes/register`)
- Heartbeat every 30s (POST `/api/v1/nodes/heartbeat`)
- Accept task assignments via Temporal (`stp-node-{node_id}` queue)
- Report results + metrics back to registry
- Graceful shutdown (deregister on SIGTERM)

#### 2.1.2 — Capability Probe
**File:** `apps/node-daemon/capability_probe.py`
- Detect: OS, CPU cores, RAM, GPU (nvidia-smi), disk space
- Detect installed CLIs: `claude --version`, `codex --version`, `gemini --version`
- Detect LLM subscriptions: check OAuth tokens in local vault
- Detect Docker availability (for sandboxed execution)
- Output: `NodeCapabilities` dataclass → sent to registry

#### 2.1.3 — Agent Runner
**File:** `apps/node-daemon/agent_runner.py`
- Download agent package from registry (content-addressed, SHA-256)
- Verify signature (Ed25519)
- Extract to local cache (`~/.wolfpoint/agents/{hash}/`)
- Set up CLI session using existing `cli_session_manager` patterns
- Execute via Temporal activity
- Return result + execution metrics

### 2.2 — Registry Service Extensions

#### 2.2.1 — Node Directory Model
**New file:** `apps/api/app/models/network_node.py`
```python
class NetworkNode(Base):
    id = Column(UUID, primary_key=True)
    tenant_id = Column(UUID, ForeignKey("tenants.id"))  # operator's tenant
    name = Column(String)
    tailscale_ip = Column(String)        # 100.x.x.x
    status = Column(String)              # online, suspect, offline
    last_heartbeat = Column(DateTime)
    capabilities = Column(JSONB)         # OS, RAM, GPU, CLIs, subscriptions
    max_concurrent_tasks = Column(Integer, default=3)
    current_load = Column(Float, default=0.0)
    pricing_tier = Column(String)        # economy, standard, premium
    total_tasks_completed = Column(Integer, default=0)
    avg_execution_time_ms = Column(Float)
    reputation_score = Column(Float, default=0.5)
```

#### 2.2.2 — Node Directory API
**New file:** `apps/api/app/api/v1/nodes.py`
- `POST /api/v1/nodes/register` — Node registration (internal, X-Internal-Key)
- `POST /api/v1/nodes/heartbeat` — Heartbeat update
- `GET /api/v1/nodes/` — List active nodes
- `GET /api/v1/nodes/{id}` — Node details + metrics
- `DELETE /api/v1/nodes/{id}` — Deregister node
- Mount in `routes.py`

#### 2.2.3 — Agent Package Format
**New file:** `apps/api/app/models/agent_package.py`
```python
class AgentPackage(Base):
    id = Column(UUID, primary_key=True)
    creator_tenant_id = Column(UUID, ForeignKey("tenants.id"))
    name = Column(String, unique=True)
    version = Column(String)             # semver
    content_hash = Column(String)        # SHA-256 of package
    signature = Column(Text)             # Ed25519 signature
    creator_public_key = Column(Text)    # Ed25519 public key
    skill_id = Column(UUID, ForeignKey("skills.id"), nullable=True)  # link to existing skill
    metadata = Column(JSONB)             # agent.yaml contents
    required_tools = Column(JSONB)       # list of MCP tool names
    required_cli = Column(String)        # claude_code, codex, gemini_cli, any
    pricing_tier = Column(String)        # simple, medium, heavy, premium
    quality_score = Column(Float, default=0.0)
    total_executions = Column(Integer, default=0)
    downloads = Column(Integer, default=0)
    status = Column(String)              # draft, published, suspended
```

#### 2.2.4 — Agent Package API
**New file:** `apps/api/app/api/v1/agent_packages.py`
- `POST /api/v1/agent-packages/publish` — Sign + upload package
- `GET /api/v1/agent-packages/` — Browse marketplace
- `GET /api/v1/agent-packages/{id}` — Package details
- `GET /api/v1/agent-packages/{id}/download` — Download package (content-addressed)
- `POST /api/v1/agent-packages/{id}/verify` — Verify signature
- Mount in `routes.py`

#### 2.2.5 — Migration
**New file:** `apps/api/migrations/048_network_nodes_agent_packages.sql`
- Create `network_nodes` table
- Create `agent_packages` table
- Indexes on status, quality_score, content_hash

### 2.3 — K3s Multi-Node Cluster

#### 2.3.1 — Tailscale Mesh Setup
- Install Tailscale on all operator machines
- Create Tailnet for Wolfpoint network
- Document join procedure: `tailscale up --authkey=<key>`
- All nodes get stable 100.x.x.x IPs

#### 2.3.2 — K3s Cluster Bootstrap
- K3s server on primary node (MacBook)
- K3s agents on secondary nodes (gaming laptops)
- Nodes join via Tailscale IPs (no port forwarding)
- Existing Helm charts adapt to K3s

#### 2.3.3 — PostgreSQL HA
- Primary on main node with synchronous streaming replication
- Secondary on backup node (hot standby)
- Automatic failover via Patroni or CloudNativePG

#### 2.3.4 — Cloudflare Tunnel Multi-Origin
- Primary tunnel on MacBook
- Secondary tunnel on gaming PC
- Cloudflare load balances / fails over automatically
- **Success metric:** Close MacBook lid → site stays up, zero data loss

### 2.4 — Task Router Enhancement

#### 2.4.1 — Multi-Node Routing
**File:** `apps/api/app/services/agent_router.py`
- Extend routing to consider node selection (not just CLI platform)
- Query `NetworkNode` table for available nodes
- Score: `agent_quality * 0.4 + node_capability * 0.2 + (1-load) * 0.2 + latency * 0.1 + price * 0.1`
- Dispatch to node-specific Temporal queue (`stp-node-{node_id}`)

#### 2.4.2 — Failover Logic
**File:** `apps/api/app/services/agent_router.py`
- Monitor heartbeats — mark nodes suspect after 60s, offline after 90s
- Re-queue tasks from offline nodes to healthy nodes
- Temporal's built-in retry handles in-flight task failover

**Phase 2 Deliverable:** Platform runs across 2+ machines. Closing laptop lid doesn't take down the site.

---

## Phase 3: Credit System + Marketplace (Weeks 5-8)

> **Goal:** Creators publish agents, users buy credits, revenue splits work.

### 3.1 — Credit Ledger

#### 3.1.1 — Credit Models
**New file:** `apps/api/app/models/credit.py`
```python
class CreditAccount(Base):
    id = Column(UUID, primary_key=True)
    tenant_id = Column(UUID, ForeignKey("tenants.id"), unique=True)
    balance = Column(Numeric(12, 4), default=0)       # current balance
    lifetime_earned = Column(Numeric(12, 4), default=0)
    lifetime_spent = Column(Numeric(12, 4), default=0)
    escrow_hold = Column(Numeric(12, 4), default=0)    # 24h dispute hold
    account_type = Column(String)                       # user, creator, operator, protocol

class CreditTransaction(Base):
    id = Column(UUID, primary_key=True)
    tenant_id = Column(UUID, ForeignKey("tenants.id"))
    amount = Column(Numeric(12, 4))
    transaction_type = Column(String)    # purchase, task_payment, creator_payout,
                                         # operator_payout, protocol_fee, refund, escrow_hold, escrow_release
    task_execution_id = Column(UUID, nullable=True)
    from_account_id = Column(UUID, ForeignKey("credit_accounts.id"), nullable=True)
    to_account_id = Column(UUID, ForeignKey("credit_accounts.id"), nullable=True)
    description = Column(String)
    created_at = Column(DateTime, server_default=func.now())
```

#### 3.1.2 — Credit Service
**New file:** `apps/api/app/services/credits.py`
- `purchase_credits(tenant_id, amount)` — Stripe checkout → add to balance
- `execute_task_payment(task_id, user_tenant, creator_tenant, operator_tenant, tier)` — Split 70/20/10
- `hold_escrow(transaction_id)` — 24h hold for disputes
- `release_escrow(transaction_id)` — Release after 24h if no dispute
- `process_refund(transaction_id)` — Refund from escrow
- `get_balance(tenant_id)` — Current balance
- `get_earnings(tenant_id, period)` — Creator/operator earnings

#### 3.1.3 — Stripe Integration
**New file:** `apps/api/app/api/v1/credits.py`
- `POST /api/v1/credits/purchase` — Stripe checkout session
- `POST /api/v1/credits/webhook` — Stripe webhook (payment confirmed → add credits)
- `GET /api/v1/credits/balance` — Current balance
- `GET /api/v1/credits/transactions` — Transaction history
- `GET /api/v1/credits/earnings` — Creator/operator earnings dashboard

#### 3.1.4 — Revenue Split Automation
- After every task execution, auto-split credits:
  - 70% → creator's `CreditAccount`
  - 20% → operator's `CreditAccount`
  - 10% → protocol's `CreditAccount`
- Escrow: hold full amount for 24h, then release split

### 3.2 — Agent Marketplace

#### 3.2.1 — Publishing Flow
- Creator writes agent (skill editor or `stp agent publish ./my-agent/`)
- Ed25519 keypair generated on first publish (stored in credential vault)
- Package signed, hashed, uploaded
- Agent appears in marketplace with quality_score = 0

#### 3.2.2 — Marketplace UI
**New file:** `apps/web/src/pages/MarketplacePage.js`
- Browse agents by category, quality score, price tier
- Agent detail page: description, creator, quality score, execution count, reviews
- One-click execute: select agent → pay credits → run task
- Creator dashboard: published agents, earnings, quality trends

#### 3.2.3 — Quality Scoring from RL
**File:** `apps/api/app/services/agent_router.py` (extend)
- After every task, update `AgentPackage.quality_score`:
  ```
  quality_score = (
      success_rate * 0.3 +
      avg_user_rating * 0.3 +
      speed_percentile * 0.1 +
      recency_weight * 0.1 +
      log(execution_count) * 0.2
  )
  ```
- Agents below 0.3 quality score get delisted after 50+ executions
- Auto-quality scorer (Ollama) provides implicit ratings at zero cost

### 3.3 — Operator Dashboard

#### 3.3.1 — Operator UI
**New file:** `apps/web/src/pages/OperatorDashboardPage.js`
- Node health: status, uptime, CPU/RAM/GPU usage
- Task metrics: completed, failed, avg execution time
- Earnings: daily/weekly/monthly, per-agent breakdown
- Settings: max concurrent tasks, pricing tier, which CLIs to offer

**Phase 3 Deliverable:** Someone publishes an agent, someone else pays credits to use it, revenue splits automatically.

---

## Phase 4: Open Network (Weeks 9-12)

> **Goal:** Anyone can download the node daemon and join as an operator.

### 4.1 — Public Node Registration
- Downloadable node daemon binary (Docker image + native binary via Go rewrite)
- `wolfpoint node start` → auto-probe → join network
- Node reputation scoring (task success rate, uptime, dispute rate)

### 4.2 — Raft Consensus
- Embedded Raft (hashicorp/raft or etcd) for registry replication
- Agent registry, node directory, credit balances replicated across all nodes
- Any node can read, leader handles writes
- No single point of failure for the registry

### 4.3 — Agent Ownership & Transfer
- Ed25519 keypair per creator
- Transfer: creator signs transfer message to new owner's public key
- Licensing: creator can sell execution rights without transferring ownership

### 4.4 — Dispute Resolution
- Users can dispute within 24h of task execution
- Credits refunded from operator's escrow
- Dispute rate affects operator reputation score
- Auto-resolve: if auto-quality score < 2/5, auto-refund

### 4.5 — Rate Limiting & Abuse Prevention
- Per-IP, per-account, per-node rate limits
- Anomaly detection: sudden spikes in task volume
- Node ban for consistently poor quality or disputes

### 4.6 — Node Daemon Rewrite (Go)
- Rewrite Python daemon to Go for single-binary distribution
- Cross-compile: macOS (arm64, amd64), Linux (arm64, amd64), Windows
- `curl -fsSL wolfpoint.ai/install | sh` installer

**Phase 4 Deliverable:** 5+ external operators, 10+ marketplace agents, self-sustaining network.

---

## Phase 5: Scale + Ecosystem (Month 4+)

### 5.1 — Agent Composition
- Agents that call other agents (meta-agents)
- Workflow marketplace: multi-step automations as products

### 5.2 — GPU Computing
- GPU detection in capability probe
- Image generation, fine-tuning tasks routed to GPU nodes
- Premium pricing for GPU tasks

### 5.3 — Enterprise Tier
- Dedicated nodes with SLA guarantees
- Private agent packages (not in public marketplace)
- Custom pricing and invoicing

### 5.4 — Mobile Operator App
- Monitor node health from phone
- Start/stop accepting tasks
- View earnings in real-time

### 5.5 — API for Third Parties
- REST + WebSocket API for external integrations
- SDKs: Python, TypeScript, Go
- Agent submission API (CI/CD for agents)

---

## Dependencies & Sequencing

```
Phase 0 (Gemini CLI)  ──────────────┐
                                     ├──→ Phase 2 (STP Foundation)
Phase 1 (Wolfpoint Rebrand) ────────┘         │
                                              ▼
                                     Phase 3 (Marketplace + Credits)
                                              │
                                              ▼
                                     Phase 4 (Open Network)
                                              │
                                              ▼
                                     Phase 5 (Scale)
```

- **Phases 0 and 1** run in parallel (independent work)
- **Phase 2** depends on Phase 0 (all 3 CLIs needed for multi-node)
- **Phase 3** depends on Phase 2 (need nodes before marketplace makes sense)
- **Phase 4** depends on Phase 3 (need credits before opening to public)
- **Phase 5** is ongoing after Phase 4 launch

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Node daemon language (Phase 2) | Python | Fast iteration, rewrite to Go in Phase 4 |
| Consensus (Phase 4) | Raft (hashicorp/raft) | Battle-tested, same as etcd/K3s |
| Agent signing | Ed25519 | Fast, small keys, widely supported |
| Knowledge sync (multi-node) | Pull on demand (Phase 2), edge cache (Phase 4) | Start simple, optimize later |
| Networking | Tailscale mesh | NAT traversal, free tier, encrypted |
| Payments | Stripe + internal ledger | Proven, handles payouts via Connect |
| Task orchestration | Temporal (existing) | Already running, durable, proven |

---

## Risk Mitigation

| Risk | Mitigation | Phase |
|------|-----------|-------|
| LLM providers block subscription sharing | Multi-CLI support (3 providers), frame as personal hardware use | 0 |
| Cold start (no operators) | Bootstrap with own hardware (MacBook + gaming PCs) | 2 |
| Agent quality | Auto-quality scorer (Ollama) + RL feedback loop (already built) | 2 |
| Node unreliability | Multi-node redundancy, task re-queue on failure, reputation scores | 2 |
| Data privacy | Credentials never leave operator's machine, sandboxed execution | 2 |
| Payment fraud | 24h escrow, rate limiting, reputation scores | 3 |

---

## Success Metrics

| Phase | Metric | Target |
|-------|--------|--------|
| 0 | CLI platforms operational | 3/3 (Claude Code, Codex, Gemini) |
| 1 | Wolfpoint.ai live | Domain serving, old domain redirecting |
| 2 | Multi-node uptime | Close laptop lid → <90s failover, zero data loss |
| 3 | Marketplace activity | 1+ external agent published, 1+ paid execution |
| 4 | Network growth | 5+ operators, 10+ marketplace agents |
| 5 | Revenue | Protocol self-sustaining from 10% fee |

---

## Files to Create/Modify Summary

### New Files
| File | Phase | Description |
|------|-------|-------------|
| `apps/api/app/api/v1/gemini_auth.py` | 0 | Gemini CLI auth flow |
| `apps/node-daemon/` (directory) | 2 | Node daemon package |
| `apps/api/app/models/network_node.py` | 2 | Node directory model |
| `apps/api/app/models/agent_package.py` | 2 | Agent package model |
| `apps/api/app/api/v1/nodes.py` | 2 | Node API endpoints |
| `apps/api/app/api/v1/agent_packages.py` | 2 | Agent package API |
| `apps/api/migrations/048_network_nodes_agent_packages.sql` | 2 | DB migration |
| `apps/api/app/models/credit.py` | 3 | Credit ledger models |
| `apps/api/app/services/credits.py` | 3 | Credit service |
| `apps/api/app/api/v1/credits.py` | 3 | Credits API + Stripe |
| `apps/web/src/pages/MarketplacePage.js` | 3 | Marketplace UI |
| `apps/web/src/pages/OperatorDashboardPage.js` | 3 | Operator dashboard |

### Modified Files
| File | Phase | Change |
|------|-------|--------|
| `apps/code-worker/workflows.py` | 0 | Add `_execute_gemini_chat()` |
| `apps/code-worker/Dockerfile` | 0 | Install Gemini CLI |
| `apps/api/app/services/cli_session_manager.py` | 0 | Add gemini_cli to supported platforms |
| `apps/api/app/services/agent_router.py` | 0, 2 | Gemini routing + multi-node routing |
| `apps/web/src/components/IntegrationsPanel.js` | 0 | Gemini integration card |
| `apps/api/app/api/v1/routes.py` | 0, 2, 3 | Mount new routers |
| `apps/api/app/models/__init__.py` | 2, 3 | Register new models |
| `docker-compose.yaml` | 2 | Add node-daemon service |
| `apps/web/src/App.js` | 3 | Add marketplace + operator routes |
| `apps/web/src/components/Layout.js` | 3 | Add marketplace + operator nav items |
