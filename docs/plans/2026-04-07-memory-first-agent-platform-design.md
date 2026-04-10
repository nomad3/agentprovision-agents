# Memory-First Agent Platform — Design Document

**Status:** Draft
**Author:** Simon Aguilera (via brainstorming session with Claude)
**Date:** 2026-04-07
**Scope:** Core platform redesign around memory and workflow orchestration as the two product pillars.

---

## 1. Vision

agentprovision.com evolves into a **memory-first, Kubernetes-native, multi-agent, multi-source agentic orchestration platform** where memory and workflow orchestration are the two product pillars. Every other subsystem — chat, MCP tools, CLI runtimes, WhatsApp, web UI, integrations — is an interface layered on those two pillars.

The platform is optimized for:

1. **Low-latency conversational interfaces** (<2s fast path for ~70% of turns)
2. **Enterprise on-prem adoption** — each customer (Integral, Levi's, HealthPets, future tenants) runs the platform inside their own K8s cluster with data sovereignty
3. **Multi-agent specialization** — many agents (Luna, Sales, Data Analyst, Code, SRE, Support, Marketing Analyst, Vet Cardiac, etc.) sharing a coherent memory substrate with clean access-control boundaries
4. **Multi-source ingestion** — chat, email, calendar, Jira, GitHub, ads platforms, scraped web data, voice notes, uploaded documents, PostgreSQL, devices, MCP servers, inbox monitor — all feeding one canonical memory layer
5. **Rust where it earns its place** — embedding service from day one, memory-core extraction in Phase 2, federation daemon in Phase 4

The ultimate product story: **"Enterprise agentic orchestration with a memory-first architecture, Rust core, deployed on Kubernetes."**

---

## 2. Goals and Non-Goals

### Goals

1. **Luna thinks like a human.** Memory is always on and pre-loaded into the model's context before it sees the user's turn. No explicit "recall tool" that Luna has to remember to call. Relevant entities, past conversations, commitments, goals, world state, and episodes surface automatically.

2. **Conversational latency that works.** Fast path under 2 seconds end-to-end for ~70% of turns (greetings, simple Q&A, quick recalls, acknowledgments). Slow path 5–15 seconds for the 30% of turns that need actual tool orchestration.

3. **Enterprise-grade deployment.** K8s-native from day one. Each customer runs their own cluster. Data stays in-cluster. Helm charts ship the whole platform. Installation is one `helm install` + OAuth configuration.

4. **Multi-agent memory with proper scoping.** Every agent sees tenant-wide memory plus its own scoped memory. Safety/trust policies govern cross-agent access. No cross-tenant leakage under any circumstances.

5. **Multi-source ingestion with attribution.** Every memory record knows its source (chat, email, calendar, etc.), source ID (for deduplication), ingestion time, and confidence. Disputes between sources are reconciled and surfaced transparently.

6. **Auditability and durability.** All non-trivial memory mutations run as Temporal workflows. You can replay, retry, and audit every write operation.

### Non-Goals (in this design)

- **No full event-sourcing rewrite.** Existing tables stay. No new event log table — the existing `memory_activities` audit log is extended with workflow attribution columns. See §4.4.
- **No rewrite of existing Temporal workflows.** Business workflows (`DynamicWorkflowExecutor`, `CodeTaskWorkflow`, `DealPipelineWorkflow`, etc.) continue unchanged. They gain memory access via a new gRPC API.
- **No MemGPT-style hierarchical memory paging.** Our three-layer model (working / episodic / semantic) is sufficient.
- **No decentralized marketplace in Phases 1–3.** Phase 4 introduces cluster federation. Marketplace economics (creator/operator revenue splits) are a separate future spec.
- **No Rust rewrite of the whole stack.** Only memory-core, embedding-service, and (later) the federation daemon are Rust. Python stays for API, workflows, and business logic.
- **No dependency on Claude Code CLI's `--resume` flag.** Session continuity is the platform's responsibility via chat-runtime pods and the memory layer. We intentionally killed `--resume` and will not re-enable it.

---

## 3. Architecture Overview

### 3.1. The three pillars

1. **Memory layer** — canonical store of everything the platform knows. Exposes a read API (`recall`) and small sync write API (`record_*`). Large or expensive writes happen via memory workflows. Rust core in Phase 2; Python in Phase 1.

2. **Workflow orchestration (Temporal)** — the execution substrate for all durable, async, retriable operations. Three categories of workflow:
   - **Ingestion workflows** — pull external data into memory (per source)
   - **Memory workflows** — process memory (extraction, summarization, reconciliation, consolidation)
   - **Business workflows** — user-defined dynamic workflows that read memory and orchestrate actions (existing subsystem, unchanged)

3. **Runtime layer** — the agents themselves. `chat-runtime` pods run warm Claude CLI processes. `code-worker` runs coding tasks. Future runtimes (local Gemma4, OpenCode, other CLIs) plug into the same pattern.

### 3.2. High-level component diagram

```
                            ┌─── K8s Cluster (per tenant) ───────┐
┌──────────────┐            │                                     │
│  External    │            │  ┌──────────┐   ┌─────────────┐     │
│  Sources     │            │  │          │   │             │     │
│  • chat      │────────────┼─►│ api      │──►│ chat-runtime│     │
│  • email     │            │  │ (Python) │   │ Deployment  │     │
│  • calendar  │            │  │          │   │ (warm Claude│     │
│  • jira      │            │  └────┬─────┘   │  CLI pool)  │     │
│  • github    │            │       │ gRPC    └─────────────┘     │
│  • ads       │            │       │              ▲              │
│  • scraper   │            │       ▼              │              │
│  • upload    │            │  ┌──────────┐        │              │
│  • voice     │            │  │ memory-  │────────┘              │
│  • sql       │            │  │ core     │  gRPC                 │
│  • devices   │            │  │ (Rust P2)│                       │
│  • inbox     │            │  └────┬─────┘                       │
│  • mcp       │            │       │                             │
│    servers   │            │       │ SQL                         │
└──────────────┘            │       ▼                             │
                            │  ┌──────────┐   ┌─────────────────┐ │
                            │  │ postgres │   │ temporal        │ │
                            │  │+pgvector │   │ workers:        │ │
                            │  └──────────┘   │ • ingestion     │ │
                            │                 │ • memory        │ │
                            │                 │ • business      │ │
                            │                 │ • code          │ │
                            │                 └─────────────────┘ │
                            │                                     │
                            │  ┌──────────┐   ┌─────────────────┐ │
                            │  │embedding-│   │ ollama          │ │
                            │  │ service  │   │ (gemma4, nomic) │ │
                            │  │ (Rust P1)│   │ GPU node / host │ │
                            │  └──────────┘   └─────────────────┘ │
                            │                                     │
                            │  ┌──────────┐                       │
                            │  │cloudflared│ (tunnel for external)│
                            │  └──────────┘                       │
                            └─────────────────────────────────────┘
                                        │
                                        │ (Phase 4: federation)
                                        ▼
                              [ Rust node daemon ]
                             cluster-to-cluster mesh
                             optional coordinator
```

### 3.3. Component responsibilities

**api (Python, existing, refactored)**
- FastAPI HTTP layer
- Auth, tenant management, OAuth flows, chat endpoints
- Pre-loads memory context on every chat request (via gRPC to memory-core)
- Dispatches ChatCliWorkflow to Temporal with session affinity
- Saves chat messages to DB and triggers PostChatMemoryWorkflow (async)
- No direct DB access for memory operations — always goes through memory-core

**memory-core (Rust Phase 2, Python Phase 1)**
- Exposes gRPC API: `Recall`, `Record`, `Embed`, `EmbedBatch`, `Rank`, `Reconcile`
- Owns embedding inference (via embedding-service in Phase 1, in-process in Phase 2)
- Owns vector search (pgvector queries)
- Owns ranking and scoping logic
- Owns entity resolution, deduplication, merge logic
- Owns world state reconciliation
- Postgres is the canonical store — memory-core is stateless
- Horizontally scalable

**embedding-service (Rust, Phase 1)**
- Thin Rust service shipping from Phase 1
- gRPC API: `Embed(text) → vector`, `EmbedBatch(texts) → vectors`, `Health()`
- Model: `nomic-embed-text-v1.5` via `candle` (or `ort` — decide in Phase 1 kickoff benchmark)
- 2–5x faster than Python sentence-transformers
- First Rust service in production, template for memory-core extraction

**chat-runtime (new K8s Deployment, Phase 3a)**

This section was significantly tightened after review. An earlier draft said "warm Claude CLI subprocess per pod" which is architecturally wrong — `claude -p` is a one-shot process that exits after producing its response. There is no long-running CLI process to keep warm at the CLI level.

**What chat-runtime actually saves** (honest accounting):

1. **Container is already running** — no image pull, no pod schedule, no Python import cost. Spawning `claude -p` from an already-running container is ~100-300ms vs ~2-5s cold from a new pod.
2. **Node.js + Claude Code module warm in OS page cache** — the second invocation on a pod is faster because binary and dependencies are cached.
3. **OAuth token is pre-fetched and held in-memory** — first turn on a pod fetches the token; subsequent turns reuse it (within TTL, with refresh).
4. **MCP server connections are warm** — the pod maintains long-lived HTTP connections to `mcp-tools`; each `claude -p` call references these via `--mcp-config`.
5. **Filesystem is pre-populated** — `CLAUDE.md` template and `mcp.json` pre-written; per-turn changes are deltas, not full rewrites.

**Net per-turn saving: ~2s** (cold subprocess spawn + MCP handshake + token fetch → ~300-600ms warm). Not the "5-10s" the first draft implied. The bigger latency win comes from pre-loaded memory recall (avoiding round-trip MCP tool calls for recall during the turn), NOT from the pod warmth.

**A long-running CLI supervisor** (true single-process multi-turn via the Claude Agent SDK) is a separate architectural bet and is **out of scope for this spec**. Phase 4+ may add a `long-running-agent-supervisor` sub-design if the saving is worth the complexity.

Concrete Phase 3a shape:

- K8s Deployment with HPA on Temporal queue depth
- Each pod runs a Temporal worker on `agentprovision-chat` queue
- Worker is a Python supervisor that:
  - Receives `ChatCliActivity` from Temporal
  - Spawns `claude -p --no-session-persistence --mcp-config /config/mcp.json --append-system-prompt @/tmp/claude-md-{turn_id}.md` as a subprocess
  - Streams stdout back, returns the activity result
  - **Keeps no cross-request state in Python memory** (tenant isolation safety)
- **Session affinity**: same `chat_session_id` → same worker pod within session lifetime. **Primary approach**: Temporal session API. **Fallback**: Redis-backed sticky hash map (`session_id` → pod IP, lease TTL = session idle timeout). Prototype session affinity in Phase 3a kickoff; if Temporal API doesn't fit, switch to Redis-based sticky routing.
- OAuth token cache: per-pod, keyed by `(tenant_id, integration_name)`, TTL = token expiry. Cache miss → API internal endpoint.
- MCP connection pool: per-pod HTTP keepalive to `mcp-tools`.
- Tenant isolation: `--no-session-persistence`, per-call OAuth token via env, no disk writes, subprocess stdout cleared after each call.

**ingestion-worker (new Temporal worker)**
- Runs source ingestion workflows:
  - `ChatIngestionWorkflow` (per turn)
  - `EmailIngestionWorkflow` (triggered by inbox monitor, batch per sync)
  - `CalendarIngestionWorkflow`
  - `JiraIngestionWorkflow`
  - `GitHubIngestionWorkflow`
  - `AdsIngestionWorkflow` (Meta, Google, TikTok)
  - `ScraperIngestionWorkflow` (competitor monitor)
  - `UploadIngestionWorkflow`
  - `VoiceIngestionWorkflow`
  - `SqlIngestionWorkflow`
  - `DeviceIngestionWorkflow`
- Each workflow calls a source adapter, converts raw events into `MemoryEvent`s, writes via memory-core

**memory-worker (new Temporal worker)**
- Runs memory processing workflows:
  - `PostChatMemoryWorkflow` — after every chat turn
  - `EpisodeWorkflow` — rolling conversation summaries
  - `NightlyConsolidationWorkflow` — cron, per tenant
  - `EntityMergeWorkflow` — on-demand
  - `WorldStateReconciliationWorkflow` — on-demand

**business-worker (existing Temporal worker)**
- Runs user-defined dynamic workflows (`DynamicWorkflowExecutor`)
- Runs legacy static workflows (DealPipelineWorkflow, etc.)
- Reads memory via memory-core gRPC (no DB access)
- No changes to business logic

**code-worker (existing Temporal worker)**
- Runs `CodeTaskWorkflow` for long coding tasks
- Runs `ChatCliWorkflow` until Phase 3 migration to chat-runtime
- `ProviderReviewWorkflow` stays here

### 3.4. Decommissioning map for existing files

Explicit fate of every file in the current memory/chat path. Prevents ambiguity during implementation.

| File | Current role | Phase 1 action |
|---|---|---|
| `apps/api/app/services/chat.py` | Chat HTTP handler, history building, session memory | **Refactor**: becomes thin HTTP layer that calls `memory.recall()` and dispatches workflow. History building moves to memory package. |
| `apps/api/app/services/cli_session_manager.py` | Builds CLAUDE.md, dispatches ChatCliWorkflow | **Refactor**: `generate_cli_instructions()` stays, but memory context injection moves to calling `memory.recall()` instead of assembling from multiple services. Hardcoded brain-gap blocks stay removed. |
| `apps/api/app/services/enhanced_chat.py` | In-use — `EnhancedChatService`, imported by `apps/api/app/api/v1/chat.py` and `test_whitelabel.py`. | **Keep**. Refactor only to consume `memory.recall()` for context, don't delete. |
| `apps/api/app/services/context_manager.py` | Conversation summarization, token counting | **Refactor**: token counting stays as utility; conversation summarization moves into `EpisodeWorkflow`. |
| `apps/api/app/services/commitment_extractor.py` | Currently a no-op stub (disabled yesterday) | **Delete** in Phase 1. Replaced by `PostChatMemoryWorkflow.detect_commitment` Gemma4 activity. |
| `apps/api/app/services/memory_recall.py` | Builds memory context blob for CLI prompt | **Delete** in Phase 1. Logic moves into `memory.recall()` in the new package. |
| `apps/api/app/services/agent_router.py` | Routes incoming messages to agent/platform | **Keep**, gains one line: it now calls `memory.recall()` before dispatching and passes the result through. |
| `apps/api/app/services/knowledge.py` | CRUD over knowledge graph | **Keep as thin wrapper**; `memory.record_*` delegates to it in Phase 1. In Phase 2 the memory-core Rust service replaces it. |
| `apps/api/app/services/commitment_service.py` | CRUD over commitments | **Keep**; memory-core wraps it. |
| `apps/api/app/services/goal_service.py` | CRUD over goals | **Keep**; memory-core wraps it. |
| `apps/api/app/services/session_journals.py` | Half-wired episode synthesis | **Refactor into** the new `EpisodeWorkflow`; delete the direct-call wiring in `cli_session_manager.py`. |
| `apps/api/app/services/behavioral_signals.py` | Half-wired, disabled | **Refactor**: writer moves into `PostChatMemoryWorkflow.update_behavioral_signals` activity; reader stays as-is, called from `memory.recall()`. |

Everything else in `apps/api/app/services/` stays untouched in Phase 1.

---

## 4. Data Model

### 4.1. Existing schema inventory and reuse

**Two existing tables we were about to accidentally clobber** — this needs to be addressed explicitly because the first draft of this spec proposed a `session_journals` table that would have collided with one already in production.

| Table | Migration | Current shape | Intent | Our use |
|---|---|---|---|---|
| `conversation_episodes` | `075_add_conversation_episodes.sql` | `session_id FK`, `summary`, `key_topics JSONB`, `key_entities JSONB`, `mood`, `outcome`, `message_count`, `source_channel`, `embedding vector(768)`, HNSW index | Per-conversation episode records | **THIS is the episode table. Reuse and extend.** |
| `session_journals` | `083_add_session_journals.sql` | `period_start DATE`, `period_end DATE`, `period_type='week'`, `key_themes`, `key_accomplishments`, `key_challenges`, `mentioned_people`, `mentioned_projects`, `episode_count`, `message_count`, `embedding vector(768)` | Weekly rollup narrative | **Keep as-is, honestly a weekly rollup.** Generated by `NightlyConsolidationWorkflow.consolidate_weekly_theme`. |

**Decision**: reuse `conversation_episodes` as the episode layer. Add the fields our design needs via additive migration:

```sql
-- Migration 086_extend_conversation_episodes.sql
ALTER TABLE conversation_episodes
    ADD COLUMN IF NOT EXISTS agent_slug VARCHAR(100),
    ADD COLUMN IF NOT EXISTS window_start TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS window_end TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS trigger_reason VARCHAR(30),  -- 'window_full' | 'idle_timeout' | 'end_of_day' | 'manual'
    ADD COLUMN IF NOT EXISTS generated_by VARCHAR(50);    -- 'gemma4' | 'sonnet' | ...

-- Idempotency guard for trigger races (see §6.3)
CREATE UNIQUE INDEX IF NOT EXISTS uk_conv_episodes_session_window
    ON conversation_episodes(session_id, window_start, window_end)
    WHERE window_start IS NOT NULL;
```

The existing rows (no `window_start`) stay valid because the unique index is partial. All new rows created by `EpisodeWorkflow` get proper window boundaries.

`session_journals` as the weekly rollup stays where it is. `NightlyConsolidationWorkflow.consolidate_weekly_theme` writes into it (it's already half-wired per the audit).

**Renaming avoided on purpose** — `session_journals` is already referenced by `session_journal_service.py` which is half-wired. Renaming it breaks more than it fixes. The confusion is resolved by clear naming in code comments and the decommissioning map.

### 4.2. Embedding storage: inline columns vs generic table

The existing `embeddings` table (migration `042_add_pgvector_and_embeddings.sql`) provides generic `(content_type, content_id, embedding, text_content)` storage and is already used for several content types including `chat_message`. Some newer tables (`knowledge_observations`, `behavioral_signals`, `conversation_episodes`) added **inline** `embedding` columns instead.

**Choice for this design**: **use the generic `embeddings` table for chat messages, commitments, and goals**, and leave the existing inline columns on observations/signals/episodes alone.

Rationale:

- **Hot-path recall queries** (`recall` on a user turn) already need a JOIN anyway because they combine multiple content types. One JOIN per type from `embeddings` is fine at current scale and pushes the embedding storage into a single index rather than scattered per-table IVFFLAT indexes.
- **Cold/heterogeneous content** (random tool outputs, attachments, episode summaries) fits the generic pattern naturally — no schema change per new content type.
- **No migration needed on `chat_messages`, `commitment_records`, `goal_records`** — writes go to the `embeddings` table with `content_type = 'chat_message' | 'commitment' | 'goal'` and the appropriate `content_id`. Saves three migrations and keeps the existing schema thin.
- **Existing inline columns stay** — `knowledge_observations.embedding`, `behavioral_signals.embedding`, `conversation_episodes.embedding` are tightly coupled to their table and queried alongside the row's other fields. Moving them is net-negative churn.

This decision inverts the first draft of this spec (which proposed inline columns on `chat_messages` et al.) and aligns with the established house pattern. The trade-off is one JOIN per recall; we accept it for schema hygiene.

### 4.3. Table changes summary

All additive. No destructive migrations.

| Table | Change |
|---|---|
| `knowledge_entities` | No change (has embedding) |
| `knowledge_observations` | No change (has embedding) |
| `knowledge_relations` | No change |
| `chat_sessions` | No change |
| `chat_messages` | **No schema change.** Embeddings stored in `embeddings` table with `content_type='chat_message'`. |
| `commitment_records` | **No schema change.** Embeddings stored in `embeddings` table with `content_type='commitment'`. Add `visibility` + `visible_to` (§4.4). |
| `goal_records` | **No schema change.** Embeddings in `embeddings` table with `content_type='goal'`. Add `visibility` + `visible_to`. |
| `behavioral_signals` | Add `visibility` + `visible_to`. Inline embedding stays. |
| `world_state_assertions` | No change |
| `world_state_snapshots` | No change |
| `agent_memories` | Add `visibility` + `visible_to`. Inline `content_embedding` stays. |
| `memory_activities` | No change |
| `plans`, `plan_steps`, `plan_assumptions` | No change |
| `conversation_episodes` | **Extend** with `agent_slug`, `window_start`, `window_end`, `trigger_reason`, `generated_by` (migration 086). Unique index on `(session_id, window_start, window_end)`. |
| `session_journals` | No change. Weekly rollups only. Written by `NightlyConsolidationWorkflow`. |
| `embeddings` | No change. Reused for chat messages, commitments, goals. |

### 4.4. New tables

**We already have a `memory_activities` audit log** (from the audit in Section 15) and it covers most of what the first draft of this doc proposed as a new `memory_events` table. **Decision: drop `memory_events` from Phase 1 scope.**

Reasoning:

- The reviewer flagged (correctly) that the first draft sat in the worst of both worlds — paying the storage cost of an event log without building projections from it, and leaving audit coverage partial (sync writes had no `workflow_id`, async writes did).
- `memory_activities` already logs entity_created, entity_updated, relation_created, memory_created, action_triggered (from the audit). It's tenant-scoped and has an attribution field.
- Phase 1 can extend `memory_activities` with one new event type (`workflow_triggered_change`) if we need workflow attribution. That's cheaper and consistent.
- If we later want true event-sourcing (projections, replay, time-travel debugging), introduce it as a Phase 5 separate spec with proper scope. Not now.

**Action**: extend `memory_activities` with `workflow_id VARCHAR(200)` and `workflow_run_id VARCHAR(200)` columns (nullable) via an additive migration. Both memory-core sync writes and memory workflows populate them when the mutation happens inside a workflow context. Sync writes without a workflow context leave them NULL — which is honest about the provenance, not partial coverage.

No new `memory_events` table. No new index juggling. One less thing to maintain.

### 4.3. Existing columns that become first-class

Add to tables that currently store visibility implicitly:

- `knowledge_entities.visibility VARCHAR(20) DEFAULT 'tenant_wide'` (values: `tenant_wide`, `agent_scoped`, `agent_group`)
- `knowledge_entities.visible_to TEXT[]` (agent slugs, when `visibility = 'agent_group'`)
- Same pair added to: `commitment_records`, `goal_records`, `behavioral_signals`, `agent_memories`

`owner_agent_slug` already exists on most of these.

### 4.4. Backfill strategy for existing data

Current production state (as of 2026-04-07, tenant `0f134606`):
- 1,239+ chat messages in `chat_messages`
- 331+ entities in `knowledge_entities`
- 4,817+ observations in `knowledge_observations`
- 2,625+ RL experiences (not memory, but relevant for historical context)

None of the chat messages, commitments, or goals currently have embeddings. Without a backfill, the "recall past conversations" promise is broken for everything older than the Phase 1 rollout date.

**Backfill plan** (Phase 1 deliverable):

- `BackfillEmbeddingsWorkflow` (Temporal, per tenant, resumable)
  - Batches of 50 rows, throttled to respect embedding-service rate limits
  - Target: backfill 1,239 chat messages in ~2 minutes, 331 entities + 4,817 observations in ~5 minutes
  - Idempotent: skip rows where `embedding IS NOT NULL`
  - Progress reported via workflow heartbeat
- Entry point: `POST /internal/memory/backfill` (admin-only) or CLI command
- Runs automatically on first startup after Phase 1 deployment for each existing tenant

For really large historical datasets (100k+ chat messages), the workflow continues-as-new every 10k rows and emits progress events.

### 4.5. MemoryEvent (the canonical ingestion shape)

```python
@dataclass
class MemoryEvent:
    tenant_id: UUID
    source_type: str  # free-text discriminator, registered in source_adapter_registry
                      # known values: chat, email, calendar, jira, github, ads,
                      # scraper, upload, voice, sql, device, mcp, inbox_monitor
                      # New sources register themselves in the adapter registry
                      # without requiring a schema/enum migration.
    source_id: str                # raw source's native ID
    source_metadata: dict         # arbitrary source-specific metadata
    actor_slug: str | None        # agent or user that created the source data
    occurred_at: datetime         # when the event happened in the source
    ingested_at: datetime         # when we processed it
    kind: Literal["text", "structured", "media"]
    text: str | None              # for text-based events
    structured: dict | None       # for structured events
    media_ref: str | None         # for media (image, audio, file)
    proposed_entities: list[dict] # pre-extracted hints from the adapter
    proposed_observations: list[dict]
    proposed_relations: list[dict]
    proposed_commitments: list[dict]
    confidence: float             # adapter's initial assessment
    visibility: str               # default tenant_wide
```

Every source adapter takes raw source data and emits a list of `MemoryEvent` objects. The downstream write pipeline turns those into typed rows across the memory tables and writes `memory_activities` audit rows (with workflow attribution).

---

## 5. gRPC APIs

### 5.1. embedding-service (Rust, Phase 1)

```protobuf
syntax = "proto3";
package embedding.v1;

service EmbeddingService {
  rpc Embed(EmbedRequest) returns (EmbedResponse);
  rpc EmbedBatch(EmbedBatchRequest) returns (EmbedBatchResponse);
  rpc Health(google.protobuf.Empty) returns (HealthResponse);
}

message EmbedRequest {
  string text = 1;
  string task_type = 2;          // "search_query" | "search_document" | "classification"
}
message EmbedResponse {
  repeated float vector = 1;     // 768 floats for nomic-embed-text-v1.5
  string model = 2;
  int32 dimensions = 3;
}

message EmbedBatchRequest {
  repeated string texts = 1;
  string task_type = 2;
}
message EmbedBatchResponse {
  repeated EmbedResponse results = 1;
}

message HealthResponse {
  string status = 1;             // "ok" | "degraded" | "loading"
  string model = 2;
  int64 uptime_seconds = 3;
}
```

Ships in Phase 1 as a standalone Rust container. Deployed as a K8s Deployment with 2 replicas behind a ClusterIP service. The Python memory package calls it for all embedding operations.

### 5.2. memory-core (Rust Phase 2, Python Phase 1 with same API)

```protobuf
syntax = "proto3";
package memory.v1;

service MemoryCore {
  // Read
  rpc Recall(RecallRequest) returns (RecallResponse);
  rpc SearchConversations(SearchConversationsRequest) returns (SearchConversationsResponse);
  rpc GetCommitments(GetCommitmentsRequest) returns (GetCommitmentsResponse);
  rpc GetGoals(GetGoalsRequest) returns (GetGoalsResponse);
  rpc GetEntity(GetEntityRequest) returns (EntityResponse);

  // Write (sync)
  rpc RecordObservation(RecordObservationRequest) returns (ObservationResponse);
  rpc UpdateConfidence(UpdateConfidenceRequest) returns (google.protobuf.Empty);
  rpc RecordBehavioralSignal(RecordBehavioralSignalRequest) returns (BehavioralSignalResponse);

  // Write (ingestion — bulk)
  rpc IngestEvents(IngestEventsRequest) returns (IngestEventsResponse);

  // Admin
  rpc Health(google.protobuf.Empty) returns (HealthResponse);
}

message RecallRequest {
  string tenant_id = 1;
  string agent_slug = 2;           // applies visibility filter
  string query = 3;                // natural language query
  string chat_session_id = 4;      // for session-aware recall
  int32 top_k_per_type = 5;        // default 5
  int32 total_token_budget = 6;    // default 8000
  repeated string source_filter = 7; // optional: restrict to these sources
}

message RecallResponse {
  repeated EntitySummary entities = 1;
  repeated ObservationSummary observations = 2;
  repeated RelationSummary relations = 3;
  repeated CommitmentSummary commitments = 4;
  repeated GoalSummary goals = 5;
  repeated ConversationSummary past_conversations = 6;
  repeated EpisodeSummary episodes = 7;
  repeated WorldStateAssertion contradictions = 8;
  int32 total_tokens_estimate = 9;
  RecallMetadata metadata = 10;    // timing, scores, etc.
}

message IngestEventsRequest {
  string tenant_id = 1;
  repeated MemoryEvent events = 2;
  string workflow_id = 3;          // Temporal workflow id for audit trail
}
```

(Full IDL is extensive — abbreviated here. The implementation plan will include the complete `.proto` files.)

### 5.3. Backwards compatibility in Phase 1

In Phase 1, the Python `apps/api/app/memory/` package exposes the SAME API as the eventual Rust service, but implemented as Python function calls (not gRPC). This means:

- Python callers (api, temporal workers) call `memory.recall(...)` as a normal Python function
- In Phase 2, the Python package becomes a thin gRPC client that proxies to the Rust memory-core
- Business logic on top of memory doesn't know or care which backend is serving

This is the critical design constraint that makes Phase 2 a rewrite (not a re-architecture). Every Phase 1 Python function that will move to Rust is designed around the gRPC contract now.

---

## 6. Data Flow

### 6.1. Hot path: receiving a chat message

```
1. User message arrives at api (HTTP POST /chat/sessions/{id}/messages)
2. api authenticates, loads session, rolls back any poisoned DB state
3. api calls agent_router.route(message, session) → decides fast/slow path, selects agent [~30ms]
   └── If router says "trivial" (greeting, ack, short Q) → skip recall entirely
4. api calls embedding-service.Embed(message) via gRPC       [~20ms]
5. api calls memory.recall(tenant_id, agent_slug, message_embedding)
   ├── Python (Phase 1) or Rust gRPC (Phase 2)
   ├── pgvector queries in parallel: entities, observations,
   │   past_conversations, episodes, commitments, goals, world_state
   ├── Ranked by weighted score (semantic 0.55, recency 0.20,
   │   confidence 0.15, source_priority 0.10)
   ├── Filtered by agent visibility
   ├── Bounded by total token budget (default 4K — see §6.1.1)
   ├── SOFT timeout: 500ms (p99 target). If exceeded, proceed with
   │   what we have so far (degraded context).
   ├── HARD timeout: 1500ms. If exceeded, degrade to working-window-
   │   only (level 4 in §6.5 degradation ordering).
   └── Returns MemoryContext object                          [~80-200ms p50]
6. api builds CLAUDE.md with pre-loaded memory context
   (no tool call needed — it's all already there)
7. api dispatches ChatCliWorkflow to Temporal with session affinity
8. Temporal routes to a chat-runtime pod (same session → same pod)
   ├── Container is already running; spawns fresh `claude -p` subprocess
   ├── Pre-warmed OS cache, pre-fetched OAuth token, pre-established
   │   MCP connections → subprocess spawn cost ~300-600ms (not 2-5s)
9. Claude responds (Haiku for fast path, Sonnet for slow path)
10. Response streams back to api
11. api saves user message + assistant message to DB
12. api dispatches PostChatMemoryWorkflow (async, fire-and-forget)
    └── embedding of the user+assistant messages happens INSIDE this
        workflow, not inline. The turn returns to the user without
        waiting. Messages become recallable ~500ms-2s after the
        response (acceptable because the next turn is usually >5s away).
13. api returns HTTP 201 to user
```

### 6.1.1. Token budget for CLAUDE.md / system prompt

For a fast-path Haiku turn (200K context window):

| Component | Tokens (target) | Notes |
|---|---|---|
| Claude Code scaffolding (baseline system prompt, tool descriptions) | ~4,000 | Fixed cost from `claude -p` |
| Skill body (Luna persona, operating principles) | ~2,000 | From skill registry |
| MCP tool manifest (81 tools) | ~6,000 | From `mcp.json` — consider pruning to agent-scoped tool subset |
| **Pre-loaded memory context (from memory.recall)** | **~4,000** | **Budget for all recalled entities, observations, commitments, goals, episodes, past conversations** |
| Recent conversation history (last N messages, full-length, budget cap) | ~8,000 | Tenant-tuneable, cap via `max_history_tokens` setting |
| Current user message | ~200 | |
| Headroom (safety margin, tool call overhead) | ~10,000 | |
| **Total** | **~34,200** | Out of 200,000 — comfortable |

The first-draft "50K history budget" was too aggressive given the other fixed costs. **Revised to 8K** for history. With 4K for recall context + 8K for history, memory-related context is 12K of a ~34K total prompt — room to grow, headroom preserved.

**Action item (Phase 1)**: add instrumentation that logs the actual prompt size per turn so we can tune these caps against real traffic.

### 6.1.2. Latency budget (revised)

Honest budget for fast-path p50 <2s target, **conditional on Phase 3a warm chat-runtime pods**:

| Stage | Budget (fast path) | Notes |
|---|---|---|
| HTTP + auth + session load | 20ms | |
| Router decision | 30ms | Embedding + rule match |
| `embedding-service.Embed` | 20ms | Rust; Python ~30-50ms |
| `memory.recall` (SOFT 500ms, HARD 1500ms) | 150ms p50 / 500ms p99 | 6 pgvector queries in parallel |
| Temporal dispatch + session routing | 50ms | Session affinity lookup |
| **chat-runtime subprocess spawn** | **400ms** | **Warm pod assumption. Cold pod = +2-4s.** |
| Claude API inference (Haiku, no tool calls, short response) | 800ms | 50-200 output tokens |
| Response streaming + DB writes | 50ms | |
| **Fast-path p50 target** | **~1.5s** | Conditional on all above |
| **Fast-path p95 target** | **~3s** | Allows 500ms recall + 2s inference worst case |

**Slow path** (Sonnet, 1-3 tool calls, analytical response):

| Stage | Budget |
|---|---|
| Platform overhead (same as fast path) | ~700ms |
| Claude API inference (Sonnet, with thinking + tool calls) | 3-8s |
| Each tool call (MCP round-trip) | 500-1500ms |
| Response streaming + DB writes | 100ms |
| **Slow-path p50 target** | **~6-10s** |
| **Slow-path p95 target** | **~20s** |

**Pre-Phase-3a reality check**: With today's cold subprocess + per-message CLAUDE.md rebuild, fast-path p50 is realistically **4-8s**. The <2s target is **unlocked by Phase 3a**. Phase 1 and Phase 2 success criteria should use a **6s fast-path p50 target** and be re-baselined after Phase 3a ships.

### 6.2. Write path: PostChatMemoryWorkflow

Fires async after every turn. Runs on `memory-worker` Temporal worker.

```
PostChatMemoryWorkflow(tenant_id, chat_session_id, user_msg_id, assistant_msg_id):

  [Activity 1: extract_knowledge]
    - Load user + assistant message content
    - Call Gemma4 (via Ollama) with extraction prompt
    - Parse structured output: entities, observations, relations
    - Call memory.IngestEvents with the extracted items
    - Write to memory_activities audit log (with workflow_id)

  [Activity 2: detect_commitment]
    - Call Gemma4 with commitment classification prompt
    - Structured output: { is_commitment: bool, title, due_at, type }
    - If yes: memory.record_commitment (sync API)

  [Activity 3: update_world_state]
    - For each new observation, check against existing world_state_assertions
    - If conflict: create dispute, flag for reconciliation
    - If corroboration: increment corroboration_count, update confidence
    - If novel: create new assertion

  [Activity 4: update_behavioral_signals]
    - If previous assistant message contained a suggestion:
      - Check if user's current message confirms/denies acted_on
      - Update behavioral_signal row

  [Activity 5: maybe_trigger_episode]
    - Check if chat_session has ≥30 unsummarized messages
    - If yes: dispatch EpisodeWorkflow (child workflow)
```

Each activity is independent and retriable. Failures in one don't block the others. All are bounded by a 60-second timeout.

### 6.3. Episode workflow (trigger: N=30 OR idle=10min OR end-of-day)

```
EpisodeWorkflow(tenant_id, chat_session_id, window_start, window_end, trigger_reason):

  [Activity 1: fetch_messages]
    - Load all chat_messages in [window_start, window_end]

  [Activity 2: summarize_window]
    - Call Gemma4 with summarization prompt
    - Extract: summary text, key_entities, topics, sentiment

  [Activity 3: embed_and_store]
    - Embed summary text via embedding-service
    - Insert row into session_journals

  [Activity 4: link_entities]
    - For each entity mentioned in key_entities, update that entity's
      "recent_mentions" counter
```

Triggers are dispatched by:
- **N=30**: PostChatMemoryWorkflow activity 5 checks the count and signals
- **Idle=10min**: a periodic `IdleEpisodeScanWorkflow` (per tenant, continues-as-new every hour) sweeps for sessions idle ≥10 minutes
- **End-of-day**: a nightly cron workflow wraps up any remaining open windows

**Idempotency and race handling**: multiple triggers could fire for the same session window. The workflow ID is deterministic: `episode-{chat_session_id}-{window_start_iso}`. Temporal rejects duplicate workflow IDs, so only one of concurrent triggers wins. The `UNIQUE (chat_session_id, window_start, window_end)` constraint is a backstop against any race that slips through (different window boundaries are possible if triggers see different message counts). On conflict, the `idle` trigger yields to `N=30` (N wins because it has a tighter window).

### 6.4. Nightly consolidation workflow

Runs once per tenant per night (staggered to avoid thundering herd).

```
NightlyConsolidationWorkflow(tenant_id):

  [Activity 1: merge_duplicate_entities]
    - For each entity with low recall count, find semantic neighbors
    - If similarity > 0.95 and same category, merge with higher-confidence one
    - Create memory_activities audit entries

  [Activity 2: decay_old_confidences]
    - For assertions older than N days, apply exponential decay
    - Flag as "stale" if confidence drops below threshold

  [Activity 3: consolidate_weekly_theme]
    - Group last 7 days of episodes into a "weekly theme" summary
    - Store as a higher-level episode in session_journals

  [Activity 4: retrain_rl_policies]
    - Aggregate RL experiences from the last day
    - Update routing policies
    - Store updated policy snapshot
```

### 6.5. Failure modes and degradation strategy

| Failure | Detection | User-visible behavior | Recovery |
|---|---|---|---|
| **embedding-service down** | gRPC connection refused | Hot path falls back to keyword search (ILIKE on content). Degraded recall quality but no outage. | K8s liveness probe restarts pod; auto-heal. |
| **memory-core down** | gRPC timeout or connection refused | Chat degrades: system prompt gets only the 20-message window, no semantic recall. User sees "Luna is recalling less context right now" banner on the UI. | K8s restarts; memory is read-through from Postgres so no data loss. |
| **Gemma4 / Ollama down** | HTTP timeout on `/api/generate` | `PostChatMemoryWorkflow` activities (extraction, commitment classification, episode summary) retry with exponential backoff for 5 minutes, then fail and log. User-facing chat is unaffected (memory extraction is async). | Ollama native host process auto-restarts; workflow retries resume. |
| **PostChatMemoryWorkflow backed up** | Temporal queue depth > threshold | Older turns process late. Commitments/episodes may lag 5-30 minutes. | Per-tenant `max_concurrent_post_chat_workflows` cap (default 3). If cap hit, workflows queue rather than spawning unlimited. HPA on memory-worker scales up. |
| **Episode trigger collision** | Workflow ID conflict on `episode-{session_id}-{window_start}` | Loser gets a Temporal "already exists" error. No duplicate episodes created. | Idempotent workflow ID handles this automatically. |
| **Embedding service returns bad vector** (NaN, wrong dim) | Validation on receive | Skip embedding for that row, log warning, backfill later. | Retry via `BackfillEmbeddingsWorkflow`. |
| **Concurrent entity update race** | Postgres serialization failure | First writer wins, second retries with fresh read. | Use `SELECT ... FOR UPDATE` in memory-core for entity merges and reconciliation. |
| **Chat-runtime warm pod crashes mid-turn** (Phase 3+) | Temporal activity failure | Turn retries on a different pod, user sees 3-5s added latency (cold start). | HPA scales up replacement; K8s restarts dead pods. |
| **pgvector query timeout** | PostgreSQL statement_timeout | Chat falls back to keyword search for that turn; logs the slow query. | Index warmup + nightly `VACUUM ANALYZE`; consider HNSW over ivfflat if latency degrades. |
| **Memory recall returns contradictions** | `RecallResponse.contradictions` non-empty | System prompt includes "⚠ I have conflicting information about X from [source A] vs [source B]. The most recent is [winner]." Luna is instructed to mention the dispute if directly relevant. | Async `WorldStateReconciliationWorkflow` handles permanent resolution. |
| **Claude Code CLI version upgrade breaks chat-runtime** | Pod liveness probe fails / activity errors | Old pod continues serving traffic until new version is validated. | Version-pinned Docker image; upgrade via rolling Deployment update; rollback via helm. |

**Degradation ordering (hot path)**: if multiple systems are unhealthy, degrade in this order:
1. No episodes (skip `EpisodeWorkflow`) — user sees no morning briefing but chat works
2. No semantic recall (fall back to keyword) — Luna loses some recall quality
3. No memory extraction (skip `PostChatMemoryWorkflow` knowledge extraction) — graph doesn't grow
4. No memory at all (window-only, the 20 most recent messages) — Luna is "dumb" but functional
5. Full outage — 500 error

The chat API has a hard timeout of **3 seconds** on the `memory.recall` call. If recall hasn't returned, the chat proceeds with an empty memory context (degradation level 4 above) and the user still gets a response. Better to be dumb-but-fast than smart-but-hung.

---

## 7. Multi-Agent Scoping and Access Control

Every memory record has:

- `tenant_id` (hard boundary — **no cross-tenant reads under any circumstances**)
- `owner_agent_slug` (the agent that created the record, or NULL for shared writes)
- `visibility` enum: `tenant_wide` (default), `agent_scoped`, `agent_group`
- `visible_to TEXT[]` (list of agent slugs when visibility = `agent_group`)

### Recall rules

```python
def visible_records_for(agent_slug: str, records: Query):
    return records.filter(
        or_(
            records.c.visibility == "tenant_wide",
            and_(
                records.c.visibility == "agent_scoped",
                records.c.owner_agent_slug == agent_slug,
            ),
            and_(
                records.c.visibility == "agent_group",
                records.c.visible_to.contains([agent_slug]),
            ),
        )
    )
```

Applied at the memory-core query layer. Business logic above never filters — the memory API does it.

**Index plan** (required by Phase 1 migration 088):

```sql
-- Composite index for the common "tenant + tenant-wide or agent-scoped to me" query
CREATE INDEX idx_commitment_records_visibility
    ON commitment_records (tenant_id, visibility, owner_agent_slug);

-- GIN index for agent_group membership lookup
CREATE INDEX idx_commitment_records_visible_to
    ON commitment_records USING GIN (visible_to)
    WHERE visibility = 'agent_group';
```

Same pattern applied to `goal_records`, `behavioral_signals`, `agent_memories`, `knowledge_entities`. At today's scale (331 entities, 4817 observations) these are free; the indexes pay off once any tenant crosses 10k+ records. Worth paying upfront to avoid schema changes under load later.

### Examples

- **Shared knowledge** (Ray Aristy, Integral's business details, Levi's SRE agenda): `tenant_wide`. All agents in the tenant see it.
- **Agent-private memory** (Luna's conversation style preferences for this user, Sales Agent's follow-up cadence): `agent_scoped`, `owner_agent_slug = "luna"` or `"sales_agent"`.
- **Team memory** (SRE + DevOps share infrastructure observations, but Customer Support does not): `agent_group`, `visible_to = ["sre_agent", "devops_agent"]`.

### Cross-agent handoff

When Luna delegates to Code Agent, the chat session stays the same. Code Agent queries memory as `agent_slug = "code_agent"` and gets tenant_wide + its own scoped memory. No special "handoff context" mechanism needed — the memory layer IS the handoff context.

---

## 8. Multi-Source Ingestion

### 8.1. Source adapter contract

```python
class SourceAdapter(Protocol):
    source_type: str   # "email" | "calendar" | ...

    async def ingest(
        self,
        raw: Any,
        source_metadata: dict,
        tenant_id: UUID,
    ) -> list[MemoryEvent]: ...

    def deduplication_key(self, raw: Any) -> str: ...
```

Each adapter lives in `apps/api/app/memory/ingestion/adapters/`. One file per source. Adapters are pure functions: raw data in, MemoryEvents out. No side effects, no DB writes. The ingestion workflow handles the write path.

### 8.2. Source priority for implementation

From the brainstorming session (option E):

1. **Chat** (Phase 1) — highest priority, fixes Luna's current problem, proves the pattern
2. **Email** (Phase 3) — highest new business value, unlocks "Luna reads your inbox"
3. **Calendar, Jira, GitHub, Ads** (Phase 3) — structured, copy-paste of the chat adapter pattern
4. **Voice, Devices, Scraper, Upload, SQL, MCP** (Phase 4+) — exotic sources, new modality complexity

### 8.3. Example: chat adapter

```python
class ChatAdapter:
    source_type = "chat"

    async def ingest(self, raw_message: ChatMessage, metadata, tenant_id):
        return [MemoryEvent(
            tenant_id=tenant_id,
            source_type="chat",
            source_id=str(raw_message.id),
            source_metadata={"session_id": str(raw_message.session_id),
                             "role": raw_message.role},
            actor_slug=raw_message.agent_slug if raw_message.role == "assistant" else None,
            occurred_at=raw_message.created_at,
            ingested_at=datetime.utcnow(),
            kind="text",
            text=raw_message.content,
            proposed_entities=[],  # populated by knowledge extraction activity
            proposed_observations=[],
            proposed_relations=[],
            proposed_commitments=[],
            confidence=1.0,
            visibility="tenant_wide",
        )]

    def deduplication_key(self, raw: ChatMessage) -> str:
        return f"chat:{raw.id}"
```

### 8.4. Source attribution and dispute reconciliation

Every memory record stores `source_type`, `source_id`, `ingested_at`, `confidence`, `superseded_by_id`.

When two sources disagree — e.g., email says "meeting at 3pm", calendar says 4pm:

1. Both observations are inserted with `status = "active"`
2. `WorldStateReconciliationWorkflow` fires
3. Workflow compares the two, uses source_priority + confidence to pick a winner
4. Winner stays `active`, loser gets `status = "disputed"` + `superseded_by_id = winner.id`
5. Both are retrievable; the disputed one is surfaced to Luna via `contradictions` field in RecallResponse

Source priority defaults (can be overridden per tenant):
```
calendar > chat > jira > github > email > scraper > voice
```

**Rationale**: calendar is the highest-fidelity source for temporal claims (user explicitly set it). Chat is the user telling Luna something directly — higher trust than inferred data from parsed emails or scraped HTML. Email and scraper have OCR/parsing errors. Voice has transcription errors.

---

## 9. Kubernetes Deployment

### 9.1. Helm chart structure

Reactivate and extend the existing helm charts:

```
helm/
├── charts/
│   ├── microservice/              # existing reusable base chart
│   └── agentprovision/            # new umbrella chart
│       ├── Chart.yaml
│       ├── values.yaml
│       ├── templates/
│       │   ├── api-deployment.yaml
│       │   ├── memory-core-deployment.yaml       # new
│       │   ├── embedding-service-deployment.yaml # new
│       │   ├── chat-runtime-deployment.yaml      # new
│       │   ├── ingestion-worker-deployment.yaml  # new
│       │   ├── memory-worker-deployment.yaml     # new
│       │   ├── business-worker-deployment.yaml   # existing
│       │   ├── code-worker-deployment.yaml       # existing
│       │   ├── temporal-statefulset.yaml         # existing
│       │   ├── postgres-statefulset.yaml         # existing
│       │   ├── cloudflared-daemonset.yaml        # existing
│       │   ├── hpa.yaml
│       │   ├── services.yaml
│       │   ├── configmaps.yaml
│       │   ├── secrets.yaml                       # externalSecrets
│       │   ├── ingress.yaml
│       │   └── networkpolicies.yaml
│       └── templates/tests/
```

### 9.2. Service layout (per tenant cluster)

| Service | Kind | Replicas (default) | Scaling | Notes |
|---|---|---|---|---|
| api | Deployment | 2 | HPA on CPU + req/s | Stateless |
| memory-core | Deployment | 2 | HPA on gRPC req/s | Stateless (P2 Rust, P1 Python-in-api) |
| embedding-service | Deployment | 2 | HPA on gRPC req/s | Rust from P1 |
| chat-runtime | Deployment | 3 | HPA on Temporal queue depth | Warm CLI pool (P3+) |
| ingestion-worker | Deployment | 2 | HPA on queue depth | Temporal worker |
| memory-worker | Deployment | 2 | HPA on queue depth | Temporal worker |
| business-worker | Deployment | 2 | HPA on queue depth | Temporal worker (existing) |
| code-worker | Deployment | 1 | HPA on queue depth | Temporal worker (existing) |
| temporal | StatefulSet | 1 | — | Existing |
| postgres + pgvector | StatefulSet | 1 | — | Canonical store |
| ollama | external (host or GPU node) | — | — | Gemma4 + nomic locally |
| cloudflared | DaemonSet | 1 | — | Tunnel |

### 9.3. Local development (kind / k3s)

- `kind create cluster --config infra/kind/kind-config.yaml` spins up a 1-control-plane + 2-worker local cluster
- `helm install agentprovision charts/agentprovision -f values/local.yaml` deploys the stack
- `make dev` wraps these into a single command for the dev loop
- The existing `local-deploy.yaml` GitHub Actions workflow deploys to the self-hosted runner

### 9.4. Tenant isolation strategies (both supported)

**Strategy A — shared cluster, namespace per tenant** (default for dev / small tenants):
- One K8s cluster runs multiple tenants
- Each tenant gets its own namespace
- Shared postgres with per-tenant schemas OR shared schema with tenant_id filter
- Shared embedding-service, memory-core (they're stateless and tenant-aware via API)
- Per-tenant chat-runtime pools for warmth guarantees

**Strategy B — cluster per tenant** (default for enterprise):
- Each enterprise customer (Integral, Levi's) gets their own K8s cluster
- Full stack deployed per cluster
- Data never leaves
- Federated later via Rust node daemon (Phase 4)

Both strategies use the same helm chart; only the values differ.

---

## 10. Phasing

### Phase 0: Prerequisites (1 week, before Phase 1 starts)

- **Full gRPC IDL frozen** and committed as `docs/plans/2026-04-07-memory-first-grpc-idl.proto` — this is the contract Phase 1 Python signatures are designed around.
- **Gemma4 commitment-classification gold set** — 200 labeled user/assistant messages from current production data. Half with commitments, half without. Target F1 ≥ 0.75 to retire the regex stub. If below threshold, commitment classification is NOT retired in Phase 1.
- **Recall accuracy gold set** — 30 labeled questions against `saguilera1608@gmail.com` real production data (Integral, Levi's, Ray Aristy, fintech leads). Threshold ≥ 80% for Phase 1 acceptance.
- **Decommission map verification** — grep for `enhanced_chat`, `context_manager`, `session_journal_service` usage in the repo and update Section 3.4 with concrete per-file decisions (no "TBD" entries).

### Phase 1: Python memory layer + chat ingester (6-8 weeks)

**Goal**: fix Luna's current memory and latency problems. Docker Compose still in use. No K8s. **Python only — no Rust in Phase 1.**

**Rust `embedding-service` is deferred to Phase 2** — the hot path uses a single query embedding (~20-50ms in Python) and all bulk embedding is async. The 2-5x Rust speedup matters for Phase 3 multi-tenant scale, not for Phase 1. Moving it out of Phase 1 cuts scope and removes a prerequisite (the candle/ort benchmark), letting the Python path ship faster.

Deliverables:

1. `apps/api/app/memory/` package with `recall`, `record_*`, `ingest_events` Python APIs, signatures designed to match the Phase 0 gRPC IDL 1:1
2. Migrations:
   - `086_extend_conversation_episodes.sql` (window_start, window_end, trigger_reason, agent_slug, generated_by, partial unique index)
   - `087_extend_memory_activities.sql` (workflow_id, workflow_run_id)
   - `088_add_visibility_to_memory_tables.sql` (visibility, visible_to on commitment_records, goal_records, behavioral_signals, agent_memories, knowledge_entities)
3. Deleted files (per §3.4): `memory_recall.py`, `commitment_extractor.py`
4. Refactored files: `chat.py`, `cli_session_manager.py`, `behavioral_signals.py`, `session_journal_service.py`
5. Pre-loaded memory context in the chat hot path (replaces ad-hoc context building)
6. Conversation history in CLAUDE.md capped at **8K tokens** (revised from 50K — see §6.1.1)
7. `ChatAdapter` source adapter
8. `PostChatMemoryWorkflow` on existing `agentprovision-orchestration` queue (no new worker deployment):
   - `extract_knowledge` activity (Gemma4)
   - `detect_commitment` activity (Gemma4, gated on Phase 0 gold set F1)
   - `update_world_state` activity
   - `update_behavioral_signals` activity
   - `embed_messages` activity (post-hoc embedding via sentence-transformers)
9. `EpisodeWorkflow` + `IdleEpisodeScanWorkflow` (writes to extended `conversation_episodes` table)
10. `BackfillEmbeddingsWorkflow` — on first Phase 1 startup, backfill 1,239+ chat messages + 331 entities + 4,817 observations
11. `agent_router` integration: router returns "trivial" classification to skip recall on greetings/acks
12. Instrumentation: log per-turn prompt token counts so we can tune caps with real data
13. Integration test suite covering recall accuracy (≥80% on gold set), cross-tenant isolation, agent scoping, episode trigger races
14. Feature flag `USE_MEMORY_V2` — rollback guard

**Explicitly NOT in Phase 1**:
- Rust embedding-service (moved to Phase 2)
- memory-core as a separate service (Phase 2)
- K8s deployment (Phase 3a)
- Chat-runtime warm pods (Phase 3a)
- Additional source adapters beyond chat (Phase 3b)

### Phase 2: Rust memory-core + embedding-service (6-10 weeks)

**Goal**: migrate memory computation to Rust. Python memory package becomes a gRPC client. First Rust services in production.

**Realistic budget**: 6-10 weeks, not 4-6. First production Rust service for a team doesn't slip 20% — it slips 50-100%. We plan for the slip.

Phase 2 prerequisites (must complete before Phase 2 starts):
- Phase 1 stable in production ≥ 1 week
- `candle` vs `ort` benchmark — 1-2 day spike on the Phase 1 codebase to decide embedding runtime
- Rust dev environment set up on the dev box (toolchain, tonic, sqlx, candle)

Deliverables:
- `embedding-service/` Rust crate: gRPC server, candle + nomic-embed-text-v1.5, containerized
- `memory-core/` Rust crate: gRPC server, pgvector via sqlx, ranking, reconciliation
- Port order:
  1. **embedding-service** first (smallest scope, biggest speedup for backfill + Phase 3 scale)
  2. `memory.recall` ranking/scoring logic (Phase 1 Python → Rust port)
  3. `memory.record_*` sync writes (small)
  4. Ingestion chat adapter (Phase 1 Python → Rust port)
  5. World state reconciliation
- Python memory package becomes a gRPC client shim calling memory-core
- **Dual-write validation phase**: for 1 week, every memory write goes to BOTH Python and Rust. Shadow reads compare rankings.
  - **Tolerance threshold**: top-3 entity IDs must match exactly; top-10 must have Jaccard ≥ 0.9.
  - **Cutover criterion**: 99% of queries meet tolerance for 3 consecutive days.
  - **Rollback**: keep Python as fallback for 1 release cycle after cutover.
- `NightlyConsolidationWorkflow` (with `consolidate_weekly_theme` writing to `session_journals`)
- `EntityMergeWorkflow`, `WorldStateReconciliationWorkflow`

### Phase 3a: K8s migration + chat-runtime (4-5 weeks)

**Goal**: move from Docker Compose to Kubernetes and land warm Claude CLI pods.

Deliverables:
- Helm charts reactivated and adapted:
  - Remove GCP-specific bits (ManagedCertificates, GKE ingress, GCP IAM workload identity)
  - Add kind/k3s-friendly defaults (NodePort or Traefik ingress)
  - Externalize secrets via ExternalSecrets or sealed-secrets
  - Add new Deployments: memory-core, embedding-service, chat-runtime, ingestion-worker, memory-worker
- Local dev on kind with `make dev` one-command setup
- All services running in K8s locally (laptop) and on self-hosted runner
- chat-runtime Deployment with warm Claude CLI pools
- Session affinity: same `chat_session_id` → same chat-runtime pod
  - Prototype session affinity first (unknown-unknown risk — may need Redis-backed session-to-pod mapping if Temporal session API doesn't fit)
  - Fallback plan: sticky hash on `session_id` via a custom workflow routing rule
- `BackfillEmbeddingsWorkflow` migrated to K8s memory-worker
- GitOps deployment via existing `local-deploy.yaml` workflow
- Documentation: "How to deploy agentprovision on your own K8s cluster"
- Migration runbook: export from Docker Compose postgres, import to K8s postgres, DNS cutover

**Prerequisites** (must be true before Phase 3a starts):
- Phase 1 stable in production for ≥1 week
- Phase 2 Rust memory-core passing dual-write validation
- `candle` vs `ort` benchmark resolved (blocks embedding-service image)

### Phase 3b: Additional source ingesters (3-4 weeks)

**Goal**: unlock "Luna reads your email / calendar / Jira / GitHub / ads" capabilities.

Deliverables:
- Email ingester (adapter + `EmailIngestionWorkflow`) — triggered by existing inbox monitor
- Calendar ingester (`CalendarIngestionWorkflow`) — triggered on sync or webhook
- Jira ingester (`JiraIngestionWorkflow`) — scheduled poll or webhook
- GitHub ingester (`GitHubIngestionWorkflow`) — existing integration, new ingestion path
- Ads ingesters (Meta, Google, TikTok) via `AdsIngestionWorkflow`
- Each adapter initially in Python; high-volume ones (email, calendar) ported to Rust once stable
- End-to-end test: email arrives → entity created in KG → Luna recalls it in chat 30 seconds later
- Installation guide for Integral and Levi's first customer deployments

### Phase 4: Federation + advanced sources (parallel / later)

- Rust federation daemon (cluster-to-cluster mesh from the AgentOps conversation)
- Optional coordinator for cross-cluster discovery
- Voice ingester (audio transcription → MemoryEvents)
- Device ingester (IoT sensor data)
- Scraper ingester (web scraping → entity updates)
- Upload ingester (PDF, docx, images → text + embeddings)
- SQL ingester (scheduled PostgreSQL/data warehouse sync)
- Marketplace mechanics (separate spec)

### Phasing summary

| Phase | Duration | Infra | Deliverable |
|---|---|---|---|
| 0 | 1 week | Docker Compose | gRPC IDL freeze, gold sets built, decommission map verified |
| 1 | **6-8 weeks** | Docker Compose | Python memory layer, chat ingester, pre-loaded recall, Gemma4 commitment classification, backfill workflow. **No Rust.** |
| 2 | **6-10 weeks** | Docker Compose | Rust `embedding-service` + `memory-core` extraction, dual-write validation, flip to Rust-primary. Nightly consolidation workflows. |
| 3a | **4-5 weeks** | **K8s** (first use) | Helm charts, kind/k3s local, chat-runtime pods with warm container + per-turn subprocess, session affinity prototype, namespace-isolated single-cluster deployment |
| 3b | 3-4 weeks | K8s | Email, calendar, Jira, GitHub, ads ingesters + customer onboarding |
| 4 | parallel | K8s | Rust federation daemon (cluster-to-cluster), exotic sources, marketplace, long-running CLI supervisor sub-design |

**Total to "single-cluster enterprise ready" (end of Phase 3b): 20-27 weeks** (~5-6 months). Start 2026-04-08, Phase 3b complete between September and November 2026.

**Important product-marketing note**: End of Phase 3b delivers **single-cluster enterprise** (Integral runs their own cluster, Levi's runs theirs, both fully isolated). End of Phase 4 delivers **federated multi-cluster** (the decentralized network story). The go-to-market team should distinguish these in customer conversations — don't promise federation when only single-cluster is shipping.

---

## 11. Success Criteria

**Technical — conditional on phase**

| Criterion | Phase 1 target | Phase 2 target | Phase 3a+ target |
|---|---|---|---|
| Fast-path latency p50 | < 6s | < 5s | **< 2s** (requires warm chat-runtime) |
| Fast-path latency p95 | < 12s | < 10s | **< 4s** |
| Slow-path latency p50 | < 12s | < 10s | < 8s |
| Slow-path latency p95 | < 40s | < 30s | < 20s |
| Memory recall accuracy on gold set (30 questions) | ≥ 80% | ≥ 85% | ≥ 90% |
| Zero cross-tenant data leaks (integration tests) | hard requirement | hard | hard |
| `InFailedSqlTransaction` errors | 0 in prod logs | 0 | 0 |
| PostChatMemoryWorkflow p95 | < 30s | < 15s | < 10s |
| Chat message recall lag (after save) | < 3s | < 2s | < 1s |
| Embedding throughput per replica | ~40 req/s (Python) | **≥ 200 req/s (Rust)** | ≥ 200 req/s |

Gold set for recall accuracy: 30 labeled questions over saguilera1608@gmail.com's real production session (Integral, Levi's, fintech leads, Ray Aristy, etc.) where we know the correct answer. Luna must find it without calling a recall tool. Built as a Phase 1 prerequisite.

**Product**

- Luna can handle a full day of conversation on WhatsApp without losing context on entities, commitments, or past topics
- Integral and Levi's can each run the platform on their own K8s cluster with a single `helm install`
- Adding a new source adapter takes ≤ 3 days of work (pattern is established)
- Onboarding a new agent type (e.g., HR Agent for Levi's) takes ≤ 1 day (scoping, tool access, identity profile)

**Operational**

- Helm upgrade rolls forward with zero downtime
- pgvector index size stays manageable with NightlyConsolidationWorkflow merging duplicates
- Temporal history size per workflow stays < 1MB (otherwise refactor into child workflows)
- Memory-core pod memory stays < 1GB under normal load

### 11.1. Anti-success criteria (rollback triggers)

Explicit things we roll back if they happen:

- **Fast-path p95 regresses > 30% from pre-Phase-1 baseline** → roll back feature flag `USE_MEMORY_V2`
- **Error rate on chat endpoint increases > 2x** → roll back feature flag
- **Gemma4 commitment classification F1 < 0.7** on the gold set (built as a Phase 1 prerequisite) → keep the regex stub no-op in place, do not retire it
- **`InFailedSqlTransaction` errors re-appear at > 0.1/min** → roll back any DB session changes
- **Chat-runtime pod memory > 2GB per replica** → revert to per-message subprocess (Phase 3a rollback)
- **Phase 2 Rust memory-core dual-read divergence > 10% of queries** → keep Python primary, do not flip
- **Any cross-tenant data leak detected in integration tests** → HARD STOP. Full rollback. Incident review.

### 11.2. Acceptance gates between phases

No phase starts until the previous phase meets its anti-success criteria AND its positive success criteria for 1 week of production use.

---

## 12. Testing Strategy

### Unit tests
- Memory API: each read/write function has unit tests with mocked pgvector
- Source adapters: raw → MemoryEvent transformations
- Ranking formula: golden-dataset tests for recall scoring
- Commitment classifier: fixture-based tests against Gemma4 output

### Integration tests
- End-to-end chat turn with memory pre-load: verify the correct context is injected into CLAUDE.md
- Multi-source reconciliation: simulate email + calendar disagreement, verify reconciliation workflow runs and surfaces contradiction
- Cross-tenant isolation: spawn two tenants, verify Tenant A's memory cannot be recalled by Tenant B's agents
- Agent scoping: verify agent_scoped records are only visible to the owning agent
- Episode generation: simulate 30 messages, verify EpisodeWorkflow fires and creates session_journal row

### Load tests
- Embedding-service: 500 concurrent embed requests
- Memory-core recall: 100 concurrent tenants, 10 recalls/sec each
- Chat-runtime warm pool: 100 concurrent chats, verify session affinity

### Chaos tests
- Kill memory-worker mid-workflow; verify Temporal retries and completes
- Kill chat-runtime pod mid-turn; verify next message lands on a different pod and succeeds (cold start acceptable)
- Kill embedding-service; verify api degrades gracefully (falls back to keyword search) and recovers when service returns

### Observability
- Prometheus metrics for all gRPC endpoints (duration, error rate, req/s)
- Tracing (OTEL) for the full chat turn: HTTP → api → memory-core → embedding-service → Temporal → chat-runtime
- Logs structured with tenant_id, agent_slug, chat_session_id, workflow_id
- Grafana dashboards: latency breakdown, memory recall hit rate, ingestion queue depth, Rust service perf

---

## 13. Migration and Rollout Plan

### Phase 1 rollout (in-place, no infra change)

1. Create feature branch
2. Implement `apps/api/app/memory/` package with tests
3. Add migrations for new columns and tables
4. Deploy to local Docker Compose, verify chat works with new memory layer
5. Deploy to staging tenant (or a test tenant) for 1 week
6. Deploy to production (saguilera1608@gmail.com first, then Integral, then Levi's)
7. Monitor: latency, recall accuracy, error rates

### Phase 2 rollout (Rust memory-core)

1. Stand up memory-core Rust service in parallel with Python memory package
2. Dual-write: every memory operation goes to BOTH Python and Rust
3. Shadow reads: Python serves the result, Rust result is compared in logs
4. Once Rust matches Python for 99%+ of queries, flip to Rust-primary
5. Keep Python as fallback for 1 release cycle
6. Remove Python memory package

### Phase 3 rollout (K8s migration)

1. Deploy full stack to kind locally (dev verifies)
2. Deploy to self-hosted runner staging
3. Write migration runbook
4. Migrate tenants one by one:
   - Export data from Docker Compose postgres
   - Import to K8s postgres
   - Cut over DNS (cloudflared config change)
   - Verify
5. Decommission Docker Compose once all tenants are on K8s

### Rollback strategy

- Each phase is independent and fully rollback-able
- Phase 1: feature flag `USE_MEMORY_V2` in settings; if disabled, old code paths run
- Phase 2: Python memory package stays in tree as fallback; flip env var to switch
- Phase 3: K8s and Docker Compose run in parallel during cutover; DNS flip is atomic

---

## 14. Open Questions

### Blocking — must resolve BEFORE Phase 1 starts

1. **`candle` vs `ort` for embedding-service** — 1-2 day benchmark. Load nomic-embed-text-v1.5 in both, measure throughput and memory footprint. Pick the winner. **Prerequisite to the first embedding-service container build.**
2. **Gemma4 commitment-classification accuracy** — build a 200-message gold-labeled fixture set (user + assistant turns, half with genuine commitments, half without). Run Gemma4 classification against it, measure F1. Must hit ≥ 0.7 to retire the regex stub; ideally ≥ 0.85. **Prerequisite to Phase 1 deliverable 'retire commitment_extractor.py'.**
3. **gRPC IDL full freeze** — publish the complete `.proto` files (not abbreviated) as `2026-04-07-memory-first-grpc-idl.proto` alongside this design doc before Phase 1 Python signatures are finalized.

### To resolve in implementation plan (non-blocking)

4. **Exact Temporal session affinity wiring** — Temporal session API vs custom queue routing vs Redis-backed sticky hash. Prototype during Phase 3a; keep Redis fallback ready.
5. **pgvector index type** — `ivfflat` vs `hnsw`; HNSW is newer but has higher memory. Start with `ivfflat`, benchmark and switch if needed.
6. **Episode summary length** — 200 words? 500? Tune against recall quality on a gold set.
7. **Consolidation aggressiveness** — how aggressively to merge entities in the nightly job. Start conservative (similarity > 0.95 AND same category), loosen over time.
8. **Observability stack choice** — Prometheus + Grafana + OTEL (probably). The dormant GKE deployment had Prometheus; reuse it.
9. **Rust async runtime** — tokio (default) vs async-std; tokio is the safe choice.
10. **gRPC vs HTTP+protobuf** — gRPC is the default; HTTP+protobuf as fallback if any component has trouble with HTTP/2.
11. **Schema migration tooling** — current `migrations/` folder is manual SQL; consider Alembic for Phase 1.
12. **Ollama deployment model in K8s** — native host is fine on a dev Mac (M-series GPU), but enterprise K8s clusters need either a GPU node pool or external Ollama. Document both options in Phase 3a.
13. **`memory_activities` retention policy** — currently unbounded. Phase 2: partition by month, drop after 12 months by default. Tenant-configurable.
14. **Fast-path intent gating is already partially solved.** The existing `agent_router.py` does deterministic routing with zero LLM cost. The right question isn't "add gating" but "how does `memory.recall` integrate with `agent_router`?". **Decision in Phase 1**: `agent_router.route()` runs first, returns a `trivial=True` flag for greetings/acks, and the chat hot path skips `memory.recall` entirely when trivial. No new classifier; reuse what's there.

---

## 15. Appendix: Alignment with Existing Code

### What this design keeps

- Temporal as the workflow engine
- Postgres + pgvector as the canonical store
- FastAPI as the HTTP layer
- Claude Code CLI as the primary reasoning runtime
- Gemma4 via Ollama for local extraction
- MCP tools (existing and future) as the external integration layer
- Knowledge graph (entities + observations + relations)
- Dynamic workflows + static workflows (business layer)
- RL experience logging + auto-scoring + provider council
- Multi-tenancy via tenant_id

### What this design changes

- Memory is now a distinct layer with a clean API boundary (instead of scattered service calls)
- Chat history is embedded (new)
- Commitments and goals are embedded (new)
- Session journals are populated (new — was half-wired, now implemented)
- Auto-extraction of commitments uses Gemma4 classification instead of regex
- Pre-loaded memory in the chat hot path (replaces ad-hoc context building)
- Warm CLI pods (replaces per-message subprocess spawn)
- Rust embedding service (replaces Python sentence-transformers in the hot path)
- K8s deployment (replaces Docker Compose)
- Single gRPC API for memory operations (replaces direct DB access from multiple places)

### What this design removes or retires

- Regex-based commitment extractor (retired in favor of Gemma4 classification)
- Hardcoded Gap 1/2/3 system prompt injection blocks (retired — memory is now surfaced via unified recall)
- `claude -p --resume` session bloat path (retired — session management is platform-owned)
- 800-char chat history truncation (retired — full messages up to 50K budget)
- `chat_session.memory_context` JSONB blob — **removed in Phase 1**. Phase 1 migration `089_drop_chat_session_memory_context.sql` drops the column after confirming no readers remain. The blob currently holds stale ADK session IDs and `claude_code_cli_session_id` (which we stopped writing yesterday). Keeping it creates drift.
- Ad-hoc threading for auto-scoring / knowledge extraction (retired — all async writes go through Temporal workflows)
