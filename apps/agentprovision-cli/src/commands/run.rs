//! `alpha run` — durable task dispatch with optional multi-provider fanout.
//!
//! Prototype for Phase 1 of the CLI differentiation roadmap
//! (`docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`).
//!
//! Semantics:
//!   - One-shot: `alpha run "<prompt>"`
//!     POSTs to `/api/v1/tasks-fanout/run`, returns a `task_id`,
//!     and (unless `--background`) tails the task's event stream
//!     until completion.
//!
//!   - Fanout: `alpha run "<prompt>" --fanout claude,codex,gemini --merge council`
//!     Same endpoint but with N providers; the backend spawns N child
//!     `ChatCliWorkflow` runs in parallel and merges the result via
//!     the meta-adjudicator already used by the provider review council.
//!
//!   - Fallback: `alpha run "<prompt>" --providers claude,codex,opencode`
//!     Backend tries providers in order; first non-quota-errored win.
//!
//! Why a single subcommand instead of `alpha run` + `alpha fanout`:
//!   `--fanout` and `--providers` are orthogonal modes of the same
//!   verb (dispatch a task across one-or-many runtimes). Splitting
//!   into separate subcommands would force users to relearn the same
//!   prompt+flags syntax twice. Keep it one verb.

use clap::Args;
use serde::{Deserialize, Serialize};
use std::fmt;
use std::time::{Duration, Instant};

use serde_json::json;

use crate::commands::watch::poll_until_terminal;
use crate::context::Context;
use crate::progress::{EventSink, ProgressEmitter};

/// `MergeMode` is the backend-visible discriminator for how to combine
/// fanout child outputs. `council` is the council-of-reviewers pattern
/// (consensus + disagreement summary), `first-wins` returns the first
/// completed child and cancels the rest, `all` returns every child
/// verbatim under a `children` array.
///
/// Round-1 N1: both `serde(rename_all = "kebab-case")` and
/// `clap(rename_all = "kebab-case")` are required because clap's
/// default variant naming is `snake_case` (`first_wins`) and serde's
/// default is also `snake_case`. The wire (and CLI flag) form is
/// `first-wins` — both adapters need the override.
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

impl fmt::Display for MergeMode {
    /// Round-1 M5: render to kebab-case (the wire / CLI flag form)
    /// instead of Rust Debug variant names. Used in
    /// `print_dispatch_banner` so the banner shows `council` /
    /// `first-wins` / `all` consistently with the `--merge` flag.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let s = match self {
            MergeMode::Council => "council",
            MergeMode::FirstWins => "first-wins",
            MergeMode::All => "all",
        };
        f.write_str(s)
    }
}

#[derive(Debug, Args)]
pub struct RunArgs {
    /// The prompt / task description to dispatch.
    #[arg(value_name = "PROMPT")]
    pub prompt: String,

    /// Bind the task to a specific agent (UUID). Defaults to the
    /// tenant's `code-agent` if available, otherwise the tenant default.
    #[arg(long)]
    pub agent: Option<String>,

    /// Bind the task to an existing chat session (UUID). Otherwise a
    /// fresh session is created and tied to `--agent`.
    #[arg(long)]
    pub session: Option<String>,

    // Round-1 B1: the `--tenant` flag was removed before initial ship.
    // Tenant identity is JWT-bound (the same posture as `--tenant` in
    // cli.rs was removed earlier for the same reason — see
    // `cli.rs:23-29` rationale). Shipping a body field that the
    // backend honored would allow an authenticated user in tenant A
    // to plant tasks under tenant B's `tenant_id`. The override will
    // return alongside `alpha tenant use` (design open question #4).
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
    /// Resume with `alpha watch <task_id>`.
    #[arg(long, short = 'b')]
    pub background: bool,

    /// Maximum number of seconds to tail the task in the foreground
    /// before exiting. The task itself keeps running on the backend —
    /// when the deadline hits, the CLI prints a hint and exits 0;
    /// resume any time with `alpha watch <task_id>` from any machine on
    /// the same account. Default 1800s (30 min). Round-2 L2-2: long
    /// migrations may want `--timeout 7200` or `--timeout 0` (= no
    /// ceiling, runs until terminal).
    #[arg(long, default_value_t = 1800)]
    pub timeout: u64,

    /// Emit a JSONL event stream of state transitions for machine
    /// consumers (CI dashboards, agent supervisors, log scrapers).
    ///
    /// Values:
    ///   * `-`          → write to stderr (default-friendly for piping)
    ///   * `<path>`     → append to a file
    ///   * unset        → no events (legacy human-only output)
    ///
    /// Schema is stable: one JSON object per line, top-level keys
    /// `ts`, `elapsed_ms`, `task_id`, `event`, `status`, `data`.
    /// New fields land under `data` so existing consumers keep parsing.
    #[arg(long, value_name = "PATH_OR_DASH")]
    pub events: Option<String>,
}

/// Request payload for `POST /api/v1/tasks-fanout/run`.
///
/// Round-1 B1: no `tenant_id` field. Tenant is JWT-bound on the
/// server. This struct is in-file (not in core/) because it is
/// prototype-scope; the public stable shape moves to
/// `agentprovision-core::tasks` once Phase 1 stabilizes.
#[derive(Debug, Serialize)]
struct RunRequest<'a> {
    prompt: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    agent_id: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    session_id: Option<&'a str>,
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
    children: Vec<RunChildDispatch>,
    /// Initial status reported by the workflow engine (e.g. "queued",
    /// "running"). Always non-empty.
    status: String,
    /// Best-effort cost / latency estimate when the backend has enough
    /// signal from past similar tasks (RL retrieval over state_text
    /// embeddings). May be `None` for novel prompts.
    ///
    /// Round-1 M1: `#[serde(default)]` so a backend that omits this
    /// field on novel prompts does not blow up deserialization.
    #[serde(default)]
    estimate: Option<RunEstimate>,
}

#[derive(Debug, Deserialize, Serialize)]
struct RunChildDispatch {
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
    // Validate flag combinations beyond what clap's `conflicts_with`
    // already enforces. `--merge` only matters with `--fanout`; warn
    // the user if they passed a non-default merge alone so it doesn't
    // silently do nothing.
    if !matches!(args.merge, MergeMode::Council) && args.fanout.is_empty() {
        eprintln!("[alpha] warning: --merge is only meaningful with --fanout; ignoring.");
    }

    // Set up the optional progress event stream. `--events -` ships
    // JSONL to stderr; `--events /tmp/run.jsonl` to a file; absent
    // → no events emitted (legacy behaviour). The emitter is cheap
    // when off (single bool check on .is_active()).
    let emitter = ProgressEmitter::new(EventSink::from_arg(args.events.as_deref())?);
    emitter.status("submitted", "running");

    let payload = RunRequest {
        prompt: &args.prompt,
        agent_id: args.agent.as_deref(),
        session_id: args.session.as_deref(),
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

    // Bind the emitter to the freshly-issued task_id so all
    // subsequent events carry it. Cheap clone; the underlying sink
    // is Arc<Mutex<File>> or a no-op.
    let emitter = emitter.with_task(&response.task_id);
    emitter.emit(
        "dispatched",
        Some("running"),
        json!({
            "providers": args.providers,
            "fanout": args.fanout,
            "merge": args.merge.to_string(),
            "children": response.children.iter().map(|c| {
                json!({"task_id": c.task_id, "provider": c.provider})
            }).collect::<Vec<_>>(),
            "estimate": response.estimate.as_ref().map(|e| json!({
                "duration_seconds": e.estimated_duration_seconds,
                "cost_usd": e.estimated_cost_usd,
                "confidence": e.confidence,
            })),
        }),
    );

    // Print a compact dispatch banner. JSON output emits the response
    // verbatim for scripting consumers.
    if ctx.json {
        println!("{}", serde_json::to_string_pretty(&response)?);
    } else {
        print_dispatch_banner(&response, &args);
    }

    if args.background {
        // `--background`: exit immediately so the user can close the
        // terminal. They can resume via `alpha watch <task_id>`. The
        // detach itself is a terminal-from-this-process event — emit
        // it so agents can short-circuit their wait.
        emitter.emit(
            "detached",
            Some("backgrounded"),
            json!({"resume": format!("alpha watch {}", response.task_id)}),
        );
        return Ok(());
    }

    // Foreground: tail the task event stream until completion or the
    // user-supplied timeout (round-1 H4). The poll helper is shared
    // with `alpha watch` (round-1 L1). Round-2 L2-2: `--timeout 0` means
    // "no ceiling — tail until terminal."
    let deadline = (args.timeout > 0).then(|| Instant::now() + Duration::from_secs(args.timeout));
    poll_until_terminal(
        &ctx,
        &response.task_id,
        deadline,
        Duration::from_millis(1500),
    )
    .await
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
            "[alpha] dispatched fanout task {task_id} with {} children:",
            children.len()
        );
        for c in &children {
            println!("       • {c}");
        }
        // Round-1 M5: kebab-case via Display, not Debug `{:?}`.
        println!("[alpha] merge mode: {}", args.merge);
    } else if !args.providers.is_empty() {
        println!(
            "[alpha] dispatched task {task_id} with fallback chain: {}",
            args.providers.join(" → ")
        );
    } else {
        println!("[alpha] dispatched task {task_id}");
    }

    if let Some(est) = &response.estimate {
        println!(
            "[alpha] estimated {}s / ${:.2} (confidence={})",
            est.estimated_duration_seconds, est.estimated_cost_usd, est.confidence
        );
    }

    if args.background {
        println!("[alpha] close this terminal any time — resume with: alpha watch {task_id}");
    } else if args.timeout == 0 {
        // Round-3 L3-1: `--timeout 0` is the "no ceiling" sentinel
        // (round-2 L2-2). Don't print "for up to 0s" which sounds
        // like immediate-exit.
        println!(
            "[alpha] tailing events with no ceiling… (Ctrl-C detaches; task continues running)"
        );
    } else {
        println!(
            "[alpha] tailing events for up to {}s… (Ctrl-C detaches; task continues running)",
            args.timeout
        );
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
        // Default timeout (round-1 H4).
        assert_eq!(a.timeout, 1800);
    }

    #[test]
    fn parses_providers_fallback_chain() {
        let a = parse(&[
            "test",
            "run",
            "task",
            "--providers",
            "claude,codex,opencode",
        ]);
        assert_eq!(a.providers, vec!["claude", "codex", "opencode"]);
        assert!(a.fanout.is_empty());
    }

    #[test]
    fn parses_fanout_with_merge() {
        let a = parse(&[
            "test",
            "run",
            "audit",
            "--fanout",
            "claude,codex,gemini",
            "--merge",
            "council",
        ]);
        assert_eq!(a.fanout, vec!["claude", "codex", "gemini"]);
        assert!(matches!(a.merge, MergeMode::Council));
    }

    #[test]
    fn fanout_and_providers_are_mutually_exclusive() {
        let res = TestCli::try_parse_from([
            "test",
            "run",
            "x",
            "--fanout",
            "claude",
            "--providers",
            "codex",
        ]);
        assert!(
            res.is_err(),
            "clap should reject --fanout + --providers together"
        );
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

    #[test]
    fn merge_mode_display_matches_wire() {
        // Round-1 M5: Display should emit kebab-case to match the
        // serde + clap form so the banner stays consistent.
        assert_eq!(format!("{}", MergeMode::Council), "council");
        assert_eq!(format!("{}", MergeMode::FirstWins), "first-wins");
        assert_eq!(format!("{}", MergeMode::All), "all");
    }

    #[test]
    fn parses_custom_timeout() {
        // Round-1 H4: --timeout overrides the 30m default.
        let a = parse(&["test", "run", "x", "--timeout", "600"]);
        assert_eq!(a.timeout, 600);
    }

    #[test]
    fn no_tenant_flag_exists() {
        // Round-1 B1: --tenant must NOT be accepted by clap.
        // Acceptance would allow tenant-spoofing via the request body.
        let res = TestCli::try_parse_from(["test", "run", "x", "--tenant", "t_x"]);
        assert!(
            res.is_err(),
            "--tenant must be rejected at parse time (round-1 B1)"
        );
    }
}
