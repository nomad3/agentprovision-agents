//! `alpha remember "<fact>"` — tenant-scoped free-form fact ingestion.
//!
//! Phase 2 of the CLI roadmap (#179). Thin wrapper around
//! `POST /api/v1/memory/remember`, which calls
//! `knowledge.create_observation` — auto-embeds via the rust embedding
//! service and stores in both the knowledge_observations table and
//! the shared vector_store. Recallable via `alpha recall`.

use clap::Args;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::context::Context;
use crate::output;

#[derive(Debug, Args)]
pub struct RememberArgs {
    /// The fact to remember. Tenant-scoped — every agent under your
    /// account will be able to surface this via semantic recall.
    #[arg(value_name = "TEXT")]
    pub text: String,

    /// Optional entity to attach this observation to. UUID of an
    /// existing knowledge_entity row. When unset, the observation is
    /// tenant-scoped without an entity binding — still recallable.
    #[arg(long, value_name = "UUID")]
    pub entity: Option<Uuid>,

    /// Coarse type for downstream classification — `fact`,
    /// `preference`, `decision`, etc. Free-form; defaults to `fact`.
    #[arg(long, value_name = "TYPE", default_value = "fact")]
    pub kind: String,
}

#[derive(Debug, Serialize)]
struct RememberRequest<'a> {
    text: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    entity_id: Option<Uuid>,
    observation_type: &'a str,
}

#[derive(Debug, Deserialize, Serialize)]
struct RememberResponse {
    id: Uuid,
    text: String,
    #[serde(default)]
    entity_id: Option<Uuid>,
    observation_type: String,
}

pub async fn run(args: RememberArgs, ctx: Context) -> anyhow::Result<()> {
    let payload = RememberRequest {
        text: &args.text,
        entity_id: args.entity,
        observation_type: &args.kind,
    };
    let resp: RememberResponse = ctx
        .client
        .post_json("/api/v1/memory/remember", &payload)
        .await?;
    if ctx.json {
        crate::output::emit(true, &resp, |_| {});
        return Ok(());
    }
    let entity_suffix = match resp.entity_id {
        Some(id) => format!(" (entity={id})"),
        None => String::new(),
    };
    output::ok(format!(
        "[alpha] remembered as {} observation {}{entity_suffix}",
        resp.observation_type, resp.id
    ));
    output::info("embedded for semantic recall — try `alpha recall \"<query>\"` later.");
    Ok(())
}
