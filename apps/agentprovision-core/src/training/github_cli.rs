//! GitHub CLI wedge scanner.
//!
//! Uses the user's existing `gh auth login` session. Shells out to
//! `gh api …` so we never see their PAT directly — the GitHub OAuth
//! token never leaves the `gh` keychain entry, and we don't need any
//! AgentProvision-side OAuth wiring for this wedge.
//!
//! What gets uploaded (all metadata only):
//!   - The authenticated GitHub user's login + email + name + bio
//!   - Up to N public + private repos the user has access to (name,
//!     owner, language, recent commit timestamp)
//!   - Up to N orgs they belong to (login, name)
//!   - Up to N recent PRs / issues they authored or are involved in
//!     (title + url + state + repo + updated_at — NO body text)
//!
//! Bodies are intentionally excluded — keeps the wire payload small
//! AND matches the privacy contract documented in `consent_summary()`.
//!
//! Wire item shape:
//! ```json
//! { "kind": "github_user",  "login": "...", "email": "...", … }
//! { "kind": "github_repo",  "name": "...", "owner": "...", … }
//! { "kind": "github_org",   "login": "...", … }
//! { "kind": "github_pr",    "title": "...", "url": "...", "state": "...", … }
//! { "kind": "github_issue", "title": "...", "url": "...", "state": "...", … }
//! ```

use std::process::Command;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::error::{Error, Result};

/// Cap stderr at 1024 chars with a head+tail keep when truncation
/// fires. Reviewer (PR #407 re-review NIT #3): the previous 512-char
/// head-only cap discarded gh's actionable remediation hint which
/// always lives at the END of stderr (e.g. "To request missing
/// scopes, run: gh auth refresh -s read:org"). Head+tail keeps both
/// the banner (HTTP code + first line) AND the fix-it hint, which
/// is what makes the error usable for the end user.
///
/// 1024 covers ~99% of gh error shapes; the rare 1500-char OAuth
/// scope-mismatch dump still ends up readable.
fn cap_stderr(bytes: &[u8]) -> String {
    let stderr = String::from_utf8_lossy(bytes);
    let trimmed = stderr.trim();
    if trimmed.chars().count() <= 1024 {
        return trimmed.to_string();
    }
    let chars: Vec<char> = trimmed.chars().collect();
    let head: String = chars.iter().take(400).collect();
    let tail: String = chars.iter().skip(chars.len() - 600).collect();
    format!("{head}...[truncated]...{tail}")
}

pub fn consent_summary() -> &'static str {
    "I'll shell out to `gh api` using your existing `gh auth` session:\n\
     • gh api user                 → your profile (login, name, email, bio)\n\
     • gh api /user/repos          → repos you have access to (metadata only)\n\
     • gh api /user/orgs           → org memberships (login, name)\n\
     • gh search prs --author=@me  → recent PRs (title + url + state, NO body)\n\
     • gh search issues --author=@me → recent issues (same)\n\
     \n\
     I will NOT touch:\n\
     • your gh OAuth token (stays in the gh keychain entry)\n\
     • PR / issue body text\n\
     • repo contents (no clone, no read of source files)"
}

/// Per-bucket limits for the scan.
///
/// **`repos_limit` is hard-capped at 100 by GitHub's REST API
/// (`per_page=100` max).** A caller setting `repos_limit: 500` will
/// silently get the 100 most-recently-pushed repos. The proper fix
/// once we need full repo coverage is to switch to paginated calls
/// (`--paginate` flag or successive `?page=N` queries); for now the
/// design intent is "seed enough signal for a useful KG, not build
/// a mirror" and 100 is the right number. Reviewer (PR #407 NIT
/// finding #3) flagged the soft-cap as fuzzy contract — documenting
/// it on the field is the cheap fix.
#[derive(Debug, Clone, Copy)]
pub struct ScanOptions {
    /// Cap at 100 due to GitHub's REST `per_page` limit (see struct
    /// docstring). Values >100 are accepted but silently capped.
    pub repos_limit: u32,
    pub orgs_limit: u32,
    pub prs_limit: u32,
    pub issues_limit: u32,
}

impl Default for ScanOptions {
    fn default() -> Self {
        Self {
            // Defaults sized for first-train UX: enough signal to
            // populate the knowledge graph, small enough to land in
            // under ~30s of Gemma extraction.
            repos_limit: 50,
            orgs_limit: 20,
            prs_limit: 50,
            issues_limit: 50,
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct GithubCliSnapshot {
    pub user: Option<Value>,
    pub repos: Vec<Value>,
    pub orgs: Vec<Value>,
    pub prs: Vec<Value>,
    pub issues: Vec<Value>,
}

impl GithubCliSnapshot {
    pub fn total_items(&self) -> usize {
        usize::from(self.user.is_some())
            + self.repos.len()
            + self.orgs.len()
            + self.prs.len()
            + self.issues.len()
    }

    /// Flatten to the wire-shape `Vec<Value>` the bulk-ingest endpoint
    /// accepts. Each item is tagged with `kind` so the server-side
    /// extract activity can dispatch per source.
    ///
    /// The `or_else` chains on `url` / `repository` / `updated_at`
    /// look like dead code today — `gh search prs --json` always
    /// emits the camelCase form. They exist as forward-compat for
    /// a future change to `gh api /search/issues` (REST) which uses
    /// `html_url` / `repo` / `updated_at` (snake_case). Reviewer
    /// (PR #407 NIT finding #6) flagged the chains — leaving the
    /// fallback in with this doc note rather than deleting it,
    /// since the cost is one branch per item and the wire schema
    /// drift between GraphQL and REST is the kind of thing that
    /// shows up in a 2.x → 3.x gh major bump.
    pub fn to_items(&self) -> Vec<Value> {
        let mut items = Vec::new();

        if let Some(u) = &self.user {
            items.push(serde_json::json!({
                "kind": "github_user",
                "login": u.get("login"),
                "name": u.get("name"),
                "email": u.get("email"),
                "bio": u.get("bio"),
                "company": u.get("company"),
                "location": u.get("location"),
            }));
        }

        for r in &self.repos {
            items.push(serde_json::json!({
                "kind": "github_repo",
                "name": r.get("name"),
                "owner": r.get("owner").and_then(|o| o.get("login")),
                "full_name": r.get("full_name"),
                "language": r.get("language"),
                "pushed_at": r.get("pushed_at"),
                "stargazers_count": r.get("stargazers_count"),
                "private": r.get("private"),
                "html_url": r.get("html_url"),
            }));
        }

        for o in &self.orgs {
            items.push(serde_json::json!({
                "kind": "github_org",
                "login": o.get("login"),
                "description": o.get("description"),
            }));
        }

        for pr in &self.prs {
            items.push(serde_json::json!({
                "kind": "github_pr",
                "title": pr.get("title"),
                "url": pr.get("url").or_else(|| pr.get("html_url")),
                "state": pr.get("state"),
                "repository": pr
                    .get("repository")
                    .and_then(|r| r.get("nameWithOwner"))
                    .or_else(|| pr.get("repo")),
                "updated_at": pr.get("updatedAt").or_else(|| pr.get("updated_at")),
            }));
        }

        for issue in &self.issues {
            items.push(serde_json::json!({
                "kind": "github_issue",
                "title": issue.get("title"),
                "url": issue.get("url").or_else(|| issue.get("html_url")),
                "state": issue.get("state"),
                "repository": issue
                    .get("repository")
                    .and_then(|r| r.get("nameWithOwner"))
                    .or_else(|| issue.get("repo")),
                "updated_at": issue
                    .get("updatedAt")
                    .or_else(|| issue.get("updated_at")),
            }));
        }

        items
    }
}

/// Shell out to `gh auth status` to confirm the user has the GitHub
/// CLI installed AND authenticated. We do NOT parse the output — `gh`
/// exits non-zero when unauthenticated, which is the contract we rely
/// on. Returns a tidy error so the CLI can hint at `gh auth login`.
pub fn ensure_gh_authenticated() -> Result<()> {
    let output = Command::new("gh")
        .args(["auth", "status"])
        .output()
        .map_err(|e| {
            Error::Other(format!(
                "gh CLI not installed or not on PATH: {e}. \
                 Install from https://cli.github.com/."
            ))
        })?;
    if !output.status.success() {
        return Err(Error::Other(
            "gh is installed but not authenticated. Run `gh auth login` first.".into(),
        ));
    }
    Ok(())
}

/// Run a `gh api` call and return the parsed JSON. We use `gh api`
/// rather than `gh repo list` / `gh search` because the JSON output
/// is more structured and version-stable. Failures bubble up — the
/// wedge can recover from a single endpoint failing (we just emit
/// fewer items) so callers wrap individual calls in `Result`.
///
/// **Subprocess-arg safety contract** (reviewer PR #407 finding #1):
/// every `arg` passed in by callers MUST NOT start with `--` unless
/// it is a hand-validated flag literal in this module. `Command::args`
/// protects against shell-metacharacter injection (it spawns via
/// `execve`, no shell), but NOT against flag-style injection where a
/// user-controlled string `--token=…` becomes a new flag to `gh`.
/// Today all args originate from this module's own templates — no
/// user input reaches here. When the next PR adds `--user <name>` or
/// `--org <name>` parameters, the caller must validate that the value
/// doesn't begin with `--`, or use `Command::arg("--")` as an end-of-
/// flags marker before the user value.
fn gh_api(args: &[&str]) -> Result<Value> {
    // Defensive guard for the contract above: refuse any arg that
    // begins with "--" since this module currently doesn't have any
    // legitimate need to pass flags through `args`. If a future PR
    // wants to use this for a flag-passing call, lift the guard
    // explicitly per-call rather than punching a hole here.
    if args.iter().any(|a| a.starts_with("--")) {
        return Err(Error::Other(format!(
            "gh_api refuses flag-style arg (got `{}`). \
             Callers must use the typed flag-builder helpers.",
            args.iter().find(|a| a.starts_with("--")).unwrap_or(&""),
        )));
    }
    let mut cmd = Command::new("gh");
    cmd.arg("api");
    for a in args {
        cmd.arg(a);
    }
    let output = cmd
        .output()
        .map_err(|e| Error::Other(format!("gh api spawn failed: {e}")))?;
    if !output.status.success() {
        return Err(Error::Other(format!(
            "gh api failed (exit {:?}): {}",
            output.status.code(),
            cap_stderr(&output.stderr),
        )));
    }
    serde_json::from_slice::<Value>(&output.stdout)
        .map_err(|e| Error::Other(format!("gh api JSON parse failed: {e}")))
}

pub fn scan(opts: ScanOptions) -> Result<GithubCliSnapshot> {
    ensure_gh_authenticated()?;

    let mut snap = GithubCliSnapshot::default();

    // User profile — single object response. We pull this first
    // because every downstream item links back to the user entity.
    snap.user = gh_api(&["user"]).ok();

    // Repos — paginated; gh handles pagination via `--paginate` but
    // we cap at `repos_limit` items via `per_page`. Sort by recent
    // push so we get high-signal repos first.
    let per_page = format!("per_page={}", opts.repos_limit.min(100));
    let repos_endpoint = format!("/user/repos?sort=pushed&direction=desc&{per_page}");
    if let Ok(Value::Array(arr)) = gh_api(&[&repos_endpoint]) {
        snap.repos = arr.into_iter().take(opts.repos_limit as usize).collect();
    }

    // Orgs — typically small (<20), no pagination knob needed.
    if let Ok(Value::Array(arr)) = gh_api(&["/user/orgs"]) {
        snap.orgs = arr.into_iter().take(opts.orgs_limit as usize).collect();
    }

    // Recent PRs and issues — uses the search API rather than the
    // user/issues feed because search returns more accurate
    // 'involves the caller' results. The bodyText field is
    // intentionally omitted from the GraphQL projection.
    snap.prs = run_gh_search("prs", opts.prs_limit).unwrap_or_default();
    snap.issues = run_gh_search("issues", opts.issues_limit).unwrap_or_default();

    Ok(snap)
}

/// Shell out to `gh search prs/issues --author=@me ... --json …`. We
/// pass `--json` so the binary returns a Vec<Value> directly,
/// avoiding the gh-pager interactive flow.
///
/// **Subprocess-arg safety contract** — every arg here is a literal
/// from this module's source. `kind` is `"prs"` / `"issues"`
/// (the only call sites in `scan()`); a future caller passing user
/// input must validate it can't begin with `--`. See `gh_api()`
/// docstring for the broader contract.
fn run_gh_search(kind: &str, limit: u32) -> Result<Vec<Value>> {
    // Hard guard: reject `kind` values that look like flags. The
    // production call sites pass literal "prs" or "issues", but a
    // future refactor could expose this to user input — fail fast.
    if kind.starts_with("--") || kind.contains(' ') {
        return Err(Error::Other(format!(
            "run_gh_search refuses suspicious kind `{kind}`"
        )));
    }
    // Projection covers exactly the fields `to_items()` reads —
    // never include `body` so the body text stays on GitHub.
    let json_fields = "title,url,state,repository,updatedAt";
    let limit_str = limit.to_string();
    let output = Command::new("gh")
        .args([
            "search",
            kind,
            "--author=@me",
            "--limit",
            &limit_str,
            "--json",
            json_fields,
        ])
        .output()
        .map_err(|e| Error::Other(format!("gh search {kind} spawn failed: {e}")))?;
    if !output.status.success() {
        return Err(Error::Other(format!(
            "gh search {kind} failed: {}",
            cap_stderr(&output.stderr),
        )));
    }
    let val: Value = serde_json::from_slice(&output.stdout)
        .map_err(|e| Error::Other(format!("gh search {kind} parse failed: {e}")))?;
    Ok(val.as_array().cloned().unwrap_or_default())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_total_items_counts_all_buckets() {
        let mut snap = GithubCliSnapshot::default();
        snap.user = Some(serde_json::json!({"login": "x"}));
        snap.repos = vec![serde_json::json!({})];
        snap.orgs = vec![serde_json::json!({}); 2];
        snap.prs = vec![serde_json::json!({}); 3];
        snap.issues = vec![serde_json::json!({}); 4];
        assert_eq!(snap.total_items(), 1 + 1 + 2 + 3 + 4);
    }

    #[test]
    fn to_items_emits_kind_tags() {
        let mut snap = GithubCliSnapshot::default();
        snap.user = Some(serde_json::json!({"login":"alice","name":"Alice"}));
        snap.repos
            .push(serde_json::json!({"name":"r","owner":{"login":"alice"}}));
        snap.orgs.push(serde_json::json!({"login":"acme"}));
        snap.prs
            .push(serde_json::json!({"title":"fix x","state":"OPEN"}));
        snap.issues
            .push(serde_json::json!({"title":"bug y","state":"CLOSED"}));
        let items = snap.to_items();
        let kinds: Vec<_> = items.iter().filter_map(|i| i.get("kind")).collect();
        let expected = vec![
            "github_user",
            "github_repo",
            "github_org",
            "github_pr",
            "github_issue",
        ];
        for k in expected {
            assert!(
                kinds.iter().any(|v| v.as_str() == Some(k)),
                "missing kind {k} in {kinds:?}"
            );
        }
    }

    #[test]
    fn to_items_extracts_repo_owner_from_nested_object() {
        let mut snap = GithubCliSnapshot::default();
        snap.repos.push(serde_json::json!({
            "name": "repo",
            "full_name": "alice/repo",
            "owner": { "login": "alice" },
            "language": "Rust"
        }));
        let items = snap.to_items();
        assert_eq!(items[0]["owner"], "alice");
        assert_eq!(items[0]["language"], "Rust");
    }

    // NB: a previous draft of this module had a
    // `ensure_gh_authenticated_returns_helpful_error_when_missing`
    // test that mutated `PATH` to simulate `gh` being absent. Reviewer
    // (PR #407 finding #5) caught that the env mutation races against
    // any parallel test that reads PATH or spawns a subprocess —
    // `cargo test` runs the suite in parallel threads of one process,
    // so the mutation window leaks. The production code's behaviour
    // when `gh` is missing is exercised end-to-end by the CLI's
    // existing acceptance tests (which run `ap quickstart --channel
    // github_cli` against a controlled `PATH` in a child cargo
    // invocation, not in-process). Dropping the in-process test is
    // the lowest-cost fix; alternatives (#[serial], a `gh_path`
    // parameter) add machinery for marginal coverage.
}
