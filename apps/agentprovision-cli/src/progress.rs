//! Live progress emission for long-running commands.
//!
//! Two consumers, one source of truth:
//!
//! * **Humans at a terminal** see `[alpha] [t+12s] dispatched → claude-code`
//!   lines on stdout / stderr as state changes — these already existed in
//!   `run.rs` / `watch.rs` and remain. This module ADDS:
//!
//! * **Agents / CI / log scrapers** can opt into a machine-readable JSONL
//!   side-channel via `--events <PATH|->`. One line per state transition:
//!
//!   ```json
//!   {"ts":"2026-05-13T16:42:01Z","elapsed_ms":1234,"task_id":"t_a4f","event":"dispatched","status":"running","data":{"provider":"claude-code"}}
//!   ```
//!
//!   Stable shape: top-level keys are guaranteed; new fields land under
//!   `data` so old consumers keep parsing. `-` writes to stderr.
//!
//! The motivating user story is "agents driving alpha should know when
//! the task they spawned completed" — same shape as Temporal's history
//! events but local to a single invocation.

use anyhow::{Context, Result};
use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::Instant;

/// Stable wire-format for one progress emission. Field ordering matches
/// the JSONL example above — `ts` first so log scrapers can sort
/// chronologically by prefix. Internal — the public surface is just the
/// `Emitter::emit_*` helpers.
///
/// **Contract: all six top-level keys are always present.** Absent
/// task_id / status / data values serialize as JSON `null` rather than
/// being omitted, so a consumer doing `event["data"]["foo"]` (or
/// `event.task_id`) doesn't blow up on bare-`status` emissions.
/// Reviewer BLOCKER B1 on PR #444: previous `skip_serializing_if`
/// attrs broke the contract for the `submitted` / `terminal` paths
/// that don't carry data.
#[derive(Debug, Serialize, Deserialize)]
struct Event<'a> {
    ts: String,
    elapsed_ms: u128,
    task_id: Option<&'a str>,
    event: &'a str,
    status: Option<&'a str>,
    data: Value,
}

/// Where to write the JSONL stream. `Off` means "don't emit anything"
/// (default; preserves the legacy human-only experience). `Stderr` is
/// `--events -`. `File` opens the given path append-only.
#[derive(Clone)]
pub enum EventSink {
    Off,
    Stderr,
    File(Arc<Mutex<std::fs::File>>),
}

impl EventSink {
    /// Parse a `--events <value>` argument:
    ///   * empty / missing → `Off`
    ///   * `-` → `Stderr`
    ///   * any other string → `File(open(...))` (append, create-if-absent)
    pub fn from_arg(spec: Option<&str>) -> Result<Self> {
        match spec {
            None | Some("") => Ok(Self::Off),
            Some("-") => Ok(Self::Stderr),
            Some(path) => {
                let f = OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(Path::new(path))
                    .with_context(|| format!("failed to open --events file {path}"))?;
                Ok(Self::File(Arc::new(Mutex::new(f))))
            }
        }
    }

    fn write_line(&self, line: &str) {
        match self {
            Self::Off => {}
            Self::Stderr => {
                // eprintln! is line-buffered on TTY and unbuffered on
                // pipe → safe for log scrapers.
                eprintln!("{line}");
            }
            Self::File(f) => {
                if let Ok(mut g) = f.lock() {
                    // Best-effort: a write failure here shouldn't take
                    // down the command. The human-visible status line
                    // is the authoritative UX; this is the side-channel.
                    let _ = writeln!(g, "{line}");
                }
            }
        }
    }
}

/// Emits structured progress events on top of a configurable sink.
/// Cheap to clone (Arc inside). Pass it down through long-running
/// command pipelines so every layer can emit on its own timeline.
#[derive(Clone)]
pub struct ProgressEmitter {
    sink: EventSink,
    task_id: Option<String>,
    started: Instant,
}

impl ProgressEmitter {
    pub fn new(sink: EventSink) -> Self {
        Self {
            sink,
            task_id: None,
            started: Instant::now(),
        }
    }

    /// Bind a task id so subsequent events carry it. Returns self for
    /// chaining: `ProgressEmitter::new(sink).with_task("t_a4f")`.
    pub fn with_task(mut self, task_id: impl Into<String>) -> Self {
        self.task_id = Some(task_id.into());
        self
    }

    /// True iff the sink is `Off`. Used by callers to skip work that
    /// only matters for the event stream (e.g. building rich data
    /// payloads). Cheap inline check.
    pub fn is_active(&self) -> bool {
        !matches!(self.sink, EventSink::Off)
    }

    /// Emit one structured event. `data` is `null` when empty; pass
    /// `serde_json::json!({...})` for richer payloads.
    ///
    /// For payloads that are expensive to construct, prefer
    /// `emit_with` — that variant takes a `FnOnce` and short-circuits
    /// the construction entirely when the sink is `Off`.
    pub fn emit(&self, event: &str, status: Option<&str>, data: Value) {
        if !self.is_active() {
            return;
        }
        let ev = Event {
            ts: Utc::now().to_rfc3339(),
            elapsed_ms: self.started.elapsed().as_millis(),
            task_id: self.task_id.as_deref(),
            event,
            status,
            data,
        };
        match serde_json::to_string(&ev) {
            Ok(s) => self.sink.write_line(&s),
            // Should be impossible (all fields are Serialize) — log
            // through stderr as a last-resort breadcrumb.
            Err(e) => eprintln!("progress: serialize failure: {e}"),
        }
    }

    /// Convenience: a no-data status transition.
    pub fn status(&self, event: &str, status: &str) {
        self.emit(event, Some(status), Value::Null);
    }

    /// Lazy variant of `emit`. The `data` closure runs ONLY when the
    /// sink is active, so callers can construct large JSON payloads
    /// (e.g. `json!({"children": vec_iter.collect()})`) without paying
    /// the allocation cost when `--events` is unset. Reviewer
    /// IMPORTANT I1 on PR #444: previously the call sites materialised
    /// the payload before `is_active()` had a chance to short-circuit.
    pub fn emit_with<F>(&self, event: &str, status: Option<&str>, data_fn: F)
    where
        F: FnOnce() -> Value,
    {
        if !self.is_active() {
            return;
        }
        self.emit(event, status, data_fn());
    }

    /// Final "task complete" emission. Always fired on completion so
    /// agents have a single deterministic terminal event to wait on
    /// regardless of outcome. Used by `alpha watch` / `alpha coalition
    /// run` in follow-up wiring; kept here so the public surface is
    /// stable across the rollout.
    #[allow(dead_code)]
    pub fn terminal(&self, status: &str, data: Value) {
        self.emit("completed", Some(status), data);
    }
}

impl Default for ProgressEmitter {
    fn default() -> Self {
        Self::new(EventSink::Off)
    }
}

/// Human-side helper: a one-line status banner with elapsed seconds.
/// Returns "[t+12s]" / "[t+1m24s]" etc. — bounded width for steady
/// terminal rendering. Used alongside the JSONL emitter, not as a
/// replacement. Used by `alpha watch` in follow-up wiring.
#[allow(dead_code)]
pub fn elapsed_label(started: Instant) -> String {
    let s = started.elapsed().as_secs();
    if s < 60 {
        format!("[t+{s}s]")
    } else if s < 3600 {
        format!("[t+{}m{}s]", s / 60, s % 60)
    } else {
        format!("[t+{}h{}m]", s / 3600, (s / 60) % 60)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::io::Read as _;

    #[test]
    fn off_sink_emits_nothing() {
        let e = ProgressEmitter::new(EventSink::Off);
        e.emit("test", Some("running"), json!({"k": "v"}));
        // No assertion possible directly; just verify is_active is
        // false and the call doesn't panic.
        assert!(!e.is_active());
    }

    #[test]
    fn file_sink_writes_jsonl_with_required_keys() {
        let dir = std::env::temp_dir().join(format!("alpha-progress-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("events.jsonl");
        let _ = std::fs::remove_file(&path);

        let sink = EventSink::from_arg(Some(path.to_str().unwrap())).unwrap();
        let e = ProgressEmitter::new(sink).with_task("t_a4f");
        e.emit(
            "dispatched",
            Some("running"),
            json!({"provider": "claude-code"}),
        );
        e.terminal("succeeded", json!({"output_chars": 1234}));

        // Drop the emitter so the file lock releases.
        drop(e);

        let mut s = String::new();
        std::fs::File::open(&path)
            .unwrap()
            .read_to_string(&mut s)
            .unwrap();
        let lines: Vec<_> = s.lines().collect();
        assert_eq!(lines.len(), 2, "want 2 lines, got {s:?}");

        // Top-level shape is the agent contract — lock it down so a
        // future refactor doesn't silently break log-scraper consumers.
        let first: Value = serde_json::from_str(lines[0]).unwrap();
        assert_eq!(first["task_id"], "t_a4f");
        assert_eq!(first["event"], "dispatched");
        assert_eq!(first["status"], "running");
        assert_eq!(first["data"]["provider"], "claude-code");
        assert!(first["ts"].is_string());
        assert!(first["elapsed_ms"].is_u64() || first["elapsed_ms"].is_i64());
        // All six top-level keys MUST be present (BLOCKER B1 fix).
        let obj = first.as_object().expect("event is a json object");
        for k in ["ts", "elapsed_ms", "task_id", "event", "status", "data"] {
            assert!(obj.contains_key(k), "missing top-level key {k:?}: {first}");
        }

        let second: Value = serde_json::from_str(lines[1]).unwrap();
        assert_eq!(second["event"], "completed");
        assert_eq!(second["status"], "succeeded");
        assert_eq!(second["data"]["output_chars"], 1234);
    }

    #[test]
    fn status_call_serializes_data_as_null_not_missing() {
        // BLOCKER B1: a bare `status()` call (no data payload) must
        // still ship `data: null` so consumers doing `event["data"]`
        // get null rather than KeyError.
        let dir =
            std::env::temp_dir().join(format!("alpha-progress-status-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("status.jsonl");
        let _ = std::fs::remove_file(&path);

        let sink = EventSink::from_arg(Some(path.to_str().unwrap())).unwrap();
        let e = ProgressEmitter::new(sink);
        e.status("submitted", "running");
        drop(e);

        let mut s = String::new();
        std::fs::File::open(&path)
            .unwrap()
            .read_to_string(&mut s)
            .unwrap();
        let parsed: Value = serde_json::from_str(s.trim()).unwrap();
        let obj = parsed.as_object().unwrap();
        // `data` MUST be present and explicitly null (not absent).
        assert!(obj.contains_key("data"));
        assert!(parsed["data"].is_null(), "expected null, got {parsed}");
        // `task_id` likewise — absent task binding still serializes
        // the key with a null value so the wire contract holds.
        assert!(obj.contains_key("task_id"));
        assert!(parsed["task_id"].is_null());

        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_dir(&dir);
    }

    #[test]
    fn emit_with_does_not_invoke_closure_when_off() {
        // Reviewer I1: payload construction must short-circuit when
        // sink is Off. The closure should NEVER fire.
        use std::sync::atomic::{AtomicBool, Ordering};
        let fired = AtomicBool::new(false);
        let e = ProgressEmitter::new(EventSink::Off);
        e.emit_with("test", Some("running"), || {
            fired.store(true, Ordering::SeqCst);
            json!({"large_payload": "would-be-allocated"})
        });
        assert!(
            !fired.load(Ordering::SeqCst),
            "closure must not run when Off"
        );
    }

    #[test]
    fn from_arg_dash_means_stderr() {
        match EventSink::from_arg(Some("-")).unwrap() {
            EventSink::Stderr => {}
            other => panic!(
                "expected Stderr, got {other:?}",
                other = format!("{:?}", matches!(other, EventSink::Off))
            ),
        }
    }

    #[test]
    fn from_arg_none_means_off() {
        assert!(matches!(EventSink::from_arg(None).unwrap(), EventSink::Off));
        assert!(matches!(
            EventSink::from_arg(Some("")).unwrap(),
            EventSink::Off
        ));
    }

    #[test]
    fn elapsed_label_formats_buckets() {
        let now = Instant::now();
        // Can't easily mock Instant; just sanity-check current is
        // sub-second.
        let s = elapsed_label(now);
        assert!(s.starts_with("[t+") && s.ends_with(']'));
    }
}
