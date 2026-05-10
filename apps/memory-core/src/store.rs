//! `MemoryStore` trait + production `PgStore` impl.
//!
//! The trait isolates the gRPC handlers in `main.rs` from their I/O
//! dependencies (sqlx Postgres pool + embedding-service gRPC client) so
//! they can be unit-tested with a `FakeStore` (see `mod tests` in
//! `main.rs`). Production keeps the behaviour identical: `PgStore` is a
//! 1:1 lift of the SQL and embedding calls that previously lived inline
//! in each handler.
//!
//! The trait surface is **operation-shaped**, not SQL-shaped: callers
//! pass parsed `Uuid`s and validated `&[f32]` embeddings; the impl owns
//! the SQL strings and the pgvector literal encoding. This keeps unit
//! tests free of sqlx and lets the production handlers stay declarative.

use crate::embedding::v1::embedding_service_client::EmbeddingServiceClient;
use crate::embedding::v1::EmbedRequest;
use crate::memory::v1::{
    CommitmentSummary, ConversationSnippet, Entity, EpisodeSummary, Observation, Relation,
};
use crate::{chrono_to_proto_ts, format_pgvector};
use sqlx::Row;
use tonic::Status;
use uuid::Uuid;

/// Operations the four gRPC handlers need from their backing store.
///
/// Implementations must be `Send + Sync + 'static` so an `Arc<dyn MemoryStore>`
/// can be shared across the tonic request handlers (which run on a tokio
/// multi-thread runtime).
#[tonic::async_trait]
pub(crate) trait MemoryStore: Send + Sync + 'static {
    /// Embed a piece of text. `task_type` is `"search_query"` for
    /// recall queries and `"search_document"` for stored content.
    async fn embed(&self, text: &str, task_type: &str) -> Result<Vec<f32>, Status>;

    // ── recall fan-out ──────────────────────────────────────────────────
    async fn fetch_entities(
        &self,
        tenant_id: Uuid,
        query_vec: &[f32],
        top_k: i64,
    ) -> Result<Vec<Entity>, Status>;

    async fn fetch_observations(
        &self,
        tenant_id: Uuid,
        query_vec: &[f32],
        entity_ids: &[String],
        top_k: i64,
    ) -> Result<Vec<Observation>, Status>;

    async fn fetch_relations(
        &self,
        tenant_id: Uuid,
        entity_ids: &[String],
    ) -> Result<Vec<Relation>, Status>;

    async fn fetch_episodes(
        &self,
        tenant_id: Uuid,
        query_vec: &[f32],
        limit: i64,
    ) -> Result<Vec<EpisodeSummary>, Status>;

    async fn fetch_commitments(
        &self,
        tenant_id: Uuid,
        top_k: i64,
    ) -> Result<Vec<CommitmentSummary>, Status>;

    async fn fetch_past_conversations(
        &self,
        tenant_id: Uuid,
        query_vec: &[f32],
        top_k: i64,
    ) -> Result<Vec<ConversationSnippet>, Status>;

    // ── write paths ─────────────────────────────────────────────────────
    /// Insert observation + audit row in a single store call. Production
    /// matches the original handler ordering: observation first, then
    /// `memory_activities`. A failure on either maps to `Status::internal`.
    async fn insert_observation_with_activity(
        &self,
        tenant_id: Uuid,
        entity_id: Uuid,
        obs_id: Uuid,
        content: &str,
        source_type: &str,
        confidence: f32,
        embedding: &[f32],
        actor_slug: &str,
    ) -> Result<(), Status>;

    /// Insert commitment + audit row, mirroring `insert_observation_with_activity`.
    #[allow(clippy::too_many_arguments)]
    async fn insert_commitment_with_activity(
        &self,
        tenant_id: Uuid,
        commitment_id: Uuid,
        owner_agent_slug: &str,
        title: &str,
        description: &str,
        commitment_type: &str,
        due_at: Option<chrono::DateTime<chrono::Utc>>,
    ) -> Result<(), Status>;

    /// Upsert one proposed entity name for a tenant. Returns `true` if a
    /// new row was inserted, `false` if an existing row was touched
    /// (`updated_at = NOW()`). The handler increments its `processed`
    /// counter regardless; the boolean exists so tests can assert which
    /// branch fired.
    async fn upsert_entity_by_name(
        &self,
        tenant_id: Uuid,
        entity_name: &str,
    ) -> Result<bool, Status>;
}

/// Production impl backed by sqlx + the embedding-service gRPC client.
///
/// The body of every method is a **1:1 lift** of the SQL and error
/// mapping that previously lived inline in `MyMemoryCore`'s handler
/// functions. Do not change the SQL here without also updating any
/// matching Python recall paths in `apps/api/app/memory/`.
pub struct PgStore {
    pool: sqlx::PgPool,
    embedding_client: EmbeddingServiceClient<tonic::transport::Channel>,
}

impl PgStore {
    pub async fn new(
        pool: sqlx::PgPool,
        embedding_url: &str,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let embedding_client =
            EmbeddingServiceClient::connect(embedding_url.to_string()).await?;
        Ok(Self {
            pool,
            embedding_client,
        })
    }
}

#[tonic::async_trait]
impl MemoryStore for PgStore {
    async fn embed(&self, text: &str, task_type: &str) -> Result<Vec<f32>, Status> {
        // tonic channels are cloneable and safe for concurrent use.
        let mut client = self.embedding_client.clone();
        let response = client
            .embed(tonic::Request::new(EmbedRequest {
                text: text.to_string(),
                task_type: task_type.to_string(),
            }))
            .await?;
        Ok(response.into_inner().vector)
    }

    async fn fetch_entities(
        &self,
        tenant_id: Uuid,
        query_vec: &[f32],
        top_k: i64,
    ) -> Result<Vec<Entity>, Status> {
        let q = format_pgvector(query_vec);
        let rows = sqlx::query(
            r#"
            SELECT
                ke.id::text as id,
                ke.name,
                ke.entity_type,
                ke.category,
                ke.description,
                (1 - (e.embedding <=> $2::vector)) as similarity
            FROM embeddings e
            JOIN knowledge_entities ke ON e.content_id = ke.id::text
            WHERE e.tenant_id = $1 AND e.content_type = 'entity' AND ke.deleted_at IS NULL
            ORDER BY e.embedding <=> $2::vector
            LIMIT $3
            "#,
        )
        .bind(tenant_id)
        .bind(&q)
        .bind(top_k)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error (entities): {}", e)))?;

        // NOTE: knowledge_entities.category and .description are nullable in the schema
        // (VARCHAR(50) / TEXT, no NOT NULL). The proto Entity defines them as `string`
        // (non-nullable, defaults to ""). Bare `r.get()` panics on NULL with sqlx
        // ColumnDecode { UnexpectedNullError } — instead pull them as Option<String>
        // and default to "". Keep id/name/entity_type as bare get since those columns
        // are NOT NULL in the schema.
        Ok(rows
            .iter()
            .map(|r| Entity {
                id: r.get("id"),
                name: r.get("name"),
                entity_type: r.get("entity_type"),
                category: r
                    .try_get::<Option<String>, _>("category")
                    .ok()
                    .flatten()
                    .unwrap_or_default(),
                description: r
                    .try_get::<Option<String>, _>("description")
                    .ok()
                    .flatten()
                    .unwrap_or_default(),
                similarity: r.get::<f64, _>("similarity") as f32,
            })
            .collect())
    }

    async fn fetch_observations(
        &self,
        tenant_id: Uuid,
        query_vec: &[f32],
        entity_ids: &[String],
        top_k: i64,
    ) -> Result<Vec<Observation>, Status> {
        let q = format_pgvector(query_vec);
        let rows = sqlx::query(
            r#"
            SELECT
                id::text as id,
                entity_id::text as entity_id,
                observation_text as content,
                (1 - (embedding <=> $2::vector)) as similarity
            FROM knowledge_observations
            WHERE tenant_id = $1 AND entity_id::text = ANY($3)
            ORDER BY embedding <=> $2::vector
            LIMIT $4
            "#,
        )
        .bind(tenant_id)
        .bind(&q)
        .bind(entity_ids)
        .bind(top_k)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error (observations): {}", e)))?;

        Ok(rows
            .iter()
            .map(|r| Observation {
                id: r.get("id"),
                entity_id: r.get("entity_id"),
                content: r.get("content"),
                similarity: r.get::<f64, _>("similarity") as f32,
            })
            .collect())
    }

    async fn fetch_relations(
        &self,
        tenant_id: Uuid,
        entity_ids: &[String],
    ) -> Result<Vec<Relation>, Status> {
        let rows = sqlx::query(
            r#"
            SELECT
                from_entity_id::text as from_entity,
                to_entity_id::text as to_entity,
                relation_type
            FROM knowledge_relations
            WHERE tenant_id = $1 AND (from_entity_id::text = ANY($2) OR to_entity_id::text = ANY($2))
            "#,
        )
        .bind(tenant_id)
        .bind(entity_ids)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error (relations): {}", e)))?;

        Ok(rows
            .iter()
            .map(|r| Relation {
                from_entity: r.get("from_entity"),
                to_entity: r.get("to_entity"),
                relation_type: r.get("relation_type"),
            })
            .collect())
    }

    async fn fetch_episodes(
        &self,
        tenant_id: Uuid,
        query_vec: &[f32],
        limit: i64,
    ) -> Result<Vec<EpisodeSummary>, Status> {
        // NOTE: conversation_episodes.created_at is `timestamp without time zone`
        // in the Postgres schema. The Rust side reads it as `DateTime<Utc>` which
        // sqlx maps to TIMESTAMPTZ — without the explicit `AT TIME ZONE 'UTC'`
        // cast every query panics with `mismatched types ... TIMESTAMPTZ vs
        // TIMESTAMP`. We treat stored values as UTC because that's the
        // convention everywhere else.
        let q = format_pgvector(query_vec);
        let rows = sqlx::query(
            r#"
            SELECT
                id::text as id,
                summary,
                (created_at AT TIME ZONE 'UTC') as created_at,
                (1 - (embedding <=> $2::vector)) as similarity
            FROM conversation_episodes
            WHERE tenant_id = $1
            ORDER BY embedding <=> $2::vector
            LIMIT $3
            "#,
        )
        .bind(tenant_id)
        .bind(&q)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error (episodes): {}", e)))?;

        Ok(rows
            .iter()
            .map(|r| EpisodeSummary {
                id: r.get("id"),
                summary: r.get("summary"),
                created_at: Some(chrono_to_proto_ts(
                    r.get::<chrono::DateTime<chrono::Utc>, _>("created_at"),
                )),
                similarity: r.get::<f64, _>("similarity") as f32,
            })
            .collect())
    }

    async fn fetch_commitments(
        &self,
        tenant_id: Uuid,
        top_k: i64,
    ) -> Result<Vec<CommitmentSummary>, Status> {
        // NOTE: commitment_records.due_at is `timestamp without time zone`;
        // cast to TIMESTAMPTZ so sqlx can decode into `Option<DateTime<Utc>>`.
        let rows = sqlx::query(
            r#"
            SELECT
                id::text as id,
                title,
                commitment_type,
                state,
                (due_at AT TIME ZONE 'UTC') as due_at,
                owner_agent_slug
            FROM commitment_records
            WHERE tenant_id = $1 AND state NOT IN ('fulfilled', 'broken', 'cancelled')
            ORDER BY due_at ASC NULLS LAST
            LIMIT $2
            "#,
        )
        .bind(tenant_id)
        .bind(top_k)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error (commitments): {}", e)))?;

        Ok(rows
            .iter()
            .map(|r| {
                let due_at: Option<chrono::DateTime<chrono::Utc>> = r.get("due_at");
                CommitmentSummary {
                    id: r.get("id"),
                    title: r.get("title"),
                    commitment_type: r.get("commitment_type"),
                    status: r.get("state"),
                    due_at: due_at.map(chrono_to_proto_ts),
                    owner_agent_slug: r.get("owner_agent_slug"),
                }
            })
            .collect())
    }

    async fn fetch_past_conversations(
        &self,
        tenant_id: Uuid,
        query_vec: &[f32],
        top_k: i64,
    ) -> Result<Vec<ConversationSnippet>, Status> {
        // NOTE: embeddings.created_at is `timestamp without time zone`;
        // cast to TIMESTAMPTZ so sqlx can decode into `Option<DateTime<Utc>>`.
        let q = format_pgvector(query_vec);
        let rows = sqlx::query(
            r#"
            SELECT
                e.content_id as session_id,
                e.text_content as content,
                'user' as role,
                (e.created_at AT TIME ZONE 'UTC') as created_at,
                (1 - (e.embedding <=> $2::vector)) as similarity
            FROM embeddings e
            WHERE e.tenant_id = $1 AND e.content_type = 'chat_message'
            ORDER BY e.embedding <=> $2::vector
            LIMIT $3
            "#,
        )
        .bind(tenant_id)
        .bind(&q)
        .bind(top_k)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error (conversations): {}", e)))?;

        Ok(rows
            .iter()
            .map(|r| {
                let dt: Option<chrono::DateTime<chrono::Utc>> = r.get("created_at");
                ConversationSnippet {
                    session_id: r.get("session_id"),
                    content: r.get("content"),
                    role: r.get("role"),
                    created_at: dt.map(chrono_to_proto_ts),
                    similarity: r.get::<f64, _>("similarity") as f32,
                }
            })
            .collect())
    }

    async fn insert_observation_with_activity(
        &self,
        tenant_id: Uuid,
        entity_id: Uuid,
        obs_id: Uuid,
        content: &str,
        source_type: &str,
        confidence: f32,
        embedding: &[f32],
        actor_slug: &str,
    ) -> Result<(), Status> {
        let embedding_str = format_pgvector(embedding);
        sqlx::query(
            r#"
            INSERT INTO knowledge_observations
                (id, tenant_id, entity_id, observation_text, observation_type, source_type, confidence, embedding, created_at)
            VALUES ($1, $2, $3, $4, 'fact', $5, $6, $7::vector, NOW())
            "#,
        )
        .bind(obs_id)
        .bind(tenant_id)
        .bind(entity_id)
        .bind(content)
        .bind(source_type)
        .bind(confidence)
        .bind(&embedding_str)
        .execute(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error inserting observation: {}", e)))?;

        sqlx::query(
            r#"
            INSERT INTO memory_activities
                (id, tenant_id, event_type, description, source, entity_id, created_at)
            VALUES ($1, $2, 'observation_created', $3, $4, $5, NOW())
            "#,
        )
        .bind(Uuid::new_v4())
        .bind(tenant_id)
        .bind(format!("Observation recorded for entity {}", entity_id))
        .bind(actor_slug)
        .bind(entity_id)
        .execute(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error inserting memory_activity: {}", e)))?;
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
        sqlx::query(
            r#"
            INSERT INTO commitment_records
                (id, tenant_id, owner_agent_slug, title, description, commitment_type, state, due_at, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'open', $7, NOW())
            "#,
        )
        .bind(commitment_id)
        .bind(tenant_id)
        .bind(owner_agent_slug)
        .bind(title)
        .bind(description)
        .bind(commitment_type)
        .bind(due_at)
        .execute(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error inserting commitment: {}", e)))?;

        sqlx::query(
            r#"
            INSERT INTO memory_activities
                (id, tenant_id, event_type, description, source, created_at)
            VALUES ($1, $2, 'commitment_created', $3, $4, NOW())
            "#,
        )
        .bind(Uuid::new_v4())
        .bind(tenant_id)
        .bind(format!("Commitment created: {}", title))
        .bind(owner_agent_slug)
        .execute(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error inserting memory_activity: {}", e)))?;
        Ok(())
    }

    async fn upsert_entity_by_name(
        &self,
        tenant_id: Uuid,
        entity_name: &str,
    ) -> Result<bool, Status> {
        let existing = sqlx::query(
            r#"
            SELECT id FROM knowledge_entities
            WHERE tenant_id = $1 AND name = $2 AND deleted_at IS NULL
            LIMIT 1
            "#,
        )
        .bind(tenant_id)
        .bind(entity_name)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| Status::internal(format!("DB error checking entity: {}", e)))?;

        if let Some(row) = existing {
            let entity_id: Uuid = row.get("id");
            sqlx::query(r#"UPDATE knowledge_entities SET updated_at = NOW() WHERE id = $1"#)
                .bind(entity_id)
                .execute(&self.pool)
                .await
                .map_err(|e| Status::internal(format!("DB error updating entity: {}", e)))?;
            Ok(false)
        } else {
            sqlx::query(
                r#"
                INSERT INTO knowledge_entities
                    (id, tenant_id, name, entity_type, category, confidence, created_at, updated_at)
                VALUES ($1, $2, $3, 'unknown', 'unknown', 0.5, NOW(), NOW())
                "#,
            )
            .bind(Uuid::new_v4())
            .bind(tenant_id)
            .bind(entity_name)
            .execute(&self.pool)
            .await
            .map_err(|e| Status::internal(format!("DB error inserting entity: {}", e)))?;
            Ok(true)
        }
    }
}
