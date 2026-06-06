//! Durable Stop latch persistence.
//!
//! The emergency Stop is a hard local safety control that must survive app
//! relaunch (control plan `Stop Semantics` #5): once the user latches Stop,
//! Luna comes back STOPPED until the user *explicitly* clears it. The previous
//! baseline only held the stop in an in-memory `AtomicU8`, so a relaunch silently
//! cleared the latch back to `control_locked` — the opposite of the plan.
//!
//! These are pure filesystem helpers (no `AppHandle`) so they can be unit
//! tested. `lib.rs` calls them with `app.path().app_data_dir()` on stop, clear,
//! and startup.

use std::path::Path;

/// File written under the Tauri app-data dir while Stop is latched.
const STOP_MARKER: &str = "desktop-control-stop";

/// Persist (or clear) the durable Stop latch in `dir`.
///
/// When `stopped` is true, writes `STOP_MARKER` containing the stop timestamp
/// (unix ms) so the UI can show when Stop was latched. When false, removes the
/// marker (idempotent — clearing an absent latch is a no-op success).
pub fn persist_stop(dir: &Path, stopped: bool, at_ms: u64) -> Result<(), String> {
    let path = dir.join(STOP_MARKER);
    if stopped {
        std::fs::create_dir_all(dir)
            .map_err(|e| format!("create app data dir for stop latch: {e}"))?;
        std::fs::write(&path, format!("{at_ms}\n"))
            .map_err(|e| format!("persist stop latch: {e}"))?;
    } else if path.exists() {
        std::fs::remove_file(&path).map_err(|e| format!("clear stop latch: {e}"))?;
    }
    Ok(())
}

/// Load the durable Stop latch from `dir`.
///
/// Returns `Some(at_ms)` when Stop is latched (marker present), `None`
/// otherwise. A present-but-unparseable marker still counts as stopped and
/// returns `Some(0)` — fail-safe toward the safest posture rather than silently
/// un-stopping on a corrupt file.
pub fn load_stop(dir: &Path) -> Option<u64> {
    let path = dir.join(STOP_MARKER);
    match std::fs::read_to_string(&path) {
        Ok(raw) => Some(raw.trim().parse::<u64>().unwrap_or(0)),
        Err(_) => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;
    use std::path::PathBuf;

    fn scratch_dir() -> PathBuf {
        std::env::temp_dir().join(format!("luna-stop-test-{}", uuid::Uuid::new_v4()))
    }

    #[test]
    fn load_stop_is_none_on_fresh_dir() {
        let dir = scratch_dir();
        assert_eq!(load_stop(&dir), None, "fresh dir has no stop latch");
    }

    #[test]
    fn persist_then_load_roundtrips_timestamp() {
        let dir = scratch_dir();
        persist_stop(&dir, true, 1_717_000_123).expect("persist stop");
        assert_eq!(
            load_stop(&dir),
            Some(1_717_000_123),
            "latched Stop must survive a fresh load with its timestamp"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn clearing_stop_removes_latch() {
        let dir = scratch_dir();
        persist_stop(&dir, true, 42).expect("persist stop");
        persist_stop(&dir, false, 0).expect("clear stop");
        assert_eq!(load_stop(&dir), None, "explicit clear must drop the latch");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn corrupt_marker_is_treated_as_stopped() {
        let dir = scratch_dir();
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join(STOP_MARKER), "not-a-number").unwrap();
        assert_eq!(
            load_stop(&dir),
            Some(0),
            "a corrupt latch must fail safe to stopped, not silently un-stop"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn clear_when_absent_is_idempotent() {
        let dir = scratch_dir();
        persist_stop(&dir, false, 0).expect("clearing an absent latch is a no-op success");
        assert_eq!(load_stop(&dir), None);
    }
}
