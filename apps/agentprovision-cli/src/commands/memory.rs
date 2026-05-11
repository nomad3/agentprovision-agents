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
    /// Record a new entity in the knowledge graph (`ap memory observe`).
    Observe(ObserveArgs),
}

#[derive(Debug, Args)]
pub struct ObserveArgs {
    /// Display name of the entity. Required.
    #[arg(long)]
    pub name: String,

    /// Entity type. One of: customer, product, person, organization,
    /// concept, prospect, signal. Defaults to "concept" for casual
    /// note-taking; pass --entity-type to disambiguate.
    #[arg(long, default_value = "concept")]
    pub entity_type: String,

    /// Optional category — used by lead/contact/investor/signal pipelines.
    #[arg(long)]
    pub category: Option<String>,

    /// Free-text description / observation body.
    #[arg(long)]
    pub description: Option<String>,

    /// Optional source URL (e.g. the article you're recording about).
    #[arg(long)]
    pub source_url: Option<String>,

    /// Comma-separated tags (e.g. `--tags "lead,inbound,priority"`).
    #[arg(long)]
    pub tags: Option<String>,

    /// Optional confidence 0.0-1.0. Defaults to backend's 1.0.
    #[arg(long)]
    pub confidence: Option<f64>,
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
        MemoryCommand::Observe(a) => observe(a, ctx).await,
    }
}

async fn observe(args: ObserveArgs, ctx: Context) -> anyhow::Result<()> {
    let tags = args.tags.as_deref().map(|s| {
        s.split(',')
            .map(|t| t.trim().to_string())
            .filter(|t| !t.is_empty())
            .collect()
    });
    let body = agentprovision_core::models::CreateEntityRequest {
        entity_type: args.entity_type,
        name: args.name,
        category: args.category,
        description: args.description,
        source_url: args.source_url,
        confidence: args.confidence,
        tags,
    };
    let created = ctx.client.create_entity(&body).await?;
    crate::output::emit(ctx.json, &created, |e| {
        let h = |t: &str| console::style(t).bold().to_string();
        output::ok(format!("recorded entity {}", e.name));
        println!("{}: {}", h("id"), e.id);
        println!("{}: {}", h("type"), e.entity_type);
        if let Some(c) = &e.category {
            println!("{}: {}", h("category"), c);
        }
        if let Some(d) = &e.description {
            println!("{}: {}", h("description"), d);
        }
    });
    Ok(())
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
