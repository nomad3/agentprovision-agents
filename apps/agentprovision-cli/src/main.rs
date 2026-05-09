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
    // PR #332 review Critical #1 fix: scope the verbose filter to our
    // own crates only, and pin reqwest/hyper to `warn` regardless of
    // -v count. Without this scoping, `-vv` flips reqwest+hyper into
    // `debug` which logs request/response bodies including the
    // `Authorization: Bearer …` header — that's the CLI's most
    // sensitive secret leaking to stderr.
    let filter = format!(
        "agentprovision_cli={lvl},agentprovision_core={lvl},reqwest=warn,hyper=warn",
        lvl = log_level
    );
    let _ = env_logger::Builder::from_env(env_logger::Env::default().default_filter_or(&filter))
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
