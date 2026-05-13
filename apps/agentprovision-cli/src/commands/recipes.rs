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

// `Serialize` derives on the response structs below are intentional
// even though we only deserialize from the wire — they're re-emitted
// verbatim via `crate::output::emit` when `--json` is set. Drop the
// derive only if `--json` passthrough goes away for this command.
// Reviewer NIT N1 on PR #447.

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
    #[serde(default)]
    source_template_id: Option<Uuid>,
}

#[derive(Debug, Deserialize, Serialize)]
struct InstalledWorkflow {
    id: Uuid,
    name: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    tier: Option<String>,
    #[serde(default)]
    source_template_id: Option<Uuid>,
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
    #[serde(default)]
    source_template_id: Option<Uuid>,
}

/// Preview shape from `GET /{workflow_id}/preview`. Surface for the
/// description-time integration list (reviewer I2). Server derives
/// these via `validate_workflow_definition`.
#[derive(Debug, Deserialize, Serialize)]
struct WorkflowPreview {
    #[serde(default)]
    steps_planned: Vec<String>,
    #[serde(default)]
    integrations_required: Vec<String>,
    #[serde(default)]
    validation_errors: Vec<String>,
    #[serde(default)]
    step_count: u32,
}

/// Real-run response: matches `WorkflowRunInDB` (id + status + ...).
#[derive(Debug, Deserialize, Serialize)]
struct RunResponse {
    id: Uuid,
    status: String,
    #[serde(default)]
    error: Option<String>,
}

/// Dry-run response: server bypasses `response_model=WorkflowRunInDB`
/// and returns `{dry_run, workflow_id, steps_planned, ...}` — no `id`
/// and no `status`. Locked by reviewer B1 on PR #447.
#[derive(Debug, Deserialize, Serialize)]
struct DryRunResponse {
    #[serde(default)]
    dry_run: bool,
    workflow_id: Uuid,
    #[serde(default)]
    steps_planned: Vec<String>,
    #[serde(default)]
    integrations_required: Vec<String>,
    #[serde(default)]
    validation_errors: Vec<String>,
    #[serde(default)]
    step_count: u32,
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
    // Required integrations and step count are NOT carried on the
    // template `definition` directly — they're derived at validation
    // time by walking `steps[].tool` through TOOL_INTEGRATION_MAP.
    // Hit the server-side preview endpoint to surface them honestly.
    // Reviewer IMPORTANT I2 on PR #447.
    let preview_path = format!("/api/v1/dynamic-workflows/{}/preview", args.recipe);
    let preview: WorkflowPreview = ctx.client.get_json(&preview_path).await?;
    if preview.step_count > 0 {
        println!("\nSteps: {}", preview.step_count);
    }
    if !preview.integrations_required.is_empty() {
        println!(
            "Required integrations: {}",
            preview.integrations_required.join(", ")
        );
    }
    if !preview.validation_errors.is_empty() {
        output::warn(format!(
            "validation errors: {}",
            preview.validation_errors.join("; ")
        ));
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
    output::info("dispatch with `alpha workflow run <id>` or `alpha recipes run <id>`");
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
            // Reviewer I1: dedupe before installing. Check whether the
            // tenant already has a copy of this template. If yes,
            // reuse it instead of creating a fresh clone — otherwise
            // every `recipes run` clutters `alpha workflow ls` and
            // inflates the template's `installs` counter falsely.
            let installed_list: Vec<InstalledWorkflow> =
                ctx.client.get_json("/api/v1/dynamic-workflows").await?;
            let existing = installed_list
                .iter()
                .find(|w| w.source_template_id == Some(args.recipe));
            if let Some(found) = existing {
                if !ctx.json {
                    output::info(format!(
                        "[alpha] reusing existing install '{}' → {}",
                        found.name, found.id
                    ));
                }
                found.id
            } else {
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
        }
        _ => args.recipe,
    };

    let run_path = format!("/api/v1/dynamic-workflows/{target_id}/run");
    let body = json!({"dry_run": args.dry_run});

    // Reviewer B1: the dry-run path returns a different shape
    // (no `id`, no `status`; instead steps_planned/validation_errors).
    // Branch the deserialize so this doesn't 422 client-side.
    if args.dry_run {
        let resp: DryRunResponse = ctx.client.post_json(&run_path, &body).await?;
        if ctx.json {
            crate::output::emit(true, &resp, |_| {});
            return Ok(());
        }
        output::ok(format!(
            "[alpha] dry-run validated — {} steps for workflow {}",
            resp.step_count, resp.workflow_id
        ));
        if !resp.integrations_required.is_empty() {
            output::info(format!(
                "required integrations: {}",
                resp.integrations_required.join(", ")
            ));
        }
        if !resp.validation_errors.is_empty() {
            output::warn(format!(
                "validation errors: {}",
                resp.validation_errors.join("; ")
            ));
        }
        return Ok(());
    }

    let resp: RunResponse = ctx.client.post_json(&run_path, &body).await?;
    if ctx.json {
        crate::output::emit(true, &resp, |_| {});
        return Ok(());
    }
    output::ok(format!(
        "[alpha] dispatched run {} — status: {}",
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
    fn parses_run_no_flags_defaults_dry_run_false() {
        let uuid = "11111111-2222-3333-4444-555555555555";
        let cmd = parse(&["test", "recipes", "run", uuid]);
        if let RecipesCommand::Run(a) = cmd {
            assert_eq!(a.recipe.to_string(), uuid);
            assert!(!a.dry_run, "default for --dry-run should be false");
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
