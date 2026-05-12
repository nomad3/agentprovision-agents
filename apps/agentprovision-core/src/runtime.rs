//! Local-runtime dispatch — detect, mint tokens for, and characterize the
//! five CLI runtimes the platform orchestrates from the server side
//! (Claude Code, Codex, Gemini CLI, GitHub Copilot CLI, OpenCode).
//!
//! The `ap` CLI uses this module to bring the same orchestration to a
//! user's local terminal: `ap claude-code "fix X"` resolves an agent,
//! mints an agent-scoped JWT via the user-scoped mint endpoint, and
//! spawns the runtime with platform-injected context (memory recall,
//! persona prompt, hook scripts, MCP config).
//!
//! See `docs/plans/2026-05-11-ap-cli-multi-runtime-dispatch-plan.md`.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::client::ApiClient;
use crate::error::{Error, Result};

/// One of the five CLI runtimes the platform supports. Wire format mirrors
/// the server-side `tenant_features.default_cli_platform` enum so the same
/// string round-trips through `/api/v1/chat/sessions/.../messages` audit
/// logs whether dispatch happened server-side or client-side.
///
/// `OpenCode` is the always-available local-Gemma-4 floor — it runs against
/// the user's local Ollama and needs no cloud subscription, which is why
/// `cli_platform_resolver.py` slots it last in the quota-fallback chain. The
/// other four runtimes need either a tenant-stored OAuth token (server
/// dispatch) or a local credential file (client dispatch via `ap`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeId {
    ClaudeCode,
    Codex,
    GeminiCli,
    CopilotCli,
    OpenCode,
}

impl RuntimeId {
    /// Canonical wire/audit name. Stable; do not change without server-side
    /// migration (the orchestration audit log queries by this value).
    pub fn as_wire(&self) -> &'static str {
        match self {
            RuntimeId::ClaudeCode => "claude_code",
            RuntimeId::Codex => "codex",
            RuntimeId::GeminiCli => "gemini_cli",
            RuntimeId::CopilotCli => "copilot_cli",
            // Server-side wire id is the bare "opencode" string (see
            // apps/api/app/services/cli_platform_resolver.py:60), not
            // "opencode_cli" — matches the npm package name (opencode-ai)
            // and the binary on PATH.
            RuntimeId::OpenCode => "opencode",
        }
    }

    /// Binary name to look up on `PATH`. Different from the wire name (the
    /// binary `claude` corresponds to the wire id `claude_code`).
    pub fn binary_name(&self) -> &'static str {
        match self {
            RuntimeId::ClaudeCode => "claude",
            RuntimeId::Codex => "codex",
            RuntimeId::GeminiCli => "gemini",
            RuntimeId::CopilotCli => "copilot",
            RuntimeId::OpenCode => "opencode",
        }
    }

    /// User-actionable install hint shown when preflight fails. Kept short —
    /// detailed install docs live on the runtime vendors' sites.
    pub fn install_hint(&self) -> &'static str {
        match self {
            RuntimeId::ClaudeCode => "Install with: npm i -g @anthropic-ai/claude-code",
            RuntimeId::Codex => "Install with: npm i -g @openai/codex (or: brew install codex)",
            RuntimeId::GeminiCli => "Install with: npm i -g @google/gemini-cli",
            RuntimeId::CopilotCli => "Install with: gh extension install github/gh-copilot",
            // OpenCode is the local-Gemma fallback — pair with a running
            // Ollama (`brew install ollama && ollama pull gemma4`) for the
            // intended zero-cloud-cost experience.
            RuntimeId::OpenCode => {
                "Install with: npm i -g opencode-ai (needs local Ollama + gemma4)"
            }
        }
    }

    /// Parse from the wire-format string. Returns `None` for unknown inputs
    /// so the caller can render a "supported runtimes: …" error rather than
    /// panic. The five canonical names are accepted, plus `gemini` and
    /// `copilot` as short aliases that users will reach for.
    pub fn from_wire(s: &str) -> Option<Self> {
        match s {
            "claude_code" | "claude-code" => Some(RuntimeId::ClaudeCode),
            "codex" => Some(RuntimeId::Codex),
            "gemini_cli" | "gemini-cli" | "gemini" => Some(RuntimeId::GeminiCli),
            "copilot_cli" | "copilot-cli" | "copilot" => Some(RuntimeId::CopilotCli),
            // OpenCode has no `_cli`/`-cli` variant on the server (the wire
            // id is the bare word) but accept the suffixed forms anyway —
            // users coming from the other four naturally type them.
            "opencode" | "opencode_cli" | "opencode-cli" => Some(RuntimeId::OpenCode),
            _ => None,
        }
    }

    /// All five — useful for `--parallel` fan-out plumbing (Section 9 of
    /// the plan) and for `ap status` enumeration.
    pub fn all() -> &'static [RuntimeId] {
        &[
            RuntimeId::ClaudeCode,
            RuntimeId::Codex,
            RuntimeId::GeminiCli,
            RuntimeId::CopilotCli,
            RuntimeId::OpenCode,
        ]
    }
}

/// Result of inspecting the local machine for a runtime binary. Designed to
/// be cheap (one PATH lookup + one `--version`) so `ap status` can render
/// the full matrix in <500ms without a network call.
#[derive(Debug, Clone, Serialize)]
pub struct PreflightReport {
    pub runtime: RuntimeId,
    pub binary_path: Option<PathBuf>,
    pub version: Option<String>,
    /// True when a runtime-local credential file is present (e.g.
    /// `~/.claude/.credentials.json`, `~/.codex/auth.json`). We don't read
    /// or validate the contents — presence is enough to tell the user
    /// whether they need `--use-tenant-token`.
    pub local_auth_present: bool,
    pub install_hint: &'static str,
}

impl PreflightReport {
    /// True iff the binary is installed and resolves to an executable file.
    /// Local-auth presence is informational; `ap run` can fall back to a
    /// tenant token even without local creds.
    pub fn is_runnable(&self) -> bool {
        self.binary_path.is_some()
    }
}

/// Detect a single runtime. Synchronous on purpose — `which` + `--version`
/// are cheap and blocking is fine in CLI startup paths.
pub fn preflight(runtime: RuntimeId) -> PreflightReport {
    let binary_path = which::which(runtime.binary_name()).ok();
    let version = binary_path
        .as_ref()
        .and_then(|p| detect_version(p, runtime));
    let local_auth_present = detect_local_auth(runtime);
    PreflightReport {
        runtime,
        binary_path,
        version,
        local_auth_present,
        install_hint: runtime.install_hint(),
    }
}

/// Detect every runtime in one shot. Used by `ap status` and by the
/// `--parallel` flow's gating loop.
pub fn preflight_all() -> Vec<PreflightReport> {
    RuntimeId::all().iter().copied().map(preflight).collect()
}

fn detect_version(binary: &std::path::Path, runtime: RuntimeId) -> Option<String> {
    // Each runtime exposes its version through `<bin> --version`; we don't
    // try to parse the output's exact format because the four runtimes
    // disagree on whether they print "v0.37.1" / "0.37.1" / "claude-code
    // 0.4.0" — the raw string is good enough for `ap status` display and
    // for issue reports.
    let _ = runtime; // currently the same flag for all four
    let out = std::process::Command::new(binary)
        .arg("--version")
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    // Multi-line --version output is common (Copilot CLI prints a version
    // line plus an "auto-update available" hint). Keep only the first
    // non-blank line so `ap status` table stays one row per runtime.
    let s = String::from_utf8_lossy(&out.stdout);
    let first = s.lines().find(|l| !l.trim().is_empty())?.trim().to_string();
    if first.is_empty() {
        None
    } else {
        Some(first)
    }
}

fn detect_local_auth(runtime: RuntimeId) -> bool {
    let home = match dirs::home_dir() {
        Some(h) => h,
        None => return false,
    };
    // Conservative — we only check the most common credential locations,
    // not every legacy path. False negatives are harmless: the worst the
    // CLI does is offer `--use-tenant-token` when the user already had
    // local creds.
    let candidates: &[&str] = match runtime {
        RuntimeId::ClaudeCode => &[".claude/.credentials.json"],
        RuntimeId::Codex => &[".codex/auth.json"],
        RuntimeId::GeminiCli => &[".gemini/oauth_creds.json", ".gemini/credentials.json"],
        RuntimeId::CopilotCli => &[".copilot/mcp-config.json"],
        // OpenCode stores its provider auth (Ollama base URL + selected
        // model) in `~/.local/share/opencode/auth.json`. Config-only
        // `~/.config/opencode/opencode.json` is enough to count as
        // "local auth present" too — it's how users typically pin the
        // model — so accept either path. Both are macOS/Linux conventions;
        // Windows users get a false negative (harmless) until we add the
        // %APPDATA% path.
        RuntimeId::OpenCode => &[
            ".local/share/opencode/auth.json",
            ".config/opencode/opencode.json",
        ],
    };
    candidates.iter().any(|rel| home.join(rel).is_file())
}

/// Token returned by the user-scoped mint endpoint, ready to drop into a
/// runtime's auth env-var or config file.
#[derive(Debug, Clone, Deserialize)]
pub struct MintedAgentToken {
    pub token: String,
    pub agent_id: String,
    pub task_id: String,
    /// TTL in seconds from mint time. Recorded as a duration not an
    /// absolute timestamp so clock skew between client and server doesn't
    /// matter for the leaf's "is my token still valid" check.
    pub expires_in_seconds: i64,
}

#[derive(Debug, Serialize)]
struct MintBody<'a> {
    agent_id: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    scope: Option<&'a [String]>,
    #[serde(skip_serializing_if = "Option::is_none")]
    heartbeat_timeout_seconds: Option<u32>,
}

/// `POST /api/v1/agent-tokens/mint` — request an agent-scoped JWT for a
/// local subprocess. The server-side gate requires editor/owner permission
/// on the agent; viewers get 403.
///
/// `scope` narrows the agent's tool allowlist for this dispatch only
/// (intersection semantics, never widens). `heartbeat_timeout_seconds`
/// controls token TTL (server multiplies by 2 for `exp`). Both are
/// optional — `None` uses the server defaults.
pub async fn mint_agent_token_for_runtime(
    client: &ApiClient,
    runtime: RuntimeId,
    agent_id: &str,
    scope: Option<&[String]>,
    heartbeat_timeout_seconds: Option<u32>,
) -> Result<MintedAgentToken> {
    // `runtime` doesn't currently propagate into the request body — the
    // server endpoint mints purely off agent_id today. The parameter is
    // here on the public signature because PR-2 plans to pass it through
    // for audit-log routing (knowing which leaf binary the token was
    // minted for is useful for forensic queries later).
    let _ = runtime;

    let body = MintBody {
        agent_id,
        scope,
        heartbeat_timeout_seconds,
    };
    let req = client
        .request(reqwest::Method::POST, "/api/v1/agent-tokens/mint")?
        .json(&body);
    let resp = client.send_json::<MintedAgentToken>(req).await?;
    if resp.token.is_empty() {
        return Err(Error::Other(
            "agent-tokens/mint returned empty token".into(),
        ));
    }
    Ok(resp)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wire_round_trip() {
        for r in RuntimeId::all() {
            assert_eq!(RuntimeId::from_wire(r.as_wire()), Some(*r));
        }
        // Common short aliases users will type
        assert_eq!(RuntimeId::from_wire("gemini"), Some(RuntimeId::GeminiCli));
        assert_eq!(RuntimeId::from_wire("copilot"), Some(RuntimeId::CopilotCli));
        // Hyphenated form (clap default for kebab-case enum values)
        assert_eq!(
            RuntimeId::from_wire("claude-code"),
            Some(RuntimeId::ClaudeCode)
        );
        // OpenCode tolerates `_cli` / `-cli` suffixes that users from the
        // other four runtimes naturally type, even though the canonical
        // wire id is the bare word.
        assert_eq!(RuntimeId::from_wire("opencode"), Some(RuntimeId::OpenCode));
        assert_eq!(
            RuntimeId::from_wire("opencode-cli"),
            Some(RuntimeId::OpenCode)
        );
        assert_eq!(
            RuntimeId::from_wire("opencode_cli"),
            Some(RuntimeId::OpenCode)
        );
        assert!(RuntimeId::from_wire("unknown").is_none());
    }

    #[test]
    fn binary_names_distinct() {
        let mut seen = std::collections::HashSet::new();
        for r in RuntimeId::all() {
            assert!(seen.insert(r.binary_name()), "duplicate binary: {:?}", r);
        }
    }

    #[test]
    fn preflight_returns_for_each_runtime() {
        // We can't assert binaries are present in CI — we only assert
        // that preflight runs without panic and yields one report per
        // runtime regardless of host install state.
        let reports = preflight_all();
        assert_eq!(reports.len(), 5);
        for (i, r) in reports.iter().enumerate() {
            assert_eq!(r.runtime, RuntimeId::all()[i]);
            assert!(!r.install_hint.is_empty());
        }
    }

    #[test]
    fn opencode_wire_matches_server() {
        // Server-side wire id is the bare "opencode" string (see
        // apps/api/app/services/cli_platform_resolver.py:60). Locking
        // it in here so a future refactor can't silently rename the
        // client-side wire to "opencode_cli" and break the round-trip
        // through the messages audit log.
        assert_eq!(RuntimeId::OpenCode.as_wire(), "opencode");
    }
}
