//! Top-level clap definitions + dispatch.

use clap::{Parser, Subcommand};

use crate::commands::{chat, login, logout, status};
use crate::context::Context;

#[derive(Debug, Parser)]
#[command(
    name = "agentprovision",
    version,
    about = "Command-line client for the AgentProvision platform.",
    long_about = "Login, chat, run workflows, and orchestrate agents from your terminal.\n\nDocs: https://agentprovision.com/docs/cli"
)]
pub struct Cli {
    /// Override the API server URL (defaults to https://agentprovision.com or `server` from config.toml).
    #[arg(long, global = true, env = "AGENTPROVISION_SERVER")]
    pub server: Option<String>,

    // PR #332 review Critical #3: a `--tenant` flag was removed before
    // initial ship. None of the user-facing subcommands in this PR
    // (login/logout/status/chat) consume `X-Tenant-Id` — it's an
    // MCP-server header. Shipping the flag would have given users a
    // silent no-op and a false sense of multi-tenancy support. The
    // tenant override will return in PR-C alongside the first
    // subcommand that actually needs it (e.g. `tenant switch`).
    /// Emit machine-readable JSON instead of pretty output.
    #[arg(long, global = true)]
    pub json: bool,

    /// Disable streaming chat responses; wait for the full reply.
    #[arg(long, global = true)]
    pub no_stream: bool,

    /// Increase verbosity; -v info, -vv debug. Logs go to stderr.
    #[arg(short, long, global = true, action = clap::ArgAction::Count)]
    pub verbose: u8,

    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Authenticate with AgentProvision. Stores the bearer token in the OS keychain.
    Login(login::LoginArgs),

    /// Remove the stored token from the OS keychain.
    Logout,

    /// Show the current user, tenant, server, and CLI version.
    Status,

    /// Chat with the default agent. Run without subcommand for an interactive REPL.
    #[command(subcommand)]
    Chat(ChatCommand),
}

#[derive(Debug, Subcommand)]
pub enum ChatCommand {
    /// Send a one-shot prompt and stream the reply.
    Send(chat::SendArgs),
    /// Open an interactive REPL.
    Repl(chat::ReplArgs),
}

pub async fn dispatch(args: Cli, ctx: Context) -> anyhow::Result<()> {
    match args.command {
        Command::Login(a) => login::run(a, ctx).await,
        Command::Logout => logout::run(ctx).await,
        Command::Status => status::run(ctx).await,
        Command::Chat(ChatCommand::Send(a)) => chat::send(a, ctx).await,
        Command::Chat(ChatCommand::Repl(a)) => chat::repl(a, ctx).await,
    }
}
