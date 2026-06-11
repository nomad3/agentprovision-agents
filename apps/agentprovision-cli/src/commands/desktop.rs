//! `alpha desktop` — operator-facing desktop-control (Luna macOS computer-use)
//! inspection verbs.
//!
//! Per the Alpha CLI kernel principle these delegate to the internal API
//! (`GET /api/v1/desktop-control/...`) and the same service entrypoints the
//! web/Tauri viewports call — they never actuate input locally.

use std::path::PathBuf;

use clap::{Args, Subcommand, ValueEnum};

use agentprovision_core::desktop::{
    DesktopActionKind, DesktopBackgroundDryRunRequest, DesktopBackgroundDryRunTarget,
    DesktopCommandStopRequest, DesktopControlAllowlistUpdate, DesktopControlEnablement,
    DesktopControlEnablementUpdate, DesktopGrantRequestBody, DesktopObservationRequestBody,
    DesktopObserveAction, DesktopRequestableAction, PerceptionFetchDenial,
};
use agentprovision_core::Error as CoreError;
use serde::Serialize;
use uuid::Uuid;

use crate::context::Context;
use crate::output;

#[derive(Debug, Subcommand)]
pub enum DesktopCommand {
    /// Validate the desktop-control envelope signing config (operator
    /// fail-fast surface). Superuser-only server-side.
    #[command(subcommand)]
    Preflight(PreflightCommand),
    /// Queue a safe background-control dry-run command for Luna/Tauri.
    #[command(subcommand)]
    DryRun(DryRunCommand),
    /// Inspect a queued desktop command.
    #[command(subcommand)]
    Command(CommandLifecycleCommand),
    /// Governed observation verbs (P5.3b): request an observation, inspect a
    /// perception artifact, and fetch ONLY its planner-safe redacted content.
    #[command(subcommand)]
    Observe(ObserveCommand),
    /// Pending desktop approval requests (P5.4b): ask a human to approve a native
    /// action and poll the request. Never mints a grant or actuates.
    #[command(subcommand)]
    Grant(GrantCommand),
    /// Inspect or update the current tenant's desktop-control bootstrap gates.
    #[command(subcommand)]
    Enablement(EnablementCommand),
    /// Inspect or replace the current tenant's native-control target allowlist.
    #[command(subcommand)]
    Allowlist(AllowlistCommand),
}

#[derive(Debug, Subcommand)]
pub enum PreflightCommand {
    /// Run the preflight and print the result.
    Run(PreflightRunArgs),
}

#[derive(Debug, Args)]
pub struct PreflightRunArgs {}

#[derive(Debug, Subcommand)]
pub enum DryRunCommand {
    /// Request a fixed background-control dry-run command.
    Request(DryRunRequestArgs),
}

#[derive(Debug, Args)]
pub struct DryRunRequestArgs {
    /// Chat/session UUID that owns the command stream.
    #[arg(long)]
    pub session: Uuid,
    /// macOS bundle id for the allowlisted target app.
    #[arg(long)]
    pub target_bundle_id: String,
    /// Optional desktop shell id when the caller has one.
    #[arg(long)]
    pub shell_id: Option<String>,
    /// Optional client nonce for idempotent command enqueue.
    #[arg(long)]
    pub nonce: Option<String>,
    /// Optional title pattern used only as reduced target metadata.
    #[arg(long)]
    pub window_title_pattern: Option<String>,
    /// Optional macOS display id for target binding.
    #[arg(long)]
    pub display_id: Option<i64>,
}

#[derive(Debug, Subcommand)]
pub enum CommandLifecycleCommand {
    /// Read the display-safe status snapshot for a queued command.
    Status(CommandStatusArgs),
    /// Preempt queued/running desktop work for a session and shell.
    Stop(CommandStopArgs),
}

#[derive(Debug, Args)]
pub struct CommandStatusArgs {
    /// Desktop command UUID.
    pub command_id: Uuid,
    /// Optional chat/session UUID to tighten the status lookup.
    #[arg(long)]
    pub session: Option<Uuid>,
}

#[derive(Debug, Args)]
pub struct CommandStopArgs {
    /// Chat/session UUID whose desktop work should stop.
    #[arg(long)]
    pub session: Uuid,
    /// Connected Luna desktop shell id to stop.
    #[arg(long)]
    pub shell_id: String,
    /// Display-safe stop reason. Raw app content must not be included.
    #[arg(long, default_value = "desktop control stopped")]
    pub reason: String,
}

#[derive(Debug, Subcommand)]
pub enum ObserveCommand {
    /// Request a governed observation (records a display-safe audit event;
    /// content delivery happens via `fetch` once an artifact is planner-safe).
    Request(ObserveRequestArgs),
    /// Read the display-safe status of a perception artifact.
    Status(ObserveStatusArgs),
    /// Download the planner-safe REDACTED content of a perception artifact.
    Fetch(ObserveFetchArgs),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum ObserveActionArg {
    Screenshot,
    ActiveApp,
    Clipboard,
}

impl From<ObserveActionArg> for DesktopObserveAction {
    fn from(value: ObserveActionArg) -> Self {
        match value {
            ObserveActionArg::Screenshot => DesktopObserveAction::CaptureScreenshot,
            ObserveActionArg::ActiveApp => DesktopObserveAction::GetActiveApp,
            ObserveActionArg::Clipboard => DesktopObserveAction::ReadClipboard,
        }
    }
}

#[derive(Debug, Args)]
pub struct ObserveRequestArgs {
    /// Chat/session UUID the observation binds to.
    #[arg(long)]
    pub session: Uuid,
    /// Observation kind (default: screenshot).
    #[arg(long, value_enum, default_value = "screenshot")]
    pub action: ObserveActionArg,
    /// Optional desktop shell id when the caller has one.
    #[arg(long)]
    pub shell_id: Option<String>,
}

#[derive(Debug, Args)]
pub struct ObserveStatusArgs {
    /// Perception artifact UUID.
    pub artifact_id: Uuid,
    /// Chat/session UUID that owns the artifact (scope check).
    #[arg(long)]
    pub session: Uuid,
    /// Optional desktop shell id to tighten the scope check.
    #[arg(long)]
    pub shell_id: Option<String>,
}

#[derive(Debug, Args)]
pub struct ObserveFetchArgs {
    /// Perception artifact UUID.
    pub artifact_id: Uuid,
    /// Chat/session UUID that owns the artifact (scope check).
    #[arg(long)]
    pub session: Uuid,
    /// File path the redacted PNG is written to (bytes never go to stdout).
    #[arg(long)]
    pub out: PathBuf,
    /// Optional desktop shell id to tighten the scope check.
    #[arg(long)]
    pub shell_id: Option<String>,
}

#[derive(Debug, Subcommand)]
pub enum GrantCommand {
    /// Record a PENDING request to run a native action (a human approves later).
    /// Creates no grant and never actuates.
    Request(GrantRequestArgs),
    /// Poll a pending approval request by id.
    Status(GrantStatusArgs),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum GrantActionArg {
    PointerMove,
    PointerClick,
    KeyboardType,
    KeyboardKeyChord,
}

impl From<GrantActionArg> for DesktopRequestableAction {
    fn from(value: GrantActionArg) -> Self {
        match value {
            GrantActionArg::PointerMove => DesktopRequestableAction::PointerMove,
            GrantActionArg::PointerClick => DesktopRequestableAction::PointerClick,
            GrantActionArg::KeyboardType => DesktopRequestableAction::KeyboardType,
            GrantActionArg::KeyboardKeyChord => DesktopRequestableAction::KeyboardKeyChord,
        }
    }
}

#[derive(Debug, Args)]
pub struct GrantRequestArgs {
    /// Chat/session UUID the request binds to.
    #[arg(long)]
    pub session: Uuid,
    /// Native action to request approval for.
    #[arg(long, value_enum)]
    pub action: GrantActionArg,
    /// macOS bundle id of the target app.
    #[arg(long)]
    pub target_bundle_id: String,
    /// Optional desktop shell id.
    #[arg(long)]
    pub shell_id: Option<String>,
    /// Optional human-readable rationale (capped server-side).
    #[arg(long)]
    pub reason: Option<String>,
}

#[derive(Debug, Args)]
pub struct GrantStatusArgs {
    /// Pending approval request UUID.
    pub request_id: Uuid,
}

#[derive(Debug, Subcommand)]
pub enum EnablementCommand {
    /// Read the current tenant's desktop-control bootstrap gates.
    Get(EnablementGetArgs),
    /// Update one or more desktop-control bootstrap gates. Superuser-only.
    Set(EnablementSetArgs),
}

#[derive(Debug, Args)]
pub struct EnablementGetArgs {}

#[derive(Debug, Args)]
pub struct EnablementSetArgs {
    /// Background app-control dry-run gate.
    #[arg(long, value_name = "BOOL")]
    pub background_control: Option<bool>,
}

#[derive(Debug, Subcommand)]
pub enum AllowlistCommand {
    /// Read the current tenant's native-control target allowlist and platform floor.
    Get(AllowlistGetArgs),
    /// Replace the current tenant target allowlist. Superuser-only.
    Set(AllowlistSetArgs),
}

#[derive(Debug, Args)]
pub struct AllowlistGetArgs {}

#[derive(Debug, Args)]
pub struct AllowlistSetArgs {
    /// Bundle id to include. Repeat for multiple bundles.
    #[arg(long = "bundle-id", required = true)]
    pub bundle_ids: Vec<String>,
}

pub async fn dispatch(cmd: DesktopCommand, ctx: Context) -> anyhow::Result<()> {
    match cmd {
        DesktopCommand::Preflight(PreflightCommand::Run(a)) => preflight_run(a, ctx).await,
        DesktopCommand::DryRun(DryRunCommand::Request(a)) => dry_run_request(a, ctx).await,
        DesktopCommand::Command(CommandLifecycleCommand::Status(a)) => command_status(a, ctx).await,
        DesktopCommand::Command(CommandLifecycleCommand::Stop(a)) => command_stop(a, ctx).await,
        DesktopCommand::Observe(ObserveCommand::Request(a)) => observe_request(a, ctx).await,
        DesktopCommand::Observe(ObserveCommand::Status(a)) => observe_status(a, ctx).await,
        DesktopCommand::Observe(ObserveCommand::Fetch(a)) => observe_fetch(a, ctx).await,
        DesktopCommand::Grant(GrantCommand::Request(a)) => grant_request(a, ctx).await,
        DesktopCommand::Grant(GrantCommand::Status(a)) => grant_status(a, ctx).await,
        DesktopCommand::Enablement(EnablementCommand::Get(a)) => enablement_get(a, ctx).await,
        DesktopCommand::Enablement(EnablementCommand::Set(a)) => enablement_set(a, ctx).await,
        DesktopCommand::Allowlist(AllowlistCommand::Get(a)) => allowlist_get(a, ctx).await,
        DesktopCommand::Allowlist(AllowlistCommand::Set(a)) => allowlist_set(a, ctx).await,
    }
}

async fn preflight_run(_args: PreflightRunArgs, ctx: Context) -> anyhow::Result<()> {
    let resp = ctx.client.desktop_preflight().await?;
    if ctx.json {
        crate::output::emit(true, &resp, |_| {});
    } else {
        if resp.ok {
            output::ok(format!(
                "[alpha] desktop preflight ok — algorithm={}",
                resp.algorithm
            ));
        } else {
            output::warn(format!(
                "[alpha] desktop preflight FAILED — algorithm={}: {}",
                resp.algorithm,
                resp.error.as_deref().unwrap_or("(no detail)"),
            ));
        }
        for c in &resp.checks {
            let mark = if c.ok { "ok" } else { "FAIL" };
            output::info(format!("  [{mark}] {}: {}", c.name, c.detail));
        }
    }
    // Non-zero exit on a failed preflight so scripts / readiness checks can
    // detect it — the result was already emitted above.
    if !resp.ok {
        anyhow::bail!("desktop preflight failed (algorithm={})", resp.algorithm);
    }
    Ok(())
}

async fn dry_run_request(args: DryRunRequestArgs, ctx: Context) -> anyhow::Result<()> {
    let body = DesktopBackgroundDryRunRequest {
        session_id: args.session.to_string(),
        shell_id: args.shell_id,
        nonce: args.nonce,
        target: DesktopBackgroundDryRunTarget {
            bundle_id: args.target_bundle_id,
            action: DesktopActionKind::BackgroundAppControlDryRun,
            window_title_pattern: args.window_title_pattern,
            display_id: args.display_id,
        },
    };
    let resp = ctx.client.desktop_background_dry_run(&body).await?;
    output::emit(ctx.json, &resp, |resp| {
        output::ok(format!(
            "[alpha] desktop dry-run queued command_id={} status={} capability={}",
            resp.desktop_command_id,
            json_string(&resp.status),
            json_string(&resp.capability),
        ));
        output::info(format!("shell_id={}", resp.shell_id));
        if let Some(event_id) = &resp.session_event_id {
            output::info(format!("session_event_id={event_id}"));
        }
        if resp.idempotent {
            output::info("idempotent=true");
        }
    });
    Ok(())
}

async fn command_status(args: CommandStatusArgs, ctx: Context) -> anyhow::Result<()> {
    let command_id = args.command_id.to_string();
    let session_id = args.session.map(|session| session.to_string());
    let resp = ctx
        .client
        .desktop_command_status(&command_id, session_id.as_deref())
        .await?;
    output::emit(ctx.json, &resp, |resp| {
        output::ok(format!(
            "[alpha] desktop command {} status={} action={} terminal={}",
            resp.command.desktop_command_id,
            json_string(&resp.command.status),
            json_string(&resp.command.action),
            resp.terminal,
        ));
        output::info(format!(
            "tool={} capability={} shell_id={}",
            resp.command.tool_name.as_deref().unwrap_or("(unknown)"),
            json_string(&resp.command.capability),
            resp.command.shell_id,
        ));
        for event in &resp.events {
            let mut line = format!(
                "event={} type={} outcome={}",
                event.desktop_event_id,
                json_string(&event.event_type),
                event.outcome,
            );
            if let Some(code) = &event.code {
                line.push_str(&format!(" code={}", json_string(code)));
            }
            output::info(line);
        }
    });
    Ok(())
}

async fn command_stop(args: CommandStopArgs, ctx: Context) -> anyhow::Result<()> {
    let body = DesktopCommandStopRequest {
        session_id: args.session.to_string(),
        shell_id: args.shell_id,
        reason: args.reason,
    };
    let resp = ctx.client.desktop_command_stop(&body).await?;
    output::emit(ctx.json, &resp, |resp| {
        output::ok(format!(
            "[alpha] desktop stop status={} preempted_count={}",
            json_string(&resp.status),
            resp.preempted_count,
        ));
        if !resp.desktop_event_ids.is_empty() {
            output::info(format!(
                "desktop_event_ids={}",
                resp.desktop_event_ids.join(",")
            ));
        }
    });
    Ok(())
}

async fn observe_request(args: ObserveRequestArgs, ctx: Context) -> anyhow::Result<()> {
    let body = DesktopObservationRequestBody {
        session_id: args.session.to_string(),
        shell_id: args.shell_id,
        action: args.action.into(),
    };
    let resp = ctx.client.desktop_observe_request(&body).await?;
    output::emit(ctx.json, &resp, |resp| {
        output::ok(format!(
            "[alpha] desktop observe requested action={} capability={} shell_id={}",
            json_string(&resp.action),
            json_string(&resp.capability),
            resp.shell_id,
        ));
        output::info(format!(
            "down_channel_available={} event={}",
            resp.down_channel_available, resp.desktop_event_id,
        ));
        if let Some(reason) = &resp.reason {
            output::info(format!("reason={reason}"));
        }
    });
    Ok(())
}

/// Map an API error into the typed planner-safe fetch denial when it is one,
/// keeping the CLI message display-safe and stable.
fn observe_denial_message(err: &anyhow::Error) -> Option<String> {
    let core = err.downcast_ref::<CoreError>()?;
    if let CoreError::Api { body, .. } = core {
        let denial = PerceptionFetchDenial::from_error_body(body)?;
        return Some(format!(
            "denied code={} reason={}",
            json_string(&denial.code),
            denial.reason,
        ));
    }
    None
}

async fn observe_status(args: ObserveStatusArgs, ctx: Context) -> anyhow::Result<()> {
    let resp = ctx
        .client
        .desktop_observation_status(
            &args.artifact_id.to_string(),
            &args.session.to_string(),
            args.shell_id.as_deref(),
        )
        .await
        .map_err(|e| {
            let err = anyhow::Error::new(e);
            match observe_denial_message(&err) {
                Some(msg) => err.context(format!("[alpha] desktop observe status {msg}")),
                None => err,
            }
        })?;
    output::emit(ctx.json, &resp, |resp| {
        output::ok(format!(
            "[alpha] observation {} status={} redacted_available={}",
            resp.artifact_id,
            json_string(&resp.redaction_status),
            resp.redacted_available,
        ));
        output::info(format!(
            "raw_deleted={} expired={} size_bytes={} sha256={}",
            resp.raw_deleted, resp.expired, resp.size_bytes, resp.sha256,
        ));
        if let Some(expires_at) = &resp.expires_at {
            output::info(format!("expires_at={expires_at}"));
        }
        if let Some(verdict) = &resp.redaction_verdict {
            output::info(format!("redaction_verdict={verdict}"));
        }
    });
    Ok(())
}

async fn observe_fetch(args: ObserveFetchArgs, ctx: Context) -> anyhow::Result<()> {
    let data = ctx
        .client
        .desktop_observation_fetch(
            &args.artifact_id.to_string(),
            &args.session.to_string(),
            args.shell_id.as_deref(),
        )
        .await
        .map_err(|e| {
            let err = anyhow::Error::new(e);
            match observe_denial_message(&err) {
                Some(msg) => err.context(format!("[alpha] desktop observe fetch {msg}")),
                None => err,
            }
        })?;
    let sha256 = {
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new();
        hasher.update(&data);
        hasher
            .finalize()
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>()
    };
    std::fs::write(&args.out, &data)?;
    // Display-safe summary only — the planner-safe bytes go to the file, never
    // to stdout/JSON output.
    let summary = serde_json::json!({
        "artifact_id": args.artifact_id.to_string(),
        "out": args.out.display().to_string(),
        "size_bytes": data.len(),
        "sha256": sha256,
    });
    output::emit(ctx.json, &summary, |_| {
        output::ok(format!(
            "[alpha] planner-safe observation {} written to {} ({} bytes, sha256={})",
            args.artifact_id,
            args.out.display(),
            data.len(),
            sha256,
        ));
    });
    Ok(())
}

/// Map an API error into a typed grant-request denial when it is one.
fn grant_denial_message(err: &anyhow::Error) -> Option<String> {
    use agentprovision_core::desktop::DesktopGrantRequestDenial;
    let core = err.downcast_ref::<CoreError>()?;
    if let CoreError::Api { body, .. } = core {
        let denial = DesktopGrantRequestDenial::from_error_body(body)?;
        return Some(format!(
            "denied code={} reason={}",
            json_string(&denial.code),
            denial.reason,
        ));
    }
    None
}

fn emit_grant_request(ctx: &Context, resp: &agentprovision_core::desktop::DesktopGrantRequest) {
    output::emit(ctx.json, resp, |resp| {
        output::ok(format!(
            "[alpha] desktop approval request {} status={} action={}",
            resp.request_id,
            json_string(&resp.status),
            json_string(&resp.action),
        ));
        output::info(format!(
            "capability={} shell_id={} grant_present={}",
            json_string(&resp.capability),
            resp.shell_id,
            resp.grant_present,
        ));
        if let Some(bundle) = &resp.target_bundle_id {
            output::info(format!("target_bundle_id={bundle}"));
        }
        if let Some(expires_at) = &resp.expires_at {
            output::info(format!("expires_at={expires_at}"));
        }
    });
}

async fn grant_request(args: GrantRequestArgs, ctx: Context) -> anyhow::Result<()> {
    let body = DesktopGrantRequestBody {
        session_id: args.session.to_string(),
        action: args.action.into(),
        target_bundle_id: args.target_bundle_id,
        shell_id: args.shell_id,
        reason: args.reason,
    };
    let resp = ctx.client.desktop_grant_request(&body).await.map_err(|e| {
        let err = anyhow::Error::new(e);
        match grant_denial_message(&err) {
            Some(msg) => err.context(format!("[alpha] desktop grant request {msg}")),
            None => err,
        }
    })?;
    emit_grant_request(&ctx, &resp);
    Ok(())
}

async fn grant_status(args: GrantStatusArgs, ctx: Context) -> anyhow::Result<()> {
    let resp = ctx
        .client
        .desktop_grant_request_status(&args.request_id.to_string())
        .await
        .map_err(|e| {
            let err = anyhow::Error::new(e);
            match grant_denial_message(&err) {
                Some(msg) => err.context(format!("[alpha] desktop grant status {msg}")),
                None => err,
            }
        })?;
    emit_grant_request(&ctx, &resp);
    Ok(())
}

async fn enablement_get(_args: EnablementGetArgs, ctx: Context) -> anyhow::Result<()> {
    let resp = ctx.client.desktop_enablement().await?;
    emit_enablement(&ctx, &resp);
    Ok(())
}

async fn enablement_set(args: EnablementSetArgs, ctx: Context) -> anyhow::Result<()> {
    if args.background_control.is_none() {
        anyhow::bail!("pass --background-control true|false");
    }
    let body = DesktopControlEnablementUpdate {
        background_control_enabled: args.background_control,
    };
    let resp = ctx.client.update_desktop_enablement(&body).await?;
    emit_enablement(&ctx, &resp);
    Ok(())
}

async fn allowlist_get(_args: AllowlistGetArgs, ctx: Context) -> anyhow::Result<()> {
    let resp = ctx.client.desktop_allowlist().await?;
    emit_enablement(&ctx, &resp);
    Ok(())
}

async fn allowlist_set(args: AllowlistSetArgs, ctx: Context) -> anyhow::Result<()> {
    let body = DesktopControlAllowlistUpdate {
        bundle_ids: args.bundle_ids,
    };
    let resp = ctx.client.update_desktop_allowlist(&body).await?;
    emit_enablement(&ctx, &resp);
    Ok(())
}

fn emit_enablement(ctx: &Context, resp: &DesktopControlEnablement) {
    output::emit(ctx.json, resp, |resp| {
        output::ok(format!(
            "[alpha] desktop enablement desktop={} pointer={} keyboard={} background={}",
            resp.desktop_control_enabled,
            resp.pointer_control_enabled,
            resp.keyboard_control_enabled,
            resp.background_control_enabled,
        ));
        output::info(format!(
            "tenant_allowlist={}",
            list_or_empty(&resp.native_control_target_allowlist)
        ));
        output::info(format!(
            "platform_floor={}",
            list_or_empty(&resp.platform_bundle_allowlist)
        ));
        output::info(format!(
            "effective_allowlist={}",
            list_or_empty(&resp.effective_native_control_allowlist)
        ));
    });
}

fn list_or_empty(values: &[String]) -> String {
    if values.is_empty() {
        "[]".to_string()
    } else {
        values.join(",")
    }
}

fn json_string<T>(value: &T) -> String
where
    T: Serialize + std::fmt::Debug,
{
    serde_json::to_value(value)
        .ok()
        .and_then(|v| v.as_str().map(ToOwned::to_owned))
        .unwrap_or_else(|| format!("{value:?}"))
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
        Desktop {
            #[command(subcommand)]
            sub: DesktopCommand,
        },
    }

    #[test]
    fn parses_preflight_run() {
        let cli =
            TestCli::try_parse_from(["t", "desktop", "preflight", "run"]).expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Preflight(PreflightCommand::Run(_)),
            } => {}
            _ => panic!("expected desktop preflight run"),
        }
    }

    #[test]
    fn parses_dry_run_request() {
        let cli = TestCli::try_parse_from([
            "t",
            "desktop",
            "dry-run",
            "request",
            "--session",
            "33333333-3333-3333-3333-333333333333",
            "--target-bundle-id",
            "com.example.LunaCanaryTarget",
            "--window-title-pattern",
            "Luna Canary",
            "--display-id",
            "1",
        ])
        .expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::DryRun(DryRunCommand::Request(args)),
            } => {
                assert_eq!(
                    args.session.to_string(),
                    "33333333-3333-3333-3333-333333333333"
                );
                assert_eq!(args.target_bundle_id, "com.example.LunaCanaryTarget");
                assert_eq!(args.window_title_pattern.as_deref(), Some("Luna Canary"));
                assert_eq!(args.display_id, Some(1));
            }
            _ => panic!("expected desktop dry-run request"),
        }
    }

    #[test]
    fn parses_command_status() {
        let cli = TestCli::try_parse_from([
            "t",
            "desktop",
            "command",
            "status",
            "99999999-9999-9999-9999-999999999999",
            "--session",
            "33333333-3333-3333-3333-333333333333",
        ])
        .expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Command(CommandLifecycleCommand::Status(args)),
            } => {
                assert_eq!(
                    args.command_id.to_string(),
                    "99999999-9999-9999-9999-999999999999"
                );
                assert_eq!(
                    args.session
                        .as_ref()
                        .map(|session| session.to_string())
                        .as_deref(),
                    Some("33333333-3333-3333-3333-333333333333")
                );
            }
            _ => panic!("expected desktop command status"),
        }
    }

    #[test]
    fn parses_command_stop() {
        let cli = TestCli::try_parse_from([
            "t",
            "desktop",
            "command",
            "stop",
            "--session",
            "33333333-3333-3333-3333-333333333333",
            "--shell-id",
            "desktop-44444444-4444-4444-4444-444444444444",
            "--reason",
            "operator Stop",
        ])
        .expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Command(CommandLifecycleCommand::Stop(args)),
            } => {
                assert_eq!(
                    args.session.to_string(),
                    "33333333-3333-3333-3333-333333333333"
                );
                assert_eq!(
                    args.shell_id,
                    "desktop-44444444-4444-4444-4444-444444444444"
                );
                assert_eq!(args.reason, "operator Stop");
            }
            _ => panic!("expected desktop command stop"),
        }
    }

    #[test]
    fn parses_enablement_get() {
        let cli =
            TestCli::try_parse_from(["t", "desktop", "enablement", "get"]).expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Enablement(EnablementCommand::Get(_)),
            } => {}
            _ => panic!("expected desktop enablement get"),
        }
    }

    #[test]
    fn parses_enablement_set() {
        let cli = TestCli::try_parse_from([
            "t",
            "desktop",
            "enablement",
            "set",
            "--background-control",
            "true",
        ])
        .expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Enablement(EnablementCommand::Set(args)),
            } => {
                assert_eq!(args.background_control, Some(true));
            }
            _ => panic!("expected desktop enablement set"),
        }
    }

    #[test]
    fn parses_allowlist_set() {
        let cli = TestCli::try_parse_from([
            "t",
            "desktop",
            "allowlist",
            "set",
            "--bundle-id",
            "com.agentprovision.luna",
            "--bundle-id",
            "com.apple.TextEdit",
        ])
        .expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Allowlist(AllowlistCommand::Set(args)),
            } => {
                assert_eq!(
                    args.bundle_ids,
                    vec![
                        "com.agentprovision.luna".to_string(),
                        "com.apple.TextEdit".to_string()
                    ]
                );
            }
            _ => panic!("expected desktop allowlist set"),
        }
    }

    #[test]
    fn rejects_unknown_desktop_subcommand() {
        let cli = TestCli::try_parse_from(["t", "desktop", "bogus"]);
        assert!(cli.is_err(), "unknown desktop subcommand should fail clap");
    }

    #[test]
    fn parses_observe_request_with_default_action() {
        let cli = TestCli::try_parse_from([
            "t",
            "desktop",
            "observe",
            "request",
            "--session",
            "33333333-3333-3333-3333-333333333333",
        ])
        .expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Observe(ObserveCommand::Request(args)),
            } => {
                assert_eq!(
                    args.session.to_string(),
                    "33333333-3333-3333-3333-333333333333"
                );
                assert_eq!(args.action, ObserveActionArg::Screenshot);
                assert!(args.shell_id.is_none());
            }
            _ => panic!("expected desktop observe request"),
        }
    }

    #[test]
    fn parses_observe_status() {
        let cli = TestCli::try_parse_from([
            "t",
            "desktop",
            "observe",
            "status",
            "77777777-7777-7777-7777-777777777777",
            "--session",
            "33333333-3333-3333-3333-333333333333",
            "--shell-id",
            "desktop-44444444-4444-4444-4444-444444444444",
        ])
        .expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Observe(ObserveCommand::Status(args)),
            } => {
                assert_eq!(
                    args.artifact_id.to_string(),
                    "77777777-7777-7777-7777-777777777777"
                );
                assert_eq!(
                    args.session.to_string(),
                    "33333333-3333-3333-3333-333333333333"
                );
                assert_eq!(
                    args.shell_id.as_deref(),
                    Some("desktop-44444444-4444-4444-4444-444444444444")
                );
            }
            _ => panic!("expected desktop observe status"),
        }
    }

    #[test]
    fn parses_observe_fetch_and_requires_out() {
        let cli = TestCli::try_parse_from([
            "t",
            "desktop",
            "observe",
            "fetch",
            "77777777-7777-7777-7777-777777777777",
            "--session",
            "33333333-3333-3333-3333-333333333333",
            "--out",
            "/tmp/redacted.png",
        ])
        .expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Observe(ObserveCommand::Fetch(args)),
            } => {
                assert_eq!(
                    args.artifact_id.to_string(),
                    "77777777-7777-7777-7777-777777777777"
                );
                assert_eq!(args.out, PathBuf::from("/tmp/redacted.png"));
            }
            _ => panic!("expected desktop observe fetch"),
        }

        // --out is required: the planner-safe bytes must go to a file, never stdout.
        let missing_out = TestCli::try_parse_from([
            "t",
            "desktop",
            "observe",
            "fetch",
            "77777777-7777-7777-7777-777777777777",
            "--session",
            "33333333-3333-3333-3333-333333333333",
        ]);
        assert!(missing_out.is_err(), "observe fetch must require --out");
    }

    #[test]
    fn observe_denial_maps_typed_fetch_denials_only() {
        let api_err = anyhow::Error::new(CoreError::Api {
            status: 409,
            body: r#"{"detail": {"code": "artifact_not_planner_safe", "reason": "perception artifact is not planner-safe"}}"#.to_string(),
        });
        let msg = observe_denial_message(&api_err).expect("typed denial");
        assert!(msg.contains("artifact_not_planner_safe"));

        let other_err = anyhow::Error::new(CoreError::Api {
            status: 404,
            body: r#"{"detail": "Session not found"}"#.to_string(),
        });
        assert!(observe_denial_message(&other_err).is_none());
    }

    #[test]
    fn parses_grant_request() {
        let cli = TestCli::try_parse_from([
            "t",
            "desktop",
            "grant",
            "request",
            "--session",
            "33333333-3333-3333-3333-333333333333",
            "--action",
            "keyboard-type",
            "--target-bundle-id",
            "net.whatsapp.WhatsApp",
            "--reason",
            "send a message",
        ])
        .expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Grant(GrantCommand::Request(args)),
            } => {
                assert_eq!(
                    args.session.to_string(),
                    "33333333-3333-3333-3333-333333333333"
                );
                assert_eq!(args.action, GrantActionArg::KeyboardType);
                assert_eq!(args.target_bundle_id, "net.whatsapp.WhatsApp");
                assert_eq!(args.reason.as_deref(), Some("send a message"));
            }
            _ => panic!("expected desktop grant request"),
        }
    }

    #[test]
    fn grant_request_rejects_non_native_action() {
        // Observe/dry-run actions are not in the requestable value-enum.
        let bad = TestCli::try_parse_from([
            "t",
            "desktop",
            "grant",
            "request",
            "--session",
            "33333333-3333-3333-3333-333333333333",
            "--action",
            "capture-screenshot",
            "--target-bundle-id",
            "net.whatsapp.WhatsApp",
        ]);
        assert!(bad.is_err(), "non-native action must fail clap");
    }

    #[test]
    fn parses_grant_status() {
        let cli = TestCli::try_parse_from([
            "t",
            "desktop",
            "grant",
            "status",
            "55555555-5555-5555-5555-555555555555",
        ])
        .expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Grant(GrantCommand::Status(args)),
            } => {
                assert_eq!(
                    args.request_id.to_string(),
                    "55555555-5555-5555-5555-555555555555"
                );
            }
            _ => panic!("expected desktop grant status"),
        }
    }

    #[test]
    fn grant_denial_maps_typed_denials_only() {
        let api_err = anyhow::Error::new(CoreError::Api {
            status: 422,
            body: r#"{"detail": {"code": "action_not_requestable", "reason": "x"}}"#.to_string(),
        });
        assert!(grant_denial_message(&api_err)
            .expect("typed denial")
            .contains("action_not_requestable"));

        let other = anyhow::Error::new(CoreError::Api {
            status: 404,
            body: r#"{"detail": "Session not found"}"#.to_string(),
        });
        assert!(grant_denial_message(&other).is_none());
    }
}
