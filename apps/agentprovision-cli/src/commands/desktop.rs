//! `alpha desktop` — operator-facing desktop-control (Luna macOS computer-use)
//! inspection verbs.
//!
//! Per the Alpha CLI kernel principle these delegate to the internal API
//! (`GET /api/v1/desktop-control/...`) and the same service entrypoints the
//! web/Tauri viewports call — they never actuate input or flip a capability.

use clap::{Args, Subcommand};

use crate::context::Context;
use crate::output;

#[derive(Debug, Subcommand)]
pub enum DesktopCommand {
    /// Validate the desktop-control envelope signing config (operator
    /// fail-fast surface). Superuser-only server-side.
    #[command(subcommand)]
    Preflight(PreflightCommand),
}

#[derive(Debug, Subcommand)]
pub enum PreflightCommand {
    /// Run the preflight and print the result.
    Run(PreflightRunArgs),
}

#[derive(Debug, Args)]
pub struct PreflightRunArgs {}

pub async fn dispatch(cmd: DesktopCommand, ctx: Context) -> anyhow::Result<()> {
    match cmd {
        DesktopCommand::Preflight(PreflightCommand::Run(a)) => preflight_run(a, ctx).await,
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
        let cli = TestCli::try_parse_from(["t", "desktop", "preflight", "run"]).expect("clap parse");
        match cli.cmd {
            TestCmd::Desktop {
                sub: DesktopCommand::Preflight(PreflightCommand::Run(_)),
            } => {}
        }
    }

    #[test]
    fn rejects_unknown_desktop_subcommand() {
        let cli = TestCli::try_parse_from(["t", "desktop", "bogus"]);
        assert!(cli.is_err(), "unknown desktop subcommand should fail clap");
    }
}
