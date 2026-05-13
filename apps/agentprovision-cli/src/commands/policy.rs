//! `alpha policy show <agent>` — read-only inspection of agent_policies.
//!
//! Phase 2 of the CLI roadmap (#179). Wraps
//! `GET /api/v1/agents/{agent_id}/policies`. Returns both
//! agent-scoped rows AND tenant-wide rows (agent_id IS NULL) so the
//! user sees every policy in effect for the named agent.
//!
//! Read-only by design: policy mutation goes through the web UI for
//! audit-trail. The roadmap explicitly excludes `alpha policy set`.

use chrono::{DateTime, Utc};
use clap::{Args, Subcommand};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::context::Context;
use crate::output;

#[derive(Debug, Args)]
pub struct PolicyArgs {
    #[command(subcommand)]
    pub command: PolicyCommand,
}

#[derive(Debug, Subcommand)]
pub enum PolicyCommand {
    /// Show the policies that apply to a specific agent. Combines
    /// agent-scoped rows (agent_policies.agent_id == <id>) with
    /// tenant-wide rows (agent_policies.agent_id IS NULL) so the
    /// rendered surface is "everything in effect for this agent".
    Show(ShowArgs),
}

#[derive(Debug, Args)]
pub struct ShowArgs {
    /// Agent UUID. Find with `alpha agent ls`.
    pub agent: Uuid,
}

#[derive(Debug, Deserialize, Serialize)]
struct PolicyRow {
    id: Uuid,
    #[serde(default)]
    agent_id: Option<Uuid>,
    policy_type: String,
    #[serde(default)]
    config: Value,
    enabled: bool,
    scope: String,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

#[derive(Debug, Deserialize, Serialize)]
struct PolicyListResponse {
    agent_id: Uuid,
    #[serde(default)]
    agent_name: Option<String>,
    policies: Vec<PolicyRow>,
}

pub async fn run(args: PolicyArgs, ctx: Context) -> anyhow::Result<()> {
    match args.command {
        PolicyCommand::Show(a) => show(a, ctx).await,
    }
}

async fn show(args: ShowArgs, ctx: Context) -> anyhow::Result<()> {
    let path = format!("/api/v1/agents/{}/policies", args.agent);
    let resp: PolicyListResponse = ctx.client.get_json(&path).await?;
    if ctx.json {
        crate::output::emit(true, &resp, |_| {});
        return Ok(());
    }
    let name = resp.agent_name.as_deref().unwrap_or("—");
    println!("policies for agent {name} ({}):", resp.agent_id);
    if resp.policies.is_empty() {
        output::info("[alpha] no policies in effect.");
        return Ok(());
    }
    // Group by policy_type for compact rendering. The server orders
    // by policy_type ASC + created_at DESC, so same-type rows are
    // adjacent — but a single policy_type can have BOTH agent-scoped
    // and tenant-scoped rows. The scope is rendered inline per row
    // rather than in the heading so the two scopes don't get
    // misattributed to whichever happened to be first. Reviewer
    // IMPORTANT I4 on PR #446.
    let mut last_type: Option<&str> = None;
    for p in &resp.policies {
        if last_type != Some(p.policy_type.as_str()) {
            println!("  {}:", p.policy_type);
            last_type = Some(p.policy_type.as_str());
        }
        let enabled = if p.enabled { "enabled" } else { "disabled" };
        // Render the config inline, compact form. JSON config can be
        // arbitrary so we don't try to pretty-print it here — the
        // user can pipe through `--json | jq` for the full shape.
        let config = serde_json::to_string(&p.config).unwrap_or_else(|_| "<invalid>".into());
        println!("    • [{}] {enabled}: {config}", p.scope);
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
        #[command(subcommand)]
        Policy(PolicyCommand),
    }

    fn parse_show(uuid: &str) -> ShowArgs {
        let cli = TestCli::try_parse_from(["test", "policy", "show", uuid]).expect("clap parse");
        match cli.cmd {
            TestCmd::Policy(PolicyCommand::Show(a)) => a,
        }
    }

    #[test]
    fn parses_show_uuid() {
        let uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
        let a = parse_show(uuid);
        assert_eq!(a.agent.to_string(), uuid);
    }

    #[test]
    fn rejects_non_uuid_agent() {
        let cli = TestCli::try_parse_from(["test", "policy", "show", "not-a-uuid"]);
        assert!(
            cli.is_err(),
            "clap should reject malformed agent UUID before reaching the handler"
        );
    }
}
