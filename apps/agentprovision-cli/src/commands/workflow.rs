//! `ap workflow` — list / show / run dynamic workflows.
//!
//! Matches the web `WorkflowsPage` surface (apps/web/src/pages/WorkflowsPage.js
//! + apps/web/src/components/workflows/DynamicWorkflowsTab.js). Uses the
//! `/api/v1/dynamic-workflows` endpoint family — the same one the web UI
//! talks to via `apps/web/src/services/dynamicWorkflowService.js`. The
//! legacy `/api/v1/workflows` surface is intentionally untouched here.

use clap::{Args, Subcommand};

use crate::context::Context;
use crate::output;

#[derive(Debug, Subcommand)]
pub enum WorkflowCommand {
    /// List dynamic workflows in the current tenant.
    Ls(LsArgs),
    /// Show a single workflow by id or name.
    Show(ShowArgs),
    /// Trigger a run (or dry-run validate) for a workflow.
    Run(RunArgs),
    /// List recent runs for a workflow.
    Runs(RunsArgs),
    /// Activate a paused / draft workflow.
    Activate(ToggleArgs),
    /// Pause an active workflow.
    Pause(ToggleArgs),
}

#[derive(Debug, Args)]
pub struct ToggleArgs {
    /// Workflow UUID or exact name.
    pub workflow: String,
}

#[derive(Debug, Args)]
pub struct LsArgs {
    /// Filter by status (draft / active / paused / archived).
    #[arg(long)]
    pub status: Option<String>,

    /// Filter by trigger type (cron / interval / webhook / event / manual / agent).
    #[arg(long)]
    pub trigger: Option<String>,
}

#[derive(Debug, Args)]
pub struct ShowArgs {
    /// Workflow UUID or exact name.
    pub workflow: String,
}

#[derive(Debug, Args)]
pub struct RunArgs {
    /// Workflow UUID or exact name.
    pub workflow: String,

    /// JSON input object passed as `input_data` to the run. Defaults to
    /// `{}`. Example: `--input '{"customer_id": "abc"}'`.
    #[arg(long)]
    pub input: Option<String>,

    /// Validate the definition without dispatching to Temporal. Mirrors the
    /// "Test" button in the web TestConsole.
    #[arg(long)]
    pub dry_run: bool,
}

#[derive(Debug, Args)]
pub struct RunsArgs {
    /// Workflow UUID or exact name.
    pub workflow: String,

    /// Max rows to return. Backend default mirrors the web RunsTab (20).
    #[arg(long, default_value_t = 20)]
    pub limit: u32,
}

pub async fn dispatch(cmd: WorkflowCommand, ctx: Context) -> anyhow::Result<()> {
    match cmd {
        WorkflowCommand::Ls(a) => ls(a, ctx).await,
        WorkflowCommand::Show(a) => show(a, ctx).await,
        WorkflowCommand::Run(a) => run(a, ctx).await,
        WorkflowCommand::Runs(a) => runs(a, ctx).await,
        WorkflowCommand::Activate(a) => toggle(a, ctx, true).await,
        WorkflowCommand::Pause(a) => toggle(a, ctx, false).await,
    }
}

async fn toggle(args: ToggleArgs, ctx: Context, activate: bool) -> anyhow::Result<()> {
    let workflow = resolve_workflow(&args.workflow, &ctx).await?;
    if activate {
        ctx.client
            .activate_dynamic_workflow(&workflow.id.to_string())
            .await?;
    } else {
        ctx.client
            .pause_dynamic_workflow(&workflow.id.to_string())
            .await?;
    }
    let verb = if activate { "activated" } else { "paused" };
    output::ok(format!("{} workflow {}", verb, workflow.name));
    // Re-fetch the freshly-mutated row and emit it so --json callers see
    // the new state without a second request.
    if ctx.json {
        let updated = ctx
            .client
            .get_dynamic_workflow(&workflow.id.to_string())
            .await?;
        crate::output::emit(ctx.json, &updated, |_| {});
    }
    Ok(())
}

async fn ls(args: LsArgs, ctx: Context) -> anyhow::Result<()> {
    let list = ctx
        .client
        .list_dynamic_workflows(args.status.as_deref())
        .await?;

    let trigger_q = args.trigger.as_deref().map(|s| s.to_lowercase());
    let filtered: Vec<_> = list
        .into_iter()
        .filter(|w| {
            trigger_q
                .as_deref()
                .map(|q| trigger_type(w).as_deref().map(|t| t == q).unwrap_or(false))
                .unwrap_or(true)
        })
        .collect();

    crate::output::emit(ctx.json, &filtered, |list| {
        if list.is_empty() {
            output::info("no workflows match the current filter.".to_string());
            return;
        }
        // Column order mirrors DynamicWorkflowsTab card metadata: name /
        // status / trigger / runs / id. `runs` is the rollup counter; if
        // it's 0 across active workflows that's a signal the scheduler
        // isn't picking the workflow up (same operational tell as the web).
        println!(
            "{:<32}  {:<10}  {:<10}  {:<6}  {}",
            console::style("NAME").bold(),
            console::style("STATUS").bold(),
            console::style("TRIGGER").bold(),
            console::style("RUNS").bold(),
            console::style("ID").bold()
        );
        for w in list {
            let name = truncate(&w.name, 32);
            let status = w.status.as_deref().unwrap_or("—");
            let trigger = trigger_type(w).unwrap_or_else(|| "—".into());
            println!(
                "{:<32}  {:<10}  {:<10}  {:<6}  {}",
                name, status, trigger, w.run_count, w.id
            );
        }
    });
    Ok(())
}

async fn show(args: ShowArgs, ctx: Context) -> anyhow::Result<()> {
    let workflow = resolve_workflow(&args.workflow, &ctx).await?;
    crate::output::emit(ctx.json, &workflow, |w| {
        let h = |t: &str| console::style(t).bold().to_string();
        println!("{}: {}", h("id"), w.id);
        println!("{}: {}", h("name"), w.name);
        if let Some(s) = &w.status {
            println!("{}: {}", h("status"), s);
        }
        if let Some(t) = trigger_type(w) {
            println!("{}: {}", h("trigger"), t);
        }
        if let Some(desc) = &w.description {
            println!("{}: {}", h("description"), desc);
        }
        if let Some(def) = &w.definition {
            let steps = def
                .get("steps")
                .and_then(|s| s.as_array())
                .map(|a| a.len())
                .unwrap_or(0);
            println!("{}: {}", h("steps"), steps);
        }
        println!("{}: {}", h("runs"), w.run_count);
        if let Some(last) = &w.last_run_at {
            println!("{}: {}", h("last run"), last);
        }
    });
    Ok(())
}

async fn run(args: RunArgs, ctx: Context) -> anyhow::Result<()> {
    let workflow = resolve_workflow(&args.workflow, &ctx).await?;
    let input = match args.input.as_deref() {
        Some(s) => Some(
            serde_json::from_str::<serde_json::Value>(s)
                .map_err(|e| anyhow::anyhow!("--input is not valid JSON: {e}"))?,
        ),
        None => None,
    };
    let run = ctx
        .client
        .run_dynamic_workflow(&workflow.id.to_string(), input, args.dry_run)
        .await?;

    crate::output::emit(ctx.json, &run, |r| {
        let h = |t: &str| console::style(t).bold().to_string();
        if args.dry_run {
            output::ok(format!(
                "dry-run validated for workflow {} (no execution dispatched)",
                workflow.name
            ));
        } else {
            output::ok(format!("run dispatched for workflow {}", workflow.name));
        }
        println!("{}: {}", h("run id"), r.id);
        println!("{}: {}", h("status"), r.status);
        println!("{}: {}", h("started"), r.started_at);
        if let Some(step) = &r.current_step {
            println!("{}: {}", h("current step"), step);
        }
    });
    Ok(())
}

async fn runs(args: RunsArgs, ctx: Context) -> anyhow::Result<()> {
    let workflow = resolve_workflow(&args.workflow, &ctx).await?;
    let runs = ctx
        .client
        .list_dynamic_workflow_runs(&workflow.id.to_string(), Some(args.limit))
        .await?;

    crate::output::emit(ctx.json, &runs, |list| {
        if list.is_empty() {
            output::info(format!("no runs recorded for {}", workflow.name));
            return;
        }
        println!(
            "{:<10}  {:<24}  {:>8}  {}",
            console::style("STATUS").bold(),
            console::style("STARTED").bold(),
            console::style("DURATION").bold(),
            console::style("RUN ID").bold(),
        );
        for r in list {
            let duration = r
                .duration_ms
                .map(|ms| format!("{}ms", ms))
                .unwrap_or_else(|| "—".into());
            // Trim sub-second precision on the displayed timestamp. The
            // server returns a naive ISO string like "2026-05-11T12:50:17.459548";
            // chop the microseconds for the table. Raw value flows through
            // --json untouched.
            let started = trim_micros(&r.started_at);
            println!(
                "{:<10}  {:<24}  {:>8}  {}",
                r.status, started, duration, r.id
            );
        }
    });
    Ok(())
}

/// Pull the workflow record by id or name. Names are matched
/// case-insensitively against the full list — the dynamic_workflows table
/// does not have a tenant-unique name index, so collisions are possible;
/// in that case we surface the ambiguity instead of guessing.
async fn resolve_workflow(
    needle: &str,
    ctx: &Context,
) -> anyhow::Result<agentprovision_core::models::DynamicWorkflow> {
    let looks_like_uuid =
        needle.len() == 36 && needle.matches('-').count() == 4 && needle.is_ascii();
    if looks_like_uuid {
        return Ok(ctx.client.get_dynamic_workflow(needle).await?);
    }
    let all = ctx.client.list_dynamic_workflows(None).await?;
    let lower = needle.to_lowercase();
    let matches: Vec<_> = all
        .into_iter()
        .filter(|w| w.name.to_lowercase() == lower)
        .collect();
    match matches.len() {
        0 => Err(anyhow::anyhow!("no workflow matches \"{}\"", needle)),
        1 => Ok(ctx
            .client
            .get_dynamic_workflow(&matches.into_iter().next().unwrap().id.to_string())
            .await?),
        n => Err(anyhow::anyhow!(
            "ambiguous: {n} workflows named \"{}\" — pass the UUID instead",
            needle
        )),
    }
}

/// Extract the `trigger_config.type` field as a lower-cased string. Returns
/// None if the field is missing or malformed — most workflows have it
/// populated; ones that don't show "—" in the table.
fn trigger_type(w: &agentprovision_core::models::DynamicWorkflow) -> Option<String> {
    w.trigger_config
        .as_ref()
        .and_then(|c| c.get("type"))
        .and_then(|t| t.as_str())
        .map(|s| s.to_lowercase())
}

/// Drop microseconds and beyond from a naive ISO timestamp like
/// "2026-05-11T12:50:17.459548" → "2026-05-11T12:50:17". Falls back to
/// the input unchanged when there's no "." separator, so a value that
/// already lacks microseconds (or is non-conforming) round-trips
/// unharmed.
fn trim_micros(s: &str) -> String {
    s.split_once('.')
        .map(|(head, _)| head.to_string())
        .unwrap_or_else(|| s.to_string())
}

/// Same fixed-width hard wrap helper as `commands::agent::truncate`. Kept
/// local to avoid a shared util module that would only have one function.
fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        let mut out: String = s.chars().take(n.saturating_sub(1)).collect();
        out.push('…');
        out
    }
}
