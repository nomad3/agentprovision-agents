//! `alpha goal` — structured autonomous task contract.
//!
//! Sugar on top of `alpha recipes run <goal-uuid>` that:
//!   1. resolves the native `Goal` recipe by name (no UUID gymnastics),
//!   2. prompts for the 5 contract slots (outcome / success criteria /
//!      operating rules / quality bar / deliverable) interactively, or
//!      accepts them via flags for non-interactive callers (CI/CD,
//!      sub-agents),
//!   3. installs the recipe into the caller's tenant if missing, and
//!   4. dispatches a manual run with `input_data` populated.
//!
//! Designed as the human-friendly counterpart of `alpha run --recipe goal`
//! — advanced users can still hit the lower-level path directly.
//!
//! Roadmap doc: docs/plans/2026-05-13-alpha-agent-view-and-goal-recipes.md

use clap::Args;
use dialoguer::{theme::ColorfulTheme, Input};
use serde::{Deserialize, Serialize};
use serde_json::json;
use uuid::Uuid;

use crate::context::Context;
use crate::output;

/// The native template's well-known name. The CLI resolves the recipe
/// by (name="Goal", tier="native") rather than a hard-coded UUID
/// because every tenant gets its own clone with a fresh UUID at install
/// time. The name is stable across releases — the API's
/// `seed_native_templates` dedupes on (name, tier).
const GOAL_RECIPE_NAME: &str = "Goal";

#[derive(Debug, Args, Default, Clone)]
pub struct GoalArgs {
    /// The outcome you want the agent to achieve. If omitted, the CLI
    /// prompts interactively for this and the other four slots.
    pub outcome: Option<String>,

    /// Success criteria, one per `--criterion` flag (repeatable). When
    /// not supplied, the CLI asks interactively. Each criterion is a
    /// concrete, testable condition that must be true before the agent
    /// declares done.
    #[arg(long = "criterion", short = 'c', value_name = "TEXT")]
    pub criteria: Vec<String>,

    /// Operating rules — repeatable; one rule per flag. Constraints the
    /// agent must obey throughout (e.g., "open draft PRs, never merge").
    #[arg(long = "rule", short = 'r', value_name = "TEXT")]
    pub rules: Vec<String>,

    /// Quality bar — single freeform sentence. Defaults to
    /// "ship-ready: tests green, no TODOs, no debug logs" when
    /// non-interactive callers omit it.
    #[arg(long, value_name = "TEXT")]
    pub quality_bar: Option<String>,

    /// Final deliverable. Defaults to "summary message describing
    /// the work done and how each success criterion was met".
    #[arg(long, value_name = "TEXT")]
    pub deliverable: Option<String>,

    /// Validate the contract + workflow without executing. Surfaces any
    /// integration gaps from the recipe definition.
    #[arg(long)]
    pub dry_run: bool,
}

/// Template row shape — minimal slice of the `dynamic-workflows`
/// browse response we care about for name-based resolution.
#[derive(Debug, Deserialize)]
struct TemplateRow {
    id: Uuid,
    name: String,
    #[serde(default)]
    tier: Option<String>,
}

/// `dynamic-workflows` row — minimal slice we need for the "already
/// installed?" check.
#[derive(Debug, Deserialize)]
struct InstalledWorkflow {
    id: Uuid,
    #[serde(default)]
    source_template_id: Option<Uuid>,
}

/// Real-run response from `POST /{id}/run`. Same shape as
/// `recipes.rs::RunResponse`; duplicated here so this command doesn't
/// reach across module boundaries.
#[derive(Debug, Deserialize, Serialize)]
struct RunResponse {
    id: Uuid,
    status: String,
    #[serde(default)]
    error: Option<String>,
}

/// Dry-run response. Server returns no id/status — instead the plan +
/// validation results.
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

pub async fn run(args: GoalArgs, ctx: Context) -> anyhow::Result<()> {
    // ── 1. Collect the 5 contract slots ──
    let contract = collect_contract(&args)?;

    // ── 2. Resolve the native Goal recipe template id ──
    let template_id = resolve_goal_template(&ctx).await?;

    // ── 3. Find an existing install or create one. Dedupe via
    //       source_template_id, matching the pattern in recipes.rs so
    //       repeated `alpha goal` invocations don't clutter the
    //       tenant's workflow list.
    let target_id = install_or_reuse(&ctx, template_id).await?;

    // ── 4. POST /run with the contract as input_data ──
    let run_path = format!("/api/v1/dynamic-workflows/{target_id}/run");
    let body = json!({
        "dry_run": args.dry_run,
        "input_data": contract,
    });

    if args.dry_run {
        let resp: DryRunResponse = ctx.client.post_json(&run_path, &body).await?;
        if ctx.json {
            crate::output::emit(true, &resp, |_| {});
            return Ok(());
        }
        output::ok(format!(
            "[alpha] dry-run validated — {} step{} for goal workflow {}",
            resp.step_count,
            if resp.step_count == 1 { "" } else { "s" },
            resp.workflow_id
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
        "[alpha] goal dispatched — run {} (status: {})",
        resp.id, resp.status
    ));
    output::info(format!(
        "follow live events: alpha watch {}",
        resp.id
    ));
    if let Some(err) = resp.error {
        output::warn(format!("error: {err}"));
    }
    Ok(())
}

/// Resolve the 5 contract slots from CLI flags, falling back to
/// interactive prompts for anything missing.
///
/// Interactive mode is opt-in: the moment any slot is provided via
/// flag, we suppress prompting for the others and apply documented
/// defaults instead. This keeps CI / sub-agent callers fully
/// non-interactive while still giving a fresh terminal user the guided
/// flow.
pub(crate) fn collect_contract(args: &GoalArgs) -> anyhow::Result<serde_json::Value> {
    let interactive = args.outcome.is_none()
        && args.criteria.is_empty()
        && args.rules.is_empty()
        && args.quality_bar.is_none()
        && args.deliverable.is_none();

    let outcome = match &args.outcome {
        Some(s) => s.clone(),
        None if interactive => Input::<String>::with_theme(&ColorfulTheme::default())
            .with_prompt("What outcome do you want?")
            .interact_text()?,
        None => anyhow::bail!("--outcome (positional) is required when running non-interactively"),
    };

    let criteria: Vec<String> = if !args.criteria.is_empty() {
        args.criteria.clone()
    } else if interactive {
        prompt_multiline("Success criteria? (one per line, blank to end)")?
    } else {
        // Non-interactive without any --criterion is a soft default —
        // require the agent to summarise its own definition of done.
        vec!["The agent must list its definition-of-done in the final message.".into()]
    };

    let rules: Vec<String> = if !args.rules.is_empty() {
        args.rules.clone()
    } else if interactive {
        prompt_multiline("Operating rules? (one per line, blank to end)")?
    } else {
        Vec::new()
    };

    let quality_bar = match &args.quality_bar {
        Some(s) => s.clone(),
        None if interactive => Input::<String>::with_theme(&ColorfulTheme::default())
            .with_prompt("Quality bar?")
            .default("ship-ready: tests green, no TODOs, no debug logs".into())
            .interact_text()?,
        None => "ship-ready: tests green, no TODOs, no debug logs".into(),
    };

    let deliverable = match &args.deliverable {
        Some(s) => s.clone(),
        None if interactive => Input::<String>::with_theme(&ColorfulTheme::default())
            .with_prompt("Final deliverable?")
            .default("summary message describing the work done and how each success criterion was met".into())
            .interact_text()?,
        None => "summary message describing the work done and how each success criterion was met".into(),
    };

    Ok(json!({
        "outcome": outcome,
        "success_criteria": render_bullets(&criteria),
        "operating_rules": render_bullets(&rules),
        "quality_bar": quality_bar,
        "deliverable": deliverable,
    }))
}

/// Render a Vec<String> as a Markdown bullet list — matches the format
/// the recipe's system prompt expects when interpolating `{{input.*}}`.
pub(crate) fn render_bullets(items: &[String]) -> String {
    if items.is_empty() {
        return "(none specified)".into();
    }
    items
        .iter()
        .map(|line| format!("- {line}"))
        .collect::<Vec<_>>()
        .join("\n")
}

/// Read lines from stdin until the user submits an empty line; each
/// non-empty trimmed line becomes one item. Used for the success-
/// criteria + operating-rules slots so the user can naturally pile up
/// constraints without quoting them on the command line.
fn prompt_multiline(label: &str) -> anyhow::Result<Vec<String>> {
    println!("{label}");
    let mut out = Vec::new();
    loop {
        let line: String = Input::<String>::with_theme(&ColorfulTheme::default())
            .with_prompt("  ")
            .allow_empty(true)
            .interact_text()?;
        let trimmed = line.trim();
        if trimmed.is_empty() {
            break;
        }
        out.push(trimmed.to_string());
    }
    Ok(out)
}

async fn resolve_goal_template(ctx: &Context) -> anyhow::Result<Uuid> {
    // Filter to native tier — the only set we seed the Goal recipe into.
    let rows: Vec<TemplateRow> = ctx
        .client
        .get_json("/api/v1/dynamic-workflows/templates/browse?tier=native")
        .await?;
    rows.into_iter()
        .find(|r| r.name == GOAL_RECIPE_NAME && r.tier.as_deref() == Some("native"))
        .map(|r| r.id)
        .ok_or_else(|| {
            anyhow::anyhow!(
                "native '{GOAL_RECIPE_NAME}' recipe not seeded on this server — \
                 ask the operator to restart the API to re-run seed_native_templates"
            )
        })
}

async fn install_or_reuse(ctx: &Context, template_id: Uuid) -> anyhow::Result<Uuid> {
    let installed: Vec<InstalledWorkflow> = ctx.client.get_json("/api/v1/dynamic-workflows").await?;
    if let Some(existing) = installed
        .iter()
        .find(|w| w.source_template_id == Some(template_id))
    {
        return Ok(existing.id);
    }
    let path = format!("/api/v1/dynamic-workflows/templates/{template_id}/install");
    let new_wf: InstalledWorkflow = ctx.client.post_json(&path, &json!({})).await?;
    Ok(new_wf.id)
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
        Goal(GoalArgs),
    }

    fn parse(args: &[&str]) -> GoalArgs {
        let cli = TestCli::try_parse_from(args).expect("clap parse");
        match cli.cmd {
            TestCmd::Goal(a) => a,
        }
    }

    #[test]
    fn parses_positional_outcome() {
        let a = parse(&["test", "goal", "Migrate auth to Clerk"]);
        assert_eq!(a.outcome.as_deref(), Some("Migrate auth to Clerk"));
        assert!(a.criteria.is_empty());
        assert!(!a.dry_run);
    }

    #[test]
    fn parses_repeatable_criteria() {
        let a = parse(&[
            "test",
            "goal",
            "X",
            "--criterion",
            "tests pass",
            "-c",
            "no TODOs",
        ]);
        assert_eq!(a.criteria, vec!["tests pass", "no TODOs"]);
    }

    #[test]
    fn parses_repeatable_rules_and_quality_bar() {
        let a = parse(&[
            "test",
            "goal",
            "X",
            "--rule",
            "open draft PRs only",
            "--quality-bar",
            "production-ready",
        ]);
        assert_eq!(a.rules, vec!["open draft PRs only"]);
        assert_eq!(a.quality_bar.as_deref(), Some("production-ready"));
    }

    #[test]
    fn parses_dry_run_flag() {
        let a = parse(&["test", "goal", "X", "--dry-run"]);
        assert!(a.dry_run);
    }

    #[test]
    fn render_bullets_empty_returns_placeholder() {
        assert_eq!(render_bullets(&[]), "(none specified)");
    }

    #[test]
    fn render_bullets_joins_with_markdown_dashes() {
        let out = render_bullets(&["a".into(), "b".into()]);
        assert_eq!(out, "- a\n- b");
    }

    #[test]
    fn collect_contract_non_interactive_with_flags() {
        // When the user supplies any flag, we MUST NOT block on stdin —
        // fall back to documented defaults for missing slots. This is
        // the contract that lets CI and sub-agent callers run goal
        // headlessly. (Asserted indirectly: if the function tried to
        // prompt, the test would hang.)
        let args = GoalArgs {
            outcome: Some("ship X".into()),
            criteria: vec!["one".into(), "two".into()],
            rules: vec![],
            quality_bar: None,
            deliverable: None,
            dry_run: false,
        };
        let v = collect_contract(&args).unwrap();
        assert_eq!(v["outcome"], "ship X");
        assert_eq!(v["success_criteria"], "- one\n- two");
        assert_eq!(v["operating_rules"], "(none specified)");
        assert!(v["quality_bar"].as_str().unwrap().contains("ship-ready"));
        assert!(v["deliverable"].as_str().unwrap().contains("success criterion"));
    }

    #[test]
    fn collect_contract_non_interactive_without_outcome_errors() {
        // Critical safety: if a non-interactive caller passes a flag
        // (e.g., --criterion) but omits the outcome, we MUST error
        // instead of silently dispatching an empty goal. Otherwise the
        // agent gets a contract with no objective and burns tokens
        // hallucinating one.
        let args = GoalArgs {
            outcome: None,
            criteria: vec!["one".into()],
            rules: vec![],
            quality_bar: None,
            deliverable: None,
            dry_run: false,
        };
        let err = collect_contract(&args).unwrap_err();
        assert!(err.to_string().contains("outcome"));
    }
}
