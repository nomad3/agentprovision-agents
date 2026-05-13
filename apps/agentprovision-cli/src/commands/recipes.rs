//! `alpha recipes` — install + run pre-built dynamic workflows.
//!
//! Phase 3 of the CLI roadmap (#180) closer — the "Helm charts for
//! AI workflows" surface. Thin wrapper around the existing
//! `dynamic_workflows` endpoints:
//!
//!   `alpha recipes ls`            → GET /api/v1/dynamic-workflows/templates/browse
//!   `alpha recipes describe <id>` → GET /api/v1/dynamic-workflows/{id}
//!   `alpha recipes install <id>`  → POST /api/v1/dynamic-workflows/templates/{id}/install
//!   `alpha recipes run <id> [--dry-run]` → install (if needed) + POST /{id}/run
//!
//! Scheduling (`--schedule CRON`) and `uninstall` are deferred — they
//! land alongside the trigger-config write path in a follow-up. Today
//! users delete an installed recipe via `alpha workflow delete <id>`.

use clap::{Args, Subcommand};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::context::Context;
use crate::output;

#[derive(Debug, Args)]
pub struct RecipesArgs {
    #[command(subcommand)]
    pub command: RecipesCommand,
}

#[derive(Debug, Subcommand)]
pub enum RecipesCommand {
    /// List available recipe templates (native + community). Each row
    /// is one template you can install with `alpha recipes install`.
    Ls(LsArgs),
    /// Show one recipe's metadata, definition, and required
    /// integrations. Useful before installing to a tenant.
    Describe(DescribeArgs),
    /// Install a recipe template into the caller's tenant. Returns
    /// the installed workflow id, which `alpha workflow` then manages.
    Install(InstallArgs),
    /// Install (if not already installed) + dispatch a one-shot run.
    /// Use `--dry-run` to validate without executing.
    Run(RunArgs),
}

#[derive(Debug, Args)]
pub struct LsArgs {
    /// Filter by tier: `native` (ships with the platform) or
    /// `community` (curated third-party). Default shows both.
    #[arg(long, value_parser = ["native", "community"])]
    pub tier: Option<String>,
}

#[derive(Debug, Args)]
pub struct DescribeArgs {
    /// Template UUID. Find with `alpha recipes ls`.
    pub recipe: Uuid,
}

#[derive(Debug, Args)]
pub struct InstallArgs {
    /// Template UUID to install. Source remains read-only; an
    /// independent copy is created under your tenant.
    pub recipe: Uuid,
}

#[derive(Debug, Args)]
pub struct RunArgs {
    /// Template UUID OR an already-installed workflow UUID. The CLI
    /// auto-detects: if the row is a template (`tier in [native,
    /// community]`), it installs first.
    pub recipe: Uuid,
    /// Validate the workflow without dispatching it. Wraps the
    /// server's existing dry-run path.
    #[arg(long)]
    pub dry_run: bool,
}

#[derive(Debug, Deserialize, Serialize)]
struct TemplateRow {
    id: Uuid,
    name: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    tier: Option<String>,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    installs: Option<i64>,
}

#[derive(Debug, Deserialize, Serialize)]
struct InstalledWorkflow {
    id: Uuid,
    name: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    tier: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
struct WorkflowDetail {
    id: Uuid,
    name: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    tier: Option<String>,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    definition: Option<Value>,
    #[serde(default)]
    trigger_config: Option<Value>,
    #[serde(default)]
    installs: Option<i64>,
}

#[derive(Debug, Deserialize, Serialize)]
struct RunResponse {
    id: Uuid,
    status: String,
    #[serde(default)]
    error: Option<String>,
}

pub async fn run(args: RecipesArgs, ctx: Context) -> anyhow::Result<()> {
    match args.command {
        RecipesCommand::Ls(a) => ls(a, ctx).await,
        RecipesCommand::Describe(a) => describe(a, ctx).await,
        RecipesCommand::Install(a) => install(a, ctx).await,
        RecipesCommand::Run(a) => run_recipe(a, ctx).await,
    }
}

async fn ls(args: LsArgs, ctx: Context) -> anyhow::Result<()> {
    let path = match args.tier {
        Some(t) => format!("/api/v1/dynamic-workflows/templates/browse?tier={t}"),
        None => "/api/v1/dynamic-workflows/templates/browse".to_string(),
    };
    let rows: Vec<TemplateRow> = ctx.client.get_json(&path).await?;
    if ctx.json {
        crate::output::emit(true, &rows, |_| {});
        return Ok(());
    }
    if rows.is_empty() {
        output::info("[alpha] no recipes available.");
        return Ok(());
    }
    println!(
        "{:<38}  {:<10}  {:<8}  {:<28}  {}",
        "id", "tier", "installs", "name", "description"
    );
    println!("{}", "-".repeat(120));
    for r in &rows {
        let tier = r.tier.as_deref().unwrap_or("—");
        let installs = r
            .installs
            .map(|n| n.to_string())
            .unwrap_or_else(|| "—".into());
        let desc = r
            .description
            .as_deref()
            .unwrap_or("")
            .chars()
            .take(50)
            .collect::<String>();
        let name = truncate(&r.name, 28);
        println!(
            "{:<38}  {tier:<10}  {installs:<8}  {name:<28}  {desc}",
            r.id
        );
    }
    Ok(())
}

async fn describe(args: DescribeArgs, ctx: Context) -> anyhow::Result<()> {
    let path = format!("/api/v1/dynamic-workflows/{}", args.recipe);
    let wf: WorkflowDetail = ctx.client.get_json(&path).await?;
    if ctx.json {
        crate::output::emit(true, &wf, |_| {});
        return Ok(());
    }
    println!(
        "{} ({}) — tier={}, installs={}",
        wf.name,
        wf.id,
        wf.tier.as_deref().unwrap_or("—"),
        wf.installs
            .map(|n| n.to_string())
            .unwrap_or_else(|| "—".into()),
    );
    if let Some(d) = &wf.description {
        println!("\n{d}");
    }
    if !wf.tags.is_empty() {
        println!("\nTags: {}", wf.tags.join(", "));
    }
    if let Some(def) = &wf.definition {
        // Surface the step count + required integrations without
        // pretty-printing the whole definition. Pipe `--json | jq`
        // for the full shape.
        let steps = def.get("steps").and_then(|s| s.as_array()).map(|a| a.len());
        if let Some(n) = steps {
            println!("\nSteps: {n}");
        }
        let integrations = def
            .get("required_integrations")
            .and_then(|i| i.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            });
        if let Some(s) = integrations {
            if !s.is_empty() {
                println!("Required integrations: {s}");
            }
        }
    }
    Ok(())
}

async fn install(args: InstallArgs, ctx: Context) -> anyhow::Result<()> {
    let path = format!(
        "/api/v1/dynamic-workflows/templates/{}/install",
        args.recipe
    );
    let installed: InstalledWorkflow = ctx.client.post_json(&path, &serde_json::json!({})).await?;
    if ctx.json {
        crate::output::emit(true, &installed, |_| {});
        return Ok(());
    }
    output::ok(format!(
        "[alpha] installed recipe '{}' → workflow {}",
        installed.name, installed.id
    ));
    output::info("dispatch with: alpha workflow run <id>  or `alpha recipes run <id>`");
    Ok(())
}

async fn run_recipe(args: RunArgs, ctx: Context) -> anyhow::Result<()> {
    // Detect: is this a template (tier in [native, community])
    // or an already-installed custom workflow? Fetching the row
    // tells us.
    let detail_path = format!("/api/v1/dynamic-workflows/{}", args.recipe);
    let wf: WorkflowDetail = ctx.client.get_json(&detail_path).await?;

    let target_id = match wf.tier.as_deref() {
        Some("native") | Some("community") => {
            // It's a template — install first, then dispatch the copy.
            let install_path = format!(
                "/api/v1/dynamic-workflows/templates/{}/install",
                args.recipe
            );
            let installed: InstalledWorkflow =
                ctx.client.post_json(&install_path, &json!({})).await?;
            if !ctx.json {
                output::ok(format!(
                    "[alpha] installed '{}' → {}",
                    installed.name, installed.id
                ));
            }
            installed.id
        }
        _ => args.recipe,
    };

    let run_path = format!("/api/v1/dynamic-workflows/{target_id}/run");
    let body = json!({"dry_run": args.dry_run});
    let resp: RunResponse = ctx.client.post_json(&run_path, &body).await?;
    if ctx.json {
        crate::output::emit(true, &resp, |_| {});
        return Ok(());
    }
    let mode = if args.dry_run {
        "dry-run"
    } else {
        "dispatched"
    };
    output::ok(format!(
        "[alpha] {mode} run {} — status: {}",
        resp.id, resp.status
    ));
    if let Some(err) = resp.error {
        output::warn(format!("error: {err}"));
    }
    Ok(())
}

fn truncate(s: &str, keep: usize) -> String {
    if s.chars().count() <= keep {
        return s.to_string();
    }
    let head: String = s.chars().take(keep.saturating_sub(1)).collect();
    format!("{head}…")
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
        #[command(subcommand)]
        Recipes(RecipesCommand),
    }

    fn parse(args: &[&str]) -> RecipesCommand {
        let cli = TestCli::try_parse_from(args).expect("clap parse");
        match cli.cmd {
            TestCmd::Recipes(c) => c,
        }
    }

    #[test]
    fn parses_ls_no_tier() {
        let cmd = parse(&["test", "recipes", "ls"]);
        if let RecipesCommand::Ls(a) = cmd {
            assert!(a.tier.is_none());
        } else {
            panic!("expected Ls variant");
        }
    }

    #[test]
    fn parses_ls_native_tier() {
        let cmd = parse(&["test", "recipes", "ls", "--tier", "native"]);
        if let RecipesCommand::Ls(a) = cmd {
            assert_eq!(a.tier.as_deref(), Some("native"));
        } else {
            panic!("expected Ls variant");
        }
    }

    #[test]
    fn rejects_invalid_tier() {
        let cli = TestCli::try_parse_from(["test", "recipes", "ls", "--tier", "junk"]);
        assert!(cli.is_err(), "clap should gate on the value_parser enum");
    }

    #[test]
    fn parses_describe_uuid() {
        let uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
        let cmd = parse(&["test", "recipes", "describe", uuid]);
        if let RecipesCommand::Describe(a) = cmd {
            assert_eq!(a.recipe.to_string(), uuid);
        } else {
            panic!("expected Describe variant");
        }
    }

    #[test]
    fn parses_install_uuid() {
        let uuid = "11111111-2222-3333-4444-555555555555";
        let cmd = parse(&["test", "recipes", "install", uuid]);
        if let RecipesCommand::Install(a) = cmd {
            assert_eq!(a.recipe.to_string(), uuid);
        } else {
            panic!("expected Install variant");
        }
    }

    #[test]
    fn parses_run_dry_run() {
        let uuid = "11111111-2222-3333-4444-555555555555";
        let cmd = parse(&["test", "recipes", "run", uuid, "--dry-run"]);
        if let RecipesCommand::Run(a) = cmd {
            assert_eq!(a.recipe.to_string(), uuid);
            assert!(a.dry_run);
        } else {
            panic!("expected Run variant");
        }
    }

    #[test]
    fn truncate_keeps_short_unchanged() {
        assert_eq!(truncate("daily-briefing", 28), "daily-briefing");
    }

    #[test]
    fn truncate_respects_keep() {
        let out = truncate("very-very-very-long-recipe-name", 10);
        assert_eq!(out.chars().count(), 10);
        assert!(out.ends_with('…'));
    }
}
