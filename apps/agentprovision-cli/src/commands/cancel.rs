//! `ap cancel <task_id>` — abort an in-flight durable task.
//!
//! Companion to `ap run` + `ap watch`. The backend route is
//! `POST /api/v1/tasks-fanout/{task_id}/cancel` (returns 204 on
//! success, 404 if the task does not exist for the caller's tenant).
//!
//! Cancellation semantics:
//!   - Stub-path (`USE_REAL_FANOUT_WORKFLOW=false`) tasks are dropped
//!     from the in-memory ledger immediately; subsequent `/status`
//!     returns 404.
//!   - Real-path tasks have their parent + child Temporal workflows
//!     cancelled. Cancellation is best-effort — Temporal queues a
//!     cancel command that the child workflow must observe at its
//!     next decision task. The leaf CLI subprocess may take seconds
//!     to receive the signal.
//!
//! Cancelling a fanout parent recursively cancels its children; the
//! backend's `cancel_task` route handles the cascade so the CLI does
//! not need to enumerate them.

use clap::Args;

use crate::context::Context;

#[derive(Debug, Args)]
pub struct CancelArgs {
    /// Task ID returned by `ap run` (e.g. `t_a4f3b2c1d2e3f4a5` for
    /// stub-path tasks, or `fanout-<tenant_uuid>-<uuid>` for real-
    /// path Temporal workflows).
    #[arg(value_name = "TASK_ID")]
    pub task_id: String,

    /// Suppress the "cancelled" success message. Useful for scripts
    /// that only care about the exit code.
    #[arg(long, short = 'q')]
    pub quiet: bool,
}

pub async fn run(args: CancelArgs, ctx: Context) -> anyhow::Result<()> {
    let path = format!("/api/v1/tasks-fanout/{}/cancel", args.task_id);

    // Use the typed `request` helper so auth headers + tenant context
    // are attached idiomatically. `send_no_body` handles the 204 case
    // and maps non-2xx to `Error::Api`. 404 is the benign "task
    // already completed or doesn't exist" path — surface it with a
    // friendly CLI message rather than the raw 404 body.
    use agentprovision_core::error::Error;
    use reqwest::Method;

    let req = ctx.client.request(Method::POST, &path)?;
    match ctx.client.send_no_body(req).await {
        Ok(()) => {
            if ctx.json {
                println!(
                    "{}",
                    serde_json::json!({"task_id": args.task_id, "status": "cancelled"})
                );
            } else if !args.quiet {
                println!("[ap] cancelled {}", args.task_id);
            }
            Ok(())
        }
        Err(Error::Api { status: 404, .. }) => {
            // The task already finished, was already cancelled, or
            // never existed for this tenant. Exit non-zero with a
            // helpful message; not a crash.
            anyhow::bail!(
                "task {} not found (already completed, cancelled, or doesn't exist)",
                args.task_id
            )
        }
        Err(e) => Err(e.into()),
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
        Cancel(CancelArgs),
    }

    #[test]
    fn parses_task_id() {
        let cli = TestCli::try_parse_from(["test", "cancel", "t_a4f3b2c1d2e3f4a5"]).unwrap();
        let TestCmd::Cancel(a) = cli.cmd;
        assert_eq!(a.task_id, "t_a4f3b2c1d2e3f4a5");
        assert!(!a.quiet);
    }

    #[test]
    fn parses_quiet_short_flag() {
        let cli = TestCli::try_parse_from(["test", "cancel", "t_x", "-q"]).unwrap();
        let TestCmd::Cancel(a) = cli.cmd;
        assert!(a.quiet);
    }

    #[test]
    fn parses_fanout_workflow_id() {
        // Real-path task_ids have the `fanout-<uuid>-<uuid>` shape
        // and must parse identically.
        let cli = TestCli::try_parse_from([
            "test",
            "cancel",
            "fanout-12345678-1234-5678-1234-567812345678-87654321",
        ])
        .unwrap();
        let TestCmd::Cancel(a) = cli.cmd;
        assert!(a.task_id.starts_with("fanout-"));
    }
}
