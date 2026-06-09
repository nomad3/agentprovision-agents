//! System cursor driver — moves the OS cursor and synthesizes clicks via
//! `enigo`. Gated behind two checks:
//!
//!   1. macOS Accessibility permission (`AXIsProcessTrusted`-ish via osascript).
//!   2. A user-controlled `cursor_global_mode` flag (default OFF). When OFF
//!      cursor moves only fire while Luna or Spatial HUD is the frontmost
//!      app, so a stray pinch doesn't click in some other app.
//!
//! Phase 4 improvements over the v1 from the gesture-system PR:
//!   - Display size read once at startup via `CGDisplayPixelsWide/High` so
//!     cursor coordinates work on Retina, multi-monitor, and non-1080p setups.
//!   - Frontmost-app check cached at 1Hz instead of shelling `osascript` per
//!     cursor frame. ~30× CPU reduction while pointing.

use std::sync::atomic::{AtomicBool, AtomicI64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use once_cell::sync::Lazy;
use tokio::sync::Mutex;

#[cfg(target_os = "macos")]
use enigo::{Button, Coordinate, Direction, Enigo, Key, Keyboard, Mouse, Settings};

static GLOBAL_MODE: AtomicBool = AtomicBool::new(false);
static ACCESSIBILITY_OK: AtomicBool = AtomicBool::new(false);

// Frontmost-Luna cache — refreshed at most once per FRONTMOST_TTL_MS.
static FRONTMOST_LAST_CHECK_MS: AtomicI64 = AtomicI64::new(0);
static FRONTMOST_IS_LUNA: AtomicBool = AtomicBool::new(false);
const FRONTMOST_TTL_MS: i64 = 1_000;

// Display dimensions cache. -1 = not yet read.
static DISPLAY_W: AtomicI64 = AtomicI64::new(-1);
static DISPLAY_H: AtomicI64 = AtomicI64::new(-1);

// `Enigo` on macOS holds a `NonNull<CGEventSource>` which is `!Send` because
// the raw pointer marker is conservative. Wrap it in a newtype that asserts
// `Send` so we can park it inside a `Lazy<Mutex<...>>` static. Safety: the
// surrounding `tokio::sync::Mutex` serializes all access to a single thread
// at a time, and Apple documents `CGEventCreate*` / `CGEventPost` family as
// thread-safe (the type is `!Send` only because rustc can't prove it).
#[cfg(target_os = "macos")]
struct SendEnigo(Enigo);

#[cfg(target_os = "macos")]
unsafe impl Send for SendEnigo {}

#[cfg(target_os = "macos")]
impl std::ops::Deref for SendEnigo {
    type Target = Enigo;
    fn deref(&self) -> &Enigo {
        &self.0
    }
}

#[cfg(target_os = "macos")]
impl std::ops::DerefMut for SendEnigo {
    fn deref_mut(&mut self) -> &mut Enigo {
        &mut self.0
    }
}

#[cfg(target_os = "macos")]
static ENIGO: Lazy<Mutex<Option<SendEnigo>>> = Lazy::new(|| Mutex::new(None));

pub fn set_global_mode(v: bool) {
    GLOBAL_MODE.store(v, Ordering::SeqCst);
}

pub fn global_mode() -> bool {
    GLOBAL_MODE.load(Ordering::SeqCst)
}

pub fn accessibility_ok() -> bool {
    ACCESSIBILITY_OK.load(Ordering::SeqCst)
}

// ---- Pre-native boundary guard (Phase 2.75 gesture-boundary hardening) ----
//
// The gesture cursor path is the only place that issues real CGEvent/enigo
// input. It must not actuate on the strength of `desktop_control_allows_
// actuation()` alone: if that single kill switch is ever flipped on, a stopped
// or ungoverned gesture path would bypass the Stop latch the command path
// enforces. This deny-by-default local Stop latch + pure guard close that gap.
// Today nothing clears the latch, so gesture actuation stays fully disabled.

/// Local Stop latch for the gesture actuation path. Defaults to `true`
/// (stopped) so a fresh process cannot drive the cursor even if the global
/// actuation kill switch is ever enabled.
static GESTURE_STOPPED: AtomicBool = AtomicBool::new(true);

/// Integration seam for the future Stop-aware control wiring (e.g. the desktop
/// Stop/Lock path). Currently uncalled in production, so the latch stays
/// engaged and gesture actuation remains closed.
#[allow(dead_code)]
pub(crate) fn set_gesture_stopped(v: bool) {
    GESTURE_STOPPED.store(v, Ordering::SeqCst);
}

pub(crate) fn gesture_stopped() -> bool {
    GESTURE_STOPPED.load(Ordering::SeqCst)
}

/// Pure pre-native boundary guard. Gesture move/click may proceed toward the
/// native adapter ONLY when the global actuation kill switch is on AND the
/// gesture path is not Stopped. Deny-by-default: `desktop_control_allows_
/// actuation()` alone is no longer sufficient to actuate.
pub(crate) fn gesture_native_boundary_allows(actuation_enabled: bool, stopped: bool) -> bool {
    actuation_enabled && !stopped
}

/// Phase 3 pointer-canary actuation guard. Distinct from the gesture-pinch path
/// above: the canary is governed by the per-capability pointer flag
/// (`LUNA_ACTUATION_POINTER_ENABLED`) plus the command-boundary proof and lease,
/// NOT the hard-disabled global `desktop_control_allows_actuation()` kill switch.
/// Pure + deny-by-default: a final live Stop re-check (`stopped`) still vetoes
/// even when the flag is on, so a flag flip alone cannot post an event while
/// Stop is latched.
pub(crate) fn canary_pointer_actuation_allowed(pointer_flag_enabled: bool, stopped: bool) -> bool {
    pointer_flag_enabled && !stopped
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

#[cfg(target_os = "macos")]
pub fn check_accessibility() -> bool {
    use std::process::Command;
    let ok = Command::new("osascript")
        .args([
            "-e",
            "tell application \"System Events\" to get name of first application process whose frontmost is true",
        ])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);
    ACCESSIBILITY_OK.store(ok, Ordering::SeqCst);
    ok
}

#[cfg(not(target_os = "macos"))]
pub fn check_accessibility() -> bool {
    false
}

#[cfg(target_os = "macos")]
fn probe_frontmost_luna_now() -> bool {
    use std::process::Command;
    Command::new("osascript")
        .args([
            "-e",
            "tell application \"System Events\" to get name of first application process whose frontmost is true",
        ])
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| {
            let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
            s == "Luna" || s == "luna"
        })
        .unwrap_or(false)
}

#[cfg(target_os = "macos")]
fn frontmost_is_luna_cached() -> bool {
    let now = now_ms();
    let last = FRONTMOST_LAST_CHECK_MS.load(Ordering::Relaxed);
    if now - last >= FRONTMOST_TTL_MS {
        let v = probe_frontmost_luna_now();
        FRONTMOST_IS_LUNA.store(v, Ordering::Relaxed);
        FRONTMOST_LAST_CHECK_MS.store(now, Ordering::Relaxed);
        v
    } else {
        FRONTMOST_IS_LUNA.load(Ordering::Relaxed)
    }
}

#[cfg(not(target_os = "macos"))]
fn frontmost_is_luna_cached() -> bool {
    false
}

/// Read main display size once; fall back to 1920×1080 if CG isn't available.
#[cfg(target_os = "macos")]
fn ensure_display_size() -> (i32, i32) {
    let cached_w = DISPLAY_W.load(Ordering::Relaxed);
    let cached_h = DISPLAY_H.load(Ordering::Relaxed);
    if cached_w > 0 && cached_h > 0 {
        return (cached_w as i32, cached_h as i32);
    }
    let (w, h) = read_main_display_size();
    DISPLAY_W.store(w as i64, Ordering::Relaxed);
    DISPLAY_H.store(h as i64, Ordering::Relaxed);
    (w, h)
}

#[cfg(target_os = "macos")]
fn read_main_display_size() -> (i32, i32) {
    // CGDirectDisplayID is u32 on macOS.
    extern "C" {
        fn CGMainDisplayID() -> u32;
        fn CGDisplayPixelsWide(display: u32) -> usize;
        fn CGDisplayPixelsHigh(display: u32) -> usize;
    }
    unsafe {
        let did = CGMainDisplayID();
        let w = CGDisplayPixelsWide(did) as i32;
        let h = CGDisplayPixelsHigh(did) as i32;
        if w > 0 && h > 0 {
            (w, h)
        } else {
            (1920, 1080)
        }
    }
}

#[cfg(not(target_os = "macos"))]
fn ensure_display_size() -> (i32, i32) {
    (1920, 1080)
}

/// Move the system cursor to absolute coordinates `(x, y)` in [0, 1] image
/// space. No-op if Accessibility is denied or if global_mode is OFF and
/// Luna isn't frontmost.
#[cfg(target_os = "macos")]
pub async fn move_abs(x: f32, y: f32) {
    // Pre-native boundary guard FIRST: deny before any native call unless the
    // kill switch is on AND the gesture path is not Stopped. Closes the bypass
    // where actuation depended on the single `desktop_control_allows_actuation`
    // bool and ignored the Stop latch.
    if !gesture_native_boundary_allows(crate::desktop_control_allows_actuation(), gesture_stopped())
    {
        return;
    }
    if !ACCESSIBILITY_OK.load(Ordering::SeqCst) {
        return;
    }
    if !GLOBAL_MODE.load(Ordering::SeqCst) && !frontmost_is_luna_cached() {
        return;
    }

    let (dw, dh) = ensure_display_size();
    let px = (x.clamp(0.0, 1.0) * dw as f32) as i32;
    let py = (y.clamp(0.0, 1.0) * dh as f32) as i32;

    let mut guard = ENIGO.lock().await;
    if guard.is_none() {
        *guard = Enigo::new(&Settings::default()).ok().map(SendEnigo);
    }
    if let Some(e) = guard.as_mut() {
        let _ = e.move_mouse(px, py, Coordinate::Abs);
    }
}

#[cfg(target_os = "macos")]
pub async fn click() {
    // Pre-native boundary guard FIRST: deny before any native call unless the
    // kill switch is on AND the gesture path is not Stopped. Closes the bypass
    // where actuation depended on the single `desktop_control_allows_actuation`
    // bool and ignored the Stop latch.
    if !gesture_native_boundary_allows(crate::desktop_control_allows_actuation(), gesture_stopped())
    {
        return;
    }
    if !ACCESSIBILITY_OK.load(Ordering::SeqCst) {
        return;
    }
    if !GLOBAL_MODE.load(Ordering::SeqCst) && !frontmost_is_luna_cached() {
        return;
    }

    let mut guard = ENIGO.lock().await;
    if guard.is_none() {
        *guard = Enigo::new(&Settings::default()).ok().map(SendEnigo);
    }
    if let Some(e) = guard.as_mut() {
        let _ = e.button(Button::Left, Direction::Click);
    }
}

#[cfg(not(target_os = "macos"))]
pub async fn move_abs(_x: f32, _y: f32) {}

#[cfg(not(target_os = "macos"))]
pub async fn click() {}

// ---- Phase 3 pointer canary actuation -----------------------------------
//
// A separate, command-boundary-governed actuation path. Unlike `move_abs` /
// `click` (the gesture-pinch path, gated on the hard-disabled global kill
// switch), these are called ONLY by the actuation command after a boundary
// proof + lease + live Stop/frontmost/bounds re-check have all passed. They
// must NOT re-impose the gesture-pinch frontmost/global-mode policy — the
// command path owns target binding. They still require Accessibility and
// surface a structured error instead of silently no-oping, so the command can
// audit the result.

/// Move the system cursor to normalized [0, 1] coordinates of the main display.
/// Caller MUST have proven the boundary + lease + live Stop/frontmost/bounds
/// first; this only performs the bounds clamp + the native move.
#[cfg(target_os = "macos")]
pub async fn canary_move_norm(norm_x: f64, norm_y: f64) -> Result<(), String> {
    // Gate on real macOS Accessibility (AX) trust (AXIsProcessTrusted via the
    // permissions module), NOT the osascript/System-Events-derived ACCESSIBILITY_OK
    // — that reflects Automation, a different permission the pointer canary does
    // not need (and which is often ungranted even when AX is).
    if !crate::computer_use::permissions::accessibility_trusted() {
        return Err("accessibility_denied".to_string());
    }
    let (dw, dh) = ensure_display_size();
    let px = (norm_x.clamp(0.0, 1.0) * dw as f64) as i32;
    let py = (norm_y.clamp(0.0, 1.0) * dh as f64) as i32;
    let mut guard = ENIGO.lock().await;
    if guard.is_none() {
        *guard = Enigo::new(&Settings::default()).ok().map(SendEnigo);
    }
    match guard.as_mut() {
        Some(e) => e
            .move_mouse(px, py, Coordinate::Abs)
            .map_err(|err| format!("enigo_move_failed: {err:?}")),
        None => Err("enigo_unavailable".to_string()),
    }
}

/// Synthesize a single left click at the current cursor position. Phase 3
/// allows left single-click only (no drag, no multi-click).
#[cfg(target_os = "macos")]
pub async fn canary_click() -> Result<(), String> {
    // Gate on real macOS Accessibility (AX) trust (AXIsProcessTrusted via the
    // permissions module), NOT the osascript/System-Events-derived ACCESSIBILITY_OK
    // — that reflects Automation, a different permission the pointer canary does
    // not need (and which is often ungranted even when AX is).
    if !crate::computer_use::permissions::accessibility_trusted() {
        return Err("accessibility_denied".to_string());
    }
    let mut guard = ENIGO.lock().await;
    if guard.is_none() {
        *guard = Enigo::new(&Settings::default()).ok().map(SendEnigo);
    }
    match guard.as_mut() {
        Some(e) => e
            .button(Button::Left, Direction::Click)
            .map_err(|err| format!("enigo_click_failed: {err:?}")),
        None => Err("enigo_unavailable".to_string()),
    }
}

/// Type a bounded plain-text string (Phase 4 keyboard canary). Caller MUST have
/// proven the boundary + lease + length bound + live Stop/frontmost/secure-input
/// first; this performs the AX gate + the native text input.
#[cfg(target_os = "macos")]
pub async fn canary_type_text(text: &str) -> Result<(), String> {
    if !crate::computer_use::permissions::accessibility_trusted() {
        return Err("accessibility_denied".to_string());
    }
    let mut guard = ENIGO.lock().await;
    if guard.is_none() {
        *guard = Enigo::new(&Settings::default()).ok().map(SendEnigo);
    }
    match guard.as_mut() {
        Some(e) => e
            .text(text)
            .map_err(|err| format!("enigo_text_failed: {err:?}")),
        None => Err("enigo_unavailable".to_string()),
    }
}

/// Send one allowlisted navigation/selection key chord (arrows + shift+arrows).
/// Re-validates the allowlist as defense-in-depth even though the command path
/// already checked it.
#[cfg(target_os = "macos")]
pub async fn canary_key_chord(keys: &[String]) -> Result<(), String> {
    use crate::computer_use::keyboard_bounds;
    if !crate::computer_use::permissions::accessibility_trusted() {
        return Err("accessibility_denied".to_string());
    }
    if !keyboard_bounds::chord_allowed(keys) {
        return Err("keyboard_chord_not_allowed".to_string());
    }
    let chord = keyboard_bounds::normalize_chord(keys);
    let shift = chord.starts_with("shift+");
    let Some(arrow) = arrow_key(chord.rsplit('+').next().unwrap_or("")) else {
        return Err("keyboard_chord_not_allowed".to_string());
    };
    let mut guard = ENIGO.lock().await;
    if guard.is_none() {
        *guard = Enigo::new(&Settings::default()).ok().map(SendEnigo);
    }
    let Some(e) = guard.as_mut() else {
        return Err("enigo_unavailable".to_string());
    };
    if shift {
        e.key(Key::Shift, Direction::Press)
            .map_err(|err| format!("enigo_key_failed: {err:?}"))?;
    }
    let click = e
        .key(arrow, Direction::Click)
        .map_err(|err| format!("enigo_key_failed: {err:?}"));
    if shift {
        let _ = e.key(Key::Shift, Direction::Release);
    }
    click
}

#[cfg(target_os = "macos")]
fn arrow_key(name: &str) -> Option<Key> {
    match name {
        "left" => Some(Key::LeftArrow),
        "right" => Some(Key::RightArrow),
        "up" => Some(Key::UpArrow),
        "down" => Some(Key::DownArrow),
        _ => None,
    }
}

#[cfg(not(target_os = "macos"))]
pub async fn canary_type_text(_text: &str) -> Result<(), String> {
    Err("unsupported_platform".to_string())
}

#[cfg(not(target_os = "macos"))]
pub async fn canary_key_chord(_keys: &[String]) -> Result<(), String> {
    Err("unsupported_platform".to_string())
}

#[cfg(not(target_os = "macos"))]
pub async fn canary_move_norm(_norm_x: f64, _norm_y: f64) -> Result<(), String> {
    Err("unsupported_platform".to_string())
}

#[cfg(not(target_os = "macos"))]
pub async fn canary_click() -> Result<(), String> {
    Err("unsupported_platform".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    // Gap this slice closes: the gesture cursor path must not reach the native
    // adapter on the strength of desktop_control_allows_actuation() alone. A
    // deny-by-default pre-native boundary guard (incorporating a local Stop
    // latch) must pass first, so flipping the single kill switch is not enough.

    #[test]
    fn kill_switch_off_denies_regardless_of_stop() {
        assert!(!gesture_native_boundary_allows(false, false));
        assert!(!gesture_native_boundary_allows(false, true));
    }

    #[test]
    fn stop_denies_even_if_kill_switch_flips_on() {
        // The crux: even if desktop_control_allows_actuation() ever returned
        // true, a stopped gesture boundary still denies before any native call.
        assert!(!gesture_native_boundary_allows(true, true));
    }

    #[test]
    fn boundary_allows_only_when_enabled_and_not_stopped() {
        assert!(gesture_native_boundary_allows(true, false));
    }

    #[test]
    fn gesture_boundary_defaults_to_stopped() {
        // Fresh process: local Stop latch engaged, so the live boundary denies
        // today regardless of the (currently false) global kill switch.
        assert!(gesture_stopped());
        assert!(!gesture_native_boundary_allows(
            crate::desktop_control_allows_actuation(),
            gesture_stopped(),
        ));
    }

    #[test]
    fn set_gesture_stopped_toggles_the_local_latch() {
        // Exercise the integration seam without enabling actuation: clearing the
        // latch alone still cannot actuate because the kill switch stays false.
        set_gesture_stopped(false);
        assert!(!gesture_stopped());
        assert!(!gesture_native_boundary_allows(
            crate::desktop_control_allows_actuation(), // still false
            gesture_stopped(),
        ));
        set_gesture_stopped(true); // restore safe default for any other test
        assert!(gesture_stopped());
    }

    #[test]
    fn canary_guard_requires_flag_and_not_stopped() {
        // Flag off denies regardless of Stop.
        assert!(!canary_pointer_actuation_allowed(false, false));
        assert!(!canary_pointer_actuation_allowed(false, true));
        // Even with the pointer flag on, a latched Stop still vetoes.
        assert!(!canary_pointer_actuation_allowed(true, true));
        // Only flag-on AND not-stopped proceeds.
        assert!(canary_pointer_actuation_allowed(true, false));
    }
}
