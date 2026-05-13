//! `ap watch <task_id>` — resume tailing a durable task from any machine.
//!
//! Companion to `ap run --background`. The same JWT in `~/.ap/config.toml`
//! authorizes the watch, so a task dispatched on a laptop can be tailed
//! from a desktop without any handoff dance.
//!
//! Prototype scope: polls `/tasks-fanout/{id}/status` every 1500ms.
//! Phase 1 ship swaps the loop for an SSE consumer on the existing
//! `/chat/sessions/{id}/events/stream` route reused for tasks.

use clap::Args;
use serde::Deserialize;
use std::time::Duration;

use crate::context::Context;

#[derive(Debug, Args)]
pub struct WatchArgs {
    /// Task ID returned by `ap run` (e.g. `t_a4f3b2`).
    #[arg(value_name = "TASK_ID")]
    pub task_id: String,

    /// Exit immediately if the task is already in a terminal state
    /// (completed / failed / cancelled). Default behavior prints the
    /// terminal state and final result, then exits successfully.
    #[arg(long)]
    pub no_tail_if_done: bool,
}

#[derive(Debug, Deserialize)]
struct TaskStatus {
    status: String,
    #[serde(default)]
    result: Option<String>,
    /// Children's terminal statuses, populated for fanout parent tasks.
    /// Empty for single-provider tasks.
    #[serde(default)]
    children: Vec<ChildStatus>,
}

#[derive(Debug, Deserialize)]
struct ChildStatus {
    task_id: String,
    provider: String,
    status: String,
}

pub async fn run(args: WatchArgs, ctx: Context) -> anyhow::Result<()> {
    let path = format!("/api/v1/tasks-fanout/{}/status", args.task_id);

    // Snapshot first to handle the already-done case before entering the
    // poll loop (avoids one wasted sleep when the user runs `ap watch`
    // on a task that finished hours ago).
    let initial: TaskStatus = ctx.client.get_json(&path).await?;
    if is_terminal(&initial.status) {
        render_terminal(&args.task_id, &initial, ctx.json);
        return Ok(());
    }

    if ctx.json {
        // JSON mode prints a status record per poll for streaming consumers.
        println!("{}", serde_json::to_string(&initial.status)?);
    } else {
        println!("[ap] {} — {}", args.task_id, initial.status);
        for c in &initial.children {
            println!("       child {} ({}) — {}", c.task_id, c.provider, c.status);
        }
    }

    let mut last_status = initial.status;
    let mut last_child_states: Vec<(String, String)> = initial
        .children
        .iter()
        .map(|c| (c.task_id.clone(), c.status.clone()))
        .collect();

    loop {
        tokio::time::sleep(Duration::from_millis(1500)).await;
        let s: TaskStatus = ctx.client.get_json(&path).await?;

        if s.status != last_status {
            if ctx.json {
                println!("{}", serde_json::to_string(&s.status)?);
            } else {
                println!("[ap] {} — {}", args.task_id, s.status);
            }
            last_status = s.status.clone();
        }

        // Report child-status transitions independently — this is the
        // signal that makes fanout watching feel real-time (e.g. "claude
        // failed quota, codex now running").
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
            render_terminal(&args.task_id, &s, ctx.json);
            return Ok(());
        }
    }
}

fn is_terminal(status: &str) -> bool {
    matches!(status, "completed" | "failed" | "cancelled")
}

fn render_terminal(task_id: &str, s: &TaskStatus, json: bool) {
    if json {
        // Emit a final structured record. Useful for `jq` pipelines.
        let payload = serde_json::json!({
            "task_id": task_id,
            "status": s.status,
            "result": s.result,
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
    if let Some(result) = &s.result {
        println!("\n{result}");
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
        let cli = TestCli::try_parse_from(["test", "watch", "t_a4f3b2"]).unwrap();
        let TestCmd::Watch(a) = cli.cmd;
        assert_eq!(a.task_id, "t_a4f3b2");
        assert!(!a.no_tail_if_done);
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
}
