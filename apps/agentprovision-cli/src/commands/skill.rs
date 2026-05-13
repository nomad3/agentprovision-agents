//! `alpha skill` — browse the file-based skill marketplace.
//!
//! Surfaces `GET /api/v1/skills/library` — the same endpoint the web
//! SkillsPage uses. Read-only for now; create/execute/import flow lives
//! behind a separate PR-C-6 slice because each verb maps to a different
//! POST endpoint with its own request shape.

use clap::{Args, Subcommand};

use crate::context::Context;
use crate::output;

#[derive(Debug, Subcommand)]
pub enum SkillCommand {
    /// List skills in the library (built-in + tenant + community).
    Ls(LsArgs),
}

#[derive(Debug, Args)]
pub struct LsArgs {
    /// Filter by tier: native (bundled), community (imported), custom (tenant).
    #[arg(long)]
    pub tier: Option<String>,

    /// Filter by category (skill manifest `category` field).
    #[arg(long)]
    pub category: Option<String>,

    /// Server-side search — uses pgvector embedding match with text fallback,
    /// same pipeline the auto-trigger uses to pick skills during chat.
    #[arg(long, short = 'q')]
    pub search: Option<String>,
}

pub async fn dispatch(cmd: SkillCommand, ctx: Context) -> anyhow::Result<()> {
    match cmd {
        SkillCommand::Ls(a) => ls(a, ctx).await,
    }
}

async fn ls(args: LsArgs, ctx: Context) -> anyhow::Result<()> {
    let skills = ctx
        .client
        .list_skills(
            args.tier.as_deref(),
            args.category.as_deref(),
            args.search.as_deref(),
        )
        .await?;

    crate::output::emit(ctx.json, &skills, |list| {
        if list.is_empty() {
            output::info("no skills match the current filter.".to_string());
            return;
        }
        // Column order mirrors SkillsPage list — slug last so users can
        // copy it from the right edge as the input to `skill_execute`.
        // Tier drives colour: native (cyan) / community (yellow) / custom (green).
        println!(
            "{:<22}  {:<10}  {:<14}  {}",
            console::style("NAME").bold(),
            console::style("TIER").bold(),
            console::style("CATEGORY").bold(),
            console::style("SLUG").bold(),
        );
        for s in list {
            let tier_styled = match s.tier.as_str() {
                "native" => console::style(&s.tier).cyan().to_string(),
                "community" => console::style(&s.tier).yellow().to_string(),
                "custom" => console::style(&s.tier).green().to_string(),
                _ => console::style(&s.tier).dim().to_string(),
            };
            let name = truncate(&s.name, 22);
            let category = truncate(&s.category, 14);
            // tier_styled escape codes break alignment; use raw width-aware
            // print by manually padding the styled cell.
            let tier_padded = pad_ansi(&tier_styled, &s.tier, 10);
            println!(
                "{:<22}  {}  {:<14}  {}",
                name, tier_padded, category, s.slug
            );
        }
    });
    Ok(())
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

/// Pad an ANSI-styled cell to a visible width of `width` by appending plain
/// spaces. `plain` is the underlying string (no escape codes) used to
/// measure the visible length — `styled` is the same content with colour
/// escapes wrapped around it. Without this, `{:<10}` counts the escape
/// bytes and the column collapses.
fn pad_ansi(styled: &str, plain: &str, width: usize) -> String {
    let visible = plain.chars().count();
    if visible >= width {
        styled.to_string()
    } else {
        let pad = " ".repeat(width - visible);
        format!("{}{}", styled, pad)
    }
}
