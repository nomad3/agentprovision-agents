//! Serde models matching the AgentProvision API schemas.
//!
//! Only the fields the CLI / Luna actually read are modelled today; new fields
//! can be added freely because everything uses `#[serde(default)]` and
//! `serde_json::Value` for unknown extras.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::fmt;
use uuid::Uuid;

#[derive(Clone, Serialize, Deserialize)]
pub struct Token {
    pub access_token: String,
    #[serde(default = "default_token_type")]
    pub token_type: String,
}

// PR #332 review Critical #1 fix: never let the bearer token print
// through the default `#[derive(Debug)]` impl — even with -vv on the
// CLI, the only thing log lines should ever see is `Token { access_token: <redacted>, .. }`.
impl fmt::Debug for Token {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Token")
            .field("access_token", &"<redacted>")
            .field("token_type", &self.token_type)
            .finish()
    }
}

fn default_token_type() -> String {
    "bearer".into()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub id: Uuid,
    pub email: String,
    #[serde(default)]
    pub full_name: Option<String>,
    #[serde(default)]
    pub tenant_id: Option<Uuid>,
    #[serde(default)]
    pub is_superuser: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tenant {
    pub id: Uuid,
    pub name: String,
    #[serde(default)]
    pub slug: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Agent {
    pub id: Uuid,
    pub name: String,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatSession {
    pub id: Uuid,
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub agent_id: Option<Uuid>,
    #[serde(default)]
    pub created_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatMessage {
    pub id: Option<Uuid>,
    pub role: String,
    pub content: String,
    #[serde(default)]
    pub created_at: Option<DateTime<Utc>>,
    /// Per-message token count. NULL when the server didn't measure
    /// (older messages, agents that don't emit a usage struct). The
    /// CLI must render absence as `—`, NOT 0 — they mean different
    /// things. Exposed via
    /// `apps/api/app/schemas/chat.py::ChatMessage.tokens_used`.
    #[serde(default)]
    pub tokens_used: Option<i32>,
}

/// Request body for `POST /api/v1/chat/sessions/{id}/messages`.
#[derive(Debug, Clone, Serialize)]
pub struct ChatMessageRequest<'a> {
    pub content: &'a str,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatTurn {
    /// The user's message in this turn. Backend serialises as `user_message`;
    /// `user` is kept as an alias for older payloads.
    #[serde(rename = "user_message", alias = "user")]
    pub user: ChatMessage,
    /// The assistant's reply.
    #[serde(rename = "assistant_message", alias = "assistant")]
    pub assistant: ChatMessage,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session: Option<ChatSession>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Workflow {
    pub id: Uuid,
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowRun {
    pub id: Uuid,
    #[serde(default)]
    pub workflow_id: Option<Uuid>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub started_at: Option<DateTime<Utc>>,
    #[serde(default)]
    pub finished_at: Option<DateTime<Utc>>,
}

/// Dynamic workflow — the modern, JSON-defined workflow that the web UI's
/// `WorkflowsPage` lists. Distinct from the legacy `Workflow` struct above
/// which targets the older `/api/v1/workflows` summary endpoint. Field set
/// matches `DynamicWorkflowInDB` in `apps/api/app/schemas/dynamic_workflow.py`;
/// optional rollup counters are wrapped in Option so older deployments that
/// haven't run migration 103 still deserialise cleanly.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DynamicWorkflow {
    pub id: Uuid,
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub tier: Option<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub trigger_config: Option<serde_json::Value>,
    #[serde(default)]
    pub definition: Option<serde_json::Value>,
    #[serde(default)]
    pub run_count: i64,
    // See note on KnowledgeEntity — backend returns naive datetimes that
    // chrono::DateTime<Utc> refuses. Kept as raw string.
    #[serde(default)]
    pub last_run_at: Option<String>,
}

/// Run record for a dynamic workflow. Matches `WorkflowRunInDB` in
/// `apps/api/app/schemas/dynamic_workflow.py`. Wider than the legacy
/// `WorkflowRun` above because `status`, `started_at`, and `duration_ms`
/// are needed for the `ap workflow runs` table view.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DynamicWorkflowRun {
    pub id: Uuid,
    pub workflow_id: Uuid,
    #[serde(default)]
    pub trigger_type: Option<String>,
    pub status: String,
    // Naive ISO timestamp string. See note on KnowledgeEntity.
    pub started_at: String,
    #[serde(default)]
    pub completed_at: Option<String>,
    #[serde(default)]
    pub duration_ms: Option<i64>,
    #[serde(default)]
    pub current_step: Option<String>,
    #[serde(default)]
    pub error: Option<String>,
    #[serde(default)]
    pub total_tokens: Option<i64>,
    #[serde(default)]
    pub total_cost_usd: Option<f64>,
}

/// Body for `POST /api/v1/dynamic-workflows/{id}/run`.
#[derive(Debug, Clone, Serialize)]
pub struct WorkflowRunRequest {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_data: Option<serde_json::Value>,
    /// Set to true to validate without executing — matches the web
    /// TestConsole's dry_run button.
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub dry_run: bool,
}

/// Body for `POST /api/v1/knowledge/entities`. Mirrors
/// `KnowledgeEntityCreate` in `apps/api/app/schemas/knowledge_entity.py`.
/// Only the fields the CLI surfaces are modelled; the backend accepts more
/// optional fields (attributes, enrichment_data, source_agent_id, etc.) —
/// those flow through if callers feed them via `--json` (the `tags` field
/// is included because it's a common power-user knob).
#[derive(Debug, Clone, Serialize)]
pub struct CreateEntityRequest {
    pub entity_type: String,
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub category: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub confidence: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<Vec<String>>,
}

/// Knowledge-graph entity entry. Matches `KnowledgeEntity` in
/// `apps/api/app/schemas/knowledge_entity.py`. Only the fields the CLI
/// renders are modelled here; the API can return a dozen+ extra columns
/// (tags, score, extraction_model, etc.) — those flow through to `--json`
/// because we don't `deny_unknown_fields`.
///
/// **Note on timestamps**: backend serialises naive datetimes from
/// `datetime.utcnow().isoformat()` (no `Z` or `+00:00`). `chrono::DateTime<Utc>`
/// would reject those with "premature end of input" because its serde impl
/// requires RFC 3339 timezone markers — so we keep timestamps as opaque
/// strings here. The CLI only renders them; if we ever need to parse,
/// switch to `chrono::NaiveDateTime` (which is the actual server contract).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KnowledgeEntity {
    pub id: Uuid,
    pub entity_type: String,
    #[serde(default)]
    pub category: Option<String>,
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub confidence: Option<f64>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub tags: Option<Vec<String>>,
    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub updated_at: Option<String>,
}

/// File-based skill entry. Matches `FileSkill` in
/// `apps/api/app/schemas/file_skill.py`. Only the fields the CLI actually
/// renders are modelled; unknowns are tolerated via the default attrs. `slug`
/// is the stable identifier (matches the `slug` column on the registry),
/// `tier` is one of native/community/custom, `engine` is one of
/// python/shell/markdown/tool.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileSkill {
    pub name: String,
    #[serde(default)]
    pub slug: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default = "default_engine")]
    pub engine: String,
    #[serde(default = "default_category")]
    pub category: String,
    #[serde(default = "default_tier")]
    pub tier: String,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default = "default_version")]
    pub version: i64,
}

fn default_engine() -> String {
    "python".into()
}
fn default_category() -> String {
    "general".into()
}
fn default_tier() -> String {
    "native".into()
}
fn default_version() -> i64 {
    1
}

/// Status entry for a single integration in the current tenant. Matches the
/// shape `GET /api/v1/integrations/status` returns — one row per registered
/// integration, with `connected = true` when an `IntegrationConfig` row exists
/// and is enabled. `name` is the registry display name (e.g. "Google
/// Calendar"); `icon` is an arbitrary identifier the web uses to look up an
/// SVG. The CLI ignores the icon but preserves it in --json output.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IntegrationStatus {
    pub name: String,
    pub connected: bool,
    #[serde(default)]
    pub icon: Option<String>,
}

/// Onboarding state for the caller's tenant. Drives `ap quickstart`
/// auto-trigger after a successful `ap login`. Schema mirrors the
/// server-side `OnboardingStatus` model in `app/api/v1/onboarding.py`.
#[derive(Debug, Clone, Deserialize)]
pub struct OnboardingStatus {
    pub onboarded: bool,
    pub deferred: bool,
    #[serde(default)]
    pub onboarded_at: Option<String>,
    #[serde(default)]
    pub onboarding_deferred_at: Option<String>,
    #[serde(default)]
    pub onboarding_source: Option<String>,
    #[serde(default)]
    pub recommended_channel: Option<String>,
}

/// One row from the `training_runs` table — the user-visible state of
/// a `POST /memory/training/bulk-ingest` dispatch.
#[derive(Debug, Clone, Deserialize)]
pub struct TrainingRun {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub source: String,
    pub snapshot_id: Uuid,
    pub status: String, // "pending" | "running" | "complete" | "failed"
    pub items_total: i64,
    pub items_processed: i64,
    #[serde(default)]
    pub progress_fraction: Option<f64>,
    #[serde(default)]
    pub error: Option<String>,
    #[serde(default)]
    pub workflow_id: Option<String>,
    // Timestamps are naive ISO strings on the wire — same defensive
    // shape as Agent/Workflow runtime fields (servers don't always
    // emit timezone suffixes and chrono::DateTime<Utc> chokes on naive).
    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub started_at: Option<String>,
    #[serde(default)]
    pub completed_at: Option<String>,
}

/// `POST /memory/training/bulk-ingest` response wrapper.
#[derive(Debug, Clone, Deserialize)]
pub struct BulkIngestResponse {
    pub run: TrainingRun,
    pub estimated_seconds: i64,
    pub deduplicated: bool,
}

/// Device-flow login response. Mirrors GitHub's device-flow shape.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceCodeResponse {
    pub device_code: String,
    pub user_code: String,
    pub verification_uri: String,
    #[serde(default)]
    pub verification_uri_complete: Option<String>,
    pub expires_in: u64,
    #[serde(default = "default_interval")]
    pub interval: u64,
}

fn default_interval() -> u64 {
    5
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Locks down the Critical #1 fix: a Token must never expose its
    /// `access_token` through `Debug` formatting. If a future refactor
    /// re-derives `Debug` on `Token`, this test fails.
    #[test]
    fn token_debug_redacts_access_token() {
        let t = Token {
            access_token: "very-secret-bearer-1234567890".into(),
            token_type: "bearer".into(),
        };
        let dbg = format!("{t:?}");
        assert!(
            !dbg.contains("very-secret-bearer"),
            "Token Debug leaked access_token: {dbg}"
        );
        assert!(dbg.contains("<redacted>"), "expected <redacted>: {dbg}");
        // token_type should still print so logs remain useful.
        assert!(dbg.contains("bearer"), "token_type should remain: {dbg}");
    }
}
