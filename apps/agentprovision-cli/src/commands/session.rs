//! `alpha session` — list and read chat sessions in the current tenant.
//!
//! Reuses `ApiClient::list_chat_sessions` + `list_chat_messages` (already in
//! core from PR-A). Matches the surface `apps/web/src/pages/ChatPage.js`
//! exposes — the left-rail session list plus the message scroll-back. Active
//! `alpha chat send`/`repl` already creates sessions; this PR exposes them.

use clap::{Args, Subcommand};

use crate::context::Context;
use crate::output;

#[derive(Debug, Subcommand)]
pub enum SessionCommand {
    /// List recent chat sessions for the current user/tenant.
    Ls(LsArgs),

    /// Show messages from a session.
    Messages(MessagesArgs),
}

#[derive(Debug, Args)]
pub struct LsArgs {
    /// Cap how many sessions to display. Backend returns the full set; this
    /// is a client-side truncate to keep the table readable.
    #[arg(long, default_value_t = 20)]
    pub limit: u32,

    /// Filter sessions whose title contains this substring (case-insensitive).
    #[arg(long)]
    pub title: Option<String>,
}

#[derive(Debug, Args)]
pub struct MessagesArgs {
    /// Session UUID.
    pub session: String,

    /// Maximum messages to print. Defaults to the last 50 so terminals
    /// don't drown in long backlogs; full history is via --all.
    #[arg(long, default_value_t = 50)]
    pub limit: u32,

    /// Show every message regardless of `--limit`.
    #[arg(long)]
    pub all: bool,
}

pub async fn dispatch(cmd: SessionCommand, ctx: Context) -> anyhow::Result<()> {
    match cmd {
        SessionCommand::Ls(a) => ls(a, ctx).await,
        SessionCommand::Messages(a) => messages(a, ctx).await,
    }
}

async fn ls(args: LsArgs, ctx: Context) -> anyhow::Result<()> {
    let mut sessions = ctx.client.list_chat_sessions().await?;

    if let Some(q) = &args.title {
        let lower = q.to_lowercase();
        sessions.retain(|s| {
            s.title
                .as_deref()
                .map(|t| t.to_lowercase().contains(&lower))
                .unwrap_or(false)
        });
    }

    // Sort newest-first by created_at so the most-recent sessions are at the
    // top of the table — same default the web ChatPage left rail uses.
    // Sessions with no timestamp sink to the bottom.
    sessions.sort_by(|a, b| b.created_at.cmp(&a.created_at));

    let truncated = sessions
        .into_iter()
        .take(args.limit as usize)
        .collect::<Vec<_>>();

    crate::output::emit(ctx.json, &truncated, |list| {
        if list.is_empty() {
            output::info("no sessions found.".to_string());
            return;
        }
        println!(
            "{:<36}  {:<20}  {}",
            console::style("ID").bold(),
            console::style("CREATED").bold(),
            console::style("TITLE").bold()
        );
        for s in list {
            let created = s
                .created_at
                .map(|d| d.format("%Y-%m-%d %H:%M:%S").to_string())
                .unwrap_or_else(|| "—".into());
            let title = s.title.as_deref().unwrap_or("(no title)");
            println!("{:<36}  {:<20}  {}", s.id, created, title);
        }
    });
    Ok(())
}

async fn messages(args: MessagesArgs, ctx: Context) -> anyhow::Result<()> {
    let mut msgs = ctx.client.list_chat_messages(&args.session).await?;

    if !args.all {
        let total = msgs.len();
        let n = args.limit as usize;
        if total > n {
            // Keep the *last* N — the message-scrollback semantic users expect.
            // ChatMessage doesn't impl Drain<Range> cleanly, so rebuild.
            msgs = msgs.split_off(total - n);
        }
    }

    crate::output::emit(ctx.json, &msgs, |list| {
        if list.is_empty() {
            output::info("no messages in this session.".to_string());
            return;
        }
        // Per-session aggregate. Sums NON-NULL token counts; NULL
        // means "the server didn't measure this turn" (older messages
        // or agents that don't emit a usage struct), so it stays
        // separate from `0`-measured turns to avoid hiding "we have no
        // data" behind a numeric zero.
        //
        // Widen to i64 before summing: an i32 accumulator overflows at
        // ~2.1B tokens, and while no single turn approaches that, a
        // long backlog of agentic dispatches (workflow fan-outs,
        // multi-turn debugging sessions) could plausibly reach it over
        // a session's lifetime. i64 gives 9.2 quintillion-token
        // headroom — cheap insurance for what is a single-pass
        // arithmetic step.
        let token_total: i64 = list
            .iter()
            .filter_map(|m| m.tokens_used.map(i64::from))
            .sum();
        let measured = list.iter().filter(|m| m.tokens_used.is_some()).count();
        // Cost aggregate uses the same NULL-distinct semantics. f64
        // is fine for accumulation up to ~$9e15 — far beyond any
        // plausible session lifetime cost (a $1000-per-month tenant
        // takes ~750000 years to overflow).
        let cost_total: f64 = list.iter().filter_map(|m| m.cost_usd).sum();
        let cost_measured = list.iter().filter(|m| m.cost_usd.is_some()).count();

        for m in list {
            // Coloured role prefix so `user:` vs `assistant:` is glanceable
            // in a long backlog. Same convention `git log --oneline` uses
            // for hash colouring — make the metadata the dim part, the
            // payload the bright part.
            let role_styled = match m.role.as_str() {
                "user" => console::style("user").cyan().bold().to_string(),
                "assistant" => console::style("assistant").green().bold().to_string(),
                other => console::style(other).dim().to_string(),
            };
            let stamp = m
                .created_at
                .map(|d| d.format("%H:%M:%S").to_string())
                .unwrap_or_default();
            // `—` for unmeasured, `<n>tok` for measured. Keeping it in
            // the line trailer so it lines up visually and doesn't
            // disrupt the role:content reading flow.
            //
            // Cost is added next to tokens when present, formatted to
            // 4 decimal places so cents are legible without
            // engineering-notation oddness for sub-cent values. Local
            // CLIs leave cost NULL even with tokens populated — keep
            // the two trailers independent so OpenCode runs show just
            // the token count.
            let mut trailer_parts: Vec<String> = Vec::new();
            if let Some(n) = m.tokens_used {
                trailer_parts.push(format!("{n}tok"));
            }
            if let Some(c) = m.cost_usd {
                trailer_parts.push(format!("${c:.4}"));
            }
            let token_str = if trailer_parts.is_empty() {
                String::new()
            } else {
                format!(" [{}]", trailer_parts.join(" "))
            };
            if stamp.is_empty() {
                println!("{}{}: {}", role_styled, token_str, m.content);
            } else {
                println!(
                    "[{}] {}{}: {}",
                    console::style(stamp).dim(),
                    role_styled,
                    token_str,
                    m.content
                );
            }
        }
        // Footer summary only when at least one message had a measured
        // count — silence when the server has no token data yet beats
        // a confusing "0 tokens across N measured turns" line. Cost
        // is appended when at least one turn had a measured cost; the
        // two sources can differ (OpenCode reports tokens but no
        // cost), so we report each with its own count.
        if measured > 0 {
            let mut parts = vec![format!(
                "{} tokens across {} measured turn{}",
                token_total,
                measured,
                if measured == 1 { "" } else { "s" },
            )];
            if cost_measured > 0 {
                parts.push(format!(
                    "${:.4} across {} priced turn{}",
                    cost_total,
                    cost_measured,
                    if cost_measured == 1 { "" } else { "s" },
                ));
            }
            println!(
                "{}",
                console::style(format!("── {}", parts.join(" · "))).dim()
            );
        }
    });
    Ok(())
}
