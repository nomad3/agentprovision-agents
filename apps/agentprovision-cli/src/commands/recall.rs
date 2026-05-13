//! `alpha recall <QUERY>` — unified semantic search across the tenant's
//! memory layer.
//!
//! Phase 2 of the CLI differentiation roadmap (#179) — see
//! `docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md` §4.
//!
//! Distinct from `alpha memory search`, which is scoped to the knowledge
//! graph (entities). `alpha recall` hits `/api/v1/memories/search` which
//! is the unified semantic search across **all** memory content types
//! (entities, observations, episodes, conversation snippets,
//! commitments, goals) — the same surface chat agents query before
//! every turn under the memory-first design.
//!
//! Wire shape:
//!   GET /api/v1/memories/search?q=<query>&limit=N[&types=<csv>]
//!   → {"results": [...], "query": "<query>"}
//! The route accepts comma-separated `types` to narrow the search;
//! we expose it as `--types entity,observation,episode,...`.

use clap::Args;
use serde::{Deserialize, Serialize};

use crate::context::Context;

#[derive(Debug, Args)]
pub struct RecallArgs {
    /// Free-form query. Use quotes for multi-word queries.
    /// Empty / whitespace-only inputs are rejected at parse time.
    #[arg(value_name = "QUERY", value_parser = non_blank_query)]
    pub query: String,

    /// Cap on result count. Defaults to 20 (matches the server-side
    /// default; explicit here for visibility).
    #[arg(long, default_value_t = 20)]
    pub limit: u32,

    /// Comma-separated content-type filter
    /// (e.g. `--types entity,observation`). Mirrors the server's
    /// `?types=...` query param. When omitted, all types are searched.
    #[arg(long, value_delimiter = ',')]
    pub types: Vec<String>,
}

/// Whitespace-aware non-empty validator. Same pattern as
/// `commands/cancel.rs::non_blank_task_id` — `clap::NonEmptyString`
/// only rejects byte-length-0; trims to also catch `"  "`.
fn non_blank_query(s: &str) -> Result<String, String> {
    if s.trim().is_empty() {
        Err("query must not be empty or whitespace-only".to_string())
    } else {
        Ok(s.to_string())
    }
}

#[derive(Debug, Deserialize, Serialize)]
struct RecallResponse {
    #[serde(default)]
    results: Vec<serde_json::Value>,
    /// Round-1 review N2: kept for the --json echo of the server's
    /// query field. Pretty mode renders the user's input from
    /// `args.query` directly so this isn't dead — it round-trips
    /// the server's canonicalization (if any) into the JSON shape
    /// that scripted consumers see.
    #[serde(default)]
    query: String,
}

pub async fn run(args: RecallArgs, ctx: Context) -> anyhow::Result<()> {
    use agentprovision_core::error::Error;
    use reqwest::Method;

    // reqwest's `.query()` URL-encodes the values for us — no
    // hand-encoding (or extra dep) needed. Build the query param
    // list, including `types` only when non-empty so we don't send
    // an empty CSV (the route accepts None vs empty differently).
    let mut params: Vec<(&str, String)> =
        vec![("q", args.query.clone()), ("limit", args.limit.to_string())];
    if !args.types.is_empty() {
        params.push(("types", args.types.join(",")));
    }

    let req = ctx
        .client
        .request(Method::GET, "/api/v1/memories/search")?
        .query(&params);
    match ctx.client.send_json::<RecallResponse>(req).await {
        Ok(resp) => render(&args, &resp, ctx.json),
        Err(Error::Unauthorized) => {
            anyhow::bail!("not logged in — run `alpha login` first")
        }
        Err(e) => Err(e.into()),
    }
}

fn render(args: &RecallArgs, resp: &RecallResponse, json: bool) -> anyhow::Result<()> {
    if json {
        println!("{}", serde_json::to_string_pretty(resp)?);
        return Ok(());
    }
    if resp.results.is_empty() {
        println!("[alpha] no memories matched: \"{}\"", args.query);
        return Ok(());
    }
    println!(
        "[alpha] {} result(s) for \"{}\":",
        resp.results.len(),
        args.query
    );
    // Round-1 review L3: scale the numbering column to the result
    // count so `--limit 500` doesn't drift the alignment past 99.
    let width = resp.results.len().to_string().len().max(2);
    for (i, r) in resp.results.iter().enumerate() {
        // Round-1 review B1: the actual wire shape from
        // `embedding_service.search_similar` (the source of
        // `/memories/search` rows) is flat:
        //   {id, tenant_id, content_type, content_id, text_content,
        //    created_at, similarity}
        // No `name` / `title` / `content` / `description` / `summary`
        // fields exist on these rows. The displayable text lives in
        // `text_content`. Dropping the multi-field fallback chain
        // (which would always have rendered empty previews).
        let kind = r
            .get("content_type")
            .and_then(|v| v.as_str())
            .unwrap_or("?");
        let content = r.get("text_content").and_then(|v| v.as_str()).unwrap_or("");
        let similarity = r
            .get("similarity")
            .and_then(|v| v.as_f64())
            .map(|f| format!(" sim={f:.2}"))
            .unwrap_or_default();
        println!("{:width$}. [{}]{}", i + 1, kind, similarity, width = width);
        if !content.is_empty() {
            // Round-1 review N1: 200-char preview (single line).
            // Newlines in the content are preserved by the terminal —
            // long entries will visually wrap but the structural cap
            // keeps any single result from dominating the screen.
            let preview: String = content.chars().take(200).collect();
            println!("    {preview}");
        }
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
        Recall(RecallArgs),
    }

    #[test]
    fn parses_bare_query() {
        let cli = TestCli::try_parse_from(["t", "recall", "hello"]).unwrap();
        let TestCmd::Recall(a) = cli.cmd;
        assert_eq!(a.query, "hello");
        assert_eq!(a.limit, 20);
        assert!(a.types.is_empty());
    }

    #[test]
    fn parses_quoted_multiword_query_and_limit() {
        let cli = TestCli::try_parse_from([
            "t",
            "recall",
            "what was that fastapi error pattern",
            "--limit",
            "5",
        ])
        .unwrap();
        let TestCmd::Recall(a) = cli.cmd;
        assert_eq!(a.query, "what was that fastapi error pattern");
        assert_eq!(a.limit, 5);
    }

    #[test]
    fn parses_types_csv() {
        let cli =
            TestCli::try_parse_from(["t", "recall", "x", "--types", "entity,observation,episode"])
                .unwrap();
        let TestCmd::Recall(a) = cli.cmd;
        assert_eq!(
            a.types,
            vec![
                "entity".to_string(),
                "observation".to_string(),
                "episode".to_string()
            ]
        );
    }

    #[test]
    fn empty_query_rejected() {
        assert!(TestCli::try_parse_from(["t", "recall", ""]).is_err());
        assert!(TestCli::try_parse_from(["t", "recall", "  "]).is_err());
        assert!(TestCli::try_parse_from(["t", "recall", "\t"]).is_err());
    }

    // Round-1 review M1: HTTP-path test coverage deferred — same
    // rationale as cancel.rs (PR #436): requires httpmock dev-dep
    // and a streaming-response harness shared across CLI commands.
    // The placeholder documents the intent so the next reviewer
    // doesn't have to ask.
    #[test]
    #[ignore = "TODO: requires httpmock dev-dep for HTTP-path coverage"]
    fn recall_renders_results_against_real_response_shape() {
        // When wired: mock GET /memories/search returning rows
        // shaped {content_type, text_content, similarity, ...} and
        // assert the rendered preview contains the text_content
        // prefix and the type tag.
    }
}
