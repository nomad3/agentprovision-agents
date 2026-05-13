//! `ap run` — durable task dispatch with optional multi-provider fanout.
//!
//! Prototype for Phase 1 of the CLI differentiation roadmap
//! (`docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`).
//!
//! Semantics:
//!   - One-shot: `ap run "<prompt>"`
//!     POSTs to `/api/v1/tasks-fanout/run`, returns a `task_id`,
//!     and (unless `--background`) tails the task's event stream
//!     until completion.
//!
//!   - Fanout: `ap run "<prompt>" --fanout claude,codex,gemini --merge council`
//!     Same endpoint but with N providers; the backend spawns N child
//!     `ChatCliWorkflow` runs in parallel and merges the result via
//!     the meta-adjudicator already used by the provider review council.
//!
//!   - Fallback: `ap run "<prompt>" --providers claude,codex,opencode`
//!     Backend tries providers in order; first non-quota-errored win.
//!
//! Why a single subcommand instead of `ap run` + `ap fanout`:
//!   `--fanout` and `--providers` are orthogonal modes of the same
//!   verb (dispatch a task across one-or-many runtimes). Splitting
//!   into separate subcommands would force users to relearn the same
//!   prompt+flags syntax twice. Keep it one verb.

use clap::Args;
use serde::{Deserialize, Serialize};
use std::time::Duration;

use crate::context::Context;

/// `MergeMode` is the backend-visible discriminator for how to combine
/// fanout child outputs. `council` is the council-of-reviewers pattern
/// (consensus + disagreement summary), `first-wins` returns the first
/// completed child and cancels the rest, `all` returns every child
/// verbatim under a `children` array. Clap maps these to lowercased
/// `kebab-case` on the wire so the CLI stays human-friendly.
#[derive(Debug, Clone, clap::ValueEnum, Serialize)]
#[serde(rename_all = "kebab-case")]
#[clap(rename_all = "kebab-case")]
pub enum MergeMode {
    Council,
    FirstWins,
    All,
}

impl Default for MergeMode {
    fn default() -> Self {
        Self::Council
    }
}

#[derive(Debug, Args)]
pub struct RunArgs {
    /// The prompt / task description to dispatch.
    #[arg(value_name = "PROMPT")]
    pub prompt: String,

    /// Bind the task to a specific agent (UUID). Defaults to the tenant's
    /// `code-agent` if available, otherwise the tenant default.
    #[arg(long)]
    pub agent: Option<String>,

    /// Comma-separated **fallback** chain. If the first provider fails
    /// with a quota / auth error, the next is tried. Mutually exclusive
    /// with `--fanout` (use `--fanout` for parallel dispatch).
    ///
    /// Example: `--providers claude,codex,opencode`
    ///
    /// When neither `--providers` nor `--fanout` is given, the backend
    /// applies the tenant's default chain from `tenant_features
    /// .default_cli_platform` and the autodetect-fallback pipeline (#245).
    #[arg(long, value_delimiter = ',', conflicts_with = "fanout")]
    pub providers: Vec<String>,

    /// Comma-separated **parallel** provider list. Dispatches one child
    /// task per provider and merges results per `--merge`. Mutually
    /// exclusive with `--providers`.
    ///
    /// Example: `--fanout claude,codex,gemini --merge council`
    #[arg(long, value_delimiter = ',', conflicts_with = "providers")]
    pub fanout: Vec<String>,

    /// How to combine fanout child outputs. Only meaningful with `--fanout`.
    #[arg(long, value_enum, default_value_t = MergeMode::default())]
    pub merge: MergeMode,

    /// Detach immediately after dispatch. Prints the task id and exits.
    /// Resume with `ap watch <task_id>`.
    #[arg(long, short = 'b')]
    pub background: bool,

    /// Bind the task to an existing chat session (UUID). Otherwise a
    /// fresh session is created and tied to `--agent`.
    #[arg(long)]
    pub session: Option<String>,

    /// Tenant override (advanced). Defaults to the JWT's tenant claim.
    #[arg(long)]
    pub tenant: Option<String>,
}

/// Request payload for `POST /api/v1/tasks-fanout/run`.
///
/// Kept in this file (not core/) because it is prototype-scope; the
/// public stable shape lives in `agentprovision-core::tasks` once Phase 1
/// stabilizes.
#[derive(Debug, Serialize)]
struct RunRequest<'a> {
    prompt: &'a str,
    agent_id: Option<&'a str>,
    session_id: Option<&'a str>,
    tenant_id: Option<&'a str>,
    /// Fallback chain. Empty when `fanout` is set.
    providers: &'a [String],
    /// Parallel-dispatch list. Empty when `providers` is set or neither
    /// is set (in which case the backend picks).
    fanout: &'a [String],
    merge: MergeMode,
}

#[derive(Debug, Deserialize, Serialize)]
struct RunResponse {
    task_id: String,
    /// Children spawned (only populated when `fanout` was non-empty).
    /// Each entry has a `task_id` and the `provider` it was dispatched to.
    #[serde(default)]
    children: Vec<RunChild>,
    /// Initial status reported by the workflow engine (e.g. "queued",
    /// "running"). Always non-empty.
    status: String,
    /// Best-effort cost / latency estimate when the backend has enough
    /// signal from past similar tasks (RL retrieval over state_text
    /// embeddings). May be `None` for novel prompts.
    estimate: Option<RunEstimate>,
}

#[derive(Debug, Deserialize, Serialize)]
struct RunChild {
    task_id: String,
    provider: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct RunEstimate {
    estimated_duration_seconds: u32,
    estimated_cost_usd: f64,
    confidence: String,
}

pub async fn run(args: RunArgs, ctx: Context) -> anyhow::Result<()> {
    // Validate flag combinations beyond what clap's conflicts_with
    // already enforces. `--merge` only matters with `--fanout`; warn
    // the user if they passed `--merge` alone so it doesn't silently
    // do nothing.
    if !matches!(args.merge, MergeMode::Council) && args.fanout.is_empty() {
        eprintln!(
            "[ap] warning: --merge is only meaningful with --fanout; ignoring."
        );
    }

    let payload = RunRequest {
        prompt: &args.prompt,
        agent_id: args.agent.as_deref(),
        session_id: args.session.as_deref(),
        tenant_id: args.tenant.as_deref(),
        providers: &args.providers,
        fanout: &args.fanout,
        merge: args.merge.clone(),
    };

    // POST to the new tasks-fanout endpoint. We do not use the existing
    // `chat/send` path because (a) it is single-provider, (b) it streams
    // synchronously which defeats `--background`. The new endpoint is
    // stubbed in `apps/api/app/api/v1/tasks_fanout.py` for the prototype
    // and will be replaced by a real Temporal dispatch in Phase 1 ship.
    let response: RunResponse = ctx
        .client
        .post_json("/api/v1/tasks-fanout/run", &payload)
        .await?;

    // Print a compact dispatch banner. JSON output emits the response
    // verbatim for scripting consumers.
    if ctx.json {
        println!("{}", serde_json::to_string_pretty(&response)?);
    } else {
        print_dispatch_banner(&response, &args);
    }

    if args.background {
        // `--background`: exit immediately so the user can close the
        // terminal. They can resume via `ap watch <task_id>`.
        return Ok(());
    }

    // Foreground: tail the task event stream until completion.
    tail_task_events(&ctx, &response.task_id).await
}

fn print_dispatch_banner(response: &RunResponse, args: &RunArgs) {
    let task_id = &response.task_id;
    if !response.children.is_empty() {
        let children: Vec<String> = response
            .children
            .iter()
            .map(|c| format!("{} ({})", c.task_id, c.provider))
            .collect();
        println!(
            "[ap] dispatched fanout task {task_id} with {} children:",
            children.len()
        );
        for c in &children {
            println!("       • {c}");
        }
        println!("[ap] merge mode: {:?}", args.merge);
    } else if !args.providers.is_empty() {
        println!(
            "[ap] dispatched task {task_id} with fallback chain: {}",
            args.providers.join(" → ")
        );
    } else {
        println!("[ap] dispatched task {task_id}");
    }

    if let Some(est) = &response.estimate {
        println!(
            "[ap] estimated {}s / ${:.2} (confidence={})",
            est.estimated_duration_seconds, est.estimated_cost_usd, est.confidence
        );
    }

    if args.background {
        println!("[ap] close this terminal any time — resume with: ap watch {task_id}");
    } else {
        println!("[ap] tailing events… (Ctrl-C detaches; task continues running)");
    }
}

/// Tail the task's event stream until terminal status. Prototype uses
/// a simple GET-polling loop against `/tasks-fanout/{id}/status` every
/// 1500ms; the real implementation will consume the existing SSE
/// `/tasks/{id}/events/stream` endpoint shared with chat sessions.
async fn tail_task_events(ctx: &Context, task_id: &str) -> anyhow::Result<()> {
    let path = format!("/api/v1/tasks-fanout/{task_id}/status");
    let mut last_status: Option<String> = None;
    loop {
        let status: TaskStatus = ctx.client.get_json(&path).await?;
        if last_status.as_deref() != Some(&status.status) {
            println!("[ap] {} — {}", task_id, status.status);
            last_status = Some(status.status.clone());
        }
        if matches!(
            status.status.as_str(),
            "completed" | "failed" | "cancelled"
        ) {
            if let Some(result) = status.result {
                println!("\n{}", result);
            }
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(1500)).await;
    }
}

#[derive(Debug, Deserialize)]
struct TaskStatus {
    status: String,
    #[serde(default)]
    result: Option<String>,
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
        Run(RunArgs),
    }

    fn parse(args: &[&str]) -> RunArgs {
        let cli = TestCli::try_parse_from(args).expect("clap parse");
        match cli.cmd {
            TestCmd::Run(a) => a,
        }
    }

    #[test]
    fn parses_bare_prompt() {
        let a = parse(&["test", "run", "hello world"]);
        assert_eq!(a.prompt, "hello world");
        assert!(a.providers.is_empty());
        assert!(a.fanout.is_empty());
        assert!(!a.background);
        assert!(matches!(a.merge, MergeMode::Council));
    }

    #[test]
    fn parses_providers_fallback_chain() {
        let a = parse(&["test", "run", "task", "--providers", "claude,codex,opencode"]);
        assert_eq!(a.providers, vec!["claude", "codex", "opencode"]);
        assert!(a.fanout.is_empty());
    }

    #[test]
    fn parses_fanout_with_merge() {
        let a = parse(&[
            "test", "run", "audit", "--fanout", "claude,codex,gemini", "--merge", "council",
        ]);
        assert_eq!(a.fanout, vec!["claude", "codex", "gemini"]);
        assert!(matches!(a.merge, MergeMode::Council));
    }

    #[test]
    fn fanout_and_providers_are_mutually_exclusive() {
        let res = TestCli::try_parse_from([
            "test", "run", "x", "--fanout", "claude", "--providers", "codex",
        ]);
        assert!(res.is_err(), "clap should reject --fanout + --providers together");
    }

    #[test]
    fn parses_background_short_flag() {
        let a = parse(&["test", "run", "go", "-b"]);
        assert!(a.background);
    }

    #[test]
    fn merge_mode_kebab_case_on_wire() {
        // Serde tag rename verifies the JSON shape the backend expects.
        let json = serde_json::to_string(&MergeMode::FirstWins).unwrap();
        assert_eq!(json, "\"first-wins\"");
    }
}
