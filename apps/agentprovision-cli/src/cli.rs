//! Top-level clap definitions + dispatch.

use clap::{Parser, Subcommand};

use crate::commands::{
    agent, cancel, chat, completions, integration, login, logout, memory, quickstart, run,
    session, skill, status, upgrade, watch, workflow,
};
use crate::context::Context;

#[derive(Debug, Parser)]
#[command(
    name = "ap",
    version,
    about = "AgentProvision CLI — orchestrator of CLIs.",
    long_about = "ap — the AgentProvision command-line client. Login, chat, run workflows, and orchestrate agents (Claude Code / Codex / Gemini CLI / Copilot) from your terminal.\n\nDocs: https://agentprovision.com/docs/cli"
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

    /// Show the current user, tenant, server, and CLI version. With
    /// `--runtimes`, also reports preflight status for Claude Code,
    /// Codex, Gemini CLI, and Copilot CLI.
    Status(status::StatusArgs),

    /// Chat with the default agent. Run without subcommand for an interactive REPL.
    #[command(subcommand)]
    Chat(ChatCommand),

    /// Dispatch a durable task. Supports multi-provider fanout
    /// (`--fanout claude,codex,gemini --merge council`), fallback
    /// chains (`--providers claude,codex,opencode`), and background
    /// execution (`--background` + later `ap watch <id>`).
    ///
    /// Phase 1 prototype — see
    /// docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md.
    Run(run::RunArgs),

    /// Tail an in-flight task's status from any machine. Pairs with
    /// `ap run --background` for fire-and-forget then later resume.
    Watch(watch::WatchArgs),

    /// Cancel an in-flight task. For fanout tasks, both the parent
    /// and all child workflows are cancelled — pass the parent
    /// task_id only; child workflows are cancelled automatically
    /// by the backend cascade. Best-effort under Temporal: the
    /// leaf CLI subprocess may take seconds to observe the signal.
    Cancel(cancel::CancelArgs),

    /// Self-update the `ap` binary from GitHub Releases.
    Upgrade(upgrade::UpgradeArgs),

    /// List and inspect agents in the current tenant.
    #[command(subcommand)]
    Agent(agent::AgentCommand),

    /// List, inspect, run, and tail dynamic workflows.
    #[command(subcommand)]
    Workflow(workflow::WorkflowCommand),

    /// List recent chat sessions and read their message history.
    #[command(subcommand)]
    Session(session::SessionCommand),

    /// Inspect integration connection status for the current tenant.
    #[command(subcommand)]
    Integration(integration::IntegrationCommand),

    /// Browse the file-based skill library.
    #[command(subcommand)]
    Skill(skill::SkillCommand),

    /// Browse and search the tenant's knowledge graph (entities).
    #[command(subcommand)]
    Memory(memory::MemoryCommand),

    /// Guided initial-training flow. Auto-fires the first time you
    /// `ap login` against a fresh tenant; can be re-run explicitly to
    /// re-train (with `--force`) or to opt back in after Skip.
    Quickstart(quickstart::QuickstartArgs),

    /// Emit shell completion script (bash / zsh / fish / powershell / elvish).
    Completions(completions::CompletionsArgs),
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
        Command::Status(a) => status::run(ctx, a.runtimes).await,
        Command::Chat(ChatCommand::Send(a)) => chat::send(a, ctx).await,
        Command::Chat(ChatCommand::Repl(a)) => chat::repl(a, ctx).await,
        Command::Run(a) => run::run(a, ctx).await,
        Command::Watch(a) => watch::run(a, ctx).await,
        Command::Cancel(a) => cancel::run(a, ctx).await,
        Command::Upgrade(a) => upgrade::run(a, ctx).await,
        Command::Agent(cmd) => agent::dispatch(cmd, ctx).await,
        Command::Workflow(cmd) => workflow::dispatch(cmd, ctx).await,
        Command::Session(cmd) => session::dispatch(cmd, ctx).await,
        Command::Integration(cmd) => integration::dispatch(cmd, ctx).await,
        Command::Skill(cmd) => skill::dispatch(cmd, ctx).await,
        Command::Memory(cmd) => memory::dispatch(cmd, ctx).await,
        Command::Quickstart(a) => quickstart::run(a, ctx).await,
        Command::Completions(a) => completions::run(a, ctx).await,
    }
}
