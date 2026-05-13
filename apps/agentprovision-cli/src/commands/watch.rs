//! `ap watch <task_id>` — resume tailing a durable task from any machine.
//!
//! Companion to `ap run --background`. The same JWT in `~/.ap/config.toml`
//! authorizes the watch, so a task dispatched on a laptop can be tailed
//! from a desktop without any handoff dance.
//!
//! Prototype scope: polls `/tasks-fanout/{id}/status` every 1500ms.
//! Phase 1 ship swaps the loop for an SSE consumer on the existing
//! `/chat/sessions/{id}/events/stream` route reused for tasks.
//!
//! Round-1 L1: the poll loop is exported as `poll_until_terminal` and
//! reused by `ap run` (foreground mode) so future SSE replacement is
//! a single-site change.

use clap::Args;
use serde::Deserialize;
use std::time::{Duration, Instant};

use crate::context::Context;

#[derive(Debug, Args)]
pub struct WatchArgs {
    /// Task ID returned by `ap run` (e.g. `t_a4f3b2c1d2e3f4a5`).
    #[arg(value_name = "TASK_ID")]
    pub task_id: String,

    /// If the task is already in a terminal state when `ap watch` is
    /// invoked, print a single-line status and exit instead of
    /// rendering the full final result. Useful for scripted polling
    /// (`ap watch t_xxx --no-tail-if-done --json`).
    ///
    /// Round-1 H3: previously declared but unused. Now wired.
    #[arg(long)]
    pub no_tail_if_done: bool,

    /// Maximum number of seconds to tail before exiting (the task
    /// itself continues running; resume with another `ap watch`).
    /// Default 1800s (30 min). Round-1 H4 cap.
    #[arg(long, default_value_t = 1800)]
    pub timeout: u64,
}

/// Status payload mirror for `GET /tasks-fanout/{id}/status`.
///
/// Mirrors `apps/api/app/api/v1/tasks_fanout.py::TaskStatusResponse`.
/// `error` (round-1 M2) is populated on `failed` / `cancelled` so the
/// CLI can render something more useful than `[ap] t_xxx — failed`.
#[derive(Debug, Deserialize)]
pub(crate) struct TaskStatus {
    pub status: String,
    #[serde(default)]
    pub result: Option<String>,
    #[serde(default)]
    pub error: Option<String>,
    /// Children's terminal statuses, populated for fanout parent tasks.
    /// Empty for single-provider tasks.
    #[serde(default)]
    pub children: Vec<ChildStatus>,
}

#[derive(Debug, Deserialize)]
pub(crate) struct ChildStatus {
    pub task_id: String,
    pub provider: String,
    pub status: String,
}

pub async fn run(args: WatchArgs, ctx: Context) -> anyhow::Result<()> {
    let path = format!("/api/v1/tasks-fanout/{}/status", args.task_id);

    // Snapshot first to handle the already-done case before entering
    // the poll loop (avoids one wasted sleep when the user runs
    // `ap watch` on a task that finished hours ago).
    let initial: TaskStatus = ctx.client.get_json(&path).await?;
    if is_terminal(&initial.status) {
        if args.no_tail_if_done {
            // Round-1 H3: scripted-polling mode. Single-line status,
            // no body, no children breakdown.
            print_terminal_short(&args.task_id, &initial, ctx.json);
        } else {
            render_terminal(&args.task_id, &initial, ctx.json);
        }
        return Ok(());
    }

    // Round-1 H4: tail with a safety ceiling.
    let deadline = Instant::now() + Duration::from_secs(args.timeout);
    poll_until_terminal(&ctx, &args.task_id, Some(deadline), Duration::from_millis(1500)).await
}

/// Round-1 L1: shared poll loop used by `ap run` (foreground) and
/// `ap watch`. Prints transitions on the parent status and on every
/// child status. Returns Ok(()) on terminal status OR deadline hit.
///
/// `deadline` is the wall-clock cutoff (None = run forever, which we
/// currently never use — both callers pass a deadline now). The
/// `tick` argument is the poll cadence; 1500ms is the prototype
/// default — Phase 1 ship replaces this with SSE.
pub async fn poll_until_terminal(
    ctx: &Context,
    task_id: &str,
    deadline: Option<Instant>,
    tick: Duration,
) -> anyhow::Result<()> {
    let path = format!("/api/v1/tasks-fanout/{}/status", task_id);

    let mut last_status: Option<String> = None;
    let mut last_child_states: Vec<(String, String)> = Vec::new();

    loop {
        let s: TaskStatus = ctx.client.get_json(&path).await?;

        if last_status.as_deref() != Some(&s.status) {
            if ctx.json {
                println!("{}", serde_json::to_string(&s.status)?);
            } else {
                println!("[ap] {} — {}", task_id, s.status);
            }
            last_status = Some(s.status.clone());
        }

        for c in &s.children {
            let prev = last_child_states
                .iter()
                .find(|(tid, _)| tid == &c.task_id)
                .map(|(_, st)| st.clone());
            if prev.as_deref() != Some(&c.status) {
                if !ctx.json {
                    println!(
                        "       child {} ({}) — {}",
                        c.task_id, c.provider, c.status
                    );
                }
                if let Some(entry) = last_child_states
                    .iter_mut()
                    .find(|(tid, _)| tid == &c.task_id)
                {
                    entry.1 = c.status.clone();
                } else {
                    last_child_states.push((c.task_id.clone(), c.status.clone()));
                }
            }
        }

        if is_terminal(&s.status) {
            render_terminal(task_id, &s, ctx.json);
            return Ok(());
        }

        if let Some(d) = deadline {
            if Instant::now() >= d {
                // Round-1 H4: hit the safety ceiling. The task continues
                // running on the backend; the user can resume via
                // `ap watch <task_id>` later.
                if !ctx.json {
                    println!(
                        "[ap] {} — still {} after timeout; task continues. \
                         Resume with: ap watch {}",
                        task_id, s.status, task_id
                    );
                }
                return Ok(());
            }
        }
        tokio::time::sleep(tick).await;
    }
}

fn is_terminal(status: &str) -> bool {
    matches!(status, "completed" | "failed" | "cancelled")
}

/// Full terminal render: status line + final result body + any error.
fn render_terminal(task_id: &str, s: &TaskStatus, json: bool) {
    if json {
        // Final structured record. Useful for `jq` pipelines.
        let payload = serde_json::json!({
            "task_id": task_id,
            "status": s.status,
            "result": s.result,
            "error": s.error,
            "children": s.children.iter().map(|c| serde_json::json!({
                "task_id": c.task_id,
                "provider": c.provider,
                "status": c.status,
            })).collect::<Vec<_>>(),
        });
        println!("{}", serde_json::to_string_pretty(&payload).unwrap());
        return;
    }
    println!("[ap] {task_id} — {} (terminal)", s.status);
    // Round-1 M2: render `error` before `result` so a failed task
    // shows the reason first.
    if let Some(err) = &s.error {
        println!("\n[ap] error: {err}");
    }
    if let Some(result) = &s.result {
        println!("\n{result}");
    }
}

/// Short terminal render (round-1 H3 — `--no-tail-if-done`).
/// Single-line status + child summary; no full result body.
fn print_terminal_short(task_id: &str, s: &TaskStatus, json: bool) {
    if json {
        let payload = serde_json::json!({
            "task_id": task_id,
            "status": s.status,
            "children": s.children.iter().map(|c| serde_json::json!({
                "task_id": c.task_id,
                "provider": c.provider,
                "status": c.status,
            })).collect::<Vec<_>>(),
        });
        println!("{}", serde_json::to_string(&payload).unwrap());
        return;
    }
    println!("[ap] {task_id} — {}", s.status);
    if !s.children.is_empty() {
        let summary: Vec<String> = s
            .children
            .iter()
            .map(|c| format!("{}:{}", c.provider, c.status))
            .collect();
        println!("       children: {}", summary.join(", "));
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
        Watch(WatchArgs),
    }

    #[test]
    fn parses_task_id() {
        let cli = TestCli::try_parse_from(["test", "watch", "t_a4f3b2c1d2e3f4a5"]).unwrap();
        let TestCmd::Watch(a) = cli.cmd;
        assert_eq!(a.task_id, "t_a4f3b2c1d2e3f4a5");
        assert!(!a.no_tail_if_done);
        // Round-1 H4: default timeout.
        assert_eq!(a.timeout, 1800);
    }

    #[test]
    fn parses_no_tail_if_done_and_timeout() {
        // Round-1 H3 + H4: both flags accepted.
        let cli = TestCli::try_parse_from([
            "test",
            "watch",
            "t_x",
            "--no-tail-if-done",
            "--timeout",
            "60",
        ])
        .unwrap();
        let TestCmd::Watch(a) = cli.cmd;
        assert!(a.no_tail_if_done);
        assert_eq!(a.timeout, 60);
    }

    #[test]
    fn terminal_status_classification() {
        assert!(is_terminal("completed"));
        assert!(is_terminal("failed"));
        assert!(is_terminal("cancelled"));
        assert!(!is_terminal("running"));
        assert!(!is_terminal("queued"));
        assert!(!is_terminal(""));
    }

    #[test]
    fn task_status_deserializes_with_error_field() {
        // Round-1 M2: TaskStatus mirror picks up the optional `error`
        // field added on the backend side without breaking when older
        // backends omit it.
        let no_error: TaskStatus =
            serde_json::from_str(r#"{"status":"completed","result":"ok"}"#).unwrap();
        assert!(no_error.error.is_none());
        assert_eq!(no_error.result.as_deref(), Some("ok"));

        let with_error: TaskStatus = serde_json::from_str(
            r#"{"status":"failed","error":"quota_exceeded after 12 tool calls"}"#,
        )
        .unwrap();
        assert_eq!(
            with_error.error.as_deref(),
            Some("quota_exceeded after 12 tool calls")
        );
    }
}
