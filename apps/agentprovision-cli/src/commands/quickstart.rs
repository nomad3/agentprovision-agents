//! `ap quickstart` — guided initial-training flow.
//!
//! Fires automatically the first time a user runs `ap login` against an
//! un-onboarded tenant; can also be invoked explicitly to re-train or
//! to opt back in after a Skip. The flow is:
//!
//!     login (assumed already done)
//!     → GET /onboarding/status   (auto-trigger gate)
//!     → channel picker            (biased by status.recommended_channel)
//!     → collect items             (stubbed in PR-Q2; PR-Q3a/b + Q4/5 fill in)
//!     → POST /memory/training/bulk-ingest
//!     → poll status               (SSE replaces poll in PR-Q1b)
//!     → POST /onboarding/complete
//!     → fire the first chat       (optional, `--no-chat` skips)
//!
//! State is persisted to `~/.config/agentprovision/quickstart.toml`
//! across runs so a network blip mid-training is recoverable via
//! `ap quickstart --resume`.

use std::path::PathBuf;
use std::time::Duration;

use clap::{Args, ValueEnum};
use console::style;
use dialoguer::{theme::ColorfulTheme, Confirm, Select};
use indicatif::{ProgressBar, ProgressStyle};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use agentprovision_core::error::Error;
use agentprovision_core::models::{BulkIngestResponse, OnboardingStatus, TrainingRun};

use crate::context::Context;

#[derive(Debug, Args)]
pub struct QuickstartArgs {
    /// Skip the interactive picker. Must match one of the server-side
    /// `Source` enum values (see `app/schemas/training_run.py`).
    #[arg(long, value_enum)]
    pub channel: Option<WedgeChannel>,

    /// Don't fire the first chat at the end. Useful for scripts that
    /// just want the training pass to complete and then exit.
    #[arg(long)]
    pub no_chat: bool,

    /// Resume a quickstart run that was interrupted (network / Ctrl-C).
    /// Looks up the persisted snapshot_id from
    /// `~/.config/agentprovision/quickstart.toml` and re-POSTs against
    /// the existing training_runs row.
    #[arg(long)]
    pub resume: bool,

    /// Re-run even when the tenant is already onboarded or has
    /// deferred. Without `--force`, an onboarded tenant just prints
    /// 'Already onboarded' and exits 0 — keeps `ap login` auto-trigger
    /// idempotent.
    #[arg(long)]
    pub force: bool,
}

#[derive(Debug, Clone, Copy, ValueEnum)]
#[clap(rename_all = "snake_case")]
pub enum WedgeChannel {
    LocalAiCli,
    GithubCli,
    Gmail,
    Calendar,
    Slack,
    Whatsapp,
}

impl WedgeChannel {
    fn as_wire(&self) -> &'static str {
        match self {
            WedgeChannel::LocalAiCli => "local_ai_cli",
            WedgeChannel::GithubCli => "github_cli",
            WedgeChannel::Gmail => "gmail",
            WedgeChannel::Calendar => "calendar",
            WedgeChannel::Slack => "slack",
            WedgeChannel::Whatsapp => "whatsapp",
        }
    }

    fn from_wire(s: &str) -> Option<Self> {
        match s {
            "local_ai_cli" => Some(WedgeChannel::LocalAiCli),
            "github_cli" => Some(WedgeChannel::GithubCli),
            "gmail" => Some(WedgeChannel::Gmail),
            "calendar" => Some(WedgeChannel::Calendar),
            "slack" => Some(WedgeChannel::Slack),
            "whatsapp" => Some(WedgeChannel::Whatsapp),
            _ => None,
        }
    }

    fn label(&self) -> &'static str {
        match self {
            WedgeChannel::LocalAiCli => "Local AI CLIs (Claude / Codex / Gemini / Copilot history)",
            WedgeChannel::GithubCli => "GitHub CLI (gh — repos, PRs, issues)",
            WedgeChannel::Gmail => "Gmail (recent inbox)",
            WedgeChannel::Calendar => "Google Calendar (upcoming events)",
            WedgeChannel::Slack => "Slack (workspace + recent channels)",
            WedgeChannel::Whatsapp => "WhatsApp (contacts + recent chats)",
        }
    }
}

/// On-disk resume state. Persisted to
/// `~/.config/agentprovision/quickstart.toml` so an interrupted run
/// can pick up exactly where it left off. The snapshot_id is the
/// idempotency key — re-POSTing it returns the existing training_run.
#[derive(Debug, Serialize, Deserialize, Default)]
struct ResumeState {
    snapshot_id: String,
    source: String,
    training_run_id: String,
}

fn resume_state_path() -> Option<PathBuf> {
    dirs::config_dir().map(|p| p.join("agentprovision").join("quickstart.toml"))
}

fn load_resume_state() -> Option<ResumeState> {
    let path = resume_state_path()?;
    let s = std::fs::read_to_string(&path).ok()?;
    toml::from_str(&s).ok()
}

fn save_resume_state(state: &ResumeState) -> Result<(), std::io::Error> {
    // best-effort — we never want a write failure to crash quickstart
    if let Some(path) = resume_state_path() {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let s = toml::to_string(state).map_err(|e| std::io::Error::other(e.to_string()))?;
        std::fs::write(&path, s)?;
    }
    Ok(())
}

fn clear_resume_state() {
    // Best-effort cleanup. We don't propagate errors — a leftover file
    // is harmless (the next `--resume` will re-POST the same snapshot
    // and the server's idempotency check makes that a no-op).
    if let Some(path) = resume_state_path() {
        let _ = std::fs::remove_file(path);
    }
}

/// Heuristic that picks a default WedgeChannel offset for the
/// dialoguer Select. We use the server's recommended channel if it
/// matches a known wedge; otherwise default to local AI CLI (the dev
/// wedge — by far the lowest friction).
fn picker_default_index(status: &OnboardingStatus, options: &[WedgeChannel]) -> usize {
    if let Some(rec) = status.recommended_channel.as_deref() {
        if let Some(matched) = WedgeChannel::from_wire(rec) {
            if let Some(i) = options.iter().position(|c| c.as_wire() == matched.as_wire()) {
                return i;
            }
        }
    }
    0
}

pub async fn run(args: QuickstartArgs, ctx: Context) -> anyhow::Result<()> {
    // Auth gate — same shape as every other subcommand.
    if ctx.client.token().is_none() {
        anyhow::bail!("not logged in — run `ap login` first");
    }

    // (1) Onboarding-status check. Drives the auto-trigger contract:
    // if already onboarded and `--force` wasn't passed, we exit 0
    // without prompting so `ap login` post-success hooks stay quiet.
    let status: OnboardingStatus = ctx
        .client
        .get_onboarding_status()
        .await
        .map_err(map_api_error)?;

    if status.onboarded && !args.force {
        crate::output::emit(
            ctx.json,
            &serde_json::json!({"already_onboarded": true}),
            |_| {
                println!(
                    "{} this tenant has already completed onboarding. Use {} to re-run.",
                    style("✓").green().bold(),
                    style("ap quickstart --force").bold()
                );
            },
        );
        return Ok(());
    }

    // (2) Channel pick — explicit `--channel` wins, then resume state,
    // then interactive picker biased toward `status.recommended_channel`.
    let (channel, resume_existing) = resolve_channel(&args, &status)?;

    // (3) Items collection — STUB in PR-Q2. Each wedge PR replaces
    // this branch with its real collector (read ~/.claude history,
    // gh api, IMAP fetch, etc). The stub returns a synthetic item so
    // the workflow path is exercised end-to-end and we can verify the
    // CLI ↔ API contract before the per-source code lands.
    let items = collect_items_stub(channel)?;

    // (4) Dispatch the bulk-ingest. snapshot_id is generated once per
    // quickstart run and persisted to disk so `--resume` re-POSTs the
    // same UUID — the server's `(tenant_id, snapshot_id)` unique index
    // ensures we never spawn a parallel workflow.
    let snapshot_id = if let Some(rs) = resume_existing.as_ref() {
        rs.snapshot_id.clone()
    } else {
        uuid::Uuid::new_v4().to_string()
    };

    let resp: BulkIngestResponse = ctx
        .client
        .bulk_ingest_training(channel.as_wire(), &items, &snapshot_id)
        .await
        .map_err(map_api_error)?;

    // Persist resume state immediately so a Ctrl-C right after the POST
    // doesn't leave a stranded server-side row the user can't recover.
    let _ = save_resume_state(&ResumeState {
        snapshot_id: snapshot_id.clone(),
        source: channel.as_wire().to_string(),
        training_run_id: resp.run.id.to_string(),
    });

    if !ctx.json {
        if resp.deduplicated {
            println!(
                "{} resumed existing training run {} ({} status: {})",
                style("⟳").yellow().bold(),
                style(&resp.run.id.to_string()[..8]).dim(),
                style(channel.label()).bold(),
                resp.run.status,
            );
        } else {
            println!(
                "{} kicked off training on {} ({} items, ETA ~{}s)",
                style("→").cyan().bold(),
                style(channel.label()).bold(),
                resp.run.items_total,
                resp.estimated_seconds,
            );
        }
    }

    // (5) Progress — poll-based for PR-Q2. SSE wired up in PR-Q1b.
    let run = poll_until_terminal(&ctx, &resp.run.id.to_string()).await?;

    if run.status == "failed" {
        let detail = run.error.as_deref().unwrap_or("(no error message)");
        anyhow::bail!("training failed: {detail}");
    }

    // (6) Mark onboarding complete + clear resume state.
    ctx.client
        .complete_onboarding("cli")
        .await
        .map_err(map_api_error)?;
    clear_resume_state();

    if !ctx.json {
        println!(
            "{} onboarded — {} items absorbed into memory",
            style("✓").green().bold(),
            run.items_processed
        );
    }

    // (7) Optional first chat. Skipped on `--no-chat`. The chat itself
    // is a one-shot send through the existing `ap chat send` path so
    // we don't duplicate streaming code.
    if !args.no_chat && !ctx.json {
        println!(
            "\nTry asking the agent: {}",
            style("ap chat send \"what should I work on next?\"").dim()
        );
    }

    if ctx.json {
        crate::output::emit(
            true,
            &serde_json::json!({
                "onboarded": true,
                "source": channel.as_wire(),
                "training_run_id": run.id,
                "items_processed": run.items_processed,
            }),
            |_| {},
        );
    }
    Ok(())
}

fn resolve_channel(
    args: &QuickstartArgs,
    status: &OnboardingStatus,
) -> anyhow::Result<(WedgeChannel, Option<ResumeState>)> {
    if args.resume {
        if let Some(state) = load_resume_state() {
            let ch = WedgeChannel::from_wire(&state.source).ok_or_else(|| {
                anyhow::anyhow!(
                    "resume state has unknown source `{}` — delete \
                     ~/.config/agentprovision/quickstart.toml and retry",
                    state.source
                )
            })?;
            return Ok((ch, Some(state)));
        }
        anyhow::bail!("no quickstart state to resume — run without --resume");
    }

    if let Some(ch) = args.channel {
        return Ok((ch, None));
    }

    let options = vec![
        WedgeChannel::LocalAiCli,
        WedgeChannel::GithubCli,
        WedgeChannel::Gmail,
        WedgeChannel::Calendar,
        WedgeChannel::Slack,
        WedgeChannel::Whatsapp,
    ];
    let default = picker_default_index(status, &options);
    let labels: Vec<&str> = options.iter().map(|c| c.label()).collect();

    let selection = Select::with_theme(&ColorfulTheme::default())
        .with_prompt("Which source should AgentProvision learn from?")
        .items(&labels)
        .default(default)
        .interact()?;
    Ok((options[selection], None))
}

/// PR-Q2 placeholder. Returns a single synthetic item so the workflow
/// runs end-to-end without per-source collectors. Replaced wedge-by-wedge
/// in PR-Q3a/b, PR-Q4, PR-Q5 — each one returns real items from its
/// channel (Claude session metadata, `gh api` rows, Gmail messages…).
fn collect_items_stub(channel: WedgeChannel) -> anyhow::Result<Vec<Value>> {
    Ok(vec![serde_json::json!({
        "kind": "quickstart-stub",
        "channel": channel.as_wire(),
        "note": "placeholder item — real collector ships in the per-wedge PR"
    })])
}

async fn poll_until_terminal(ctx: &Context, run_id: &str) -> anyhow::Result<TrainingRun> {
    // 2-second poll interval. Each batch is ~3s on the local Gemma 4
    // path, so 2s is fast enough to feel live without hammering the API.
    // Hard cap of 10 minutes — if a run hasn't terminated by then,
    // something else is wrong and we'd rather surface that than spin.
    const POLL_INTERVAL: Duration = Duration::from_secs(2);
    const POLL_DEADLINE: Duration = Duration::from_secs(600);

    let pb = if !ctx.json {
        let pb = ProgressBar::new(0);
        pb.set_style(
            ProgressStyle::with_template(
                "{spinner:.cyan} training: {pos}/{len} items ({percent}%) {msg}",
            )
            .unwrap()
            .tick_chars("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏ "),
        );
        Some(pb)
    } else {
        None
    };

    let start = std::time::Instant::now();
    let mut last: TrainingRun;
    loop {
        last = ctx
            .client
            .get_training_run(run_id)
            .await
            .map_err(map_api_error)?;
        if let Some(pb) = pb.as_ref() {
            // Workflow may not have set items_total yet on the very
            // first poll; guard against 0-length progress bars.
            let total = last.items_total.max(1) as u64;
            pb.set_length(total);
            pb.set_position(last.items_processed.max(0) as u64);
            pb.set_message(format!("[{}]", last.status));
        }
        if last.status == "complete" || last.status == "failed" {
            break;
        }
        if start.elapsed() >= POLL_DEADLINE {
            if let Some(pb) = pb.as_ref() {
                pb.abandon_with_message("timed out");
            }
            anyhow::bail!(
                "training run {} did not complete within 10 minutes — \
                 server status is `{}`; re-run with --resume later",
                &run_id[..8.min(run_id.len())],
                last.status
            );
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }

    if let Some(pb) = pb {
        pb.finish_with_message(format!("[{}]", last.status));
    }
    Ok(last)
}

fn map_api_error(e: Error) -> anyhow::Error {
    // The core Error type already carries the API status + body for
    // `Error::Api`; we just lift it into anyhow so the dispatcher's
    // single failure path works for every subcommand. Worth keeping
    // separate from a generic `e.into()` so a future surface (JSON
    // error envelope, etc.) has one well-known choke point.
    anyhow::anyhow!(e.to_string())
}

/// Helper used by the `ap login` post-success hook to auto-fire
/// quickstart for un-onboarded tenants without forcing the user to
/// type `ap quickstart`. Caller is responsible for not calling this
/// when stdin is non-interactive (e.g. piped) since the picker uses
/// `dialoguer::Select` which requires a tty.
pub async fn maybe_auto_trigger(ctx: &Context) -> anyhow::Result<()> {
    let status = match ctx.client.get_onboarding_status().await {
        Ok(s) => s,
        // Endpoint unreachable / unauthorized — don't surface as a
        // post-login error. The user already authenticated; the
        // missing onboarding signal is informational. Silent skip.
        Err(_) => return Ok(()),
    };
    if status.onboarded || status.deferred {
        return Ok(());
    }
    if !console::Term::stdout().is_term() {
        // Non-tty (CI / pipe) — don't try to render a picker. The user
        // can run `ap quickstart` explicitly when they're at a terminal.
        return Ok(());
    }

    let proceed = Confirm::with_theme(&ColorfulTheme::default())
        .with_prompt("Set up your agent's initial memory now? (~2 minutes)")
        .default(true)
        .interact()
        .unwrap_or(false);
    if !proceed {
        // User said no — record the defer so the next `ap login`
        // doesn't re-prompt. Best-effort; an HTTP failure here is
        // non-fatal (worst case the user gets the prompt again).
        let _ = ctx.client.defer_onboarding().await;
        return Ok(());
    }

    // Re-enter the main flow with default args.
    run(
        QuickstartArgs {
            channel: None,
            no_chat: false,
            resume: false,
            force: false,
        },
        ctx.clone(),
    )
    .await
}
