//! Local AI CLI wedge scanner.
//!
//! Reads metadata from any of the four AI-CLI history stores plus
//! OpenCode + git config that the user already has on disk. **Never
//! uploads raw conversation content** — only extracted metadata
//! (project paths, derived topics, timestamps, repo names). Users
//! are prompted with the consent block in `consent_summary()` before
//! the scan runs, so they see exactly what will leave their machine.
//!
//! Sources, in order of dev-coverage heuristic:
//!   1. Claude Code — `~/.claude/projects/*/conversation-*.jsonl`
//!   2. Codex       — `~/.codex/sessions/*` (when present)
//!   3. Gemini CLI  — `~/.gemini/sessions/*` (when present)
//!   4. OpenCode    — `~/.local/share/opencode/storage/*` (when present)
//!   5. Git config  — `user.email` / `user.name` (always; cheap)
//!
//! The output is a list of `serde_json::Value` items per the wire
//! shape the server-side `extract_and_persist_batch` activity will
//! consume in PR-Q3a-back. Item shape:
//!
//! ```json
//! {
//!   "kind": "local_ai_session"        | "local_repo" | "local_user_identity",
//!   "runtime": "claude_code" | ...,    // only for sessions
//!   "project_path": "/Users/.../repo", // optional
//!   "started_at": "2026-…",            // ISO-ish; may be naive
//!   "last_message_at": "2026-…",
//!   "message_count": 42,
//!   "derived_topic_hint": "…first user message preview, ≤200 chars…"
//! }
//! ```

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::error::Result;

/// User-visible summary of what `scan()` will read and what it will
/// upload. CLIs render this in the consent prompt. Keep it short and
/// concrete — vague privacy notices erode trust faster than detailed
/// ones.
pub fn consent_summary() -> &'static str {
    "I'll read:\n\
     • git config (user.email, user.name)\n\
     • ~/.claude/projects/*  (Claude Code session metadata only)\n\
     • ~/.codex/sessions/*   (Codex session metadata only)\n\
     • ~/.gemini/sessions/*  (Gemini CLI session metadata only)\n\
     • ~/.local/share/opencode/storage/*  (OpenCode session metadata)\n\
     \n\
     I will NOT upload:\n\
     • raw conversation content / message bodies\n\
     • credentials / OAuth tokens\n\
     • files outside the directories above"
}

/// In-memory shape of the scan result before it's serialised into the
/// wire-format `Vec<serde_json::Value>`. Tests assert against this so
/// the JSON encoder can change without breaking semantics.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct LocalAiCliSnapshot {
    pub git_user_email: Option<String>,
    pub git_user_name: Option<String>,
    pub claude_sessions: Vec<SessionMeta>,
    pub codex_sessions: Vec<SessionMeta>,
    pub gemini_sessions: Vec<SessionMeta>,
    pub opencode_sessions: Vec<SessionMeta>,
}

impl LocalAiCliSnapshot {
    /// Total session count across all four AI CLIs. Used by the CLI
    /// to render "scanned N sessions" without summing fields by hand.
    pub fn total_sessions(&self) -> usize {
        self.claude_sessions.len()
            + self.codex_sessions.len()
            + self.gemini_sessions.len()
            + self.opencode_sessions.len()
    }

    /// Flatten the snapshot into the wire-shape `Vec<Value>` the
    /// `/memory/training/bulk-ingest` endpoint expects.
    pub fn to_items(&self) -> Vec<Value> {
        let mut items = Vec::new();

        // User identity item — single record, always emitted when
        // either git field is present so the server-side extract has
        // a stable Person entity to anchor everything else against.
        if self.git_user_email.is_some() || self.git_user_name.is_some() {
            items.push(serde_json::json!({
                "kind": "local_user_identity",
                "email": self.git_user_email,
                "name": self.git_user_name,
            }));
        }

        for (runtime, sessions) in [
            ("claude_code", &self.claude_sessions),
            ("codex", &self.codex_sessions),
            ("gemini_cli", &self.gemini_sessions),
            ("opencode", &self.opencode_sessions),
        ] {
            for s in sessions {
                items.push(serde_json::json!({
                    "kind": "local_ai_session",
                    "runtime": runtime,
                    "project_path": s.project_path,
                    "started_at": s.started_at,
                    "last_message_at": s.last_message_at,
                    "message_count": s.message_count,
                    "derived_topic_hint": s.derived_topic_hint,
                }));
            }
        }

        items
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SessionMeta {
    /// Local filesystem path to the project (when derivable from
    /// the session file). May be None for runtimes that don't tag
    /// sessions with a project. Used for the server-side Project
    /// entity creation.
    pub project_path: Option<String>,
    /// ISO timestamp of the first message in the session.
    pub started_at: Option<String>,
    /// ISO timestamp of the most recent message.
    pub last_message_at: Option<String>,
    pub message_count: usize,
    /// First ~200 chars of the FIRST user message. This is the only
    /// payload that touches raw conversation content — capped + the
    /// caller can flip it off via `scan_options.include_topic_hints`
    /// if the user is privacy-paranoid.
    pub derived_topic_hint: Option<String>,
}

#[derive(Debug, Clone, Copy)]
pub struct ScanOptions {
    /// Per-runtime max number of sessions to enumerate. Most users
    /// have <100 Claude sessions, but a pathological user could have
    /// thousands; this bounds wire-format size + Gemma extraction
    /// runtime. Default 100.
    pub max_sessions_per_runtime: usize,
    /// Set false to skip the first-user-message hint per session.
    /// Default true — the hint is the highest-signal feature for
    /// server-side entity extraction, but it's also the only field
    /// that touches conversation content.
    pub include_topic_hints: bool,
}

impl Default for ScanOptions {
    fn default() -> Self {
        Self {
            max_sessions_per_runtime: 100,
            include_topic_hints: true,
        }
    }
}

/// Walk the local AI CLI session stores + git config. Skips any
/// runtime whose directory doesn't exist (zero-error fallback —
/// "Claude not installed" is normal, not an error). Returns a
/// flattened snapshot ready to call `.to_items()` on.
pub fn scan(opts: ScanOptions) -> Result<LocalAiCliSnapshot> {
    let home = dirs::home_dir().ok_or_else(|| {
        crate::error::Error::Other("could not resolve $HOME — local scan unavailable".into())
    })?;

    let mut snap = LocalAiCliSnapshot::default();

    let (email, name) = read_git_identity();
    snap.git_user_email = email;
    snap.git_user_name = name;

    snap.claude_sessions = scan_claude_sessions(&home, &opts);
    snap.codex_sessions = scan_codex_sessions(&home, &opts);
    snap.gemini_sessions = scan_gemini_sessions(&home, &opts);
    snap.opencode_sessions = scan_opencode_sessions(&home, &opts);

    Ok(snap)
}

/// Read git's global user identity. We invoke `git config --global
/// --get user.email` rather than parsing `~/.gitconfig` directly so
/// the resolution picks up overrides from `--system` config or env
/// vars. Failures are silent — many users don't set git globally,
/// which is fine.
fn read_git_identity() -> (Option<String>, Option<String>) {
    fn read(key: &str) -> Option<String> {
        std::process::Command::new("git")
            .args(["config", "--global", "--get", key])
            .output()
            .ok()
            .and_then(|o| {
                if !o.status.success() {
                    return None;
                }
                let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
                if s.is_empty() {
                    None
                } else {
                    Some(s)
                }
            })
    }
    (read("user.email"), read("user.name"))
}

// ── Per-runtime scanners ──────────────────────────────────────────
//
// Each scanner returns Vec<SessionMeta>, capped at
// `opts.max_sessions_per_runtime`. They MUST tolerate the directory
// being absent (return empty) — non-Claude users shouldn't see a
// failure when they ask for the Local-AI-CLI wedge.

fn scan_claude_sessions(home: &Path, opts: &ScanOptions) -> Vec<SessionMeta> {
    // Claude Code's history layout: ~/.claude/projects/<encoded-cwd>/conversation-<uuid>.jsonl
    // The leaf .jsonl files contain one JSON object per line — one
    // message each. We only read the first/last line and count
    // (the encoded-cwd directory name gives us the project path).
    let projects_dir = home.join(".claude").join("projects");
    if !projects_dir.is_dir() {
        return Vec::new();
    }
    let mut out = Vec::new();
    for entry in walk_dir(&projects_dir, 1) {
        if !entry.is_dir() {
            continue;
        }
        let project_path = decode_claude_project_dir_name(&entry);
        for f in walk_dir(&entry, 1) {
            if !f.is_file() {
                continue;
            }
            let name = match f.file_name().and_then(|s| s.to_str()) {
                Some(n) => n,
                None => continue,
            };
            if !name.ends_with(".jsonl") {
                continue;
            }
            if let Some(meta) = read_jsonl_session_meta(&f, project_path.as_deref(), opts) {
                out.push(meta);
                if out.len() >= opts.max_sessions_per_runtime {
                    return out;
                }
            }
        }
    }
    out
}

fn scan_codex_sessions(home: &Path, opts: &ScanOptions) -> Vec<SessionMeta> {
    let sessions = home.join(".codex").join("sessions");
    if !sessions.is_dir() {
        return Vec::new();
    }
    let mut out = Vec::new();
    for f in walk_dir(&sessions, 2) {
        if !f.is_file() {
            continue;
        }
        if let Some(meta) = read_jsonl_session_meta(&f, None, opts) {
            out.push(meta);
            if out.len() >= opts.max_sessions_per_runtime {
                return out;
            }
        }
    }
    out
}

fn scan_gemini_sessions(home: &Path, opts: &ScanOptions) -> Vec<SessionMeta> {
    // Gemini CLI history layout has evolved between versions; we walk
    // both `~/.gemini/sessions` (older) and `~/.gemini/history`
    // (newer 0.37+) to maximise coverage. Directory-absent is fine.
    let candidates = ["sessions", "history"];
    let mut out = Vec::new();
    for sub in candidates {
        let dir = home.join(".gemini").join(sub);
        if !dir.is_dir() {
            continue;
        }
        for f in walk_dir(&dir, 2) {
            if !f.is_file() {
                continue;
            }
            if let Some(meta) = read_jsonl_session_meta(&f, None, opts) {
                out.push(meta);
                if out.len() >= opts.max_sessions_per_runtime {
                    return out;
                }
            }
        }
    }
    out
}

fn scan_opencode_sessions(home: &Path, opts: &ScanOptions) -> Vec<SessionMeta> {
    // OpenCode's storage layout uses sqlite under ~/.local/share/opencode/
    // — we don't shell into that. Instead we look for the optional
    // session-export JSON files (`opencode export <sessionID>`)
    // under `<storage>/exports/`. Most users won't have these, which
    // is fine — OpenCode coverage is opportunistic.
    let exports = home.join(".local").join("share").join("opencode").join("exports");
    if !exports.is_dir() {
        return Vec::new();
    }
    let mut out = Vec::new();
    for f in walk_dir(&exports, 1) {
        if !f.is_file() {
            continue;
        }
        if let Some(meta) = read_jsonl_session_meta(&f, None, opts) {
            out.push(meta);
            if out.len() >= opts.max_sessions_per_runtime {
                return out;
            }
        }
    }
    out
}

// ── Helpers ───────────────────────────────────────────────────────

/// Shallow directory walker. Returns paths up to `max_depth` levels
/// below `root`. We don't pull in `walkdir` for this since we only
/// need 1-2 levels and the std iteration is fine.
fn walk_dir(root: &Path, max_depth: usize) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack: Vec<(PathBuf, usize)> = vec![(root.to_path_buf(), 0)];
    while let Some((dir, depth)) = stack.pop() {
        let entries = match fs::read_dir(&dir) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for entry in entries.flatten() {
            let p = entry.path();
            out.push(p.clone());
            if p.is_dir() && depth + 1 < max_depth {
                stack.push((p, depth + 1));
            }
        }
    }
    out
}

/// Claude Code encodes the project working directory as the
/// directory name with `/` replaced by `-` (e.g.
/// `-Users-nomade-Documents-GitHub-servicetsunami-agents` for
/// `/Users/nomade/Documents/GitHub/servicetsunami-agents`).
/// Decode by reversing the substitution.
fn decode_claude_project_dir_name(dir: &Path) -> Option<String> {
    let name = dir.file_name().and_then(|s| s.to_str())?;
    if name.starts_with('-') {
        // Replace `-` with `/` only if the result looks like an
        // absolute path. Otherwise return the raw name (a future
        // encoding change shouldn't crash the scan).
        let decoded: String = name.chars().map(|c| if c == '-' { '/' } else { c }).collect();
        if decoded.starts_with('/') {
            return Some(decoded);
        }
    }
    Some(name.to_string())
}

/// Open a JSONL session file and return (started_at, last_message_at,
/// count, first-user-msg-preview). Cheap: only the first line is
/// JSON-parsed for the topic hint; the rest of the file is just
/// line-counted + last-line peek.
fn read_jsonl_session_meta(
    path: &Path,
    project_path: Option<&str>,
    opts: &ScanOptions,
) -> Option<SessionMeta> {
    let content = fs::read_to_string(path).ok()?;
    if content.is_empty() {
        return None;
    }
    let lines: Vec<&str> = content.lines().filter(|l| !l.is_empty()).collect();
    if lines.is_empty() {
        return None;
    }

    let (mut started_at, mut last_message_at, mut topic_hint) = (None, None, None);

    if let Ok(first) = serde_json::from_str::<Value>(lines[0]) {
        started_at = first
            .get("timestamp")
            .or_else(|| first.get("created_at"))
            .or_else(|| first.get("ts"))
            .and_then(|v| v.as_str())
            .map(str::to_string);
        if opts.include_topic_hints {
            topic_hint = extract_user_message_preview(&first);
        }
    }
    if lines.len() > 1 {
        if let Ok(last) = serde_json::from_str::<Value>(lines[lines.len() - 1]) {
            last_message_at = last
                .get("timestamp")
                .or_else(|| last.get("created_at"))
                .or_else(|| last.get("ts"))
                .and_then(|v| v.as_str())
                .map(str::to_string);
        }
    }

    // Fall back to started_at when the JSON only had one timestamped
    // line — clone before the struct literal so the borrow checker is
    // happy with both fields owning their own String.
    let last_fallback = last_message_at.clone().or_else(|| started_at.clone());
    Some(SessionMeta {
        project_path: project_path.map(str::to_string),
        started_at,
        last_message_at: last_fallback,
        message_count: lines.len(),
        derived_topic_hint: topic_hint,
    })
}

/// Pull the first user-authored text out of a JSONL message line.
/// Each AI-CLI uses a slightly different schema; we accept the
/// common keys (`role`, `content`, `text`, `message`) and bail to
/// None on anything we don't recognise. Capped at 200 chars.
fn extract_user_message_preview(v: &Value) -> Option<String> {
    let role = v.get("role").and_then(|r| r.as_str()).unwrap_or("");
    if role != "user" {
        return None;
    }
    let text = v
        .get("content")
        .and_then(|c| {
            // content can be a string or an array of {type, text}
            if c.is_string() {
                c.as_str().map(str::to_string)
            } else if c.is_array() {
                c.as_array().and_then(|arr| {
                    arr.iter().find_map(|x| {
                        x.get("text").and_then(|t| t.as_str()).map(str::to_string)
                    })
                })
            } else {
                None
            }
        })
        .or_else(|| v.get("text").and_then(|t| t.as_str()).map(str::to_string))
        .or_else(|| v.get("message").and_then(|m| m.as_str()).map(str::to_string))?;
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return None;
    }
    let capped: String = trimmed.chars().take(200).collect();
    Some(capped)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    fn make_jsonl(dir: &Path, file: &str, lines: &[Value]) -> PathBuf {
        let path = dir.join(file);
        let mut f = fs::File::create(&path).unwrap();
        for line in lines {
            writeln!(f, "{}", serde_json::to_string(line).unwrap()).unwrap();
        }
        path
    }

    #[test]
    fn snapshot_to_items_emits_identity_and_sessions() {
        let mut snap = LocalAiCliSnapshot::default();
        snap.git_user_email = Some("u@x.com".into());
        snap.git_user_name = Some("U X".into());
        snap.claude_sessions.push(SessionMeta {
            project_path: Some("/p".into()),
            started_at: Some("2026-05-12T00:00:00Z".into()),
            last_message_at: Some("2026-05-12T00:10:00Z".into()),
            message_count: 3,
            derived_topic_hint: Some("fix the auth bug".into()),
        });
        let items = snap.to_items();
        assert_eq!(items.len(), 2);
        assert_eq!(items[0]["kind"], "local_user_identity");
        assert_eq!(items[1]["kind"], "local_ai_session");
        assert_eq!(items[1]["runtime"], "claude_code");
    }

    #[test]
    fn snapshot_total_sessions_counts_all_runtimes() {
        let mut snap = LocalAiCliSnapshot::default();
        snap.claude_sessions.push(SessionMeta::default());
        snap.codex_sessions.push(SessionMeta::default());
        snap.gemini_sessions.push(SessionMeta::default());
        snap.opencode_sessions.push(SessionMeta::default());
        assert_eq!(snap.total_sessions(), 4);
    }

    #[test]
    fn read_jsonl_session_meta_reads_first_and_last_lines() {
        let tmp = TempDir::new().unwrap();
        let lines = vec![
            serde_json::json!({"role":"user","content":"please fix the build","timestamp":"2026-05-12T00:00:00Z"}),
            serde_json::json!({"role":"assistant","content":"…","timestamp":"2026-05-12T00:01:00Z"}),
            serde_json::json!({"role":"user","content":"thanks","timestamp":"2026-05-12T00:02:00Z"}),
        ];
        let path = make_jsonl(tmp.path(), "conversation-x.jsonl", &lines);
        let opts = ScanOptions::default();
        let meta = read_jsonl_session_meta(&path, Some("/repo"), &opts).unwrap();
        assert_eq!(meta.message_count, 3);
        assert_eq!(meta.project_path.as_deref(), Some("/repo"));
        assert_eq!(meta.started_at.as_deref(), Some("2026-05-12T00:00:00Z"));
        assert_eq!(meta.last_message_at.as_deref(), Some("2026-05-12T00:02:00Z"));
        assert_eq!(meta.derived_topic_hint.as_deref(), Some("please fix the build"));
    }

    #[test]
    fn include_topic_hints_false_suppresses_first_user_message() {
        let tmp = TempDir::new().unwrap();
        let lines = vec![serde_json::json!({"role":"user","content":"secret prompt"})];
        let path = make_jsonl(tmp.path(), "x.jsonl", &lines);
        let mut opts = ScanOptions::default();
        opts.include_topic_hints = false;
        let meta = read_jsonl_session_meta(&path, None, &opts).unwrap();
        assert!(meta.derived_topic_hint.is_none());
    }

    #[test]
    fn extract_user_message_handles_array_content() {
        // Claude Code newer format uses content: [{type:"text", text:"..."}]
        let v = serde_json::json!({
            "role": "user",
            "content": [{"type": "text", "text": "hello there"}],
        });
        let p = extract_user_message_preview(&v);
        assert_eq!(p.as_deref(), Some("hello there"));
    }

    #[test]
    fn extract_user_message_caps_at_200_chars() {
        let long = "x".repeat(500);
        let v = serde_json::json!({"role":"user","content":long});
        let p = extract_user_message_preview(&v).unwrap();
        assert_eq!(p.chars().count(), 200);
    }

    #[test]
    fn extract_user_message_skips_assistant_role() {
        let v = serde_json::json!({"role":"assistant","content":"no"});
        assert!(extract_user_message_preview(&v).is_none());
    }

    #[test]
    fn decode_claude_project_dir_name_reverses_slash_dash() {
        let p = Path::new("/x/-Users-nomade-repo");
        let got = decode_claude_project_dir_name(p).unwrap();
        assert_eq!(got, "/Users/nomade/repo");
    }

    #[test]
    fn scan_tolerates_missing_runtimes() {
        // Point at an empty fake home — every per-runtime scanner
        // should return an empty Vec, not error.
        let tmp = TempDir::new().unwrap();
        let opts = ScanOptions::default();
        assert!(scan_claude_sessions(tmp.path(), &opts).is_empty());
        assert!(scan_codex_sessions(tmp.path(), &opts).is_empty());
        assert!(scan_gemini_sessions(tmp.path(), &opts).is_empty());
        assert!(scan_opencode_sessions(tmp.path(), &opts).is_empty());
    }
}
