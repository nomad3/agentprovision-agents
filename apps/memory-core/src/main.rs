use tonic::{transport::Server, Request, Response, Status};
use tonic_health::server::health_reporter;
use memory::v1::memory_core_server::{MemoryCore, MemoryCoreServer};
use memory::v1::{
    RecallRequest, RecallResponse, Entity, Observation, EpisodeSummary,
    CommitmentSummary, GoalSummary, ConversationSnippet, ContradictionSummary, RecallMetadata,
    RecordObservationRequest, RecordCommitmentRequest, IngestRequest, IngestResponse,
};
use sqlx::postgres::PgPoolOptions;
use std::sync::Arc;
use std::time::{Duration, Instant};
use uuid::Uuid;

pub mod memory {
    pub mod v1 {
        tonic::include_proto!("memory.v1");
    }
}

pub mod embedding {
    pub mod v1 {
        tonic::include_proto!("embedding.v1");
    }
}

mod store;
use store::{MemoryStore, PgStore};

// ─── pure helpers (no I/O, unit-tested below) ───────────────────────────────

/// Encode a Rust f32 slice into the literal pgvector accepts via parameter
/// binding: e.g. `[0.1,0.2,-0.3]`. Centralizing this lets us regression-test
/// the encoding (e.g. that we never emit scientific notation that pgvector
/// would reject).
pub(crate) fn format_pgvector(v: &[f32]) -> String {
    format!(
        "[{}]",
        v.iter().map(|x| x.to_string()).collect::<Vec<String>>().join(",")
    )
}

/// Validate and parse a tenant-scoped UUID string as it arrives off the wire.
/// Maps any parse failure to a gRPC `invalid_argument` so the client can act
/// on it without inspecting backend logs.
pub(crate) fn parse_tenant_id(raw: &str) -> Result<Uuid, Status> {
    Uuid::parse_str(raw).map_err(|_| Status::invalid_argument("Invalid tenant_id"))
}

/// Same as `parse_tenant_id` but for the entity_id field. Kept distinct so
/// the error message tells the client which field they got wrong.
pub(crate) fn parse_entity_id(raw: &str) -> Result<Uuid, Status> {
    Uuid::parse_str(raw).map_err(|_| Status::invalid_argument("Invalid entity_id"))
}

/// Convert an inbound protobuf Timestamp to `chrono::DateTime<Utc>`. A
/// timestamp that protobuf considers in-range but chrono cannot represent
/// degrades to `Utc::now()` — the same fallback the production handler uses.
pub(crate) fn proto_ts_to_chrono(ts: Option<prost_types::Timestamp>) -> Option<chrono::DateTime<chrono::Utc>> {
    ts.map(|t| {
        chrono::DateTime::from_timestamp(t.seconds, t.nanos as u32)
            .unwrap_or_else(chrono::Utc::now)
    })
}

/// Convert a `chrono::DateTime<Utc>` to a protobuf Timestamp.
pub(crate) fn chrono_to_proto_ts(dt: chrono::DateTime<chrono::Utc>) -> prost_types::Timestamp {
    prost_types::Timestamp {
        seconds: dt.timestamp(),
        nanos: dt.timestamp_subsec_nanos() as i32,
    }
}

/// Resolve the source_type used when persisting an observation. Empty string
/// from the caller defaults to `"agent"`; everything else passes through.
pub(crate) fn default_source_type(provided: &str) -> String {
    if provided.is_empty() {
        "agent".to_string()
    } else {
        provided.to_string()
    }
}

/// gRPC handler shell — owns nothing but an `Arc<dyn MemoryStore>`.
///
/// All I/O lives behind the trait so each handler is unit-testable with
/// a fake store (see `mod tests` below). Production wires this up with
/// a `PgStore` in `main()`. Refactor introduced 2026-05-05 (phase 5.5):
/// the handlers are a 1:1 lift of the previous inline-SQL bodies.
pub struct MyMemoryCore {
    store: Arc<dyn MemoryStore>,
}

impl MyMemoryCore {
    /// Production constructor: build a `PgStore` and wrap it.
    pub async fn new(
        pool: sqlx::PgPool,
        embedding_url: &str,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let store = PgStore::new(pool, embedding_url).await?;
        Ok(Self {
            store: Arc::new(store),
        })
    }

    /// Constructor for unit tests — accepts any `MemoryStore` impl.
    #[cfg(test)]
    pub(crate) fn from_store(store: Arc<dyn MemoryStore>) -> Self {
        Self { store }
    }
}

#[tonic::async_trait]
impl MemoryCore for MyMemoryCore {
    async fn recall(
        &self,
        request: Request<RecallRequest>,
    ) -> Result<Response<RecallResponse>, Status> {
        let start = Instant::now();
        let req = request.into_inner();
        let tenant_id = parse_tenant_id(&req.tenant_id)?;

        println!("Recalling for tenant {} query: {}", tenant_id, req.query);

        // 1. Embed the query
        let query_vec = self.store.embed(&req.query, "search_query").await?;

        // 2. Search entities
        let entities: Vec<Entity> = self
            .store
            .fetch_entities(tenant_id, &query_vec, req.top_k_per_type as i64)
            .await?;

        // 3. Search observations
        let entity_ids: Vec<String> = entities.iter().map(|e| e.id.clone()).collect();
        let observations: Vec<Observation> = self
            .store
            .fetch_observations(tenant_id, &query_vec, &entity_ids, req.top_k_per_type as i64)
            .await?;

        // 4. Search relations
        let relations = self.store.fetch_relations(tenant_id, &entity_ids).await?;

        // 5. Search episodes (limit fixed at 5 to match prior behaviour)
        let episodes: Vec<EpisodeSummary> =
            self.store.fetch_episodes(tenant_id, &query_vec, 5).await?;

        // 6. Search commitments (open/in_progress, not fulfilled/broken/cancelled)
        let commitments: Vec<CommitmentSummary> = self
            .store
            .fetch_commitments(tenant_id, req.top_k_per_type as i64)
            .await?;

        // 7. Search past conversations (chat_message embeddings, vector similarity)
        let past_conversations: Vec<ConversationSnippet> = self
            .store
            .fetch_past_conversations(tenant_id, &query_vec, req.top_k_per_type as i64)
            .await?;

        // 8. Goals — empty for now (no goals table yet)
        let goals: Vec<GoalSummary> = Vec::new();

        // 9. Contradictions — empty for now (no contradiction detection yet)
        let contradictions: Vec<ContradictionSummary> = Vec::new();

        // 10. Build metadata
        let query_time_ms = start.elapsed().as_millis() as i32;
        let total_tokens_estimate = estimate_tokens(
            &entities,
            &observations,
            &episodes,
            &commitments,
            &past_conversations,
        );

        let metadata = Some(RecallMetadata {
            query_time_ms,
            total_tokens_estimate,
            degraded: false,
            degradation_reason: String::new(),
        });

        println!(
            "Recall completed in {}ms, ~{} tokens",
            query_time_ms, total_tokens_estimate
        );

        Ok(Response::new(RecallResponse {
            entities,
            observations,
            relations,
            episodes,
            commitments,
            goals,
            past_conversations,
            contradictions,
            metadata,
        }))
    }

    async fn record_observation(
        &self,
        request: Request<RecordObservationRequest>,
    ) -> Result<Response<()>, Status> {
        let req = request.into_inner();
        let tenant_id = parse_tenant_id(&req.tenant_id)?;
        let entity_id = parse_entity_id(&req.entity_id)?;

        // Embed the observation text
        let embedding = self.store.embed(&req.content, "search_document").await?;

        let obs_id = Uuid::new_v4();
        let source_type = default_source_type(&req.source_type);

        self.store
            .insert_observation_with_activity(
                tenant_id,
                entity_id,
                obs_id,
                &req.content,
                &source_type,
                req.confidence,
                &embedding,
                &req.actor_slug,
            )
            .await?;

        println!(
            "RecordObservation: tenant={} entity={} obs_id={}",
            tenant_id, entity_id, obs_id
        );

        Ok(Response::new(()))
    }

    async fn record_commitment(
        &self,
        request: Request<RecordCommitmentRequest>,
    ) -> Result<Response<()>, Status> {
        let req = request.into_inner();
        let tenant_id = parse_tenant_id(&req.tenant_id)?;

        let commitment_id = Uuid::new_v4();

        // Convert optional protobuf Timestamp to chrono DateTime
        let due_at: Option<chrono::DateTime<chrono::Utc>> = proto_ts_to_chrono(req.due_at);

        self.store
            .insert_commitment_with_activity(
                tenant_id,
                commitment_id,
                &req.owner_agent_slug,
                &req.title,
                &req.description,
                &req.commitment_type,
                due_at,
            )
            .await?;

        println!(
            "RecordCommitment: tenant={} id={} title={}",
            tenant_id, commitment_id, req.title
        );

        Ok(Response::new(()))
    }

    async fn ingest_events(
        &self,
        request: Request<IngestRequest>,
    ) -> Result<Response<IngestResponse>, Status> {
        let req = request.into_inner();
        let tenant_id = parse_tenant_id(&req.tenant_id)?;

        let mut processed: i32 = 0;

        for event in &req.events {
            for entity_name in &event.proposed_entities {
                if entity_name.trim().is_empty() {
                    continue;
                }
                // upsert_entity_by_name returns true on insert, false on
                // update. Both branches still count toward `processed` —
                // matches the pre-refactor behaviour exactly.
                let _ = self.store.upsert_entity_by_name(tenant_id, entity_name).await?;
                processed += 1;
            }
        }

        println!(
            "IngestEvents: tenant={} processed={} entities",
            tenant_id, processed
        );

        Ok(Response::new(IngestResponse { processed }))
    }
}

/// Rough token estimate: ~1 token per 4 chars of text content.
fn estimate_tokens(
    entities: &[Entity],
    observations: &[Observation],
    episodes: &[EpisodeSummary],
    commitments: &[CommitmentSummary],
    conversations: &[ConversationSnippet],
) -> i32 {
    let mut chars: usize = 0;
    for e in entities {
        chars += e.name.len() + e.description.len() + e.entity_type.len() + e.category.len();
    }
    for o in observations {
        chars += o.content.len();
    }
    for ep in episodes {
        chars += ep.summary.len();
    }
    for c in commitments {
        chars += c.title.len() + c.commitment_type.len() + c.status.len();
    }
    for cv in conversations {
        chars += cv.content.len();
    }
    (chars / 4) as i32
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();

    let database_url = std::env::var("DATABASE_URL")
        .unwrap_or_else(|_| "postgresql://postgres:postgres@localhost:5432/agentprovision".to_string());
    
    let embedding_url = std::env::var("EMBEDDING_SERVICE_URL")
        .unwrap_or_else(|_| "http://localhost:50051".to_string());

    println!("Connecting to database...");
    let pool = PgPoolOptions::new()
        .max_connections(20)
        .acquire_timeout(Duration::from_secs(5))
        .idle_timeout(Duration::from_secs(300))
        .connect(&database_url)
        .await?;

    println!("Connecting to embedding service at {}...", embedding_url);
    let service = MyMemoryCore::new(pool, &embedding_url).await?;

    let (mut health_reporter, health_service) = health_reporter();
    health_reporter
        .set_serving::<MemoryCoreServer<MyMemoryCore>>()
        .await;

    let addr = "0.0.0.0:50052".parse()?;
    println!("MemoryCore listening on {}", addr);

    Server::builder()
        .timeout(Duration::from_secs(30))
        .add_service(health_service)
        .add_service(MemoryCoreServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use memory::v1::{
        CommitmentSummary, ConversationSnippet, Entity, EpisodeSummary, Observation,
    };
    use pretty_assertions::assert_eq;

    // ---- format_pgvector ---------------------------------------------------

    #[test]
    fn format_pgvector_simple_three_dim() {
        assert_eq!(format_pgvector(&[0.1, 0.2, 0.3]), "[0.1,0.2,0.3]");
    }

    #[test]
    fn format_pgvector_empty_vector_renders_empty_brackets() {
        assert_eq!(format_pgvector(&[]), "[]");
    }

    #[test]
    fn format_pgvector_single_element() {
        assert_eq!(format_pgvector(&[1.0_f32]), "[1]");
    }

    #[test]
    fn format_pgvector_handles_negative_and_zero() {
        let s = format_pgvector(&[0.0, -0.5, 0.5]);
        assert_eq!(s, "[0,-0.5,0.5]");
    }

    #[test]
    fn format_pgvector_round_trips_via_split() {
        // Round-trip: parse the literal back into f32 values and compare.
        // pgvector requires plain decimal — this guards against accidental
        // scientific-notation output for large/small floats.
        let original: Vec<f32> = vec![1e-3, 2.5, -7.25];
        let s = format_pgvector(&original);
        let inner = &s[1..s.len() - 1];
        let parsed: Vec<f32> = inner.split(',').map(|t| t.parse::<f32>().unwrap()).collect();
        assert_eq!(parsed, original);
    }

    #[test]
    fn format_pgvector_768_dim_has_brackets_and_767_commas() {
        let v = vec![0.0_f32; 768];
        let s = format_pgvector(&v);
        assert!(s.starts_with('['));
        assert!(s.ends_with(']'));
        let commas = s.chars().filter(|c| *c == ',').count();
        assert_eq!(commas, 767);
    }

    // ---- parse_tenant_id / parse_entity_id ---------------------------------

    #[test]
    fn parse_tenant_id_accepts_valid_uuid() {
        let u = Uuid::new_v4();
        let parsed = parse_tenant_id(&u.to_string()).expect("should parse");
        assert_eq!(parsed, u);
    }

    #[test]
    fn parse_tenant_id_rejects_garbage_with_invalid_argument() {
        let err = parse_tenant_id("not-a-uuid").expect_err("should fail");
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
        assert!(err.message().contains("tenant_id"));
    }

    #[test]
    fn parse_tenant_id_rejects_empty_string() {
        let err = parse_tenant_id("").expect_err("empty must fail");
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
    }

    #[test]
    fn parse_entity_id_accepts_valid_uuid() {
        let u = Uuid::new_v4();
        let parsed = parse_entity_id(&u.to_string()).expect("should parse");
        assert_eq!(parsed, u);
    }

    #[test]
    fn parse_entity_id_rejects_garbage_with_distinct_message() {
        let err = parse_entity_id("nope").expect_err("should fail");
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
        assert!(err.message().contains("entity_id"));
    }

    #[test]
    fn parse_tenant_id_and_entity_id_have_different_messages() {
        // Sanity: clients can tell which field is wrong from the error alone.
        let t_err = parse_tenant_id("x").unwrap_err();
        let e_err = parse_entity_id("x").unwrap_err();
        assert_ne!(t_err.message(), e_err.message());
    }

    // ---- proto_ts_to_chrono / chrono_to_proto_ts ---------------------------

    #[test]
    fn proto_ts_to_chrono_none_passes_through() {
        assert!(proto_ts_to_chrono(None).is_none());
    }

    #[test]
    fn proto_ts_to_chrono_round_trip() {
        let ts = prost_types::Timestamp { seconds: 1_700_000_000, nanos: 123_456_789 };
        let chrono_dt = proto_ts_to_chrono(Some(ts.clone())).expect("should convert");
        let back = chrono_to_proto_ts(chrono_dt);
        assert_eq!(back.seconds, ts.seconds);
        assert_eq!(back.nanos, ts.nanos);
    }

    #[test]
    fn chrono_to_proto_ts_unix_epoch() {
        let dt = chrono::DateTime::<chrono::Utc>::from_timestamp(0, 0).unwrap();
        let ts = chrono_to_proto_ts(dt);
        assert_eq!(ts.seconds, 0);
        assert_eq!(ts.nanos, 0);
    }

    #[test]
    fn proto_ts_to_chrono_zero_is_unix_epoch() {
        let ts = prost_types::Timestamp { seconds: 0, nanos: 0 };
        let dt = proto_ts_to_chrono(Some(ts)).expect("should convert");
        assert_eq!(dt.timestamp(), 0);
    }

    // ---- default_source_type -----------------------------------------------

    #[test]
    fn default_source_type_empty_yields_agent() {
        assert_eq!(default_source_type(""), "agent");
    }

    #[test]
    fn default_source_type_passthrough() {
        assert_eq!(default_source_type("user"), "user");
        assert_eq!(default_source_type("imported"), "imported");
    }

    #[test]
    fn default_source_type_whitespace_is_not_empty() {
        // Caller intent: whitespace was a deliberate input, do not coerce it.
        assert_eq!(default_source_type(" "), " ");
    }

    // ---- estimate_tokens ---------------------------------------------------

    fn entity(name: &str, etype: &str, cat: &str, desc: &str) -> Entity {
        Entity {
            id: "e".into(),
            name: name.into(),
            entity_type: etype.into(),
            category: cat.into(),
            description: desc.into(),
            similarity: 0.0,
        }
    }

    #[test]
    fn estimate_tokens_empty_inputs_return_zero() {
        let n = estimate_tokens(&[], &[], &[], &[], &[]);
        assert_eq!(n, 0);
    }

    #[test]
    fn estimate_tokens_uses_chars_div_4() {
        // Total content length = 16 chars => 4 tokens (16 / 4).
        let entities = vec![entity("aaaa", "bb", "cc", "dddddd")]; // 4+2+2+6 = 14
        let observations = vec![Observation { id: "".into(), entity_id: "".into(), content: "xx".into(), similarity: 0.0 }]; // 2
        // total chars = 14 + 2 = 16 -> 16/4 = 4
        let n = estimate_tokens(&entities, &observations, &[], &[], &[]);
        assert_eq!(n, 4);
    }

    #[test]
    fn estimate_tokens_aggregates_all_buckets() {
        let entities = vec![entity("ab", "cd", "ef", "gh")]; // 8
        let observations = vec![Observation { id: "".into(), entity_id: "".into(), content: "ijkl".into(), similarity: 0.0 }]; // 4
        let episodes = vec![EpisodeSummary { id: "".into(), summary: "mnop".into(), created_at: None, similarity: 0.0 }]; // 4
        let commitments = vec![CommitmentSummary {
            id: "".into(), title: "qrst".into(), commitment_type: "uv".into(),
            status: "wx".into(), due_at: None, owner_agent_slug: "".into(),
        }]; // 4+2+2 = 8
        let conversations = vec![ConversationSnippet {
            session_id: "".into(), content: "yzAB".into(), role: "".into(),
            created_at: None, similarity: 0.0,
        }]; // 4
        // Total = 8 + 4 + 4 + 8 + 4 = 28 -> 28/4 = 7
        let n = estimate_tokens(&entities, &observations, &episodes, &commitments, &conversations);
        assert_eq!(n, 7);
    }

    #[test]
    fn estimate_tokens_truncates_toward_zero() {
        // 7 chars / 4 = 1 (integer division)
        let entities = vec![entity("aaaaaaa", "", "", "")]; // 7
        let n = estimate_tokens(&entities, &[], &[], &[], &[]);
        assert_eq!(n, 1);
    }

    // ── handler unit tests via FakeStore ────────────────────────────────
    //
    // These cover the four gRPC methods on `MyMemoryCore` without touching
    // Postgres or the embedding-service. The fake lets each test
    // (a) assert the call dispatch order/arguments and (b) inject errors
    // to exercise the failure branches.
    //
    // Refactor introduced 2026-05-05 (phase 5.5) — see `src/store.rs`.

    use crate::memory::v1::memory_core_server::MemoryCore;
    use crate::memory::v1::{
        IngestRequest, MemoryEvent, RecallRequest, RecordCommitmentRequest,
        RecordObservationRequest,
    };
    use crate::store::MemoryStore;
    use std::sync::{Arc, Mutex};
    use tonic::Code;

    #[derive(Default)]
    struct FakeStoreState {
        embed_calls: Vec<(String, String)>,
        upsert_calls: Vec<(Uuid, String)>,
        observation_inserts: Vec<(Uuid, Uuid, Uuid, String, String, f32, String)>,
        commitment_inserts:
            Vec<(Uuid, Uuid, String, String, String, Option<chrono::DateTime<chrono::Utc>>)>,
    }

    /// Configurable in-memory `MemoryStore` for handler tests.
    #[derive(Default)]
    struct FakeStore {
        state: Mutex<FakeStoreState>,
        // ── inject ──
        embed_result: Option<Vec<f32>>,
        embed_fail: bool,
        entities_result: Vec<Entity>,
        entities_fail: bool,
        observations_result: Vec<Observation>,
        relations_result: Vec<crate::memory::v1::Relation>,
        episodes_result: Vec<EpisodeSummary>,
        commitments_result: Vec<CommitmentSummary>,
        conversations_result: Vec<ConversationSnippet>,
        observation_insert_fail: bool,
        commitment_insert_fail: bool,
        // for ingest: sequence of bool returns (true = inserted, false = updated).
        upsert_returns: Mutex<Vec<bool>>,
        upsert_fail_on_name: Option<String>,
    }

    impl FakeStore {
        fn arc(self) -> Arc<dyn MemoryStore> {
            Arc::new(self)
        }
    }

    #[tonic::async_trait]
    impl MemoryStore for FakeStore {
        async fn embed(&self, text: &str, task_type: &str) -> Result<Vec<f32>, Status> {
            self.state
                .lock()
                .unwrap()
                .embed_calls
                .push((text.to_string(), task_type.to_string()));
            if self.embed_fail {
                return Err(Status::unavailable("embed boom"));
            }
            Ok(self.embed_result.clone().unwrap_or_else(|| vec![0.1, 0.2, 0.3]))
        }

        async fn fetch_entities(
            &self,
            _t: Uuid,
            _v: &[f32],
            _k: i64,
        ) -> Result<Vec<Entity>, Status> {
            if self.entities_fail {
                return Err(Status::internal("DB error (entities): pool exhausted"));
            }
            Ok(self.entities_result.clone())
        }

        async fn fetch_observations(
            &self,
            _t: Uuid,
            _v: &[f32],
            _ids: &[String],
            _k: i64,
        ) -> Result<Vec<Observation>, Status> {
            Ok(self.observations_result.clone())
        }

        async fn fetch_relations(
            &self,
            _t: Uuid,
            _ids: &[String],
        ) -> Result<Vec<crate::memory::v1::Relation>, Status> {
            Ok(self.relations_result.clone())
        }

        async fn fetch_episodes(
            &self,
            _t: Uuid,
            _v: &[f32],
            _l: i64,
        ) -> Result<Vec<EpisodeSummary>, Status> {
            Ok(self.episodes_result.clone())
        }

        async fn fetch_commitments(
            &self,
            _t: Uuid,
            _k: i64,
        ) -> Result<Vec<CommitmentSummary>, Status> {
            Ok(self.commitments_result.clone())
        }

        async fn fetch_past_conversations(
            &self,
            _t: Uuid,
            _v: &[f32],
            _k: i64,
        ) -> Result<Vec<ConversationSnippet>, Status> {
            Ok(self.conversations_result.clone())
        }

        async fn insert_observation_with_activity(
            &self,
            tenant_id: Uuid,
            entity_id: Uuid,
            obs_id: Uuid,
            content: &str,
            source_type: &str,
            confidence: f32,
            _embedding: &[f32],
            actor_slug: &str,
        ) -> Result<(), Status> {
            if self.observation_insert_fail {
                return Err(Status::internal(
                    "DB error inserting observation: connection refused",
                ));
            }
            self.state.lock().unwrap().observation_inserts.push((
                tenant_id,
                entity_id,
                obs_id,
                content.to_string(),
                source_type.to_string(),
                confidence,
                actor_slug.to_string(),
            ));
            Ok(())
        }

        async fn insert_commitment_with_activity(
            &self,
            tenant_id: Uuid,
            commitment_id: Uuid,
            owner_agent_slug: &str,
            title: &str,
            description: &str,
            commitment_type: &str,
            due_at: Option<chrono::DateTime<chrono::Utc>>,
        ) -> Result<(), Status> {
            if self.commitment_insert_fail {
                return Err(Status::internal(
                    "DB error inserting commitment: connection refused",
                ));
            }
            self.state.lock().unwrap().commitment_inserts.push((
                tenant_id,
                commitment_id,
                owner_agent_slug.to_string(),
                title.to_string(),
                description.to_string(),
                due_at,
            ));
            let _ = (commitment_type,);
            Ok(())
        }

        async fn upsert_entity_by_name(
            &self,
            tenant_id: Uuid,
            entity_name: &str,
        ) -> Result<bool, Status> {
            if let Some(ref bad) = self.upsert_fail_on_name {
                if bad == entity_name {
                    return Err(Status::internal("DB error checking entity: timeout"));
                }
            }
            self.state
                .lock()
                .unwrap()
                .upsert_calls
                .push((tenant_id, entity_name.to_string()));
            // Pop a queued bool, default to true (insert) if none queued.
            let next = {
                let mut g = self.upsert_returns.lock().unwrap();
                if g.is_empty() {
                    true
                } else {
                    g.remove(0)
                }
            };
            Ok(next)
        }
    }

    fn rt() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
    }

    fn ent(id: &str) -> Entity {
        Entity {
            id: id.into(),
            name: format!("name-{}", id),
            entity_type: "person".into(),
            category: "internal".into(),
            description: "desc".into(),
            similarity: 0.9,
        }
    }

    // ── Recall ──────────────────────────────────────────────────────────

    #[test]
    fn recall_invalid_tenant_returns_invalid_argument() {
        let svc = MyMemoryCore::from_store(FakeStore::default().arc());
        let req = Request::new(RecallRequest {
            tenant_id: "not-a-uuid".into(),
            agent_slug: "luna".into(),
            query: "anything".into(),
            user_id: "".into(),
            chat_session_id: "".into(),
            top_k_per_type: 5,
            total_token_budget: 0,
        });
        let err = rt().block_on(svc.recall(req)).expect_err("must reject");
        assert_eq!(err.code(), Code::InvalidArgument);
    }

    #[test]
    fn recall_happy_path_assembles_full_response() {
        let mut fake = FakeStore::default();
        fake.entities_result = vec![ent("e1"), ent("e2")];
        fake.observations_result = vec![Observation {
            id: "o1".into(),
            entity_id: "e1".into(),
            content: "obs".into(),
            similarity: 0.8,
        }];
        let svc = MyMemoryCore::from_store(fake.arc());

        let tid = Uuid::new_v4();
        let req = Request::new(RecallRequest {
            tenant_id: tid.to_string(),
            agent_slug: "luna".into(),
            query: "what is up".into(),
            user_id: "".into(),
            chat_session_id: "".into(),
            top_k_per_type: 3,
            total_token_budget: 0,
        });

        let resp = rt().block_on(svc.recall(req)).expect("ok").into_inner();
        assert_eq!(resp.entities.len(), 2);
        assert_eq!(resp.observations.len(), 1);
        // Goals + contradictions are still empty stubs.
        assert!(resp.goals.is_empty());
        assert!(resp.contradictions.is_empty());
        let md = resp.metadata.expect("metadata present");
        assert!(!md.degraded);
        assert!(md.degradation_reason.is_empty());
    }

    #[test]
    fn recall_propagates_embed_failure_as_status() {
        let fake = FakeStore {
            embed_fail: true,
            ..Default::default()
        };
        let svc = MyMemoryCore::from_store(fake.arc());
        let req = Request::new(RecallRequest {
            tenant_id: Uuid::new_v4().to_string(),
            agent_slug: "luna".into(),
            query: "q".into(),
            user_id: "".into(),
            chat_session_id: "".into(),
            top_k_per_type: 5,
            total_token_budget: 0,
        });
        let err = rt().block_on(svc.recall(req)).expect_err("embed err must surface");
        // embed errors are tonic Status; whatever code the embedder emitted is
        // forwarded to the caller (here `Unavailable`).
        assert_eq!(err.code(), Code::Unavailable);
    }

    #[test]
    fn recall_db_failure_on_entities_returns_internal() {
        let fake = FakeStore {
            entities_fail: true,
            ..Default::default()
        };
        let svc = MyMemoryCore::from_store(fake.arc());
        let req = Request::new(RecallRequest {
            tenant_id: Uuid::new_v4().to_string(),
            agent_slug: "luna".into(),
            query: "q".into(),
            user_id: "".into(),
            chat_session_id: "".into(),
            top_k_per_type: 5,
            total_token_budget: 0,
        });
        let err = rt().block_on(svc.recall(req)).expect_err("entity fetch must fail");
        assert_eq!(err.code(), Code::Internal);
        assert!(err.message().contains("entities"));
    }

    // ── RecordObservation ───────────────────────────────────────────────

    #[test]
    fn record_observation_invalid_tenant_rejected() {
        let svc = MyMemoryCore::from_store(FakeStore::default().arc());
        let req = Request::new(RecordObservationRequest {
            tenant_id: "garbage".into(),
            entity_id: Uuid::new_v4().to_string(),
            content: "x".into(),
            confidence: 1.0,
            source_type: "".into(),
            source_id: "".into(),
            actor_slug: "luna".into(),
        });
        let err = rt()
            .block_on(svc.record_observation(req))
            .expect_err("tenant gate must fire first");
        assert_eq!(err.code(), Code::InvalidArgument);
        assert!(err.message().contains("tenant_id"));
    }

    #[test]
    fn record_observation_invalid_entity_rejected_with_distinct_message() {
        let svc = MyMemoryCore::from_store(FakeStore::default().arc());
        let req = Request::new(RecordObservationRequest {
            tenant_id: Uuid::new_v4().to_string(),
            entity_id: "garbage".into(),
            content: "x".into(),
            confidence: 1.0,
            source_type: "".into(),
            source_id: "".into(),
            actor_slug: "luna".into(),
        });
        let err = rt().block_on(svc.record_observation(req)).expect_err("must reject");
        assert_eq!(err.code(), Code::InvalidArgument);
        assert!(err.message().contains("entity_id"));
    }

    #[test]
    fn record_observation_happy_path_dispatches_with_default_source() {
        let fake = Arc::new(FakeStore::default());
        let svc = MyMemoryCore::from_store(fake.clone() as Arc<dyn MemoryStore>);

        let tid = Uuid::new_v4();
        let eid = Uuid::new_v4();
        let req = Request::new(RecordObservationRequest {
            tenant_id: tid.to_string(),
            entity_id: eid.to_string(),
            content: "hello world".into(),
            confidence: 0.7,
            source_type: "".into(), // empty -> defaults to "agent"
            source_id: "".into(),
            actor_slug: "luna".into(),
        });
        rt().block_on(svc.record_observation(req)).expect("ok");

        let st = fake.state.lock().unwrap();
        assert_eq!(st.embed_calls.len(), 1);
        assert_eq!(st.embed_calls[0].1, "search_document");
        assert_eq!(st.observation_inserts.len(), 1);
        let (got_t, got_e, _obs_id, content, src, conf, actor) =
            &st.observation_inserts[0];
        assert_eq!(*got_t, tid);
        assert_eq!(*got_e, eid);
        assert_eq!(content, "hello world");
        assert_eq!(src, "agent"); // default applied
        assert!((*conf - 0.7).abs() < 1e-6);
        assert_eq!(actor, "luna");
    }

    #[test]
    fn record_observation_db_failure_maps_to_internal() {
        let fake = FakeStore {
            observation_insert_fail: true,
            ..Default::default()
        };
        let svc = MyMemoryCore::from_store(fake.arc());
        let req = Request::new(RecordObservationRequest {
            tenant_id: Uuid::new_v4().to_string(),
            entity_id: Uuid::new_v4().to_string(),
            content: "x".into(),
            confidence: 1.0,
            source_type: "user".into(),
            source_id: "".into(),
            actor_slug: "luna".into(),
        });
        let err = rt().block_on(svc.record_observation(req)).expect_err("db boom");
        assert_eq!(err.code(), Code::Internal);
        assert!(err.message().contains("observation"));
    }

    // ── RecordCommitment ────────────────────────────────────────────────

    #[test]
    fn record_commitment_invalid_tenant_rejected() {
        let svc = MyMemoryCore::from_store(FakeStore::default().arc());
        let req = Request::new(RecordCommitmentRequest {
            tenant_id: "garbage".into(),
            owner_agent_slug: "luna".into(),
            title: "t".into(),
            description: "d".into(),
            commitment_type: "deliverable".into(),
            due_at: None,
        });
        let err = rt().block_on(svc.record_commitment(req)).expect_err("must reject");
        assert_eq!(err.code(), Code::InvalidArgument);
    }

    #[test]
    fn record_commitment_with_due_at_propagates_timestamp() {
        let fake = Arc::new(FakeStore::default());
        let svc = MyMemoryCore::from_store(fake.clone() as Arc<dyn MemoryStore>);

        let tid = Uuid::new_v4();
        let due = prost_types::Timestamp {
            seconds: 1_700_000_000,
            nanos: 0,
        };
        let req = Request::new(RecordCommitmentRequest {
            tenant_id: tid.to_string(),
            owner_agent_slug: "luna".into(),
            title: "Send the report".into(),
            description: "Friday EOD".into(),
            commitment_type: "deliverable".into(),
            due_at: Some(due),
        });
        rt().block_on(svc.record_commitment(req)).expect("ok");

        let st = fake.state.lock().unwrap();
        assert_eq!(st.commitment_inserts.len(), 1);
        let (got_t, _id, owner, title, desc, due_at) = &st.commitment_inserts[0];
        assert_eq!(*got_t, tid);
        assert_eq!(owner, "luna");
        assert_eq!(title, "Send the report");
        assert_eq!(desc, "Friday EOD");
        assert_eq!(due_at.unwrap().timestamp(), 1_700_000_000);
        // Embed is NOT called for commitments — they aren't vector-searched.
        assert_eq!(st.embed_calls.len(), 0);
    }

    #[test]
    fn record_commitment_db_failure_maps_to_internal() {
        let fake = FakeStore {
            commitment_insert_fail: true,
            ..Default::default()
        };
        let svc = MyMemoryCore::from_store(fake.arc());
        let req = Request::new(RecordCommitmentRequest {
            tenant_id: Uuid::new_v4().to_string(),
            owner_agent_slug: "luna".into(),
            title: "t".into(),
            description: "d".into(),
            commitment_type: "deliverable".into(),
            due_at: None,
        });
        let err = rt().block_on(svc.record_commitment(req)).expect_err("db boom");
        assert_eq!(err.code(), Code::Internal);
        assert!(err.message().contains("commitment"));
    }

    // ── IngestEvents ────────────────────────────────────────────────────

    #[test]
    fn ingest_invalid_tenant_rejected() {
        let svc = MyMemoryCore::from_store(FakeStore::default().arc());
        let req = Request::new(IngestRequest {
            tenant_id: "garbage".into(),
            events: vec![],
        });
        let err = rt().block_on(svc.ingest_events(req)).expect_err("must reject");
        assert_eq!(err.code(), Code::InvalidArgument);
    }

    #[test]
    fn ingest_skips_blank_names_and_counts_only_real_ones() {
        let fake = Arc::new(FakeStore::default());
        let svc = MyMemoryCore::from_store(fake.clone() as Arc<dyn MemoryStore>);

        let tid = Uuid::new_v4();
        let req = Request::new(IngestRequest {
            tenant_id: tid.to_string(),
            events: vec![MemoryEvent {
                source_type: "gmail".into(),
                source_id: "msg-1".into(),
                proposed_entities: vec![
                    "Acme Corp".into(),
                    "".into(),       // skipped
                    "   ".into(),    // skipped (whitespace only)
                    "Jane Doe".into(),
                ],
                actor_slug: "luna".into(),
            }],
        });
        let resp = rt().block_on(svc.ingest_events(req)).expect("ok").into_inner();
        assert_eq!(resp.processed, 2);

        let st = fake.state.lock().unwrap();
        assert_eq!(st.upsert_calls.len(), 2);
        assert_eq!(st.upsert_calls[0].1, "Acme Corp");
        assert_eq!(st.upsert_calls[1].1, "Jane Doe");
    }

    #[test]
    fn ingest_counts_both_insert_and_update_branches() {
        // Ensure the `processed` counter increments regardless of whether
        // the upsert created or updated the row — both branches must count.
        let fake = FakeStore {
            upsert_returns: Mutex::new(vec![true, false, true]),
            ..Default::default()
        };
        let fake = Arc::new(fake);
        let svc = MyMemoryCore::from_store(fake.clone() as Arc<dyn MemoryStore>);

        let req = Request::new(IngestRequest {
            tenant_id: Uuid::new_v4().to_string(),
            events: vec![MemoryEvent {
                source_type: "".into(),
                source_id: "".into(),
                proposed_entities: vec!["A".into(), "B".into(), "C".into()],
                actor_slug: "luna".into(),
            }],
        });
        let resp = rt().block_on(svc.ingest_events(req)).expect("ok").into_inner();
        assert_eq!(resp.processed, 3);
    }

    #[test]
    fn ingest_propagates_store_failure() {
        let fake = FakeStore {
            upsert_fail_on_name: Some("Bad Entity".into()),
            ..Default::default()
        };
        let svc = MyMemoryCore::from_store(fake.arc());
        let req = Request::new(IngestRequest {
            tenant_id: Uuid::new_v4().to_string(),
            events: vec![MemoryEvent {
                source_type: "".into(),
                source_id: "".into(),
                proposed_entities: vec!["Bad Entity".into()],
                actor_slug: "luna".into(),
            }],
        });
        let err = rt().block_on(svc.ingest_events(req)).expect_err("must surface");
        assert_eq!(err.code(), Code::Internal);
    }
}
