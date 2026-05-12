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
use agentprovision_core::training::local_ai_cli;

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

/// Per-tenant resume-state path. Reviewer I-3: keying the file
/// globally meant a second `ap login` against a different tenant
/// silently clobbered the first's stranded snapshot, and `--resume`
/// would re-POST under the wrong tenant. Tenant-scoping fixes that
/// without adding any state-sharing surface between tenants.
fn resume_state_path(tenant_id: &str) -> Option<PathBuf> {
    dirs::config_dir().map(|p| {
        p.join("agentprovision")
            .join(format!("quickstart-{tenant_id}.toml"))
    })
}

fn load_resume_state(tenant_id: &str) -> Option<ResumeState> {
    let path = resume_state_path(tenant_id)?;
    let s = std::fs::read_to_string(&path).ok()?;
    toml::from_str(&s).ok()
}

fn save_resume_state(tenant_id: &str, state: &ResumeState) -> Result<(), std::io::Error> {
    // best-effort — we never want a write failure to crash quickstart
    if let Some(path) = resume_state_path(tenant_id) {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let s = toml::to_string(state).map_err(|e| std::io::Error::other(e.to_string()))?;
        std::fs::write(&path, s)?;
    }
    Ok(())
}

fn clear_resume_state(tenant_id: &str) {
    // Best-effort cleanup. We don't propagate errors — a leftover file
    // is harmless (the next `--resume` will re-POST the same snapshot
    // and the server's idempotency check makes that a no-op).
    if let Some(path) = resume_state_path(tenant_id) {
        let _ = std::fs::remove_file(path);
    }
}

/// Heuristic that picks a default WedgeChannel offset for the
/// dialoguer Select. We use the server's recommended channel if it
/// matches a known wedge; otherwise default to local AI CLI (the dev
/// wedge — by far the lowest friction).
/// Cross-map between the server's `OnboardingStatus.recommended_channel`
/// vocabulary (9 values, including AI-CLI sub-kinds) and the CLI's
/// wedge enum (6 values). Reviewer B-1 caught this: the previous
/// `WedgeChannel::from_wire` only recognised the 6 `Source` enum
/// values, so the five AI-CLI recommendations (`claude_code`, `codex`,
/// `gemini_cli`, `copilot_cli`, `opencode`) silently returned `None`
/// and the picker fell back to index 0 — accidentally-correct because
/// `LocalAiCli` happens to be index 0, but a future option reorder
/// would silently invert the recommendation.
fn recommended_to_wedge(rec: &str) -> Option<WedgeChannel> {
    match rec {
        // The AI-CLI sub-kinds all bucket into the single LocalAiCli
        // wedge (the scanner reads metadata from each runtime present
        // on disk; the user doesn't pick by runtime).
        "claude_code" | "codex" | "gemini_cli" | "copilot_cli" | "opencode" => {
            Some(WedgeChannel::LocalAiCli)
        }
        "github_cli" => Some(WedgeChannel::GithubCli),
        "gmail" => Some(WedgeChannel::Gmail),
        "calendar" => Some(WedgeChannel::Calendar),
        "slack" => Some(WedgeChannel::Slack),
        "whatsapp" => Some(WedgeChannel::Whatsapp),
        _ => None,
    }
}

fn picker_default_index(status: &OnboardingStatus, options: &[WedgeChannel]) -> usize {
    if let Some(rec) = status.recommended_channel.as_deref() {
        if let Some(matched) = recommended_to_wedge(rec) {
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

    // Resolve the tenant_id once up front. Reviewer I-3: resume state
    // is keyed by tenant_id so a user with multiple tenants doesn't
    // overwrite one tenant's stranded snapshot when running quickstart
    // against another. JWT carries it; we trust `current_user()`.
    let me = ctx.client.current_user().await?;
    let tenant_id = me
        .tenant_id
        .ok_or_else(|| anyhow::anyhow!("user has no tenant_id — server contract violation"))?
        .to_string();

    // (1) Onboarding-status check. Drives the auto-trigger contract:
    // if already onboarded and `--force` wasn't passed, we exit 0
    // without prompting so `ap login` post-success hooks stay quiet.
    // Plain `?` here keeps the typed Error chain (B-2 / I-4) so the
    // caller can downcast on Error::Api { status, .. }.
    let status: OnboardingStatus = ctx.client.get_onboarding_status().await?;

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
    let (channel, resume_existing) = resolve_channel(&args, &status, &tenant_id)?;

    // (3) Items collection. PR-Q3a wires the Local-AI-CLI wedge to a
    // real scanner that reads git config + ~/.{claude,codex,gemini,
    // local/share/opencode} session metadata. Other wedges still
    // use the stub until their respective PRs land.
    let items = collect_items(channel, &ctx).await?;

    // (4) Dispatch the bulk-ingest. snapshot_id is generated once per
    // quickstart run and persisted to disk BEFORE the POST so a Ctrl-C
    // between request and response still leaves a recoverable state.
    // The server's `(tenant_id, snapshot_id)` unique index ensures we
    // never spawn a parallel workflow on retry; `--resume` simply
    // re-POSTs the same UUID and gets `deduplicated=true` back.
    // Reviewer NIT #6: write BEFORE POST so the recovery story is
    // 'rerun --resume', not 'rm the file by hand'.
    let snapshot_id = if let Some(rs) = resume_existing.as_ref() {
        rs.snapshot_id.clone()
    } else {
        uuid::Uuid::new_v4().to_string()
    };
    let _ = save_resume_state(
        &tenant_id,
        &ResumeState {
            snapshot_id: snapshot_id.clone(),
            source: channel.as_wire().to_string(),
            // Empty until we get the response back; --resume will
            // re-POST with the same snapshot_id and refresh this.
            training_run_id: resume_existing
                .as_ref()
                .map(|r| r.training_run_id.clone())
                .unwrap_or_default(),
        },
    );

    let resp: BulkIngestResponse = ctx
        .client
        .bulk_ingest_training(channel.as_wire(), &items, &snapshot_id)
        .await?;

    // Refresh the resume state with the now-known training_run_id so
    // status polling and downstream `--resume` retries can short-circuit.
    let _ = save_resume_state(
        &tenant_id,
        &ResumeState {
            snapshot_id: snapshot_id.clone(),
            source: channel.as_wire().to_string(),
            training_run_id: resp.run.id.to_string(),
        },
    );

    if !ctx.json {
        // Truncated run-id render: UUID round-trip guarantees ≥36 chars
        // so the slice is safe (NIT #11 — was guarded with `.min(len)`
        // belt-and-suspenders; UUID type makes that dead code).
        let run_id_short = &resp.run.id.to_string()[..8];
        if resp.deduplicated {
            println!(
                "{} resumed existing training run {} ({} status: {})",
                style("⟳").yellow().bold(),
                style(run_id_short).dim(),
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
    ctx.client.complete_onboarding("cli").await?;
    clear_resume_state(&tenant_id);

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
    tenant_id: &str,
) -> anyhow::Result<(WedgeChannel, Option<ResumeState>)> {
    if args.resume {
        if let Some(state) = load_resume_state(tenant_id) {
            let ch = WedgeChannel::from_wire(&state.source).ok_or_else(|| {
                anyhow::anyhow!(
                    "resume state has unknown source `{}` — delete \
                     ~/.config/agentprovision/quickstart-{}.toml and retry",
                    state.source,
                    tenant_id
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

/// Per-wedge item collection. Dispatches to the right scanner; the
/// stub branch still covers wedges whose PR hasn't landed yet so the
/// flow is end-to-end testable.
async fn collect_items(channel: WedgeChannel, ctx: &Context) -> anyhow::Result<Vec<Value>> {
    match channel {
        WedgeChannel::LocalAiCli => collect_local_ai_cli(ctx),
        // Stub branches — replaced by Q3b / Q4 / Q5 as those land.
        WedgeChannel::GithubCli
        | WedgeChannel::Gmail
        | WedgeChannel::Calendar
        | WedgeChannel::Slack
        | WedgeChannel::Whatsapp => Ok(vec![serde_json::json!({
            "kind": "quickstart-stub",
            "channel": channel.as_wire(),
            "note": "placeholder item — real collector ships in the per-wedge PR"
        })]),
    }
}

/// Local-AI-CLI wedge (PR-Q3a). Shows the consent summary, prompts
/// for confirmation, then runs the scanner. JSON mode auto-consents
/// because the scanner has the same blast radius as `ap memory ls`
/// — fileystem reads bounded to the documented directories — and
/// scripted callers shouldn't hang on a tty prompt.
fn collect_local_ai_cli(ctx: &Context) -> anyhow::Result<Vec<Value>> {
    use dialoguer::{theme::ColorfulTheme, Confirm};

    if !ctx.json && console::Term::stdout().is_term() {
        println!("\n{}", local_ai_cli::consent_summary());
        let ok = Confirm::with_theme(&ColorfulTheme::default())
            .with_prompt("Scan local AI CLI history and upload extracted metadata?")
            .default(true)
            .interact()
            .unwrap_or(false);
        if !ok {
            anyhow::bail!("local AI CLI scan declined — rerun and choose another wedge");
        }
    }

    let snap = local_ai_cli::scan(local_ai_cli::ScanOptions::default())?;
    let items = snap.to_items();
    if !ctx.json {
        println!(
            "  scanned: {} sessions across Claude / Codex / Gemini / OpenCode",
            snap.total_sessions()
        );
    }
    Ok(items)
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
        last = ctx.client.get_training_run(run_id).await?;
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
            // NIT #11 cleanup: run_id comes from the POST response
            // (UUID round-trip → always 36 chars), so the defensive
            // .min(run_id.len()) guard was dead. Match the simpler
            // slice used at the success path above.
            anyhow::bail!(
                "training run {} did not complete within 10 minutes — \
                 server status is `{}`; re-run with --resume later",
                &run_id[..8],
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

/// Helper used by the `ap login` post-success hook to auto-fire
/// quickstart for un-onboarded tenants without forcing the user to
/// type `ap quickstart`. Caller is responsible for not calling this
/// when stdin is non-interactive (e.g. piped) since the picker uses
/// `dialoguer::Select` which requires a tty.
///
/// Error semantics (reviewer B-2 fix): 404 from the onboarding-status
/// probe is treated as 'server is older than the CLI' — silent skip.
/// Any other API error (401, 5xx, transport) is **logged as a warning
/// to stderr** so a real outage isn't hidden behind the silent path.
/// We still return `Ok(())` so the parent `ap login` succeeds; the
/// user can rerun `ap quickstart` explicitly to retry.
pub async fn maybe_auto_trigger(ctx: &Context) -> anyhow::Result<()> {
    let status = match ctx.client.get_onboarding_status().await {
        Ok(s) => s,
        // 404 = endpoint missing on older API server. The only
        // legitimate reason to silently skip. Anything else means the
        // probe touched a real server and got rejected — surface it.
        Err(Error::Api { status: 404, .. }) => return Ok(()),
        Err(e) => {
            crate::output::warn(format!(
                "onboarding-status probe failed ({}); skipping auto-trigger. \
                 Run `ap quickstart` to retry.",
                e
            ));
            return Ok(());
        }
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

#[cfg(test)]
mod tests {
    use super::*;

    /// Reviewer NIT #12: prove the wire round-trip stays intact across
    /// future enum additions. If a new variant is added without a
    /// matching from_wire arm, this fails immediately.
    #[test]
    fn wedge_channel_wire_round_trip() {
        for ch in [
            WedgeChannel::LocalAiCli,
            WedgeChannel::GithubCli,
            WedgeChannel::Gmail,
            WedgeChannel::Calendar,
            WedgeChannel::Slack,
            WedgeChannel::Whatsapp,
        ] {
            let wire = ch.as_wire();
            let back = WedgeChannel::from_wire(wire).unwrap_or_else(|| {
                panic!("from_wire returned None for self-emitted {wire:?}")
            });
            assert_eq!(back.as_wire(), wire);
        }
    }

    /// Reviewer B-1: server emits AI-CLI sub-kinds that the CLI
    /// flattens into LocalAiCli. Without this mapping the picker
    /// silently fell back to index 0 — accidentally correct, but
    /// brittle. Lock the contract here.
    #[test]
    fn recommended_to_wedge_maps_ai_cli_subkinds_to_local_ai_cli() {
        for rec in ["claude_code", "codex", "gemini_cli", "copilot_cli", "opencode"] {
            assert_eq!(
                recommended_to_wedge(rec).map(|w| w.as_wire()),
                Some("local_ai_cli"),
                "expected {rec} → local_ai_cli"
            );
        }
        assert_eq!(
            recommended_to_wedge("gmail").map(|w| w.as_wire()),
            Some("gmail")
        );
        assert_eq!(
            recommended_to_wedge("github_cli").map(|w| w.as_wire()),
            Some("github_cli")
        );
        assert!(recommended_to_wedge("flarp").is_none());
    }

    /// `picker_default_index` selects the LocalAiCli row when the
    /// server recommends any AI-CLI sub-kind. This exact test would
    /// have FAILED before the B-1 fix (the previous code returned 0
    /// only because LocalAiCli happened to be in slot 0).
    #[test]
    fn picker_default_index_honours_ai_cli_recommendation() {
        let options = vec![
            // Intentionally NOT in the natural order — proves the
            // logic doesn't rely on LocalAiCli being slot 0.
            WedgeChannel::Gmail,
            WedgeChannel::GithubCli,
            WedgeChannel::LocalAiCli,
            WedgeChannel::Slack,
        ];
        let status = OnboardingStatus {
            onboarded: false,
            deferred: false,
            onboarded_at: None,
            onboarding_deferred_at: None,
            onboarding_source: None,
            recommended_channel: Some("claude_code".into()),
        };
        assert_eq!(picker_default_index(&status, &options), 2);
    }

    /// Unknown recommendation falls back to slot 0 (the safest
    /// default — won't crash; user can override).
    #[test]
    fn picker_default_index_falls_back_on_unknown_recommendation() {
        let options = vec![WedgeChannel::LocalAiCli, WedgeChannel::GithubCli];
        let status = OnboardingStatus {
            onboarded: false,
            deferred: false,
            onboarded_at: None,
            onboarding_deferred_at: None,
            onboarding_source: None,
            recommended_channel: Some("not-a-real-channel".into()),
        };
        assert_eq!(picker_default_index(&status, &options), 0);
    }

    /// Tenant-scoped resume path includes the tenant_id in the
    /// filename — reviewer I-3. A second tenant's run can't clobber
    /// the first's resume state.
    #[test]
    fn resume_state_path_is_tenant_scoped() {
        let p1 = resume_state_path("tenant-aaa").unwrap();
        let p2 = resume_state_path("tenant-bbb").unwrap();
        assert_ne!(p1, p2);
        assert!(p1.to_string_lossy().contains("tenant-aaa"));
        assert!(p2.to_string_lossy().contains("tenant-bbb"));
    }
}
