//! `ap memory` — browse and search the tenant's knowledge graph.
//!
//! Surfaces `/api/v1/knowledge/entities` (list) and
//! `/api/v1/knowledge/entities/search` (server-side search). Same endpoints
//! the web MemoryPage browses. Operators can answer 'what does the platform
//! know about <X>?' from the terminal.

use clap::{Args, Subcommand};

use crate::context::Context;
use crate::output;

#[derive(Debug, Subcommand)]
pub enum MemoryCommand {
    /// List entities in the knowledge graph (paginated).
    Ls(LsArgs),
    /// Search entities by name (server-side text + embedding).
    Search(SearchArgs),
}

#[derive(Debug, Args)]
pub struct LsArgs {
    /// Filter by entity type (customer / product / person / organization / concept / prospect).
    #[arg(long)]
    pub entity_type: Option<String>,

    /// Filter by category (lead / contact / investor / signal / etc.).
    #[arg(long)]
    pub category: Option<String>,

    /// Page size. Default 25; mirrors a typical terminal column count.
    #[arg(long, default_value_t = 25)]
    pub limit: u32,

    /// Page offset. Pair with --limit for `ap memory ls --skip 25 --limit 25`
    /// to walk a long graph.
    #[arg(long, default_value_t = 0)]
    pub skip: u32,
}

#[derive(Debug, Args)]
pub struct SearchArgs {
    /// Query string (matched against entity name and description).
    pub query: String,

    /// Optional entity-type filter on the search results.
    #[arg(long)]
    pub entity_type: Option<String>,

    /// Optional category filter on the search results.
    #[arg(long)]
    pub category: Option<String>,
}

pub async fn dispatch(cmd: MemoryCommand, ctx: Context) -> anyhow::Result<()> {
    match cmd {
        MemoryCommand::Ls(a) => ls(a, ctx).await,
        MemoryCommand::Search(a) => search(a, ctx).await,
    }
}

async fn ls(args: LsArgs, ctx: Context) -> anyhow::Result<()> {
    let entities = ctx
        .client
        .list_entities(
            args.entity_type.as_deref(),
            args.category.as_deref(),
            Some(args.limit),
            Some(args.skip),
        )
        .await?;
    render_table(ctx.json, &entities);
    Ok(())
}

async fn search(args: SearchArgs, ctx: Context) -> anyhow::Result<()> {
    let entities = ctx
        .client
        .search_entities(
            &args.query,
            args.entity_type.as_deref(),
            args.category.as_deref(),
        )
        .await?;
    render_table(ctx.json, &entities);
    Ok(())
}

fn render_table(json: bool, entities: &[agentprovision_core::models::KnowledgeEntity]) {
    crate::output::emit(json, entities, |list| {
        if list.is_empty() {
            output::info("no entities match.".to_string());
            return;
        }
        // Web MemoryPage columns: name / entity_type / category / description.
        // We add id last so users can pipe into other tools (no entity-show
        // verb yet, but the id is the input when one lands).
        println!(
            "{:<28}  {:<14}  {:<14}  {}",
            console::style("NAME").bold(),
            console::style("TYPE").bold(),
            console::style("CATEGORY").bold(),
            console::style("ID").bold(),
        );
        for e in list {
            let name = truncate(&e.name, 28);
            let cat = e
                .category
                .as_deref()
                .map(|c| truncate(c, 14))
                .unwrap_or_else(|| "—".into());
            let etype = truncate(&e.entity_type, 14);
            println!("{:<28}  {:<14}  {:<14}  {}", name, etype, cat, e.id);
        }
    });
}

fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        let mut out: String = s.chars().take(n.saturating_sub(1)).collect();
        out.push('…');
        out
    }
}
