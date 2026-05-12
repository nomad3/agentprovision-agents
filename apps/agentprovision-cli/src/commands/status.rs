//! `ap status` — show the current user, tenant, server, and (with
//! `--runtimes`) the preflight matrix for the four CLI runtimes the
//! platform can dispatch locally.

use agentprovision_core::runtime::{preflight_all, PreflightReport, RuntimeId};
use clap::Args;
use serde::Serialize;

use crate::context::Context;

#[derive(Debug, Args)]
pub struct StatusArgs {
    /// Include a preflight matrix for the four CLI runtimes the platform
    /// orchestrates locally (Claude Code, Codex, Gemini CLI, Copilot CLI).
    /// Runs four `--version` subprocesses, so opt-in — the default
    /// `ap status` stays a single API round-trip.
    #[arg(long)]
    pub runtimes: bool,
}

#[derive(Serialize)]
struct Status {
    server: String,
    cli_version: &'static str,
    authenticated: bool,
    /// Human-readable name of the active token-store backend ("OS keychain"
    /// or "token file"). Useful when debugging why a session looks logged
    /// out — common cause is the keychain probe falling back to file.
    token_store: &'static str,
    user: Option<UserSummary>,
    #[serde(skip_serializing_if = "Option::is_none")]
    runtimes: Option<Vec<RuntimePreflight>>,
}

#[derive(Serialize)]
struct UserSummary {
    id: String,
    email: String,
    full_name: Option<String>,
    tenant_id: Option<String>,
    is_superuser: bool,
}

/// Wire shape for the runtime preflight matrix. Mirrors core's
/// `PreflightReport` but with String paths (PathBuf serializes to a
/// platform-tagged enum that's awkward in CLI JSON output).
#[derive(Serialize)]
struct RuntimePreflight {
    runtime: &'static str,
    binary: Option<String>,
    version: Option<String>,
    local_auth: bool,
    install_hint: &'static str,
}

impl From<PreflightReport> for RuntimePreflight {
    fn from(r: PreflightReport) -> Self {
        Self {
            runtime: r.runtime.as_wire(),
            binary: r.binary_path.map(|p| p.display().to_string()),
            version: r.version,
            local_auth: r.local_auth_present,
            install_hint: r.install_hint,
        }
    }
}

pub async fn run(ctx: Context, show_runtimes: bool) -> anyhow::Result<()> {
    let authenticated = ctx.client.token().is_some();
    let user = if authenticated {
        match ctx.client.current_user().await {
            Ok(u) => Some(UserSummary {
                id: u.id.to_string(),
                email: u.email,
                full_name: u.full_name,
                tenant_id: u.tenant_id.map(|x| x.to_string()),
                is_superuser: u.is_superuser,
            }),
            Err(_) => None,
        }
    } else {
        None
    };

    // Runtime preflight is opt-in (`--runtimes`) so the default `ap status`
    // stays a sub-200ms round-trip. Spawning five `--version` subprocesses
    // (one per supported CLI runtime) adds ~100-400ms depending on shell
    // init cost, which is annoying for users who just want to confirm auth.
    let runtimes = if show_runtimes {
        let _ = RuntimeId::all; // explicit dependency on the enum
        Some(preflight_all().into_iter().map(Into::into).collect())
    } else {
        None
    };

    let payload = Status {
        server: ctx.server.clone(),
        cli_version: env!("CARGO_PKG_VERSION"),
        authenticated: user.is_some(),
        token_store: ctx.token_store_kind.human(),
        user,
        runtimes,
    };

    crate::output::emit(ctx.json, &payload, |s| {
        let style_h = |t: &str| console::style(t).bold().to_string();
        println!("{}: {}", style_h("server"), s.server);
        println!("{}: {}", style_h("cli"), s.cli_version);
        println!("{}: {}", style_h("token store"), s.token_store);
        println!(
            "{}: {}",
            style_h("authenticated"),
            if s.authenticated { "yes" } else { "no" }
        );
        if let Some(u) = &s.user {
            println!(
                "{}: {} <{}>",
                style_h("user"),
                u.full_name.clone().unwrap_or_else(|| "—".into()),
                u.email
            );
            println!(
                "{}: {}",
                style_h("tenant"),
                u.tenant_id.clone().unwrap_or_else(|| "—".into())
            );
        }
        if let Some(rt) = &s.runtimes {
            println!();
            println!("{}", style_h("runtimes"));
            // Fixed-width columns over a table crate — keeps the binary
            // smaller and the output greppable. 14 chars covers
            // "gemini_cli" plus a margin; 8 chars covers the on/off
            // "yes/no" auth column.
            println!(
                "  {:<14} {:<8} {:<12} {}",
                "runtime", "auth", "version", "binary"
            );
            for r in rt {
                let auth = if r.local_auth { "yes" } else { "—" };
                let ver = r.version.as_deref().unwrap_or("—");
                let bin = r.binary.as_deref().unwrap_or("not found — see hint");
                println!("  {:<14} {:<8} {:<12} {}", r.runtime, auth, ver, bin);
            }
            // Show install hints only for the missing ones; suppresses
            // noise when the user already has everything installed.
            let missing: Vec<_> = rt.iter().filter(|r| r.binary.is_none()).collect();
            if !missing.is_empty() {
                println!();
                for r in missing {
                    println!("  {} {}: {}", style_h("hint"), r.runtime, r.install_hint);
                }
            }
        }
    });
    Ok(())
}
