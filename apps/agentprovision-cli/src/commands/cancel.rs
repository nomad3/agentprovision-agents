//! `alpha cancel <task_id>` — abort an in-flight durable task.
//!
//! Companion to `alpha run` + `alpha watch`. The backend route is
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

use agentprovision_core::error::Error;
use reqwest::Method;

use crate::context::Context;

/// Round-2 L2-2: `NonEmptyStringValueParser` only rejects byte-length-0
/// strings; whitespace-only IDs slipped through into a URL like
/// `/api/v1/tasks-fanout/%20%20/cancel` and produced a misleading
/// network 502/404. This custom validator trims first so both empty
/// and whitespace-only inputs are caught at parse time.
fn non_blank_task_id(s: &str) -> Result<String, String> {
    if s.trim().is_empty() {
        Err("task_id must not be empty or whitespace-only".to_string())
    } else {
        Ok(s.to_string())
    }
}

#[derive(Debug, Args)]
pub struct CancelArgs {
    /// Task ID returned by `alpha run`. Stub-path tasks use a
    /// `t_<hex>` form (variable length). Real-path Temporal tasks
    /// use `fanout-<tenant_uuid>-<uuid>`. Always pass the parent
    /// task_id — child workflows are cancelled automatically by
    /// the backend cascade.
    ///
    /// Round-1 review L2 + round-2 L2-2: empty AND whitespace-only
    /// IDs are rejected at parse time. Clap's built-in
    /// NonEmptyStringValueParser only catches byte-length-0; the
    /// custom validator trims first so "   " is also rejected.
    #[arg(value_name = "TASK_ID", value_parser = non_blank_task_id)]
    pub task_id: String,

    /// Suppress the "cancelled" success line. Useful for scripts
    /// that only care about the exit code.
    ///
    /// Round-1 review L4: ignored when `--json` is set (JSON
    /// emission always happens). The two flags compose: `--quiet`
    /// suppresses the human-friendly line; `--json` suppresses it
    /// too but emits a structured record instead.
    #[arg(long, short = 'q')]
    pub quiet: bool,
}

pub async fn run(args: CancelArgs, ctx: Context) -> anyhow::Result<()> {
    let path = format!("/api/v1/tasks-fanout/{}/cancel", args.task_id);

    let req = ctx.client.request(Method::POST, &path)?;
    match ctx.client.send_no_body(req).await {
        Ok(()) => {
            if ctx.json {
                println!(
                    "{}",
                    serde_json::json!({"task_id": args.task_id, "status": "cancelled"})
                );
            } else if !args.quiet {
                println!("[alpha] cancelled {}", args.task_id);
            }
            Ok(())
        }
        // Round-1 review M1: dedicated 401 hint matches `quickstart`
        // and is the first thing a logged-out user reaches for.
        Err(Error::Unauthorized) => {
            anyhow::bail!("not logged in — run `alpha login` first")
        }
        // Round-1 review L3: include the server-side body on -vv so
        // a Cloudflare / proxy intermediary stripping a real 404 is
        // distinguishable from a clean backend 404. `log::debug!`
        // emits only when the user passes `-vv`.
        Err(Error::Api { status: 404, body }) => {
            log::debug!("cancel 404 body: {body}");
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
        // and must parse identically. Round-1 review N3: assert
        // round-trip equality, not just prefix.
        let wf_id = "fanout-12345678-1234-5678-1234-567812345678-87654321";
        let cli = TestCli::try_parse_from(["test", "cancel", wf_id]).unwrap();
        let TestCmd::Cancel(a) = cli.cmd;
        assert_eq!(a.task_id, wf_id);
    }

    #[test]
    fn empty_task_id_rejected() {
        // Round-1 review L2 + round-2 L2-2: empty AND whitespace-only
        // IDs must fail at parse time.
        assert!(
            TestCli::try_parse_from(["test", "cancel", ""]).is_err(),
            "empty task_id must be rejected"
        );
        assert!(
            TestCli::try_parse_from(["test", "cancel", "   "]).is_err(),
            "whitespace-only task_id must be rejected"
        );
        assert!(
            TestCli::try_parse_from(["test", "cancel", "\t"]).is_err(),
            "tab-only task_id must be rejected"
        );
    }

    // Round-1 review M2: HTTP-path test coverage is deferred — would
    // require either `httpmock` as a dev-dep or refactoring the
    // function to take a trait-object client for test injection. The
    // current crate pattern is parser-only tests on command files
    // (peers: `chat.rs`, `agent.rs`, `watch.rs`). Tracked for a
    // follow-up PR that adds mock-server coverage across all the
    // CLI commands at once. See round-1 review thread on PR #436.
    #[test]
    #[ignore = "TODO: requires httpmock dev-dep for HTTP-path coverage"]
    fn cancel_204_prints_success_line() {
        // Placeholder for the round-1 M2 follow-up — when wired,
        // mock POST /cancel → 204 and assert the "[alpha] cancelled <id>"
        // line is printed (or suppressed under --quiet / --json).
    }
}
