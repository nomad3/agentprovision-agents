//! Client-side wedge-source scanners for `ap quickstart`.
//!
//! Each submodule owns one wedge channel from the design doc §3 and
//! exposes a `scan()` function returning a normalized item list ready
//! to POST to `/api/v1/memory/training/bulk-ingest`. The CLI never
//! uploads raw conversation bodies — only extracted metadata
//! (project paths, timestamps, derived topics, repo names). Privacy
//! semantics are part of each scanner's docstring.
//!
//! Each `scan()` returns `Result<Vec<serde_json::Value>>` keyed by
//! item shape the server-side `extract_and_persist_batch` activity
//! understands (see PR-Q3a-back follow-up for the per-source
//! extraction adapter).

pub mod local_ai_cli;

pub use local_ai_cli::{scan as scan_local_ai_cli, LocalAiCliSnapshot};
