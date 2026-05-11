//! `ap integration` — inspect integration connection status.
//!
//! Surfaces `GET /api/v1/integrations/status` — the same endpoint the web
//! IntegrationsPage and the dynamic-workflow activation gate hit. Tells
//! users which integrations (Google Calendar, Gmail, Slack, etc.) the
//! current tenant has actually connected vs. which are merely registered.

use clap::{Args, Subcommand};

use crate::context::Context;
use crate::output;

#[derive(Debug, Subcommand)]
pub enum IntegrationCommand {
    /// List registered integrations and whether the tenant has connected each.
    Ls(LsArgs),
}

#[derive(Debug, Args)]
pub struct LsArgs {
    /// Only show integrations that are currently connected.
    #[arg(long)]
    pub connected: bool,
}

pub async fn dispatch(cmd: IntegrationCommand, ctx: Context) -> anyhow::Result<()> {
    match cmd {
        IntegrationCommand::Ls(a) => ls(a, ctx).await,
    }
}

async fn ls(args: LsArgs, ctx: Context) -> anyhow::Result<()> {
    let mut entries = ctx.client.list_integration_status().await?;
    if args.connected {
        entries.retain(|e| e.connected);
    }

    // Sort connected-first so the actionable rows surface at the top, then
    // alphabetical inside each group. Mirrors how IntegrationsPanel renders
    // its card grid.
    entries.sort_by(|a, b| {
        b.connected
            .cmp(&a.connected)
            .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });

    crate::output::emit(ctx.json, &entries, |list| {
        if list.is_empty() {
            output::info("no integrations registered.".to_string());
            return;
        }
        println!(
            "{:<10}  {}",
            console::style("STATUS").bold(),
            console::style("NAME").bold(),
        );
        for e in list {
            // Use coloured glyphs instead of literal "true/false" — same
            // convention `kubectl get pods` uses for Ready / NotReady.
            let glyph = if e.connected {
                console::style("✓ on").green().to_string()
            } else {
                console::style("· off").dim().to_string()
            };
            println!("{:<10}  {}", glyph, e.name);
        }
    });
    Ok(())
}
