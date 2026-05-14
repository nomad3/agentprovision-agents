//! `alpha tasks` — cross-machine dashboard of working + recently
//! completed work for the caller's tenant.
//!
//! Parity with Anthropic's Claude Code "Agent View" that landed
//! 2026-05-13, with the upgrade that alpha tasks transcend a single
//! machine — they're tenant-scoped, so a goal dispatched on a laptop
//! shows up in `alpha tasks` from a desktop, a CI runner, anywhere.
//!
//! Surface:
//!   alpha tasks                — render the rollup
//!   alpha tasks --json         — machine-readable for scripts
//!   alpha tasks attach <id>    — delegates to `alpha watch <id>`
//!   alpha tasks cancel <id>    — delegates to `alpha cancel <id>`
//!
//! v1 scope: working + completed only. `needs_input` is deferred to a
//! follow-up because the workflow_runs schema has no canonical
//! "awaiting human input" column yet — see the design doc for the
//! schema gap and the migration that unlocks v2.
//!
//! Roadmap: docs/plans/2026-05-13-alpha-agent-view-and-goal-recipes.md

use chrono::{DateTime, Utc};
use clap::{Args, Subcommand};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::commands::{cancel, watch};
use crate::context::Context;
use crate::output;

#[derive(Debug, Args)]
pub struct TasksArgs {
    #[command(subcommand)]
    pub command: Option<TasksCommand>,

    /// Cap each group to N rows (default 50, max 200). Values above
    /// 200 are clamped client-side with a stderr warning rather than
    /// sent through to a server-side 422 (PR #454 review I4).
    #[arg(long, default_value_t = 50)]
    pub limit: u32,
}

/// Server-side maximum on `?limit=` — keep in sync with
/// `dashboard_tasks.py::list_dashboard_tasks` `Query(..., le=200)`.
const LIMIT_CAP: u32 = 200;

#[derive(Debug, Subcommand)]
pub enum TasksCommand {
    /// Stream a task's live event log. Delegates to `alpha watch`.
    /// Pass the task id (workflow run id) shown in `alpha tasks`.
    Attach(AttachArgs),
    /// Cancel a task. Delegates to `alpha cancel`.
    Cancel(CancelArgs),
}

#[derive(Debug, Args)]
pub struct AttachArgs {
    /// Workflow run id from `alpha tasks` output.
    pub task_id: String,

    /// Fall back to the legacy polling loop instead of SSE — useful
    /// behind proxies that strip text/event-stream. Mirrors the flag
    /// on `alpha watch`.
    #[arg(long)]
    pub poll: bool,

    /// Maximum number of seconds to tail before exiting. The task
    /// itself keeps running on the backend; the CLI just stops
    /// rendering. `0` = no ceiling, follow until terminal. Default
    /// 1800s (30 min). PR #454 review I3 — previously hardcoded,
    /// which silently capped long-running goal recipes at 30 min.
    #[arg(long, default_value_t = 1800)]
    pub timeout: u64,

    /// Mirrors `alpha watch --no-tail-if-done`: if the task is
    /// already in a terminal state when attach is invoked, print one
    /// status line and exit instead of rendering the full final
    /// transcript. Useful for scripted polling.
    #[arg(long)]
    pub no_tail_if_done: bool,
}

#[derive(Debug, Args)]
pub struct CancelArgs {
    /// Workflow run id from `alpha tasks` output.
    pub task_id: String,
}

/// Server response wire format. Mirrors
/// `apps/api/app/api/v1/dashboard_tasks.py::TaskDashboardResponse`.
#[derive(Debug, Deserialize, Serialize)]
struct TaskDashboard {
    working: Vec<TaskRow>,
    completed: Vec<TaskRow>,
    #[serde(default)]
    supports_needs_input: bool,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
struct TaskRow {
    id: Uuid,
    status: String,
    raw_status: String,
    title: String,
    workflow_id: Uuid,
    workflow_name: String,
    started_at: DateTime<Utc>,
    #[serde(default)]
    completed_at: Option<DateTime<Utc>>,
    #[serde(default)]
    duration_ms: Option<i64>,
    #[serde(default)]
    total_tokens: Option<i64>,
    #[serde(default)]
    total_cost_usd: Option<f64>,
    #[serde(default)]
    error: Option<String>,
}

pub async fn run(args: TasksArgs, ctx: Context) -> anyhow::Result<()> {
    match args.command {
        None => list(args.limit, ctx).await,
        Some(TasksCommand::Attach(a)) => attach(a, ctx).await,
        Some(TasksCommand::Cancel(a)) => cancel_task(a, ctx).await,
    }
}

async fn list(limit: u32, ctx: Context) -> anyhow::Result<()> {
    // Clamp client-side to match the server's `Query(..., le=200)`.
    // Sending a higher value would 422 with an opaque body — preserve
    // the user's intent by capping silently with a stderr warning so
    // scripted callers still get useful behaviour. PR #454 review I4.
    let effective_limit = if limit > LIMIT_CAP {
        output::warn(format!(
            "--limit {limit} exceeds server cap {LIMIT_CAP}; clamping"
        ));
        LIMIT_CAP
    } else if limit < 1 {
        // Should be unreachable (clap default is 50, no negative for
        // u32) but defend anyway.
        1
    } else {
        limit
    };
    let path = format!("/api/v1/dashboard/tasks?limit={effective_limit}");
    let board: TaskDashboard = ctx.client.get_json(&path).await?;

    if ctx.json {
        crate::output::emit(true, &board, |_| {});
        return Ok(());
    }

    if board.working.is_empty() && board.completed.is_empty() {
        output::info("[alpha] no tasks right now — `alpha run` or `alpha goal` to start one.");
        return Ok(());
    }

    if !board.working.is_empty() {
        println!("WORKING ({})", board.working.len());
        for row in &board.working {
            print_row(row, /*completed=*/ false);
        }
    }

    if !board.completed.is_empty() {
        if !board.working.is_empty() {
            println!();
        }
        println!("COMPLETED ({})", board.completed.len());
        for row in &board.completed {
            print_row(row, /*completed=*/ true);
        }
    }

    // Surface the v1 limitation honestly so users don't assume the
    // dashboard caught a needs_input task and miss something blocking.
    if !board.supports_needs_input {
        println!();
        output::info(
            "NEEDS INPUT: not yet surfaced. Run `alpha watch <id>` on a workflow you suspect is blocked."
        );
    }

    Ok(())
}

async fn attach(args: AttachArgs, ctx: Context) -> anyhow::Result<()> {
    // v1 delegates to `alpha watch` — the underlying SSE stream is the
    // same. Keeps a single source of truth for tail behaviour; once
    // we add reply-on-needs-input, attach grows its own loop.
    //
    // `--timeout` and `--no-tail-if-done` are explicit pass-throughs
    // (PR #454 review I3) so long-running goal recipes aren't silently
    // capped at 30 min and scripted polling has the same escape hatch
    // as `alpha watch`.
    let wa = watch::WatchArgs {
        task_id: args.task_id,
        no_tail_if_done: args.no_tail_if_done,
        timeout: args.timeout,
        poll: args.poll,
    };
    watch::run(wa, ctx).await
}

async fn cancel_task(args: CancelArgs, ctx: Context) -> anyhow::Result<()> {
    // `quiet: false` keeps the same UX as `alpha cancel <id>` —
    // suppression is an explicit power-user knob, not the default
    // for someone invoking it through the dashboard.
    let ca = cancel::CancelArgs {
        task_id: args.task_id,
        quiet: false,
    };
    cancel::run(ca, ctx).await
}

fn print_row(row: &TaskRow, completed: bool) {
    let when = if completed {
        row.completed_at.unwrap_or(row.started_at)
    } else {
        row.started_at
    };
    let age = format_age(when);
    let status_glyph = match row.raw_status.as_str() {
        "running" => "·",
        "completed" => "✓",
        "failed" => "✗",
        "cancelled" | "canceled" => "—",
        _ => "?",
    };
    let title = truncate(&row.title, 40);
    // Distinguish "unmeasured" (None → `—`) from "measured but $0.00"
    // (Some(0.0) → `$0.000`). The cost tracker emits 0.00 for cached-
    // response cases; hiding it as `—` would make those rows look
    // unmeasured. PR #454 review N4.
    let cost = match row.total_cost_usd {
        Some(c) if c >= 0.0 => format!("${c:.3}"),
        _ => "—".into(),
    };
    println!(
        "  {status_glyph} {id:<38}  {title:<40}  {cost:>8}  {age}",
        id = row.id,
    );
    if let Some(err) = row.error.as_deref().filter(|_| completed) {
        println!("    error: {}", truncate(err, 100));
    }
}

/// Render a UTC timestamp as "Nm ago" / "Nh ago" / "Nd ago". Keeps
/// the dashboard digestible without forcing the user to read ISO
/// strings.
fn format_age(when: DateTime<Utc>) -> String {
    let now = Utc::now();
    let secs = (now - when).num_seconds();
    if secs < 60 {
        format!("{secs}s ago")
    } else if secs < 3600 {
        format!("{}m ago", secs / 60)
    } else if secs < 86_400 {
        format!("{}h ago", secs / 3600)
    } else {
        format!("{}d ago", secs / 86_400)
    }
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
    use chrono::Duration;
    use clap::Parser;
    use serde_json::json;

    #[derive(Parser)]
    struct TestCli {
        #[command(subcommand)]
        cmd: TestCmd,
    }
    #[derive(clap::Subcommand)]
    enum TestCmd {
        Tasks(TasksArgs),
    }

    fn parse(args: &[&str]) -> TasksArgs {
        let cli = TestCli::try_parse_from(args).expect("clap parse");
        match cli.cmd {
            TestCmd::Tasks(a) => a,
        }
    }

    #[test]
    fn parses_bare_tasks_defaults_to_list() {
        let a = parse(&["test", "tasks"]);
        assert!(a.command.is_none());
        assert_eq!(a.limit, 50);
    }

    #[test]
    fn parses_attach_subcommand() {
        let a = parse(&["test", "tasks", "attach", "t-abc"]);
        match a.command {
            Some(TasksCommand::Attach(att)) => {
                assert_eq!(att.task_id, "t-abc");
                // PR #454 review I3: defaults must match `alpha watch`.
                assert_eq!(att.timeout, 1800);
                assert!(!att.no_tail_if_done);
                assert!(!att.poll);
            }
            other => panic!("expected Attach, got {other:?}"),
        }
    }

    #[test]
    fn parses_attach_timeout_and_no_tail_if_done() {
        // PR #454 review I3: long-running goal recipes need to be able
        // to override the 30-min default, and scripted polling needs
        // --no-tail-if-done parity with `alpha watch`.
        let a = parse(&[
            "test",
            "tasks",
            "attach",
            "t-long",
            "--timeout",
            "7200",
            "--no-tail-if-done",
        ]);
        match a.command {
            Some(TasksCommand::Attach(att)) => {
                assert_eq!(att.timeout, 7200);
                assert!(att.no_tail_if_done);
            }
            other => panic!("expected Attach, got {other:?}"),
        }
    }

    #[test]
    fn parses_attach_timeout_zero_for_no_ceiling() {
        // `--timeout 0` is the "follow until terminal" escape hatch
        // documented on `alpha watch`. Must round-trip cleanly.
        let a = parse(&["test", "tasks", "attach", "t-x", "--timeout", "0"]);
        match a.command {
            Some(TasksCommand::Attach(att)) => assert_eq!(att.timeout, 0),
            other => panic!("expected Attach, got {other:?}"),
        }
    }

    #[test]
    fn parses_cancel_subcommand() {
        let a = parse(&["test", "tasks", "cancel", "t-xyz"]);
        match a.command {
            Some(TasksCommand::Cancel(c)) => assert_eq!(c.task_id, "t-xyz"),
            other => panic!("expected Cancel, got {other:?}"),
        }
    }

    #[test]
    fn parses_limit_flag() {
        let a = parse(&["test", "tasks", "--limit", "200"]);
        assert_eq!(a.limit, 200);
    }

    #[test]
    fn format_age_seconds() {
        let now = Utc::now();
        assert!(format_age(now - Duration::seconds(5)).ends_with("s ago"));
    }

    #[test]
    fn format_age_minutes() {
        let now = Utc::now();
        let s = format_age(now - Duration::minutes(7));
        assert_eq!(s, "7m ago");
    }

    #[test]
    fn format_age_hours() {
        let now = Utc::now();
        let s = format_age(now - Duration::hours(3));
        assert_eq!(s, "3h ago");
    }

    #[test]
    fn format_age_days() {
        let now = Utc::now();
        let s = format_age(now - Duration::days(2));
        assert_eq!(s, "2d ago");
    }

    #[test]
    fn truncate_short_unchanged() {
        assert_eq!(truncate("hello", 40), "hello");
    }

    #[test]
    fn truncate_long_ellipsises() {
        let out = truncate("aaaaaaaaaaaaaaaaaaaa", 5);
        assert_eq!(out.chars().count(), 5);
        assert!(out.ends_with('…'));
    }

    #[test]
    fn deserialises_dashboard_payload_round_trip() {
        // Lock the wire shape against the server's pydantic schema —
        // any rename to a field would break this and surface the
        // contract drift in CI rather than at runtime.
        let payload = json!({
            "working": [{
                "id": "00000000-0000-0000-0000-000000000001",
                "status": "working",
                "raw_status": "running",
                "title": "Migrate auth",
                "workflow_id": "00000000-0000-0000-0000-000000000002",
                "workflow_name": "Goal",
                "started_at": "2026-05-13T19:00:00Z",
                "total_cost_usd": 0.0,
            }],
            "completed": [{
                "id": "00000000-0000-0000-0000-000000000003",
                "status": "completed",
                "raw_status": "completed",
                "title": "Daily Briefing",
                "workflow_id": "00000000-0000-0000-0000-000000000004",
                "workflow_name": "Daily Briefing",
                "started_at": "2026-05-13T18:00:00Z",
                "completed_at": "2026-05-13T18:02:00Z",
                "duration_ms": 120000,
                "total_tokens": 4200,
                "total_cost_usd": 0.012,
            }],
            "supports_needs_input": false,
        });
        let parsed: TaskDashboard = serde_json::from_value(payload).expect("parse");
        assert_eq!(parsed.working.len(), 1);
        assert_eq!(parsed.completed.len(), 1);
        assert_eq!(parsed.working[0].raw_status, "running");
        assert!(!parsed.supports_needs_input);
    }
}
