//! `alpha desktop` — operator-facing desktop-control (Luna macOS computer-use)
//! inspection verbs.
//!
//! Per the Alpha CLI kernel principle these delegate to the internal API
//! (`GET /api/v1/desktop-control/...`) and the same service entrypoints the
//! web/Tauri viewports call — they never actuate input locally.

use clap::{Args, Subcommand};

use agentprovision_core::desktop::{
    DesktopActionKind, DesktopBackgroundDryRunRequest, DesktopBackgroundDryRunTarget,
    DesktopControlAllowlistUpdate, DesktopControlEnablement, DesktopControlEnablementUpdate,
};
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
}

#[derive(Debug, Args)]
pub struct CommandStatusArgs {
    /// Desktop command UUID.
    pub command_id: Uuid,
    /// Optional chat/session UUID to tighten the status lookup.
    #[arg(long)]
    pub session: Option<Uuid>,
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
}
