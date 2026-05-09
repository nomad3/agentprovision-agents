//! `agentprovision` CLI entry point.
//!
//! Skeleton baseline (PR-B): login / logout / status / chat / chat send.
//! Subcommand expansion (agent, workflow, integration, ...) lands in PR-C.

mod cli;
mod commands;
mod context;
mod output;

use clap::Parser;

#[tokio::main]
async fn main() {
    let args = cli::Cli::parse();

    // -v/-vv on the global args bumps env_logger.
    let log_level = match args.verbose {
        0 => "warn",
        1 => "info",
        _ => "debug",
    };
    let _ = env_logger::Builder::from_env(env_logger::Env::default().default_filter_or(log_level))
        .target(env_logger::Target::Stderr)
        .try_init();

    if let Err(e) = run(args).await {
        eprintln!("{} {}", console::style("error:").red().bold(), e);
        std::process::exit(1);
    }
}

async fn run(args: cli::Cli) -> anyhow::Result<()> {
    let ctx = context::Context::new(&args).await?;
    cli::dispatch(args, ctx).await
}
