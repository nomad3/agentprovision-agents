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
//!   "kind": "local_ai_session" | "local_user_identity",
//!   "runtime": "claude_code" | ...,    // only for sessions
//!   "project_path": "/Users/.../repo", // optional
//!   "started_at": "2026-…",            // ISO-ish; may be naive
//!   "last_message_at": "2026-…",
//!   "message_count": 42,
//!   "derived_topic_hint": "…first user message preview, ≤200 chars…"
//! }
//! ```
//!
//! (Earlier drafts of this doc listed `local_repo` as a kind — Q3a does
//! not emit it. `git remote` based repo discovery is queued as a Q3a-
//! back follow-up but isn't shipping in this PR.)

use std::fs;
use std::io::{BufRead, BufReader};
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
     • ~/.claude/projects/*  (Claude Code session metadata)\n\
     • ~/.codex/sessions/*   (Codex session metadata)\n\
     • ~/.gemini/sessions/*  (Gemini CLI session metadata)\n\
     • ~/.local/share/opencode/exports/*  (OpenCode session metadata)\n\
     \n\
     I WILL upload (per session): runtime + project_path + timestamps +\n\
     message_count + the first 200 chars of your opening user message\n\
     in that session as a 'derived_topic_hint'. Pass --no-topic-hints\n\
     to omit the topic hint entirely.\n\
     \n\
     I will NOT upload:\n\
     • full conversation bodies (messages 2..N stay on disk)\n\
     • credentials / OAuth tokens\n\
     • files outside the directories above\n\
     • directories reached through symlinks (symlinked entries are\n\
       skipped to avoid loops + cross-tree leakage)"
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
    let exports = home
        .join(".local")
        .join("share")
        .join("opencode")
        .join("exports");
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
///
/// **Skips symlinks.** `fs::read_dir` follows symlinks by default,
/// which means a `~/.claude/projects → $HOME` link would have the
/// scanner enumerating unrelated files as session JSONLs. Reviewer
/// (PR #406 finding #2) called this out — the loop is bounded by
/// `max_depth` so no infinite traversal, but cross-tree leakage was
/// still undesirable. `entry.file_type()` returns the entry's own
/// type (not the link target), so an `is_symlink()` check skips
/// links regardless of what they point to.
fn walk_dir(root: &Path, max_depth: usize) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack: Vec<(PathBuf, usize)> = vec![(root.to_path_buf(), 0)];
    while let Some((dir, depth)) = stack.pop() {
        let entries = match fs::read_dir(&dir) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for entry in entries.flatten() {
            // Skip symlinks regardless of what they target. Saves us
            // from infinite loops AND from cross-tree leakage when a
            // user has a `~/.claude/projects` symlinked into `$HOME`.
            if let Ok(ft) = entry.file_type() {
                if ft.is_symlink() {
                    continue;
                }
            }
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
/// `-Users-nomade-Documents-GitHub-agentprovision-agents` for
/// `/Users/nomade/Documents/GitHub/agentprovision-agents`).
/// Decode by reversing the substitution.
fn decode_claude_project_dir_name(dir: &Path) -> Option<String> {
    let name = dir.file_name().and_then(|s| s.to_str())?;
    if name.starts_with('-') {
        // Replace `-` with `/` only if the result looks like an
        // absolute path. Otherwise return the raw name (a future
        // encoding change shouldn't crash the scan).
        let decoded: String = name
            .chars()
            .map(|c| if c == '-' { '/' } else { c })
            .collect();
        if decoded.starts_with('/') {
            return Some(decoded);
        }
    }
    Some(name.to_string())
}

/// Open a JSONL session file and return (started_at, last_message_at,
/// count, first-user-msg-preview). Cheap: only the first line and
/// the last line are JSON-parsed; the rest of the file is streamed
/// to count + locate the last non-empty line. Reviewer (PR #406
/// finding #3) caught that `fs::read_to_string` loads the whole
/// file into memory — a 200MB Claude session × 100 capped sessions
/// = 20GB RSS on a pathological tenant. BufReader streaming bounds
/// resident memory to one line at a time.
fn read_jsonl_session_meta(
    path: &Path,
    project_path: Option<&str>,
    opts: &ScanOptions,
) -> Option<SessionMeta> {
    let file = fs::File::open(path).ok()?;
    let reader = BufReader::new(file);

    let mut first_line: Option<String> = None;
    let mut last_nonempty_line: Option<String> = None;
    let mut nonempty_count: usize = 0;
    for line in reader.lines().map_while(std::result::Result::ok) {
        if line.is_empty() {
            continue;
        }
        if first_line.is_none() {
            first_line = Some(line.clone());
        }
        nonempty_count += 1;
        last_nonempty_line = Some(line);
    }
    let first_line = first_line?;
    if nonempty_count == 0 {
        return None;
    }
    // Synthesise a fake `lines` vec for the rest of the function so
    // the downstream first/last extraction logic stays identical.
    let lines: Vec<&str> = std::iter::once(first_line.as_str())
        .chain(
            last_nonempty_line
                .as_deref()
                .filter(|s| *s != first_line.as_str()),
        )
        .collect();

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
        // Use the streamed `nonempty_count` rather than `lines.len()`
        // — the new BufReader path collapses `lines` to {first, last}
        // (or just {first}) because we no longer materialise the
        // entire file into memory. The streamed counter is the only
        // place the true message count lives.
        message_count: nonempty_count,
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
                    arr.iter()
                        .find_map(|x| x.get("text").and_then(|t| t.as_str()).map(str::to_string))
                })
            } else {
                None
            }
        })
        .or_else(|| v.get("text").and_then(|t| t.as_str()).map(str::to_string))
        .or_else(|| {
            v.get("message")
                .and_then(|m| m.as_str())
                .map(str::to_string)
        })?;
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
        assert_eq!(
            meta.last_message_at.as_deref(),
            Some("2026-05-12T00:02:00Z")
        );
        assert_eq!(
            meta.derived_topic_hint.as_deref(),
            Some("please fix the build")
        );
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

    /// Public-API smoke test (reviewer NIT #7): `scan()` must not
    /// crash even when invoked with no AI CLIs installed and no
    /// session history on disk. We can't fully fake `$HOME` from
    /// safe Rust, so this only asserts the public path is robust
    /// against `to_items()` panic + serialisation. The host's git
    /// config may or may not leak in — we don't assert on that.
    #[test]
    fn scan_smoke_does_not_crash() {
        let snap = scan(ScanOptions::default()).expect("scan must not error");
        // to_items must always serialise cleanly, even if all
        // per-runtime scanners returned empty.
        let items = snap.to_items();
        for it in &items {
            // each item has a non-empty `kind` field
            assert!(it.get("kind").and_then(|v| v.as_str()).is_some());
        }
    }

    /// Reviewer NIT #3 (PR #406): streaming reader must handle large
    /// files without loading them whole. We can't easily build a
    /// 200MB fixture in unit tests, but we can prove the streaming
    /// path correctly counts a file whose lines exceed the previous
    /// implementation's `Vec<&str>` materialisation overhead.
    #[test]
    fn streaming_parser_counts_many_lines() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("big.jsonl");
        {
            let mut f = fs::File::create(&path).unwrap();
            // 1000 messages — small enough for the test to be fast,
            // large enough that any "load whole file" regression
            // would show up in CI memory profilers.
            for i in 0..1000 {
                writeln!(
                    f,
                    "{}",
                    serde_json::to_string(&serde_json::json!({
                        "role": if i == 0 { "user" } else { "assistant" },
                        "content": "...",
                        "timestamp": format!("2026-05-12T00:00:{:02}Z", (i % 60)),
                    }))
                    .unwrap()
                )
                .unwrap();
            }
        }
        let meta = read_jsonl_session_meta(&path, Some("/p"), &ScanOptions::default()).unwrap();
        assert_eq!(meta.message_count, 1000);
    }
}
