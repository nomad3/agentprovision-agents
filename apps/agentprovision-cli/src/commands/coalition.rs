//! `ap coalition` — dispatch and inspect multi-agent coalitions.
//!
//! Phase 3 of the CLI differentiation roadmap (#180) — see
//! `docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md` §5.
//!
//! Subcommands:
//!   ap coalition list                 GET  /api/v1/collaborations
//!   ap coalition run "<task>"         POST /api/v1/collaborations/trigger
//!
//! Backend reference:
//!   - `CoalitionWorkflow` on `agentprovision-orchestration` queue
//!     (shipped 2026-04-12).
//!   - `Blackboard` model + entries; events fan out via Redis pub/sub
//!     and the existing `/collaborations/{id}/stream` SSE endpoint.
//!   - Patterns: `incident_investigation`, `deal_brief`,
//!     `cardiology_case_review`.
//!
//! `ap coalition watch` is deliberately not in this PR — the watch
//! flow requires consuming the SSE stream and resolving the
//! collaboration_id from the chat-session event feed. Deferred to a
//! follow-up that reuses the SSE infrastructure shipped in #438.

use clap::{Args, Subcommand};
use serde::{Deserialize, Serialize};

use crate::context::Context;

#[derive(Debug, Subcommand)]
pub enum CoalitionCommand {
    /// List recent coalition / collaboration sessions for the
    /// current tenant.
    List(ListArgs),

    /// Dispatch a multi-agent coalition. Creates a fresh chat
    /// session under the hood, then triggers a CoalitionWorkflow
    /// against it. Returns the chat_session_id; follow via the
    /// existing web UI or (eventually) `ap coalition watch`.
    Run(RunArgs),
}

#[derive(Debug, Args)]
pub struct ListArgs {
    /// Cap on returned sessions. Defaults to 20.
    #[arg(long, default_value_t = 20)]
    pub limit: u32,
}

#[derive(Debug, Args)]
pub struct RunArgs {
    /// Free-form task description. The router uses this to pick the
    /// appropriate coalition pattern (incident_investigation,
    /// deal_brief, cardiology_case_review). Pass concrete keywords:
    /// "P1 incident on orders-api", "Levi MDM outage", etc.
    #[arg(value_name = "TASK", value_parser = non_blank_task)]
    pub task: String,

    /// Override pattern explicitly instead of letting the router
    /// pick. One of: incident_investigation | deal_brief |
    /// cardiology_case_review.
    #[arg(long)]
    pub pattern: Option<String>,

    /// Bind to an existing chat session. Default: create a fresh
    /// session via `POST /chat/sessions` and use that.
    #[arg(long)]
    pub session: Option<String>,
}

fn non_blank_task(s: &str) -> Result<String, String> {
    if s.trim().is_empty() {
        Err("task must not be empty or whitespace-only".to_string())
    } else {
        Ok(s.to_string())
    }
}

#[derive(Debug, Deserialize, Serialize)]
struct CollaborationSession {
    id: String,
    #[serde(default)]
    pattern: Option<String>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    current_phase: Option<String>,
    #[serde(default)]
    title: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
struct TriggerResponse {
    status: String,
    chat_session_id: String,
    task_description: String,
    #[serde(default)]
    message: Option<String>,
}

pub async fn dispatch(cmd: CoalitionCommand, ctx: Context) -> anyhow::Result<()> {
    match cmd {
        CoalitionCommand::List(a) => list(a, ctx).await,
        CoalitionCommand::Run(a) => run(a, ctx).await,
    }
}

async fn list(args: ListArgs, ctx: Context) -> anyhow::Result<()> {
    use agentprovision_core::error::Error;
    use reqwest::Method;

    let req = ctx
        .client
        .request(Method::GET, "/api/v1/collaborations")?
        .query(&[("limit", args.limit.to_string())]);
    let sessions: Vec<CollaborationSession> = match ctx.client.send_json(req).await {
        Ok(s) => s,
        Err(Error::Unauthorized) => {
            anyhow::bail!("not logged in — run `ap login` first")
        }
        Err(e) => return Err(e.into()),
    };

    if ctx.json {
        println!("{}", serde_json::to_string_pretty(&sessions)?);
        return Ok(());
    }
    if sessions.is_empty() {
        println!("[ap] no coalition sessions yet for this tenant");
        return Ok(());
    }
    println!(
        "[ap] {} coalition session(s):",
        sessions.len()
    );
    let width = sessions.len().to_string().len().max(2);
    for (i, s) in sessions.iter().enumerate() {
        let pattern = s.pattern.as_deref().unwrap_or("(unknown)");
        let status = s.status.as_deref().unwrap_or("?");
        let phase = s.current_phase.as_deref().unwrap_or("");
        let title = s.title.as_deref().unwrap_or("");
        let phase_suffix = if phase.is_empty() {
            String::new()
        } else {
            format!(" / {phase}")
        };
        let title_suffix = if title.is_empty() {
            String::new()
        } else {
            format!("  {title}")
        };
        println!(
            "{:width$}. {} [{}{}] {}{}",
            i + 1,
            s.id,
            status,
            phase_suffix,
            pattern,
            title_suffix,
            width = width,
        );
    }
    Ok(())
}

async fn run(args: RunArgs, ctx: Context) -> anyhow::Result<()> {
    use agentprovision_core::error::Error;
    use reqwest::Method;

    // Resolve / create a chat session to anchor the coalition.
    let session_id = match args.session.clone() {
        Some(s) => s,
        None => {
            let session = ctx
                .client
                .create_chat_session(
                    Some(&format!("ap coalition: {}", truncate(&args.task, 60))),
                    None,
                )
                .await?;
            session.id.to_string()
        }
    };

    // Build the trigger body. `pattern` is optional — when None, the
    // router picks based on task_description keywords.
    let body = serde_json::json!({
        "chat_session_id": session_id,
        "task_description": args.task,
        "pattern": args.pattern,
    });

    let req = ctx
        .client
        .request(Method::POST, "/api/v1/collaborations/trigger")?
        .json(&body);
    let resp: TriggerResponse = match ctx.client.send_json(req).await {
        Ok(r) => r,
        Err(Error::Unauthorized) => {
            anyhow::bail!("not logged in — run `ap login` first")
        }
        Err(e) => return Err(e.into()),
    };

    if ctx.json {
        println!("{}", serde_json::to_string_pretty(&resp)?);
        return Ok(());
    }
    println!("[ap] coalition dispatched");
    println!("       chat_session_id: {}", resp.chat_session_id);
    println!("       task: {}", resp.task_description);
    if let Some(msg) = resp.message {
        println!("       note: {msg}");
    }
    println!(
        "       follow via web: https://agentprovision.com/chat/{}",
        resp.chat_session_id
    );
    Ok(())
}

fn truncate(s: &str, max: usize) -> String {
    let s = s.trim();
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let truncated: String = s.chars().take(max).collect();
        format!("{truncated}…")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;

    #[derive(Parser)]
    struct TestCli {
        #[command(subcommand)]
        cmd: TestCmd,
    }
    #[derive(clap::Subcommand)]
    enum TestCmd {
        #[command(subcommand)]
        Coalition(CoalitionCommand),
    }

    #[test]
    fn parses_list() {
        let cli = TestCli::try_parse_from(["t", "coalition", "list"]).unwrap();
        let TestCmd::Coalition(CoalitionCommand::List(a)) = cli.cmd else {
            panic!("wrong subcommand")
        };
        assert_eq!(a.limit, 20);
    }

    #[test]
    fn parses_list_custom_limit() {
        let cli =
            TestCli::try_parse_from(["t", "coalition", "list", "--limit", "5"]).unwrap();
        let TestCmd::Coalition(CoalitionCommand::List(a)) = cli.cmd else {
            panic!()
        };
        assert_eq!(a.limit, 5);
    }

    #[test]
    fn parses_run_basic() {
        let cli = TestCli::try_parse_from([
            "t",
            "coalition",
            "run",
            "P1 incident on orders-api",
        ])
        .unwrap();
        let TestCmd::Coalition(CoalitionCommand::Run(a)) = cli.cmd else {
            panic!()
        };
        assert_eq!(a.task, "P1 incident on orders-api");
        assert!(a.pattern.is_none());
        assert!(a.session.is_none());
    }

    #[test]
    fn parses_run_with_pattern_and_session() {
        let cli = TestCli::try_parse_from([
            "t",
            "coalition",
            "run",
            "Levi MDM outage",
            "--pattern",
            "incident_investigation",
            "--session",
            "abc-123",
        ])
        .unwrap();
        let TestCmd::Coalition(CoalitionCommand::Run(a)) = cli.cmd else {
            panic!()
        };
        assert_eq!(a.pattern.as_deref(), Some("incident_investigation"));
        assert_eq!(a.session.as_deref(), Some("abc-123"));
    }

    #[test]
    fn empty_task_rejected() {
        assert!(
            TestCli::try_parse_from(["t", "coalition", "run", ""]).is_err()
        );
        assert!(
            TestCli::try_parse_from(["t", "coalition", "run", "  "]).is_err()
        );
    }

    #[test]
    fn truncate_helper() {
        assert_eq!(truncate("short", 10), "short");
        assert_eq!(truncate("exactly-ten", 11), "exactly-ten");
        assert_eq!(truncate("longer-than-cap", 5), "longe…");
        // Whitespace trimmed.
        assert_eq!(truncate("  padded  ", 10), "padded");
    }
}
