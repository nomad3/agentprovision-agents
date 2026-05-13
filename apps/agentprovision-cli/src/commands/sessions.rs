//! `alpha sessions list` / `alpha sessions revoke <id>` — manage the
//! long-lived refresh tokens minted by `alpha login` (PR
//! `feat(auth): long-lived CLI sessions`).
//!
//! These are NOT chat sessions — those live under `alpha session` (no
//! trailing 's'). The distinction is awkward but the chat surface
//! shipped first; renaming would break scripted callers. The plural
//! form means "auth sessions" / "logged-in devices".

use chrono::{DateTime, Utc};
use clap::{Args, Subcommand};
use serde::{Deserialize, Serialize};

use crate::context::Context;
use crate::output;

#[derive(Debug, Args)]
pub struct SessionsArgs {
    #[command(subcommand)]
    pub command: SessionsCommand,
}

#[derive(Debug, Subcommand)]
pub enum SessionsCommand {
    /// List active "log in once" sessions for the current user. Each
    /// row is one refresh token still in its 30-day window — one per
    /// `alpha login` invocation that hasn't been revoked.
    List,
    /// Revoke a single session by id. Use this if a laptop is lost
    /// or compromised. Other sessions on that account keep working;
    /// only the revoked id can no longer auto-refresh.
    Revoke(RevokeArgs),
}

#[derive(Debug, Args)]
pub struct RevokeArgs {
    /// Session id (the `id` column from `alpha sessions list`).
    pub id: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct SessionRow {
    id: String,
    #[serde(default)]
    device_label: Option<String>,
    #[serde(default)]
    user_agent: Option<String>,
    created_at: DateTime<Utc>,
    #[serde(default)]
    last_used_at: Option<DateTime<Utc>>,
    expires_at: DateTime<Utc>,
}

pub async fn run(args: SessionsArgs, ctx: Context) -> anyhow::Result<()> {
    match args.command {
        SessionsCommand::List => list_sessions(ctx).await,
        SessionsCommand::Revoke(r) => revoke_session(ctx, &r.id).await,
    }
}

async fn list_sessions(ctx: Context) -> anyhow::Result<()> {
    let rows: Vec<SessionRow> = ctx.client.get_json("/api/v1/auth/sessions").await?;
    if ctx.json {
        crate::output::emit(true, &rows, |_| {});
        return Ok(());
    }
    if rows.is_empty() {
        output::info("[alpha] no active long-lived sessions. run `alpha login` to create one.");
        return Ok(());
    }
    println!(
        "{:<38}  {:<24}  {:<24}  {:<24}",
        "id", "device", "last used", "expires"
    );
    println!("{}", "-".repeat(112));
    for r in &rows {
        let device = r
            .device_label
            .as_deref()
            .or(r.user_agent.as_deref())
            .unwrap_or("—");
        let last_used = r
            .last_used_at
            .map(|t| t.format("%Y-%m-%d %H:%M UTC").to_string())
            .unwrap_or_else(|| "never".into());
        let expires = r.expires_at.format("%Y-%m-%d").to_string();
        println!(
            "{:<38}  {:<24}  {:<24}  {:<24}",
            r.id,
            truncate(device, 24),
            last_used,
            expires
        );
    }
    Ok(())
}

async fn revoke_session(ctx: Context, id: &str) -> anyhow::Result<()> {
    let path = format!("/api/v1/auth/sessions/{id}");
    let req = ctx.client.request(reqwest::Method::DELETE, &path)?;
    ctx.client.send_no_body(req).await?;
    if !ctx.json {
        output::ok(format!("[alpha] revoked session {id}"));
        output::info(
            "if this was your current laptop, run `alpha login` again to create a fresh session.",
        );
    }
    Ok(())
}

fn truncate(s: &str, keep: usize) -> String {
    if s.chars().count() <= keep {
        return s.to_string();
    }
    let head: String = s.chars().take(keep.saturating_sub(1)).collect();
    format!("{head}…")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn truncate_short_strings_unchanged() {
        assert_eq!(truncate("alpha CLI", 24), "alpha CLI");
    }

    #[test]
    fn truncate_respects_keep() {
        // 5-char input vs keep=4 → 3 chars + ellipsis = 4 visible chars
        let out = truncate("abcde", 4);
        assert_eq!(out.chars().count(), 4);
        assert!(out.ends_with('…'));
    }
}
