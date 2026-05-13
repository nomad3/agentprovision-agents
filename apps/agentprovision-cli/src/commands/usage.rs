//! `alpha usage` + `alpha costs` — tenant-scoped cost & token rollups.
//!
//! Phase 4 of the CLI differentiation roadmap (#181). Thin wrappers
//! around `GET /api/v1/usage` and `GET /api/v1/costs`.
//!
//! Roadmap §7:
//!   alpha usage --period mtd
//!   alpha costs --agent <id> --period 7d
//!
//! The `--team` flag from the roadmap example is deferred until
//! chat_messages carry team_id (agent.team_id exists but isn't
//! denormalised onto messages yet).

use chrono::{DateTime, Utc};
use clap::{Args, ValueEnum};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::context::Context;
use crate::output;

#[derive(Debug, Clone, ValueEnum, Serialize)]
#[serde(rename_all = "kebab-case")]
#[clap(rename_all = "kebab-case")]
pub enum Period {
    /// Last 24 hours.
    #[clap(name = "24h")]
    H24,
    /// Last 7 days.
    #[clap(name = "7d")]
    D7,
    /// Last 30 days.
    #[clap(name = "30d")]
    D30,
    /// Month-to-date.
    Mtd,
}

impl Period {
    fn as_wire(&self) -> &'static str {
        match self {
            Period::H24 => "24h",
            Period::D7 => "7d",
            Period::D30 => "30d",
            Period::Mtd => "mtd",
        }
    }
}

// `alpha usage` — top-level command with optional period.
#[derive(Debug, Args)]
pub struct UsageArgs {
    /// Period to aggregate over. Defaults to month-to-date.
    #[arg(long, value_enum, default_value_t = Period::Mtd)]
    pub period: Period,
}

// `alpha costs` — top-level command with optional period + agent.
#[derive(Debug, Args)]
pub struct CostsArgs {
    /// Period to aggregate over. Defaults to last 7 days.
    #[arg(long, value_enum, default_value_t = Period::D7)]
    pub period: Period,
    /// Optional agent UUID to scope the daily cost rollup.
    #[arg(long)]
    pub agent: Option<Uuid>,
}

// ──────────────────────────────────────────────────────────────────────
// `alpha usage`
// ──────────────────────────────────────────────────────────────────────

#[derive(Debug, Deserialize, Serialize)]
struct ProviderUsage {
    provider: String,
    #[serde(default)]
    input_tokens: i64,
    #[serde(default)]
    output_tokens: i64,
    #[serde(default)]
    cost_usd: f64,
    #[serde(default)]
    message_count: i64,
}

#[derive(Debug, Deserialize, Serialize)]
struct UsageResponse {
    period: String,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    rows: Vec<ProviderUsage>,
    #[serde(default)]
    total_input_tokens: i64,
    #[serde(default)]
    total_output_tokens: i64,
    #[serde(default)]
    total_cost_usd: f64,
}

pub async fn usage(args: UsageArgs, ctx: Context) -> anyhow::Result<()> {
    let path = format!("/api/v1/usage?period={}", args.period.as_wire());
    let resp: UsageResponse = ctx.client.get_json(&path).await?;
    if ctx.json {
        crate::output::emit(true, &resp, |_| {});
        return Ok(());
    }
    println!(
        "Tenant usage — {} ({} → {}):",
        resp.period,
        resp.start.format("%Y-%m-%d"),
        resp.end.format("%Y-%m-%d %H:%M UTC"),
    );
    if resp.rows.is_empty() {
        output::info("[alpha] no usage recorded in this period.");
        return Ok(());
    }
    println!();
    println!(
        "  {:<12}  {:>12}  {:>12}  {:>11}  {:>8}",
        "provider", "tokens_in", "tokens_out", "cost_usd", "msgs"
    );
    println!("  {}", "─".repeat(60));
    for r in &resp.rows {
        println!(
            "  {:<12}  {:>12}  {:>12}  {:>11}  {:>8}",
            r.provider,
            format_num(r.input_tokens),
            format_num(r.output_tokens),
            format_cost(r.cost_usd),
            r.message_count,
        );
    }
    println!("  {}", "─".repeat(60));
    println!(
        "  {:<12}  {:>12}  {:>12}  {:>11}  {:>8}",
        "total",
        format_num(resp.total_input_tokens),
        format_num(resp.total_output_tokens),
        format_cost(resp.total_cost_usd),
        resp.rows.iter().map(|r| r.message_count).sum::<i64>(),
    );
    Ok(())
}

// ──────────────────────────────────────────────────────────────────────
// `alpha costs`
// ──────────────────────────────────────────────────────────────────────

#[derive(Debug, Deserialize, Serialize)]
struct DailyCost {
    day: String,
    #[serde(default)]
    message_count: i64,
    #[serde(default)]
    cost_usd: f64,
}

#[derive(Debug, Deserialize, Serialize)]
struct CostsResponse {
    period: String,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    days: Vec<DailyCost>,
    #[serde(default)]
    total_cost_usd: f64,
    #[serde(default)]
    total_messages: i64,
}

pub async fn costs(args: CostsArgs, ctx: Context) -> anyhow::Result<()> {
    let mut path = format!("/api/v1/costs?period={}", args.period.as_wire());
    if let Some(a) = args.agent {
        path.push_str(&format!("&agent_id={a}"));
    }
    let resp: CostsResponse = ctx.client.get_json(&path).await?;
    if ctx.json {
        crate::output::emit(true, &resp, |_| {});
        return Ok(());
    }
    println!("Tenant costs — {}", resp.period);
    if let Some(a) = args.agent {
        println!("(agent: {a})");
    }
    if resp.days.is_empty() {
        output::info("[alpha] no cost-bearing activity in this period.");
        return Ok(());
    }
    println!();
    println!("  {:<12}  {:>8}  {:>11}", "day", "tasks", "cost_usd");
    println!("  {}", "─".repeat(36));
    for d in &resp.days {
        println!(
            "  {:<12}  {:>8}  {:>11}",
            d.day,
            d.message_count,
            format_cost(d.cost_usd),
        );
    }
    println!("  {}", "─".repeat(36));
    println!(
        "  {:<12}  {:>8}  {:>11}",
        "total",
        resp.total_messages,
        format_cost(resp.total_cost_usd),
    );
    Ok(())
}

// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────

/// Human-readable number with K / M suffixes for the token columns.
/// Mirrors the roadmap example (`1.2M`, `180K`).
fn format_num(n: i64) -> String {
    let f = n as f64;
    if f.abs() >= 1_000_000.0 {
        format!("{:.1}M", f / 1_000_000.0)
    } else if f.abs() >= 1_000.0 {
        format!("{:.0}K", f / 1_000.0)
    } else {
        n.to_string()
    }
}

/// USD cost rendered as `$12.34`. Zero stays `$0.00` (don't render as
/// `—` here — zero is a real value once a tenant has any usage rows).
fn format_cost(c: f64) -> String {
    format!("${:.2}", c)
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
        Usage(UsageArgs),
        Costs(CostsArgs),
    }

    #[test]
    fn usage_defaults_to_mtd() {
        let cli = TestCli::try_parse_from(["test", "usage"]).expect("clap parse");
        if let TestCmd::Usage(a) = cli.cmd {
            assert!(matches!(a.period, Period::Mtd));
        } else {
            panic!("expected Usage variant");
        }
    }

    #[test]
    fn usage_period_30d() {
        let cli =
            TestCli::try_parse_from(["test", "usage", "--period", "30d"]).expect("clap parse");
        if let TestCmd::Usage(a) = cli.cmd {
            assert!(matches!(a.period, Period::D30));
            assert_eq!(a.period.as_wire(), "30d");
        } else {
            panic!("expected Usage variant");
        }
    }

    #[test]
    fn usage_rejects_bogus_period() {
        let cli = TestCli::try_parse_from(["test", "usage", "--period", "yesterday"]);
        assert!(cli.is_err(), "clap should reject non-enum period");
    }

    #[test]
    fn costs_defaults_to_7d() {
        let cli = TestCli::try_parse_from(["test", "costs"]).expect("clap parse");
        if let TestCmd::Costs(a) = cli.cmd {
            assert!(matches!(a.period, Period::D7));
            assert!(a.agent.is_none());
        } else {
            panic!("expected Costs variant");
        }
    }

    #[test]
    fn costs_with_agent_uuid() {
        let uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
        let cli = TestCli::try_parse_from(["test", "costs", "--agent", uuid]).expect("clap parse");
        if let TestCmd::Costs(a) = cli.cmd {
            assert_eq!(a.agent.map(|u| u.to_string()).as_deref(), Some(uuid));
        } else {
            panic!("expected Costs variant");
        }
    }

    #[test]
    fn format_num_thresholds() {
        assert_eq!(format_num(500), "500");
        assert_eq!(format_num(1_500), "2K"); // rounds to nearest
        assert_eq!(format_num(890_000), "890K");
        assert_eq!(format_num(1_200_000), "1.2M");
        assert_eq!(format_num(0), "0");
    }

    #[test]
    fn format_cost_two_decimals() {
        assert_eq!(format_cost(0.0), "$0.00");
        assert_eq!(format_cost(14.2), "$14.20");
        assert_eq!(format_cost(0.005), "$0.01"); // rounds up
    }
}
