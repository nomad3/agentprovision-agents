# Memory-First Phase 2: Rust Microservices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the scaffolded Rust microservices (`embedding-service` and `memory-core`) production-ready, generate Python gRPC bindings so the API can talk to them, implement the stub RPCs (record/ingest), wire gRPC health probes, and set up dual-write validation so the Rust path can safely replace the Python fallback.

**Architecture:** Two Rust gRPC services (embedding-service on :50051, memory-core on :50052) replace the Python hot-path memory operations. The Python `apps/api/app/memory/` package becomes a thin gRPC client when `USE_RUST_MEMORY=true`. Dual-write validation runs both paths and compares results before cutting over. Helm charts and Dockerfiles already exist from the Phase 2 scaffolding commit (`e66877c0`).

**Tech Stack:** Rust (tonic 0.11, sqlx, candle, tokio), protobuf/gRPC, Python (grpcio, grpcio-tools), PostgreSQL + pgvector, Docker, Helm/K8s.

**Source documents:**
- Design: `docs/plans/2026-04-07-memory-first-agent-platform-design.md` (Phase 2 scope at line 960-986)
- Phase 1 plan: `docs/plans/2026-04-07-memory-first-phase-1-plan.md`
- Existing Rust code: `apps/embedding-service/src/main.rs`, `apps/memory-core/src/main.rs`
- Proto files: `apps/api/proto/embedding.proto`, `apps/api/proto/memory.proto`
- Helm: `helm/values/embedding-service.yaml`, `helm/values/memory-core.yaml`
- Full gRPC IDL spec: `docs/plans/2026-04-07-memory-first-grpc-idl.proto`

**Branch:** `feat/memory-first-phase-2` (create from `main`). All work commits to this branch.

**What's already done (from commit `e66877c0`):**
- Rust `embedding-service`: gRPC server with Embed, EmbedBatch, Health RPCs fully implemented (CPU, candle, nomic-embed-text-v1.5)
- Rust `memory-core`: Recall RPC fully implemented (pgvector queries for entities, observations, relations, episodes). RecordObservation, RecordCommitment, IngestEvents are stubs returning empty responses.
- Proto files in `apps/api/proto/` (embedding.proto + memory.proto)
- Dockerfiles for both services (multi-stage Rust builds)
- Helm values for both services
- Python `recall.py` has gRPC client code gated on `USE_RUST_MEMORY` env var
- Python `embedding_service.py` has gRPC client code gated on `EMBEDDING_SERVICE_URL` env var

**What's broken/missing (blockers this plan fixes):**
1. `apps/api/app/generated/` is empty — no Python protobuf bindings exist
2. `recall.py` references `os.environ.get()` but never imports `os` (NameError when `USE_RUST_MEMORY=true`)
3. `memory-core` stubs: RecordObservation, RecordCommitment, IngestEvents do nothing
4. No gRPC health probes (both services use `ps aux | grep` in Helm)
5. No dual-write validation infrastructure
6. No connection pooling or retry logic on Python gRPC clients
7. No integration tests for the Rust services

**Scope note — Temporal workflows deferred:**
The design doc Phase 2 also lists NightlyConsolidationWorkflow, EntityMergeWorkflow, and WorldStateReconciliationWorkflow. These are Python Temporal workflows (not Rust) and are deferred to a follow-up plan (Phase 2b) because:
- They depend on the Rust services being functional first (they call memory-core gRPC)
- The K8s migration (running in parallel with Gemini) needs to land first for Temporal workers
- This plan focuses on the Rust extraction path — getting the services production-ready and validated

---

## Table of Contents

- [S1: Python gRPC Bindings (Tasks 1-3)](#s1-python-grpc-bindings)
- [S2: Fix Python Client Bugs (Tasks 4-5)](#s2-fix-python-client-bugs)
- [S3: Embedding Service Hardening (Tasks 6-8)](#s3-embedding-service-hardening)
- [S4: Memory-Core Write RPCs (Tasks 9-13)](#s4-memory-core-write-rpcs)
- [S5: gRPC Health Probes (Tasks 14-15)](#s5-grpc-health-probes)
- [S6: Dual-Write Validation (Tasks 16-19)](#s6-dual-write-validation)
- [S7: Helm & Deployment (Tasks 20-22)](#s7-helm--deployment)
- [S8: Integration Tests & Acceptance (Tasks 23-26)](#s8-integration-tests--acceptance)

---

## S1: Python gRPC Bindings

**Goal:** Generate Python protobuf stubs from the existing `.proto` files so the API can actually talk to the Rust services.

### Task 1: Add protobuf compilation to API build

**Files:**
- Create: `apps/api/app/generated/__init__.py`
- Create: `apps/api/scripts/gen_proto.sh`
- Modify: `apps/api/requirements.txt` (add grpcio, grpcio-tools)
- Modify: `apps/api/Dockerfile` (add protoc step)

- [ ] **Step 1: Add gRPC dependencies to requirements.txt**

Add to `apps/api/requirements.txt`:
```
grpcio>=1.62.0
grpcio-tools>=1.62.0
protobuf>=4.25.0
```

- [ ] **Step 2: Create the proto generation script**

```bash
# apps/api/scripts/gen_proto.sh
#!/bin/bash
set -euo pipefail

PROTO_DIR="$(dirname "$0")/../proto"
OUT_DIR="$(dirname "$0")/../app/generated"

mkdir -p "$OUT_DIR"

python -m grpc_tools.protoc \
  -I"$PROTO_DIR" \
  --python_out="$OUT_DIR" \
  --grpc_python_out="$OUT_DIR" \
  "$PROTO_DIR/embedding.proto" \
  "$PROTO_DIR/memory.proto"

# Fix relative imports for Python 3 (works on macOS and Linux)
if [[ "$OSTYPE" == "darwin"* ]]; then
  SED_INPLACE="sed -i ''"
else
  SED_INPLACE="sed -i"
fi

$SED_INPLACE 's/^import embedding_pb2/from app.generated import embedding_pb2/' "$OUT_DIR/embedding_pb2_grpc.py"
$SED_INPLACE 's/^import memory_pb2/from app.generated import memory_pb2/' "$OUT_DIR/memory_pb2_grpc.py"

echo "Proto stubs generated in $OUT_DIR"
```

- [ ] **Step 3: Create `__init__.py` for the generated package**

```python
# apps/api/app/generated/__init__.py
"""Auto-generated protobuf stubs. Run scripts/gen_proto.sh to regenerate."""
```

- [ ] **Step 4: Run the generation script**

```bash
cd apps/api
pip install grpcio-tools protobuf
chmod +x scripts/gen_proto.sh
bash scripts/gen_proto.sh
```

Expected: `app/generated/` now contains `embedding_pb2.py`, `embedding_pb2_grpc.py`, `memory_pb2.py`, `memory_pb2_grpc.py`.

- [ ] **Step 5: Verify imports work**

```bash
cd apps/api
python -c "from app.generated import embedding_pb2, embedding_pb2_grpc, memory_pb2, memory_pb2_grpc; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Add protoc step to Dockerfile**

In `apps/api/Dockerfile`, after `pip install`, add:
```dockerfile
COPY proto/ /app/proto/
COPY scripts/gen_proto.sh /app/scripts/gen_proto.sh
RUN bash /app/scripts/gen_proto.sh
```

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/generated/ apps/api/scripts/gen_proto.sh apps/api/requirements.txt apps/api/Dockerfile
git commit -m "feat(memory-first): generate Python gRPC bindings from proto files"
```

---

### Task 2: Update proto files to match the frozen IDL

The current `apps/api/proto/memory.proto` is a simplified version. Align it with the design doc's full IDL for the RPCs we're implementing in this phase.

**Files:**
- Modify: `apps/api/proto/memory.proto`
- Modify: `apps/memory-core/proto/memory.proto` (keep in sync)

- [ ] **Step 1: Add missing fields to RecallResponse**

The current RecallResponse is missing commitments, goals, past_conversations, contradictions, total_tokens_estimate, and metadata fields. Add them:

```protobuf
message CommitmentSummary {
  string id = 1;
  string title = 2;
  string commitment_type = 3;
  string status = 4;
  google.protobuf.Timestamp due_at = 5;
  string owner_agent_slug = 6;
}

message GoalSummary {
  string id = 1;
  string title = 2;
  string status = 3;
  string owner_agent_slug = 4;
}

message ConversationSnippet {
  string session_id = 1;
  string content = 2;
  string role = 3;
  google.protobuf.Timestamp created_at = 4;
  float similarity = 5;
}

message ContradictionSummary {
  string assertion_id = 1;
  string claim = 2;
  string counter_claim = 3;
  string source_a = 4;
  string source_b = 5;
}

message RecallMetadata {
  int32 query_time_ms = 1;
  int32 total_tokens_estimate = 2;
  bool degraded = 3;
  string degradation_reason = 4;
}

message RecallResponse {
  repeated Entity entities = 1;
  repeated Observation observations = 2;
  repeated Relation relations = 3;
  repeated EpisodeSummary episodes = 4;
  repeated CommitmentSummary commitments = 5;
  repeated GoalSummary goals = 6;
  repeated ConversationSnippet past_conversations = 7;
  repeated ContradictionSummary contradictions = 8;
  RecallMetadata metadata = 9;
}
```

- [ ] **Step 2: Copy the updated proto to memory-core**

```bash
cp apps/api/proto/memory.proto apps/memory-core/proto/memory.proto
```

- [ ] **Step 3: Regenerate Python bindings**

```bash
cd apps/api && bash scripts/gen_proto.sh
```

- [ ] **Step 4: Verify both Rust and Python compile**

```bash
# Rust (memory-core)
cd apps/memory-core && cargo check 2>&1 | tail -5

# Python
cd apps/api && python -c "from app.generated import memory_pb2; print(memory_pb2.RecallResponse.DESCRIPTOR.fields_by_name.keys())"
```

- [ ] **Step 5: Commit**

```bash
git add apps/api/proto/ apps/memory-core/proto/ apps/api/app/generated/
git commit -m "feat(memory-first): align proto IDL with design doc (commitments, goals, metadata)"
```

---

### Task 3: Regenerate Rust protobuf code after proto changes

**Files:**
- Modify: `apps/memory-core/src/main.rs` (update struct references for new proto fields)

- [ ] **Step 1: Run cargo build to regenerate tonic stubs**

```bash
cd apps/memory-core && cargo build 2>&1 | tail -20
```

Expected: may fail with missing trait implementations for the new message types. Fix compilation errors.

- [ ] **Step 2: Update the Recall RPC to populate new fields**

Add queries for commitments, goals, and past_conversations in `main.rs`. Add metadata (query_time_ms) tracking.

In `recall()`, add after the episodes query:

```rust
// 6. Search commitments
let commitment_rows = sqlx::query(
    r#"
    SELECT id::text as id, title, commitment_type, status,
           due_at, owner_agent_slug
    FROM commitment_records
    WHERE tenant_id = $1 AND status != 'completed'
    ORDER BY created_at DESC
    LIMIT $2
    "#
)
.bind(tenant_id)
.bind(req.top_k_per_type as i64)
.fetch_all(&self.pool).await
.map_err(|e| Status::internal(format!("DB error (commitments): {}", e)))?;

// 7. Search past conversations via embeddings table
let conversation_rows = sqlx::query(
    r#"
    SELECT e.content_id as session_id, e.text_content as content,
           (1 - (e.embedding <=> $2::vector)) as similarity
    FROM embeddings e
    WHERE e.tenant_id = $1 AND e.content_type = 'chat_message'
    ORDER BY e.embedding <=> $2::vector
    LIMIT $3
    "#
)
.bind(tenant_id)
.bind(&query_vec_str)
.bind(req.top_k_per_type as i64)
.fetch_all(&self.pool).await
.map_err(|e| Status::internal(format!("DB error (conversations): {}", e)))?;
```

- [ ] **Step 3: Verify cargo build succeeds**

```bash
cd apps/memory-core && cargo build
```

Expected: compiles without errors.

- [ ] **Step 4: Commit**

```bash
git add apps/memory-core/
git commit -m "feat(memory-first): memory-core recall returns commitments, goals, conversations"
```

---

## S2: Fix Python Client Bugs

### Task 4: Fix missing `import os` in recall.py

**Files:**
- Modify: `apps/api/app/memory/recall.py:1-30`

- [ ] **Step 1: Add the missing import**

Add `import os` to the imports at the top of `recall.py`, after the existing `import uuid` line.

- [ ] **Step 2: Verify the import chain works**

```bash
cd apps/api
python -c "from app.memory.recall import recall; print('import OK')"
```

Expected: `import OK` (no NameError)

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/memory/recall.py
git commit -m "fix(memory-first): add missing os import in recall.py"
```

---

### Task 5: Wire gRPC client with retry and connection pooling

**Files:**
- Modify: `apps/api/app/memory/recall.py:56-82` (the `_get_grpc_stub` function)
- Modify: `apps/api/app/services/embedding_service.py` (same pattern)

- [ ] **Step 1: Replace naive gRPC client with retry-aware channel**

In `recall.py`, replace `_get_grpc_stub()`:

```python
import os
import grpc

_grpc_channel = None
_grpc_stub = None

def _get_grpc_stub():
    """Lazy-init gRPC client stub for Rust memory-core with keepalive."""
    global _grpc_channel, _grpc_stub
    if _grpc_stub is not None:
        return _grpc_stub

    url = os.environ.get("MEMORY_CORE_URL")
    if not url:
        return None

    try:
        from app.generated import memory_pb2_grpc
    except ImportError:
        logger.warning("gRPC generated code not found. Rust memory disabled.")
        return None

    try:
        options = [
            ('grpc.keepalive_time_ms', 30000),
            ('grpc.keepalive_timeout_ms', 5000),
            ('grpc.keepalive_permit_without_calls', 1),
            ('grpc.max_receive_message_length', 16 * 1024 * 1024),
        ]
        _grpc_channel = grpc.insecure_channel(url, options=options)
        _grpc_stub = memory_pb2_grpc.MemoryCoreStub(_grpc_channel)
        logger.info("Connected to Rust memory-core at %s", url)
        return _grpc_stub
    except Exception as e:
        logger.warning("Failed to connect to Rust memory-core: %s", e)
        return None
```

- [ ] **Step 2: Apply the same pattern to embedding_service.py**

Same keepalive options in `embedding_service.py`'s `_get_grpc_stub()`.

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/memory/recall.py apps/api/app/services/embedding_service.py
git commit -m "feat(memory-first): gRPC clients with keepalive and connection pooling"
```

---

## S3: Embedding Service Hardening

### Task 6: Add gRPC health service to embedding-service

**Files:**
- Modify: `apps/embedding-service/Cargo.toml` (add tonic-health)
- Modify: `apps/embedding-service/src/main.rs`

- [ ] **Step 1: Add tonic-health dependency**

In `apps/embedding-service/Cargo.toml`, add:
```toml
tonic-health = "0.11"
```

- [ ] **Step 2: Wire health service into the server**

In `main.rs`, update the server builder:

```rust
use tonic_health::server::health_reporter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();

    println!("Loading model...");
    let model = Model::load()?;
    let service = MyEmbeddingService::new(model);

    let (mut health_reporter, health_service) = health_reporter();
    health_reporter
        .set_serving::<EmbeddingServiceServer<MyEmbeddingService>>()
        .await;

    let addr = "0.0.0.0:50051".parse()?;
    println!("EmbeddingService listening on {}", addr);

    Server::builder()
        .add_service(health_service)
        .add_service(EmbeddingServiceServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}
```

- [ ] **Step 3: Build and verify**

```bash
cd apps/embedding-service && cargo build
```

- [ ] **Step 4: Commit**

```bash
git add apps/embedding-service/
git commit -m "feat(memory-first): add gRPC health service to embedding-service"
```

---

### Task 7: Add batch parallelism to embedding-service

The current `embed_batch` processes texts sequentially. For backfill performance, process in parallel.

**Files:**
- Modify: `apps/embedding-service/src/main.rs` (the `embed_batch` method)

- [ ] **Step 1: Replace sequential loop with parallel spawn_blocking**

```rust
async fn embed_batch(&self, request: Request<EmbedBatchRequest>) -> Result<Response<EmbedBatchResponse>, Status> {
    let req = request.into_inner();
    let task_type = req.task_type.clone();

    let mut handles = Vec::with_capacity(req.texts.len());
    for text in req.texts {
        let m = self.model.clone();
        let tt = task_type.clone();
        handles.push(tokio::task::spawn_blocking(move || m.embed(&text, &tt)));
    }

    let mut results = Vec::with_capacity(handles.len());
    for handle in handles {
        let vector = handle
            .await
            .map_err(|e| Status::internal(e.to_string()))?
            .map_err(|e| Status::internal(e.to_string()))?;
        results.push(EmbedResponse {
            vector,
            model: "nomic-embed-text-v1.5".to_string(),
            dimensions: 768,
        });
    }

    Ok(Response::new(EmbedBatchResponse { results }))
}
```

- [ ] **Step 2: Build and verify**

```bash
cd apps/embedding-service && cargo build
```

- [ ] **Step 3: Commit**

```bash
git add apps/embedding-service/src/main.rs
git commit -m "feat(memory-first): parallel embed_batch in embedding-service"
```

---

### Task 8: Add request timeout to embedding-service

**Files:**
- Modify: `apps/embedding-service/src/main.rs`

- [ ] **Step 1: Add tower timeout layer**

In `Cargo.toml`:
```toml
tower = { version = "0.4", features = ["timeout"] }
```

In `main.rs`, wrap the server:
```rust
use std::time::Duration;
use tower::timeout::TimeoutLayer;

Server::builder()
    .timeout(Duration::from_secs(30))
    .add_service(health_service)
    .add_service(EmbeddingServiceServer::new(service))
    .serve(addr)
    .await?;
```

- [ ] **Step 2: Build and verify**

```bash
cd apps/embedding-service && cargo build
```

- [ ] **Step 3: Commit**

```bash
git add apps/embedding-service/
git commit -m "feat(memory-first): 30s request timeout on embedding-service"
```

---

## S4: Memory-Core Write RPCs

### Task 9: Implement RecordObservation RPC

**Files:**
- Modify: `apps/memory-core/src/main.rs`

- [ ] **Step 1: Implement the handler**

Replace the stub with actual DB write logic:

```rust
async fn record_observation(&self, request: Request<RecordObservationRequest>) -> Result<Response<()>, Status> {
    let req = request.into_inner();
    let tenant_id = Uuid::parse_str(&req.tenant_id)
        .map_err(|_| Status::invalid_argument("Invalid tenant_id"))?;
    let entity_id = Uuid::parse_str(&req.entity_id)
        .map_err(|_| Status::invalid_argument("Invalid entity_id"))?;

    // 1. Embed the observation text
    let embedding = self.get_embedding(&req.content, "search_document").await?;
    let embedding_str = format!("[{}]", embedding.iter().map(|v| v.to_string()).collect::<Vec<String>>().join(","));

    // 2. Insert observation
    let obs_id = Uuid::new_v4();
    sqlx::query(
        r#"
        INSERT INTO knowledge_observations (id, tenant_id, entity_id, observation_text,
            observation_type, source_type, confidence, embedding, created_at)
        VALUES ($1, $2, $3, $4, 'fact', $5, $6, $7::vector, NOW())
        "#
    )
    .bind(obs_id)
    .bind(tenant_id)
    .bind(entity_id)
    .bind(&req.content)
    .bind(&req.source_type)
    .bind(req.confidence)
    .bind(&embedding_str)
    .execute(&self.pool).await
    .map_err(|e| Status::internal(format!("DB error: {}", e)))?;

    // 3. Audit trail
    sqlx::query(
        r#"
        INSERT INTO memory_activities (id, tenant_id, event_type, description,
            source, entity_id, created_at)
        VALUES ($1, $2, 'observation_created', $3, $4, $5, NOW())
        "#
    )
    .bind(Uuid::new_v4())
    .bind(tenant_id)
    .bind(format!("Rust: observation on entity {}", entity_id))
    .bind(&req.source_type)
    .bind(entity_id)
    .execute(&self.pool).await
    .map_err(|e| Status::internal(format!("Audit error: {}", e)))?;

    println!("Recorded observation {} for entity {}", obs_id, entity_id);
    Ok(Response::new(()))
}
```

- [ ] **Step 2: Build and verify**

```bash
cd apps/memory-core && cargo build
```

- [ ] **Step 3: Commit**

```bash
git add apps/memory-core/src/main.rs
git commit -m "feat(memory-first): implement RecordObservation RPC in memory-core"
```

---

### Task 10: Implement RecordCommitment RPC

**Files:**
- Modify: `apps/memory-core/src/main.rs`

- [ ] **Step 1: Implement the handler**

```rust
async fn record_commitment(&self, request: Request<RecordCommitmentRequest>) -> Result<Response<()>, Status> {
    let req = request.into_inner();
    let tenant_id = Uuid::parse_str(&req.tenant_id)
        .map_err(|_| Status::invalid_argument("Invalid tenant_id"))?;

    let commitment_id = Uuid::new_v4();
    let due_at = req.due_at.map(|ts| {
        chrono::DateTime::from_timestamp(ts.seconds, ts.nanos as u32)
            .unwrap_or_else(chrono::Utc::now)
    });

    sqlx::query(
        r#"
        INSERT INTO commitment_records (id, tenant_id, owner_agent_slug, title,
            description, commitment_type, status, due_at, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, 'active', $7, NOW())
        "#
    )
    .bind(commitment_id)
    .bind(tenant_id)
    .bind(&req.owner_agent_slug)
    .bind(&req.title)
    .bind(&req.description)
    .bind(&req.commitment_type)
    .bind(due_at)
    .execute(&self.pool).await
    .map_err(|e| Status::internal(format!("DB error: {}", e)))?;

    // Audit trail
    sqlx::query(
        r#"
        INSERT INTO memory_activities (id, tenant_id, event_type, description,
            source, created_at)
        VALUES ($1, $2, 'commitment_created', $3, 'rust_memory_core', NOW())
        "#
    )
    .bind(Uuid::new_v4())
    .bind(tenant_id)
    .bind(format!("Rust: commitment '{}'", &req.title))
    .execute(&self.pool).await
    .map_err(|e| Status::internal(format!("Audit error: {}", e)))?;

    println!("Recorded commitment {} for tenant {}", commitment_id, tenant_id);
    Ok(Response::new(()))
}
```

- [ ] **Step 2: Build and verify**

```bash
cd apps/memory-core && cargo build
```

- [ ] **Step 3: Commit**

```bash
git add apps/memory-core/src/main.rs
git commit -m "feat(memory-first): implement RecordCommitment RPC in memory-core"
```

---

### Task 11: Implement IngestEvents RPC

**Files:**
- Modify: `apps/memory-core/src/main.rs`

- [ ] **Step 1: Implement bulk event ingestion**

```rust
async fn ingest_events(&self, request: Request<IngestRequest>) -> Result<Response<IngestResponse>, Status> {
    let req = request.into_inner();
    let tenant_id = Uuid::parse_str(&req.tenant_id)
        .map_err(|_| Status::invalid_argument("Invalid tenant_id"))?;

    let mut processed = 0i32;
    for event in &req.events {
        // For each proposed entity, upsert
        for entity_name in &event.proposed_entities {
            sqlx::query(
                r#"
                INSERT INTO knowledge_entities (id, tenant_id, name, entity_type,
                    category, description, confidence, created_at, updated_at)
                VALUES ($1, $2, $3, 'general', 'general', '', 0.7, NOW(), NOW())
                ON CONFLICT (tenant_id, name) WHERE deleted_at IS NULL
                DO UPDATE SET updated_at = NOW()
                "#
            )
            .bind(Uuid::new_v4())
            .bind(tenant_id)
            .bind(entity_name)
            .execute(&self.pool).await
            .map_err(|e| Status::internal(format!("Entity upsert error: {}", e)))?;
        }
        processed += 1;
    }

    Ok(Response::new(IngestResponse { processed }))
}
```

- [ ] **Step 2: Build and verify**

```bash
cd apps/memory-core && cargo build
```

- [ ] **Step 3: Commit**

```bash
git add apps/memory-core/src/main.rs
git commit -m "feat(memory-first): implement IngestEvents RPC in memory-core"
```

---

### Task 12: Add connection pooling and error handling to memory-core

**Files:**
- Modify: `apps/memory-core/src/main.rs`

- [ ] **Step 1: Increase pool size and add connection timeout**

```rust
let pool = PgPoolOptions::new()
    .max_connections(20)
    .acquire_timeout(std::time::Duration::from_secs(5))
    .idle_timeout(std::time::Duration::from_secs(300))
    .connect(&database_url)
    .await?;
```

- [ ] **Step 2: Cache the embedding client connection**

Instead of creating a new `EmbeddingServiceClient` per request, store it in the struct:

```rust
use tokio::sync::Mutex;

pub struct MyMemoryCore {
    pool: sqlx::PgPool,
    embedding_client: Arc<Mutex<Option<EmbeddingServiceClient<tonic::transport::Channel>>>>,
    embedding_url: String,
}

impl MyMemoryCore {
    async fn get_embedding(&self, text: &str, task_type: &str) -> Result<Vec<f32>, Status> {
        let mut guard = self.embedding_client.lock().await;
        let client = match guard.as_mut() {
            Some(c) => c,
            None => {
                let c = EmbeddingServiceClient::connect(self.embedding_url.clone())
                    .await
                    .map_err(|e| Status::internal(format!("Embedding connect failed: {}", e)))?;
                *guard = Some(c);
                guard.as_mut().unwrap()
            }
        };

        let response = client.embed(Request::new(EmbedRequest {
            text: text.to_string(),
            task_type: task_type.to_string(),
        })).await?;

        Ok(response.into_inner().vector)
    }
}
```

- [ ] **Step 3: Build and verify**

```bash
cd apps/memory-core && cargo build
```

- [ ] **Step 4: Commit**

```bash
git add apps/memory-core/src/main.rs
git commit -m "feat(memory-first): connection pooling and cached embedding client in memory-core"
```

---

### Task 13: Add query timing and metadata to Recall response

**Files:**
- Modify: `apps/memory-core/src/main.rs`

- [ ] **Step 1: Wrap recall in timing and populate metadata**

At the start of `recall()`:
```rust
let start = std::time::Instant::now();
```

At the end, before returning:
```rust
let query_time_ms = start.elapsed().as_millis() as i32;
let total_tokens = entities.len() * 50 + observations.len() * 30
    + relations.len() * 20 + episodes.len() * 100
    + commitments.len() * 40 + conversations.len() * 60;

Ok(Response::new(RecallResponse {
    entities,
    observations,
    relations,
    episodes,
    commitments,
    goals: vec![],  // TODO: add goal query
    past_conversations: conversations,
    contradictions: vec![],
    metadata: Some(RecallMetadata {
        query_time_ms,
        total_tokens_estimate: total_tokens as i32,
        degraded: false,
        degradation_reason: String::new(),
    }),
}))
```

- [ ] **Step 2: Build and verify**

```bash
cd apps/memory-core && cargo build
```

- [ ] **Step 3: Commit**

```bash
git add apps/memory-core/src/main.rs
git commit -m "feat(memory-first): recall metadata with timing and token estimates"
```

---

## S5: gRPC Health Probes

### Task 14: Add gRPC health service to memory-core

**Files:**
- Modify: `apps/memory-core/Cargo.toml`
- Modify: `apps/memory-core/src/main.rs`

- [ ] **Step 1: Add tonic-health dependency**

```toml
tonic-health = "0.11"
```

- [ ] **Step 2: Wire health reporter**

Same pattern as Task 6 — add `health_reporter()` and `set_serving` on the `MemoryCoreServer`.

- [ ] **Step 3: Build and verify**

```bash
cd apps/memory-core && cargo build
```

- [ ] **Step 4: Commit**

```bash
git add apps/memory-core/
git commit -m "feat(memory-first): add gRPC health service to memory-core"
```

---

### Task 15: Update Helm health probes to use gRPC

**Files:**
- Modify: `helm/values/embedding-service.yaml`
- Modify: `helm/values/memory-core.yaml`

- [ ] **Step 1: Replace exec probes with gRPC probes**

For `embedding-service.yaml`:
```yaml
livenessProbe:
  enabled: true
  grpc:
    port: 50051
  initialDelaySeconds: 30
  periodSeconds: 15

readinessProbe:
  enabled: true
  grpc:
    port: 50051
  initialDelaySeconds: 10
  periodSeconds: 10
```

For `memory-core.yaml`:
```yaml
livenessProbe:
  enabled: true
  grpc:
    port: 50052
  initialDelaySeconds: 10
  periodSeconds: 15

readinessProbe:
  enabled: true
  grpc:
    port: 50052
  initialDelaySeconds: 5
  periodSeconds: 10
```

- [ ] **Step 2: Verify Helm template renders**

```bash
helm template test helm/charts/microservice -f helm/values/embedding-service.yaml | grep -A 5 livenessProbe
helm template test helm/charts/microservice -f helm/values/memory-core.yaml | grep -A 5 livenessProbe
```

Expected: gRPC probes appear in the rendered output.

- [ ] **Step 3: Check the microservice chart supports gRPC probes**

Read `helm/charts/microservice/templates/deployment.yaml` and verify it has a conditional for `grpc` probe type. If not, add it.

- [ ] **Step 4: Commit**

```bash
git add helm/values/embedding-service.yaml helm/values/memory-core.yaml
git commit -m "feat(memory-first): gRPC health probes for Rust services"
```

---

## S6: Dual-Write Validation

### Task 16: Add shadow recall comparison in Python

**Files:**
- Modify: `apps/api/app/memory/recall.py`

- [ ] **Step 1: Add dual-read mode**

When `MEMORY_DUAL_READ=true`, run both Python and Rust recall, compare results, log divergences:

```python
def recall(db: Session, request: RecallRequest) -> RecallResponse:
    """Pre-load memory context for a chat turn."""
    dual_read = os.environ.get("MEMORY_DUAL_READ", "false").lower() == "true"
    use_rust = os.environ.get("USE_RUST_MEMORY", "false").lower() == "true"

    # Always run Python path (primary in Phase 2 validation)
    python_result = _recall_python(db, request)

    if dual_read or use_rust:
        rust_result = _recall_rust(request)
        if rust_result and dual_read:
            _compare_and_log(request, python_result, rust_result)

    if use_rust:
        rust_result = _recall_rust(request)
        if rust_result:
            return rust_result

    return python_result
```

- [ ] **Step 2: Implement `_compare_and_log`**

```python
def _compare_and_log(request, python_result, rust_result):
    """Compare Python vs Rust recall results and log divergences."""
    py_entity_ids = set(e.id for e in python_result.entities[:10])
    rs_entity_ids = set(e.id for e in rust_result.entities[:10])

    # Top-3 exact match
    py_top3 = [e.id for e in python_result.entities[:3]]
    rs_top3 = [e.id for e in rust_result.entities[:3]]
    top3_match = py_top3 == rs_top3

    # Top-10 Jaccard
    if py_entity_ids or rs_entity_ids:
        jaccard = len(py_entity_ids & rs_entity_ids) / len(py_entity_ids | rs_entity_ids)
    else:
        jaccard = 1.0

    if not top3_match or jaccard < 0.9:
        logger.warning(
            "DUAL_READ divergence: query=%s top3_match=%s jaccard=%.2f py=%s rs=%s",
            request.query[:50], top3_match, jaccard, py_top3, rs_top3,
        )
    else:
        logger.debug("DUAL_READ match: jaccard=%.2f", jaccard)
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/memory/recall.py
git commit -m "feat(memory-first): dual-read validation mode for Python vs Rust recall"
```

---

### Task 17: Add shadow write comparison for record operations

**Files:**
- Modify: `apps/api/app/memory/record.py`

- [ ] **Step 1: Add dual-write wrapper**

When `MEMORY_DUAL_WRITE=true`, write to both Python and Rust, compare:

```python
import os

def record_observation(db, tenant_id, *, entity_id, content, confidence=0.7, **kwargs):
    # Always write via Python (primary)
    result = _record_observation_python(db, tenant_id, entity_id=entity_id,
                                         content=content, confidence=confidence, **kwargs)

    if os.environ.get("MEMORY_DUAL_WRITE", "false").lower() == "true":
        try:
            _record_observation_rust(tenant_id, entity_id=entity_id,
                                     content=content, confidence=confidence, **kwargs)
        except Exception as e:
            logger.warning("Rust shadow write failed: %s", e)

    return result
```

Rename existing `record_observation` to `_record_observation_python`. Create `_record_observation_rust` that calls gRPC.

- [ ] **Step 2: Commit**

```bash
git add apps/api/app/memory/record.py
git commit -m "feat(memory-first): dual-write validation for record operations"
```

---

### Task 18: Add metrics logging for dual validation

**Files:**
- Create: `apps/api/app/memory/validation_metrics.py`

- [ ] **Step 1: Create a simple metrics tracker**

```python
"""Dual-read/write validation metrics for Phase 2 cutover."""
import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class ValidationMetrics:
    total_reads: int = 0
    matching_reads: int = 0
    divergent_reads: int = 0
    total_writes: int = 0
    successful_rust_writes: int = 0
    failed_rust_writes: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_read(self, matched: bool):
        with self._lock:
            self.total_reads += 1
            if matched:
                self.matching_reads += 1
            else:
                self.divergent_reads += 1

    def record_write(self, success: bool):
        with self._lock:
            self.total_writes += 1
            if success:
                self.successful_rust_writes += 1
            else:
                self.failed_rust_writes += 1

    @property
    def read_match_rate(self) -> float:
        return self.matching_reads / max(self.total_reads, 1)

    def report(self) -> dict:
        with self._lock:
            return {
                "total_reads": self.total_reads,
                "read_match_rate": f"{self.read_match_rate:.2%}",
                "divergent_reads": self.divergent_reads,
                "total_writes": self.total_writes,
                "rust_write_success_rate": f"{self.successful_rust_writes / max(self.total_writes, 1):.2%}",
            }

# Singleton
metrics = ValidationMetrics()
```

- [ ] **Step 2: Wire into recall.py and record.py**

Import `metrics` and call `record_read()` / `record_write()` in the dual paths.

- [ ] **Step 3: Add metrics endpoint**

In `apps/api/app/api/v1/memory_admin.py`, add:
```python
@router.get("/memory/validation-metrics")
def get_validation_metrics(current_user = Depends(get_current_admin)):
    from app.memory.validation_metrics import metrics
    return metrics.report()
```

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/memory/validation_metrics.py apps/api/app/api/v1/memory_admin.py apps/api/app/memory/recall.py apps/api/app/memory/record.py
git commit -m "feat(memory-first): validation metrics for dual-read/write Phase 2 cutover"
```

---

### Task 19: Document cutover criteria

**Files:**
- Create: `docs/plans/2026-04-10-phase-2-cutover-criteria.md`

- [ ] **Step 1: Write the criteria doc**

```markdown
# Phase 2 Cutover Criteria: Python → Rust

## Recall (dual-read)
- Top-3 entity IDs must match exactly
- Top-10 Jaccard similarity >= 0.9
- Meet criteria for 99% of queries over 3 consecutive days
- Rust recall p50 latency <= Python p50 latency

## Writes (dual-write)
- Rust write success rate >= 99.9% over 3 days
- No data corruption (audit trail matches)

## Rollback plan
- Set `USE_RUST_MEMORY=false` to revert to Python immediately
- Keep Python fallback for 1 full release cycle after cutover
- Monitor error rates for 48 hours after cutover

## Monitoring
- `GET /api/v1/memory/validation-metrics` for live metrics
- Log search: `DUAL_READ divergence` for individual mismatches
```

- [ ] **Step 2: Commit**

```bash
git add docs/plans/2026-04-10-phase-2-cutover-criteria.md
git commit -m "docs(memory-first): Phase 2 cutover criteria"
```

---

## S7: Helm & Deployment

### Task 20: Build Rust service Docker images locally

**Files:**
- Modify: `apps/embedding-service/Dockerfile` (if needed)
- Modify: `apps/memory-core/Dockerfile` (if needed)

- [ ] **Step 1: Build embedding-service image**

```bash
cd apps/embedding-service
docker build -t agentprovision-embedding-service:latest .
```

Expected: multi-stage build completes. Final image is small (~100MB + model cache).

- [ ] **Step 2: Build memory-core image**

```bash
cd apps/memory-core
docker build -t agentprovision-memory-core:latest .
```

- [ ] **Step 3: Verify images run**

```bash
docker run --rm -e DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:5432/agentprovision \
  -e EMBEDDING_SERVICE_URL=http://host.docker.internal:50051 \
  -p 50052:50052 agentprovision-memory-core:latest &

# Wait for startup, then test health
sleep 5
grpcurl -plaintext localhost:50052 grpc.health.v1.Health/Check
```

Expected: `SERVING` status.

- [ ] **Step 4: Commit any Dockerfile fixes**

```bash
git add apps/embedding-service/Dockerfile apps/memory-core/Dockerfile
git commit -m "fix(memory-first): Dockerfile fixes for Rust services"
```

---

### Task 21: Add Rust services to local deploy workflow

**Files:**
- Modify: `.github/workflows/local-deploy.yaml`

- [ ] **Step 1: Add build + deploy steps for embedding-service and memory-core**

Add after existing service builds:
```yaml
- name: Build embedding-service
  run: |
    docker build -t agentprovision-embedding-service:latest apps/embedding-service/

- name: Build memory-core
  run: |
    docker build -t agentprovision-memory-core:latest apps/memory-core/

- name: Deploy embedding-service
  run: |
    helm upgrade --install embedding-service helm/charts/microservice \
      -f helm/values/embedding-service.yaml \
      -n agentprovision --create-namespace

- name: Deploy memory-core
  run: |
    helm upgrade --install memory-core helm/charts/microservice \
      -f helm/values/memory-core.yaml \
      -n agentprovision --create-namespace
```

- [ ] **Step 2: Add env vars to API deployment for gRPC URLs**

In the API helm values or configmap, add:
```yaml
EMBEDDING_SERVICE_URL: "http://embedding-service:50051"
MEMORY_CORE_URL: "memory-core:50052"
MEMORY_DUAL_READ: "true"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/local-deploy.yaml
git commit -m "feat(memory-first): add Rust services to local deploy pipeline"
```

---

### Task 22: Create local-values overrides for embedding-service and memory-core

**Files:**
- Create: `helm/values/embedding-service-local.yaml`
- Create: `helm/values/memory-core-local.yaml`

- [ ] **Step 1: Create local override for embedding-service**

```yaml
# helm/values/embedding-service-local.yaml
# Local overrides for Rancher Desktop / kind
persistence:
  storageClass: local-path  # Rancher Desktop default
```

- [ ] **Step 2: Create local override for memory-core**

```yaml
# helm/values/memory-core-local.yaml
# Local overrides for Rancher Desktop / kind
env:
  - name: DATABASE_URL
    value: "postgresql://postgres:postgres@postgresql:5432/agentprovision"
  - name: RUST_LOG
    value: "debug"
```

- [ ] **Step 3: Commit**

```bash
git add helm/values/embedding-service-local.yaml helm/values/memory-core-local.yaml
git commit -m "feat(memory-first): local Helm value overrides for Rust services"
```

---

## S8: Integration Tests & Acceptance

### Task 23: gRPC smoke test for embedding-service

**Files:**
- Create: `apps/api/tests/memory/test_embedding_grpc.py`

- [ ] **Step 1: Write the test**

```python
"""Smoke test for Rust embedding-service gRPC.

Requires embedding-service running on localhost:50051.
Skip if not available.
"""
import os
import pytest
import grpc

pytestmark = pytest.mark.skipif(
    not os.environ.get("EMBEDDING_SERVICE_URL"),
    reason="EMBEDDING_SERVICE_URL not set"
)

def test_embed_single():
    from app.generated import embedding_pb2, embedding_pb2_grpc
    channel = grpc.insecure_channel(os.environ["EMBEDDING_SERVICE_URL"])
    stub = embedding_pb2_grpc.EmbeddingServiceStub(channel)

    response = stub.Embed(embedding_pb2.EmbedRequest(
        text="hello world",
        task_type="search_query",
    ))
    assert len(response.vector) == 768
    assert response.model == "nomic-embed-text-v1.5"

def test_embed_batch():
    from app.generated import embedding_pb2, embedding_pb2_grpc
    channel = grpc.insecure_channel(os.environ["EMBEDDING_SERVICE_URL"])
    stub = embedding_pb2_grpc.EmbeddingServiceStub(channel)

    response = stub.EmbedBatch(embedding_pb2.EmbedBatchRequest(
        texts=["hello", "world", "test"],
        task_type="search_document",
    ))
    assert len(response.results) == 3
    for r in response.results:
        assert len(r.vector) == 768

def test_health():
    from app.generated import embedding_pb2, embedding_pb2_grpc
    channel = grpc.insecure_channel(os.environ["EMBEDDING_SERVICE_URL"])
    stub = embedding_pb2_grpc.EmbeddingServiceStub(channel)

    response = stub.Health(embedding_pb2.google_dot_protobuf_dot_empty__pb2.Empty())
    assert response.status == "ok"
```

- [ ] **Step 2: Run (if service is up)**

```bash
cd apps/api
EMBEDDING_SERVICE_URL=localhost:50051 pytest tests/memory/test_embedding_grpc.py -v
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/memory/test_embedding_grpc.py
git commit -m "test(memory-first): gRPC smoke tests for embedding-service"
```

---

### Task 24: gRPC smoke test for memory-core

**Files:**
- Create: `apps/api/tests/memory/test_memory_core_grpc.py`

- [ ] **Step 1: Write the test**

```python
"""Smoke test for Rust memory-core gRPC.

Requires memory-core running on localhost:50052 with a seeded database.
Skip if not available.
"""
import os
import pytest
import grpc

pytestmark = pytest.mark.skipif(
    not os.environ.get("MEMORY_CORE_URL"),
    reason="MEMORY_CORE_URL not set"
)

TENANT_ID = "0f134606-3906-44a5-9e88-6c2020f0f776"

def test_recall():
    from app.generated import memory_pb2, memory_pb2_grpc
    channel = grpc.insecure_channel(os.environ["MEMORY_CORE_URL"])
    stub = memory_pb2_grpc.MemoryCoreStub(channel)

    response = stub.Recall(memory_pb2.RecallRequest(
        tenant_id=TENANT_ID,
        query="what is integral",
        top_k_per_type=5,
        total_token_budget=4000,
    ))
    # Should return at least some entities from the seeded data
    assert response.metadata.query_time_ms > 0
    assert response.metadata.query_time_ms < 5000  # under 5s

def test_record_observation():
    from app.generated import memory_pb2, memory_pb2_grpc
    channel = grpc.insecure_channel(os.environ["MEMORY_CORE_URL"])
    stub = memory_pb2_grpc.MemoryCoreStub(channel)

    # This should not raise
    stub.RecordObservation(memory_pb2.RecordObservationRequest(
        tenant_id=TENANT_ID,
        entity_id="00000000-0000-0000-0000-000000000001",  # may not exist, test error handling
        content="test observation from integration test",
        confidence=0.5,
        source_type="test",
        source_id="test-1",
    ))

def test_record_commitment():
    from app.generated import memory_pb2, memory_pb2_grpc
    channel = grpc.insecure_channel(os.environ["MEMORY_CORE_URL"])
    stub = memory_pb2_grpc.MemoryCoreStub(channel)

    stub.RecordCommitment(memory_pb2.RecordCommitmentRequest(
        tenant_id=TENANT_ID,
        owner_agent_slug="test_agent",
        title="Test commitment from integration test",
        commitment_type="action",
    ))
```

- [ ] **Step 2: Run (if service is up)**

```bash
cd apps/api
MEMORY_CORE_URL=localhost:50052 pytest tests/memory/test_memory_core_grpc.py -v
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/memory/test_memory_core_grpc.py
git commit -m "test(memory-first): gRPC smoke tests for memory-core"
```

---

### Task 25: Dual-read validation end-to-end test

**Files:**
- Create: `apps/api/tests/memory/test_dual_read.py`

- [ ] **Step 1: Write the test**

```python
"""End-to-end test for dual-read validation.

Requires both Python (PostgreSQL) and Rust (memory-core) paths available.
"""
import os
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.skipif(
    not os.environ.get("MEMORY_CORE_URL"),
    reason="MEMORY_CORE_URL not set (Rust services not running)"
)

def test_dual_read_does_not_crash(db_session, test_tenant):
    """When MEMORY_DUAL_READ=true, recall should complete without errors."""
    from app.memory.recall import recall
    from app.memory.types import RecallRequest

    with patch.dict(os.environ, {"MEMORY_DUAL_READ": "true", "MEMORY_CORE_URL": os.environ["MEMORY_CORE_URL"]}):
        request = RecallRequest(
            tenant_id=test_tenant.id,
            agent_slug="luna",
            query="what meetings do I have today",
            top_k_per_type=5,
            total_token_budget=4000,
        )
        result = recall(db_session, request)
        assert result is not None

def test_validation_metrics_increment(db_session, test_tenant):
    """Dual-read should increment validation metrics."""
    from app.memory.recall import recall
    from app.memory.types import RecallRequest
    from app.memory.validation_metrics import metrics

    before = metrics.total_reads
    with patch.dict(os.environ, {"MEMORY_DUAL_READ": "true", "MEMORY_CORE_URL": os.environ["MEMORY_CORE_URL"]}):
        request = RecallRequest(
            tenant_id=test_tenant.id,
            agent_slug="luna",
            query="who is ray aristy",
            top_k_per_type=3,
            total_token_budget=2000,
        )
        recall(db_session, request)
    assert metrics.total_reads > before
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/tests/memory/test_dual_read.py
git commit -m "test(memory-first): dual-read validation end-to-end test"
```

---

### Task 26: Acceptance gate — Rust services build and pass smoke tests

**Files:** (none new — this is a verification task)

- [ ] **Step 1: Build both Rust services**

```bash
cd apps/embedding-service && cargo build --release
cd apps/memory-core && cargo build --release
```

Expected: both compile without errors.

- [ ] **Step 2: Build Docker images**

```bash
docker build -t agentprovision-embedding-service:latest apps/embedding-service/
docker build -t agentprovision-memory-core:latest apps/memory-core/
```

Expected: images build successfully.

- [ ] **Step 3: Run smoke tests**

```bash
# Start services (requires running PostgreSQL)
docker run -d --name test-embedding -p 50051:50051 agentprovision-embedding-service:latest
docker run -d --name test-memory-core -p 50052:50052 \
  -e DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:5432/agentprovision \
  -e EMBEDDING_SERVICE_URL=http://host.docker.internal:50051 \
  agentprovision-memory-core:latest

sleep 10

cd apps/api
EMBEDDING_SERVICE_URL=localhost:50051 MEMORY_CORE_URL=localhost:50052 \
  pytest tests/memory/test_embedding_grpc.py tests/memory/test_memory_core_grpc.py -v

# Cleanup
docker stop test-embedding test-memory-core
docker rm test-embedding test-memory-core
```

Expected: all tests pass.

- [ ] **Step 4: Verify Python gRPC bindings import cleanly**

```bash
cd apps/api
python -c "
from app.generated import embedding_pb2, embedding_pb2_grpc
from app.generated import memory_pb2, memory_pb2_grpc
print('All gRPC bindings import OK')
print('RecallResponse fields:', list(memory_pb2.RecallResponse.DESCRIPTOR.fields_by_name.keys()))
"
```

Expected: imports succeed, RecallResponse has entities, observations, relations, episodes, commitments, goals, past_conversations, contradictions, metadata.

- [ ] **Step 5: Verify Helm templates render**

```bash
helm template test helm/charts/microservice -f helm/values/embedding-service.yaml > /dev/null && echo "embedding OK"
helm template test helm/charts/microservice -f helm/values/memory-core.yaml > /dev/null && echo "memory-core OK"
```

Expected: both OK.

- [ ] **Step 6: Create PR**

```bash
git push -u origin feat/memory-first-phase-2
gh pr create --title "feat: Phase 2 Memory-First — Rust services production-ready" \
  --body "## Summary
- Generate Python gRPC bindings from proto files
- Fix missing os import in recall.py
- Implement RecordObservation, RecordCommitment, IngestEvents RPCs in memory-core
- Add gRPC health probes to both Rust services
- Add dual-read/dual-write validation infrastructure
- Add connection pooling and retry logic
- Add integration tests for gRPC endpoints
- Update Helm values for gRPC probes
- Add Rust services to local deploy pipeline

## Test plan
- [ ] Both Rust services build (cargo build --release)
- [ ] Docker images build successfully
- [ ] gRPC smoke tests pass against running services
- [ ] Python gRPC bindings import cleanly
- [ ] Helm templates render without errors
- [ ] Dual-read mode returns results from both paths
"
```
