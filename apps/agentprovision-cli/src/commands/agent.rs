//! `ap agent` — list and show agents in the current tenant.
//!
//! PR-C-1 first surface. Reuses `ApiClient::list_agents` (already on `core`)
//! and adds `get_agent(id)` for `show`. Matches the web UX in
//! `apps/web/src/pages/AgentsPage.js` — id / name / role / status columns.

use clap::{Args, Subcommand};

use crate::context::Context;
use crate::output;

#[derive(Debug, Subcommand)]
pub enum AgentCommand {
    /// List all agents in the current tenant.
    Ls(LsArgs),

    /// Show a single agent by id or name.
    Show(ShowArgs),
}

#[derive(Debug, Args)]
pub struct LsArgs {
    /// Filter by role substring (case-insensitive). Matches the web
    /// `AgentsPage` search field. Server-side filtering may land later;
    /// for now we filter client-side from the full list response.
    #[arg(long)]
    pub role: Option<String>,

    /// Filter by status (draft / staging / production / deprecated).
    #[arg(long)]
    pub status: Option<String>,
}

#[derive(Debug, Args)]
pub struct ShowArgs {
    /// Agent UUID or exact name. Names are tenant-unique per the
    /// `idx_agents_tenant_name_unique` partial index.
    pub agent: String,
}

pub async fn dispatch(cmd: AgentCommand, ctx: Context) -> anyhow::Result<()> {
    match cmd {
        AgentCommand::Ls(a) => ls(a, ctx).await,
        AgentCommand::Show(a) => show(a, ctx).await,
    }
}

async fn ls(args: LsArgs, ctx: Context) -> anyhow::Result<()> {
    let agents = ctx.client.list_agents().await?;

    let role_q = args.role.as_deref().map(|s| s.to_lowercase());
    let status_q = args.status.as_deref().map(|s| s.to_lowercase());

    let filtered: Vec<_> = agents
        .into_iter()
        .filter(|a| {
            role_q
                .as_deref()
                .map(|q| {
                    a.role
                        .as_deref()
                        .map(|r| r.to_lowercase().contains(q))
                        .unwrap_or(false)
                })
                .unwrap_or(true)
                && status_q
                    .as_deref()
                    .map(|q| {
                        a.status
                            .as_deref()
                            .map(|s| s.to_lowercase() == q)
                            .unwrap_or(false)
                    })
                    .unwrap_or(true)
        })
        .collect();

    crate::output::emit(ctx.json, &filtered, |list| {
        if list.is_empty() {
            output::info("no agents match the current filter.".to_string());
            return;
        }
        // Mirror the AgentsPage column order: name / role / status / id.
        // ID last so users can copy it from the right edge without
        // mis-grabbing other columns. Same convention `gh repo list` uses.
        println!(
            "{:<28}  {:<18}  {:<12}  {}",
            console::style("NAME").bold(),
            console::style("ROLE").bold(),
            console::style("STATUS").bold(),
            console::style("ID").bold()
        );
        for a in list {
            let name = truncate(&a.name, 28);
            let role = a
                .role
                .as_deref()
                .map(|r| truncate(r, 18))
                .unwrap_or_else(|| "—".into());
            let status = a.status.as_deref().unwrap_or("—");
            println!("{:<28}  {:<18}  {:<12}  {}", name, role, status, a.id);
        }
    });
    Ok(())
}

async fn show(args: ShowArgs, ctx: Context) -> anyhow::Result<()> {
    // Try as UUID first; fall back to name lookup via list+filter so users
    // can `ap agent show luna` without remembering the id. This mirrors how
    // the web AgentsPage links from a name pill to the detail page.
    // Detect UUID without pulling `uuid` as a direct dep — `agentprovision-cli`
    // intentionally treats UUIDs as opaque strings everywhere else.
    let looks_like_uuid =
        args.agent.len() == 36 && args.agent.matches('-').count() == 4 && args.agent.is_ascii();
    let agent = if looks_like_uuid {
        ctx.client.get_agent(&args.agent).await?
    } else {
        let all = ctx.client.list_agents().await?;
        let lower = args.agent.to_lowercase();
        let hit = all
            .into_iter()
            .find(|a| a.name.to_lowercase() == lower)
            .ok_or_else(|| anyhow::anyhow!("no agent matches \"{}\"", args.agent))?;
        // Round-trip via id so we get the same payload shape as the
        // direct-by-id path. Backend may attach fields on the detail
        // endpoint that the list endpoint omits.
        ctx.client.get_agent(&hit.id.to_string()).await?
    };
    crate::output::emit(ctx.json, &agent, |a| {
        let h = |t: &str| console::style(t).bold().to_string();
        println!("{}: {}", h("id"), a.id);
        println!("{}: {}", h("name"), a.name);
        if let Some(role) = &a.role {
            println!("{}: {}", h("role"), role);
        }
        if let Some(status) = &a.status {
            println!("{}: {}", h("status"), status);
        }
        if let Some(desc) = &a.description {
            println!("{}: {}", h("description"), desc);
        }
    });
    Ok(())
}

/// Hard-wrap helper for fixed-width table cells. Trims to `n` chars and
/// appends `…` if truncated, so long agent names don't blow out the column
/// layout. Unicode-safe via char counting.
fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        let mut out: String = s.chars().take(n.saturating_sub(1)).collect();
        out.push('…');
        out
    }
}
