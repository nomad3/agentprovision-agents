use base64::Engine;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use std::fmt::Write as _;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicU8, Ordering};
use std::sync::Arc;
use tauri::{Emitter, Manager};

mod computer_use;
mod gesture;

lazy_static::lazy_static! {
    static ref CAPTURE_RUNNING: Arc<AtomicBool> = Arc::new(AtomicBool::new(false));
    static ref NATIVE_BOUNDARY_REPLAY_NONCES: std::sync::Mutex<std::collections::HashMap<String, u64>> =
        std::sync::Mutex::new(std::collections::HashMap::new());
}

const CONTROL_MODE_LOCKED: u8 = 0;
const CONTROL_MODE_OBSERVE: u8 = 1;
const CONTROL_MODE_STOPPED: u8 = 2;

static CONTROL_MODE: AtomicU8 = AtomicU8::new(CONTROL_MODE_LOCKED);
static LAST_STOP_AT_MS: AtomicU64 = AtomicU64::new(0);

/// Serializes every CONTROL_MODE write together with its durable-latch file
/// side effect, so concurrent control commands from multiple Tauri windows (or
/// the planned tray / keyboard Stop entrypoints) can't interleave a mode store
/// with a latch write and leave memory and disk disagreeing about whether the
/// emergency Stop is latched.
static STOP_LATCH_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// Acquire the latch lock, recovering from poisoning — the guarded data is `()`
/// so a panicked holder cannot have corrupted anything.
fn lock_latch() -> std::sync::MutexGuard<'static, ()> {
    STOP_LATCH_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

#[cfg(desktop)]
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
};

#[cfg(desktop)]
fn show_main_window_maximized(app: &tauri::AppHandle) -> Result<(), String> {
    let Some(window) = app.get_webview_window("main") else {
        return Err("main window not registered".into());
    };

    window
        .show()
        .map_err(|e| format!("show main window: {e}"))?;
    let _ = window.unminimize();
    // Maximize-to-visible-frame, never true fullscreen: leave any fullscreen
    // state first so `maximize()` zooms to the work area (menu bar + Dock stay
    // reachable) instead of taking over the whole display.
    let _ = window.set_fullscreen(false);
    if let Err(err) = window.maximize() {
        log::warn!("main window maximize failed: {err}");
    }
    window
        .set_focus()
        .map_err(|e| format!("focus main window: {e}"))?;
    Ok(())
}

#[cfg(not(desktop))]
fn show_main_window_maximized(app: &tauri::AppHandle) -> Result<(), String> {
    let Some(window) = app.get_webview_window("main") else {
        return Err("main window not registered".into());
    };

    window
        .show()
        .map_err(|e| format!("show main window: {e}"))?;
    window
        .set_focus()
        .map_err(|e| format!("focus main window: {e}"))?;
    Ok(())
}

#[tauri::command]
fn get_platform() -> String {
    std::env::consts::OS.to_string()
}

#[tauri::command]
fn get_arch() -> String {
    std::env::consts::ARCH.to_string()
}

#[tauri::command]
fn alpha_kernel_status() -> AlphaKernelStatus {
    discover_alpha_kernel()
}

fn now_unix_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn executable_file_exists(path: &std::path::Path) -> bool {
    let Ok(metadata) = std::fs::metadata(path) else {
        return false;
    };
    if !metadata.is_file() {
        return false;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        metadata.permissions().mode() & 0o111 != 0
    }
    #[cfg(not(unix))]
    {
        true
    }
}

fn available_alpha_kernel(path: std::path::PathBuf, source: &str) -> AlphaKernelStatus {
    AlphaKernelStatus {
        status: "available".to_string(),
        available: true,
        binary_path: Some(path.to_string_lossy().to_string()),
        source: Some(source.to_string()),
        manages_chat_jobs: true,
        manages_tasks: true,
        cli_parity_required: true,
        platform_scope: "macos".to_string(),
        reason: None,
    }
}

fn missing_alpha_kernel(reason: String) -> AlphaKernelStatus {
    AlphaKernelStatus {
        status: "missing".to_string(),
        available: false,
        binary_path: None,
        source: None,
        manages_chat_jobs: true,
        manages_tasks: true,
        cli_parity_required: true,
        platform_scope: "macos".to_string(),
        reason: Some(reason),
    }
}

fn discover_alpha_kernel() -> AlphaKernelStatus {
    if let Ok(value) = std::env::var("LUNA_ALPHA_CLI") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            let path = std::path::PathBuf::from(trimmed);
            return if executable_file_exists(&path) {
                available_alpha_kernel(path, "LUNA_ALPHA_CLI")
            } else {
                missing_alpha_kernel(format!(
                    "LUNA_ALPHA_CLI does not point to an executable alpha CLI: {trimmed}"
                ))
            };
        }
    }

    let mut candidates: Vec<(std::path::PathBuf, &'static str)> = Vec::new();
    if let Some(home) = std::env::var_os("HOME") {
        candidates.push((
            std::path::PathBuf::from(home).join(".local/bin/alpha"),
            "home",
        ));
    }
    candidates.push((
        std::path::PathBuf::from("/opt/homebrew/bin/alpha"),
        "homebrew",
    ));
    candidates.push((
        std::path::PathBuf::from("/usr/local/bin/alpha"),
        "usr_local",
    ));
    if let Some(paths) = std::env::var_os("PATH") {
        for entry in std::env::split_paths(&paths) {
            candidates.push((entry.join("alpha"), "PATH"));
        }
    }

    let mut seen = std::collections::HashSet::new();
    for (path, source) in candidates {
        let key = path.to_string_lossy().to_string();
        if !seen.insert(key) {
            continue;
        }
        if executable_file_exists(&path) {
            return available_alpha_kernel(path, source);
        }
    }

    missing_alpha_kernel(
        "Alpha CLI was not found in LUNA_ALPHA_CLI, standard local paths, or PATH.".to_string(),
    )
}

fn current_macos_app_monitor_status(
    mode: u8,
    permissions: &computer_use::DesktopPermissionReadiness,
) -> MacosAppMonitorStatus {
    #[cfg(not(target_os = "macos"))]
    {
        let _ = mode;
        MacosAppMonitorStatus {
            platform: std::env::consts::OS.to_string(),
            status: "unsupported".to_string(),
            reason: "Native app monitoring is scoped to macOS for this phase.".to_string(),
            accessibility_status: permissions.accessibility.status.clone(),
            automation_system_events_status: permissions.automation_system_events.status.clone(),
            observed_at_ms: None,
        }
    }

    #[cfg(target_os = "macos")]
    {
        let (status, reason) = if mode == CONTROL_MODE_STOPPED {
            (
                "stopped",
                "Desktop Stop is latched; macOS app monitoring is off.",
            )
        } else if mode != CONTROL_MODE_OBSERVE {
            (
                "locked",
                "Observe-only mode is not armed; macOS app monitoring is locked.",
            )
        } else if permissions.accessibility.status != "granted" {
            (
                "denied",
                "macOS Accessibility is required before Luna can monitor the active app.",
            )
        } else {
            (
                "ready",
                "macOS active-app monitoring is ready in metadata-only mode.",
            )
        };

        MacosAppMonitorStatus {
            platform: "macos".to_string(),
            status: status.to_string(),
            reason: reason.to_string(),
            accessibility_status: permissions.accessibility.status.clone(),
            automation_system_events_status: permissions.automation_system_events.status.clone(),
            observed_at_ms: None,
        }
    }
}

fn valid_desktop_shell_id(id: &str) -> bool {
    id.strip_prefix("desktop-")
        .is_some_and(|rest| uuid::Uuid::parse_str(rest).is_ok())
}

#[tauri::command]
fn get_or_create_shell_id(app: tauri::AppHandle) -> Result<String, String> {
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("Failed to resolve Luna app data dir: {}", e))?;
    std::fs::create_dir_all(&app_data_dir)
        .map_err(|e| format!("Failed to create Luna app data dir: {}", e))?;

    let path = app_data_dir.join("desktop-shell-id");
    if let Ok(raw) = std::fs::read_to_string(&path) {
        let shell_id = raw.trim();
        if valid_desktop_shell_id(shell_id) {
            return Ok(shell_id.to_string());
        }
    }

    let shell_id = format!("desktop-{}", uuid::Uuid::new_v4());
    std::fs::write(&path, format!("{}\n", shell_id))
        .map_err(|e| format!("Failed to persist Luna desktop shell id: {}", e))?;
    Ok(shell_id)
}

#[derive(Clone, serde::Serialize)]
struct ControlSafetyState {
    mode: String,
    observe_enabled: bool,
    assist_enabled: bool,
    control_enabled: bool,
    stopped: bool,
    control_locked: bool,
    capture_running: bool,
    gesture_state: String,
    cursor_global: bool,
    can_observe: bool,
    can_assist: bool,
    can_control: bool,
    can_control_pointer: bool,
    can_control_keyboard: bool,
    alpha_kernel: AlphaKernelStatus,
    macos_app_monitor: MacosAppMonitorStatus,
    permissions: computer_use::DesktopPermissionReadiness,
    last_stop_at_ms: Option<u64>,
}

#[derive(Clone, serde::Serialize)]
struct AlphaKernelStatus {
    status: String,
    available: bool,
    binary_path: Option<String>,
    source: Option<String>,
    manages_chat_jobs: bool,
    manages_tasks: bool,
    cli_parity_required: bool,
    platform_scope: String,
    reason: Option<String>,
}

#[derive(Clone, serde::Serialize)]
struct MacosAppMonitorStatus {
    platform: String,
    status: String,
    reason: String,
    accessibility_status: String,
    automation_system_events_status: String,
    observed_at_ms: Option<u64>,
}

#[derive(Clone, serde::Serialize)]
struct DesktopObservationAuditEvent {
    event_id: String,
    event_type: String,
    source: String,
    action: String,
    capability: String,
    outcome: String,
    reason: Option<String>,
    mode: String,
    shell_id: Option<String>,
    created_at_ms: u64,
    screen_recording_status: String,
    accessibility_status: String,
    automation_system_events_status: String,
}

#[derive(Clone, serde::Serialize)]
struct DesktopNativeControlAuditEvent {
    event_id: String,
    event_type: String,
    source: String,
    action: String,
    capability: String,
    outcome: String,
    reason: Option<String>,
    mode: String,
    shell_id: Option<String>,
    desktop_command_id: Option<String>,
    approval_id: Option<String>,
    device_id: Option<String>,
    session_id: Option<String>,
    created_at_ms: u64,
    screen_recording_status: String,
    accessibility_status: String,
    automation_system_events_status: String,
}

#[derive(Clone)]
struct ObservationAuditContext {
    event_id: String,
    action: &'static str,
    capability: computer_use::ObservationCapability,
    mode: computer_use::DesktopControlMode,
    permissions: computer_use::DesktopPermissionReadiness,
    shell_id: Option<String>,
}

#[derive(Clone, serde::Deserialize)]
struct NativeControlBoundaryProofRequest {
    desktop_command_id: Option<String>,
    shell_id: Option<String>,
    session_id: Option<String>,
    device_id: Option<String>,
    action: String,
    capability: Option<String>,
    approval_id: Option<String>,
    target: Option<NativeControlBoundaryTarget>,
    live_frontmost_bundle_id: Option<String>,
    // Set Rust-side at proof time from IsSecureEventInputEnabled() — never
    // trusted from the JS request. Phase 2.75: keyboard actuation is denied
    // while macOS Secure Input is active anywhere on the system.
    #[serde(default)]
    secure_input_active: Option<bool>,
    command_envelope: Option<serde_json::Value>,
    approval: Option<NativeControlBoundaryApproval>,
}

#[derive(Clone, serde::Deserialize)]
struct NativeControlBoundaryEnvelope {
    schema: Option<String>,
    signed: Option<bool>,
    signature_alg: Option<String>,
    key_id: Option<String>,
    signature: Option<String>,
    policy_version: Option<u16>,
    issuer: Option<String>,
    nonce: Option<String>,
    expires_at_ms: Option<u64>,
    desktop_command_id: Option<String>,
    shell_id: Option<String>,
    session_id: Option<String>,
    device_id: Option<String>,
    action: Option<String>,
    capability: Option<String>,
    approval_id: Option<String>,
    approval_risk_tier: Option<String>,
    risk_tier: Option<String>,
    policy_decision: Option<String>,
    target: Option<NativeControlBoundaryTarget>,
    revoked: Option<bool>,
    replayed: Option<bool>,
}

#[derive(Clone, serde::Deserialize)]
struct NativeControlBoundaryTarget {
    bundle_id: Option<String>,
    window_title_pattern: Option<String>,
    window_title_hash: Option<String>,
    display_id: Option<serde_json::Value>,
    bounds: Option<serde_json::Value>,
    observed_at: Option<String>,
}

#[derive(Clone, serde::Deserialize)]
struct NativeControlBoundaryApproval {
    approval_id: Option<String>,
    risk_tier: Option<String>,
    capability: Option<String>,
    expires_at_ms: Option<u64>,
    revoked: Option<bool>,
}

#[derive(Clone, serde::Serialize)]
struct NativeControlBoundaryProofResult {
    allowed: bool,
    outcome: String,
    reason: String,
    action: String,
    capability: String,
    audit_event_id: String,
    mode: String,
}

struct NativeControlBoundaryDecision {
    allowed: bool,
    outcome: &'static str,
    reason: String,
    action: String,
    capability: String,
}

struct ValidNativeControlBoundaryEnvelope {
    envelope: computer_use::policy::NativeControlCommandEnvelope,
    target_bundle_id: String,
}

const DESKTOP_COMMAND_ENVELOPE_SCHEMA: &str = "agentprovision.desktop_command_envelope.v1";
const DESKTOP_COMMAND_ENVELOPE_SIGNATURE_ALG: &str = "Ed25519";
const DESKTOP_COMMAND_ENVELOPE_DEFAULT_KEY_ID: &str = "agentprovision-desktop-command-ed25519-v1";
const DESKTOP_COMMAND_ENVELOPE_ISSUER: &str = "agentprovision-api";
const DESKTOP_COMMAND_APPROVAL_RISK_NATIVE_CONTROL: &str = "native_control";
const DESKTOP_COMMAND_POLICY_DECISION_LEASE_CLAIMED: &str = "lease_claimed";

fn control_mode_name(mode: u8) -> &'static str {
    match mode {
        CONTROL_MODE_OBSERVE => "observe",
        CONTROL_MODE_STOPPED => "stopped",
        _ => "control_locked",
    }
}

fn current_desktop_control_mode() -> computer_use::DesktopControlMode {
    match CONTROL_MODE.load(Ordering::SeqCst) {
        CONTROL_MODE_OBSERVE => computer_use::DesktopControlMode::Observe,
        CONTROL_MODE_STOPPED => computer_use::DesktopControlMode::Stopped,
        _ => computer_use::DesktopControlMode::ControlLocked,
    }
}

/// Mode after a Lock request. Preserves STOPPED so that only an explicit
/// Resume (`control_clear_stop`) can leave a latched emergency Stop — this is
/// the single most fragile point of durable-Stop (Stop Semantics #5): if a
/// Lock ever downgraded STOPPED to LOCKED, `AuthContext`'s logout/stale-token
/// `control_lock_all` would silently un-stop on the next launch.
fn next_mode_for_lock(current: u8) -> u8 {
    if current == CONTROL_MODE_STOPPED {
        CONTROL_MODE_STOPPED
    } else {
        CONTROL_MODE_LOCKED
    }
}

/// Whether an Observe request may proceed. Never out of a latched Stop.
fn observe_allowed_in_mode(current: u8) -> bool {
    current != CONTROL_MODE_STOPPED
}

fn desktop_control_stopped() -> bool {
    CONTROL_MODE.load(Ordering::SeqCst) == CONTROL_MODE_STOPPED
}

fn desktop_control_observe_enabled() -> bool {
    CONTROL_MODE.load(Ordering::SeqCst) == CONTROL_MODE_OBSERVE
}

fn ensure_desktop_control_not_stopped(action: &str) -> Result<(), String> {
    if desktop_control_stopped() {
        Err(format!("desktop control stopped; {action} denied"))
    } else {
        Ok(())
    }
}

fn ensure_desktop_control_allows_observation(action: &str) -> Result<(), String> {
    let mode = CONTROL_MODE.load(Ordering::SeqCst);
    if mode == CONTROL_MODE_STOPPED {
        Err(format!("desktop control stopped; {action} denied"))
    } else if mode == CONTROL_MODE_OBSERVE {
        Ok(())
    } else {
        Err(format!("desktop observe locked; {action} denied"))
    }
}

fn existing_shell_id_for_audit(app: &tauri::AppHandle) -> Option<String> {
    let dir = app.path().app_data_dir().ok()?;
    let raw = std::fs::read_to_string(dir.join("desktop-shell-id")).ok()?;
    let shell_id = raw.trim();
    if valid_desktop_shell_id(shell_id) {
        Some(shell_id.to_string())
    } else {
        None
    }
}

fn emit_observation_audit(
    app: &tauri::AppHandle,
    ctx: &ObservationAuditContext,
    event_type: &str,
    outcome: &str,
    reason: Option<String>,
) {
    let event = DesktopObservationAuditEvent {
        event_id: ctx.event_id.clone(),
        event_type: event_type.to_string(),
        source: "tauri_local".to_string(),
        action: ctx.action.to_string(),
        capability: ctx.capability.as_str().to_string(),
        outcome: outcome.to_string(),
        reason,
        mode: ctx.mode.as_str().to_string(),
        shell_id: ctx.shell_id.clone(),
        created_at_ms: now_unix_ms(),
        screen_recording_status: ctx.permissions.screen_recording.status.clone(),
        accessibility_status: ctx.permissions.accessibility.status.clone(),
        automation_system_events_status: ctx.permissions.automation_system_events.status.clone(),
    };
    if let Err(e) = app.emit("desktop-control-audit", &event) {
        log::warn!("desktop control audit emit failed for {}: {e}", ctx.action);
    }
    match event.outcome.as_str() {
        "denied" | "failed" => log::warn!(
            "desktop observation audit: action={} capability={} outcome={} reason={}",
            event.action,
            event.capability,
            event.outcome,
            event.reason.as_deref().unwrap_or("")
        ),
        _ => log::info!(
            "desktop observation audit: action={} capability={} outcome={}",
            event.action,
            event.capability,
            event.outcome
        ),
    }
}

fn begin_observation_audit(
    app: &tauri::AppHandle,
    action: &'static str,
    capability: computer_use::ObservationCapability,
) -> Result<ObservationAuditContext, String> {
    let mode = current_desktop_control_mode();
    let permissions = computer_use::current_permission_readiness();
    let ctx = ObservationAuditContext {
        event_id: uuid::Uuid::new_v4().to_string(),
        action,
        capability,
        mode,
        permissions,
        shell_id: existing_shell_id_for_audit(app),
    };

    if let Err(denial) =
        computer_use::evaluate_observation_policy(ctx.mode, &ctx.permissions, capability, action)
    {
        let reason = denial.reason;
        emit_observation_audit(
            app,
            &ctx,
            "desktop_observation_denied",
            "denied",
            Some(reason.clone()),
        );
        return Err(reason);
    }

    emit_observation_audit(app, &ctx, "desktop_observation_started", "started", None);
    Ok(ctx)
}

fn observation_policy_currently_allows(
    action: &str,
    capability: computer_use::ObservationCapability,
) -> bool {
    let mode = current_desktop_control_mode();
    let permissions = computer_use::current_permission_readiness();
    computer_use::evaluate_observation_policy(mode, &permissions, capability, action).is_ok()
}

fn complete_observation_audit(app: &tauri::AppHandle, ctx: &ObservationAuditContext) {
    emit_observation_audit(app, ctx, "desktop_observation_completed", "succeeded", None);
}

fn fail_observation_audit(app: &tauri::AppHandle, ctx: &ObservationAuditContext, reason: &str) {
    emit_observation_audit(
        app,
        ctx,
        "desktop_observation_failed",
        "failed",
        Some(reason.to_string()),
    );
}

fn native_control_capability_for_action(
    action: &str,
) -> Option<computer_use::NativeControlCapability> {
    match action {
        "pointer_move" | "pointer_click" => Some(computer_use::NativeControlCapability::Pointer),
        "keyboard_type" | "keyboard_key_chord" => {
            Some(computer_use::NativeControlCapability::Keyboard)
        }
        _ => None,
    }
}

fn non_empty_text(value: &Option<String>) -> Option<&str> {
    value.as_deref().map(str::trim).filter(|s| !s.is_empty())
}

fn required_binding(value: &Option<String>) -> Result<&str, &'static str> {
    non_empty_text(value).ok_or("desktop command envelope binding mismatch")
}

fn envelope_field_matches(actual: &Option<String>, expected: &str) -> bool {
    non_empty_text(actual) == Some(expected)
}

fn decode_envelope_key_material(value: &str) -> Result<Vec<u8>, &'static str> {
    let trimmed = value.trim();
    let encoded = trimmed
        .strip_prefix("base64url:")
        .or_else(|| trimmed.strip_prefix("base64:"))
        .unwrap_or(trimmed);
    if let Some(hex) = trimmed.strip_prefix("hex:") {
        if hex.len() % 2 != 0 {
            return Err("desktop command envelope signature invalid");
        }
        let mut bytes = Vec::with_capacity(hex.len() / 2);
        for index in (0..hex.len()).step_by(2) {
            let byte = u8::from_str_radix(&hex[index..index + 2], 16)
                .map_err(|_| "desktop command envelope signature invalid")?;
            bytes.push(byte);
        }
        return Ok(bytes);
    }
    base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(encoded)
        .or_else(|_| base64::engine::general_purpose::STANDARD.decode(encoded))
        .map_err(|_| "desktop command envelope signature invalid")
}

fn desktop_command_envelope_key_registry_config() -> Option<String> {
    std::env::var("LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEYS")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            option_env!("LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEYS")
                .map(str::to_string)
                .filter(|value| !value.trim().is_empty())
        })
}

fn desktop_command_envelope_default_public_key_config() -> Option<String> {
    std::env::var("LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            option_env!("LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY")
                .map(str::to_string)
                .filter(|value| !value.trim().is_empty())
        })
}

fn public_key_from_desktop_command_envelope_registry(
    key_id: &str,
    registry: Option<&str>,
    default_public_key: Option<&str>,
) -> Result<String, &'static str> {
    let key_id = key_id.trim();
    if key_id.is_empty() {
        return Err("desktop command envelope key unknown");
    }
    if let Some(registry) = registry {
        for raw_entry in registry.split(|c| matches!(c, ',' | ';' | '\n')) {
            let entry = raw_entry.trim();
            if entry.is_empty() {
                continue;
            }
            let Some((entry_key_id, public_key)) = entry.split_once('=') else {
                return Err("desktop command envelope key registry invalid");
            };
            if entry_key_id.trim() == key_id {
                let public_key = public_key.trim();
                if public_key.is_empty() {
                    return Err("desktop command envelope public key invalid");
                }
                return Ok(public_key.to_string());
            }
        }
    }
    if key_id == DESKTOP_COMMAND_ENVELOPE_DEFAULT_KEY_ID {
        if let Some(public_key) = default_public_key
            .map(str::trim)
            .filter(|value| !value.is_empty())
        {
            return Ok(public_key.to_string());
        }
    }
    Err("desktop command envelope key unknown")
}

fn desktop_command_envelope_public_key_config_for_key_id(
    key_id: &str,
) -> Result<String, &'static str> {
    public_key_from_desktop_command_envelope_registry(
        key_id,
        desktop_command_envelope_key_registry_config().as_deref(),
        desktop_command_envelope_default_public_key_config().as_deref(),
    )
}

fn write_canonical_json_string(value: &str, output: &mut String) {
    output.push('"');
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\u{08}' => output.push_str("\\b"),
            '\u{0c}' => output.push_str("\\f"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            character if (character as u32) < 0x20 || character == '\u{7f}' => {
                write!(output, "\\u{:04x}", character as u32)
                    .expect("writing to string cannot fail");
            }
            character if (character as u32) < 0x80 => output.push(character),
            character if (character as u32) <= 0xffff => {
                write!(output, "\\u{:04x}", character as u32)
                    .expect("writing to string cannot fail");
            }
            character => {
                let scalar = character as u32 - 0x1_0000;
                let high = 0xd800 + (scalar >> 10);
                let low = 0xdc00 + (scalar & 0x3ff);
                write!(output, "\\u{high:04x}\\u{low:04x}").expect("writing to string cannot fail");
            }
        }
    }
    output.push('"');
}

fn write_canonical_json_value(
    value: &serde_json::Value,
    output: &mut String,
) -> Result<(), &'static str> {
    match value {
        serde_json::Value::Null => output.push_str("null"),
        serde_json::Value::Bool(true) => output.push_str("true"),
        serde_json::Value::Bool(false) => output.push_str("false"),
        serde_json::Value::Number(number) => output.push_str(&number.to_string()),
        serde_json::Value::String(value) => write_canonical_json_string(value, output),
        serde_json::Value::Array(values) => {
            output.push('[');
            for (index, value) in values.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                write_canonical_json_value(value, output)?;
            }
            output.push(']');
        }
        serde_json::Value::Object(object) => {
            let mut entries: Vec<_> = object.iter().collect();
            entries.sort_by(|(left, _), (right, _)| left.cmp(right));
            output.push('{');
            for (index, (key, value)) in entries.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                write_canonical_json_string(key, output);
                output.push(':');
                write_canonical_json_value(value, output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

fn canonical_envelope_payload_json(
    envelope_value: &serde_json::Value,
) -> Result<Vec<u8>, &'static str> {
    let mut payload = envelope_value.clone();
    let Some(object) = payload.as_object_mut() else {
        return Err("desktop command envelope binding mismatch");
    };
    object.remove("signature");
    let mut canonical = String::new();
    write_canonical_json_value(&payload, &mut canonical)?;
    Ok(canonical.into_bytes())
}

fn verify_native_control_boundary_envelope_signature(
    envelope_value: &serde_json::Value,
) -> Result<(), &'static str> {
    let envelope: NativeControlBoundaryEnvelope = serde_json::from_value(envelope_value.clone())
        .map_err(|_| "desktop command envelope binding mismatch")?;
    let key_id = non_empty_text(&envelope.key_id).ok_or("desktop command envelope key unknown")?;
    let public_key = desktop_command_envelope_public_key_config_for_key_id(key_id)?;
    verify_native_control_boundary_envelope_signature_with_public_key(envelope_value, &public_key)
}

fn verify_native_control_boundary_envelope_signature_with_public_key(
    envelope_value: &serde_json::Value,
    public_key_config: &str,
) -> Result<(), &'static str> {
    let envelope: NativeControlBoundaryEnvelope = serde_json::from_value(envelope_value.clone())
        .map_err(|_| "desktop command envelope binding mismatch")?;
    if envelope.signature_alg.as_deref() != Some(DESKTOP_COMMAND_ENVELOPE_SIGNATURE_ALG)
        || non_empty_text(&envelope.key_id).is_none()
    {
        return Err("desktop command envelope signature invalid");
    }
    let signature = non_empty_text(&envelope.signature)
        .ok_or("desktop command envelope signature invalid")
        .and_then(decode_envelope_key_material)?;
    let bytes = decode_envelope_key_material(public_key_config)
        .map_err(|_| "desktop command envelope public key invalid")?;
    let key_bytes: [u8; 32] = bytes
        .try_into()
        .map_err(|_| "desktop command envelope public key invalid")?;
    let public_key = VerifyingKey::from_bytes(&key_bytes)
        .map_err(|_| "desktop command envelope public key invalid")?;
    let signature = Signature::from_slice(&signature)
        .map_err(|_| "desktop command envelope signature invalid")?;
    public_key
        .verify(
            &canonical_envelope_payload_json(envelope_value)?,
            &signature,
        )
        .map_err(|_| "desktop command envelope signature invalid")
}

fn native_boundary_denial(
    action: &str,
    capability: computer_use::NativeControlCapability,
    outcome: &'static str,
    base_reason: &str,
) -> NativeControlBoundaryDecision {
    NativeControlBoundaryDecision {
        allowed: false,
        outcome,
        reason: format!("{base_reason}; {action} denied"),
        action: action.to_string(),
        capability: capability.as_str().to_string(),
    }
}

fn native_boundary_policy_decision(
    action: &str,
    result: Result<(), computer_use::policy::NativeControlPolicyDenial>,
) -> NativeControlBoundaryDecision {
    match result {
        Ok(()) => NativeControlBoundaryDecision {
            allowed: true,
            outcome: "allowed",
            reason: String::new(),
            action: action.to_string(),
            capability: "native_control".to_string(),
        },
        Err(denial) => NativeControlBoundaryDecision {
            allowed: false,
            outcome: if denial.reason.contains("desktop control stopped") {
                "preempted"
            } else {
                "denied"
            },
            reason: denial.reason,
            action: action.to_string(),
            capability: denial.capability.as_str().to_string(),
        },
    }
}

fn lock_native_boundary_replay_nonces(
) -> std::sync::MutexGuard<'static, std::collections::HashMap<String, u64>> {
    NATIVE_BOUNDARY_REPLAY_NONCES
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn remember_native_boundary_nonce(nonce: &str, expires_at_ms: u64, now_ms: u64) -> bool {
    let mut nonces = lock_native_boundary_replay_nonces();
    nonces.retain(|_, expires_at| *expires_at > now_ms);
    if nonces.contains_key(nonce) {
        return false;
    }
    nonces.insert(nonce.to_string(), expires_at_ms);
    true
}

fn validate_native_control_boundary_envelope(
    request: &NativeControlBoundaryProofRequest,
    action: &str,
    expected_capability: computer_use::NativeControlCapability,
    now_ms: u64,
    mut verify_signature: impl FnMut(&serde_json::Value) -> Result<(), &'static str>,
    mut remember_nonce: impl FnMut(&str, u64, u64) -> bool,
) -> Result<ValidNativeControlBoundaryEnvelope, &'static str> {
    let envelope_value = request
        .command_envelope
        .as_ref()
        .ok_or("desktop command envelope missing")?;
    let envelope: NativeControlBoundaryEnvelope = serde_json::from_value(envelope_value.clone())
        .map_err(|_| "desktop command envelope binding mismatch")?;
    let nonce = non_empty_text(&envelope.nonce)
        .ok_or("desktop command envelope nonce missing")?
        .to_string();

    if envelope.replayed == Some(true) {
        return Err("desktop command envelope replayed");
    }
    if envelope.revoked == Some(true)
        || non_empty_text(&envelope.policy_decision) == Some("revoked")
    {
        return Err("desktop command approval grant revoked");
    }
    if envelope.schema.as_deref() != Some(DESKTOP_COMMAND_ENVELOPE_SCHEMA)
        || envelope.signed != Some(true)
        || envelope.signature_alg.as_deref() != Some(DESKTOP_COMMAND_ENVELOPE_SIGNATURE_ALG)
        || non_empty_text(&envelope.key_id).is_none()
        || envelope.policy_version
            != Some(computer_use::policy::CURRENT_NATIVE_CONTROL_POLICY_VERSION)
        || envelope.issuer.as_deref() != Some(DESKTOP_COMMAND_ENVELOPE_ISSUER)
    {
        return Err("desktop command envelope binding mismatch");
    }
    if non_empty_text(&envelope.signature).is_none() {
        return Err("desktop command envelope signature invalid");
    }
    let envelope_target = envelope
        .target
        .as_ref()
        .ok_or("desktop command target not allowlisted")?;
    let envelope_target_bundle = non_empty_text(&envelope_target.bundle_id)
        .ok_or("desktop command target not allowlisted")?;
    if let Some(request_target) = request.target.as_ref() {
        let request_target_bundle = non_empty_text(&request_target.bundle_id)
            .ok_or("desktop command target not allowlisted")?;
        if request_target_bundle != envelope_target_bundle {
            return Err("desktop command envelope binding mismatch");
        }
    }
    verify_signature(envelope_value)?;
    let expires_at_ms = envelope
        .expires_at_ms
        .ok_or("desktop command envelope expired")?;
    if expires_at_ms <= now_ms {
        return Err("desktop command envelope expired");
    }

    let approval = request
        .approval
        .as_ref()
        .ok_or("desktop command approval grant missing")?;
    if approval.revoked == Some(true) {
        return Err("desktop command approval grant revoked");
    }
    if approval
        .expires_at_ms
        .is_some_and(|approval_expires_at_ms| approval_expires_at_ms <= now_ms)
    {
        return Err("desktop command approval grant expired");
    }

    let request_approval_id =
        non_empty_text(&request.approval_id).ok_or("desktop command approval grant missing")?;
    let approval_id =
        non_empty_text(&approval.approval_id).ok_or("desktop command approval grant missing")?;
    if uuid::Uuid::parse_str(request_approval_id).is_err()
        || uuid::Uuid::parse_str(approval_id).is_err()
    {
        return Err("desktop command approval grant missing");
    }
    if request_approval_id != approval_id {
        return Err("desktop command approval grant binding mismatch");
    }

    let expected_capability_label = expected_capability.as_str();
    if non_empty_text(&approval.risk_tier) != Some(DESKTOP_COMMAND_APPROVAL_RISK_NATIVE_CONTROL)
        || non_empty_text(&approval.capability) != Some(expected_capability_label)
        || non_empty_text(&envelope.risk_tier) != Some(DESKTOP_COMMAND_APPROVAL_RISK_NATIVE_CONTROL)
        || non_empty_text(&envelope.approval_risk_tier)
            != Some(DESKTOP_COMMAND_APPROVAL_RISK_NATIVE_CONTROL)
        || non_empty_text(&envelope.policy_decision)
            != Some(DESKTOP_COMMAND_POLICY_DECISION_LEASE_CLAIMED)
    {
        return Err("desktop command approval grant binding mismatch");
    }

    let desktop_command_id = required_binding(&request.desktop_command_id)?;
    let shell_id = required_binding(&request.shell_id)?;
    let session_id = required_binding(&request.session_id)?;
    let device_id = required_binding(&request.device_id)?;
    let request_capability = required_binding(&request.capability)?;
    if request_capability != expected_capability_label
        || !envelope_field_matches(&envelope.desktop_command_id, desktop_command_id)
        || !envelope_field_matches(&envelope.shell_id, shell_id)
        || !envelope_field_matches(&envelope.session_id, session_id)
        || !envelope_field_matches(&envelope.device_id, device_id)
        || !envelope_field_matches(&envelope.action, action)
        || !envelope_field_matches(&envelope.capability, expected_capability_label)
        || !envelope_field_matches(&envelope.approval_id, request_approval_id)
    {
        return Err("desktop command envelope binding mismatch");
    }

    if !remember_nonce(&nonce, expires_at_ms, now_ms) {
        return Err("desktop command envelope replayed");
    }

    Ok(ValidNativeControlBoundaryEnvelope {
        envelope: computer_use::policy::NativeControlCommandEnvelope {
            signed: true,
            policy_version: envelope
                .policy_version
                .expect("policy version was checked above"),
            expires_at_ms,
        },
        target_bundle_id: envelope_target_bundle.to_string(),
    })
}

fn evaluate_native_control_boundary_request(
    request: &NativeControlBoundaryProofRequest,
    mode: computer_use::DesktopControlMode,
    permissions: &computer_use::DesktopPermissionReadiness,
    now_ms: u64,
    verify_signature: impl FnMut(&serde_json::Value) -> Result<(), &'static str>,
    remember_nonce: impl FnMut(&str, u64, u64) -> bool,
) -> NativeControlBoundaryDecision {
    let action = request.action.trim();
    let action = if action.is_empty() { "unknown" } else { action };
    let Some(capability) = native_control_capability_for_action(action) else {
        return NativeControlBoundaryDecision {
            allowed: false,
            outcome: "denied",
            reason: format!("desktop native control action unsupported; {action} denied"),
            action: action.to_string(),
            capability: request
                .capability
                .as_deref()
                .unwrap_or("unknown")
                .to_string(),
        };
    };

    if mode == computer_use::DesktopControlMode::Stopped {
        return native_boundary_denial(action, capability, "preempted", "desktop control stopped");
    }

    let envelope = match validate_native_control_boundary_envelope(
        request,
        action,
        capability,
        now_ms,
        verify_signature,
        remember_nonce,
    ) {
        Ok(envelope) => envelope,
        Err(reason) => return native_boundary_denial(action, capability, "denied", reason),
    };

    if let Some(denial) = computer_use::denial_codes::frontmost_app_decision(
        non_empty_text(&request.live_frontmost_bundle_id),
        &envelope.target_bundle_id,
    ) {
        return native_boundary_denial(action, capability, "denied", denial.as_str());
    }

    // Phase 2.75: deny keyboard actuation while macOS Secure Input is active (a
    // password/secure field is focused anywhere), before the policy/adapter path.
    // Pointer is unaffected — secure input only gates keyboard.
    if let Some(denial) = computer_use::denial_codes::secure_input_decision(
        request.secure_input_active.unwrap_or(false),
        capability,
    ) {
        return native_boundary_denial(action, capability, "denied", denial.as_str());
    }

    native_boundary_policy_decision(
        action,
        computer_use::evaluate_native_control_command_policy(
            computer_use::NativeControlCommandPolicy {
                mode,
                capability,
                has_claim_lease: true,
                tier_enabled: desktop_control_allows_capability(capability),
                envelope: Some(envelope.envelope),
                now_ms,
            },
            permissions,
            action,
        ),
    )
}

/// True when macOS Secure Input is enabled by ANY process (e.g. a password field
/// is focused). Read locally via Carbon `IsSecureEventInputEnabled` — a harmless
/// system-state read, no TCC. While active, synthetic keystrokes are unsafe, so
/// the boundary denies keyboard actuation.
#[cfg(target_os = "macos")]
fn secure_input_is_active() -> bool {
    #[link(name = "Carbon", kind = "framework")]
    extern "C" {
        fn IsSecureEventInputEnabled() -> u8;
    }
    unsafe { IsSecureEventInputEnabled() != 0 }
}

#[cfg(not(target_os = "macos"))]
fn secure_input_is_active() -> bool {
    false
}

fn boundary_request_with_native_frontmost_bundle(
    mut request: NativeControlBoundaryProofRequest,
    live_frontmost_bundle_id: Option<String>,
) -> NativeControlBoundaryProofRequest {
    request.live_frontmost_bundle_id = live_frontmost_bundle_id;
    request
}

fn emit_native_control_audit(
    app: &tauri::AppHandle,
    request: &NativeControlBoundaryProofRequest,
    decision: &NativeControlBoundaryDecision,
    event_id: &str,
    mode: computer_use::DesktopControlMode,
    permissions: &computer_use::DesktopPermissionReadiness,
) {
    let event = DesktopNativeControlAuditEvent {
        event_id: event_id.to_string(),
        event_type: "desktop_native_control_denied".to_string(),
        source: "tauri_local".to_string(),
        action: decision.action.clone(),
        capability: decision.capability.clone(),
        outcome: decision.outcome.to_string(),
        reason: if decision.reason.is_empty() {
            None
        } else {
            Some(decision.reason.clone())
        },
        mode: mode.as_str().to_string(),
        shell_id: request.shell_id.clone(),
        desktop_command_id: request.desktop_command_id.clone(),
        approval_id: request.approval_id.clone(),
        device_id: request.device_id.clone(),
        session_id: request.session_id.clone(),
        created_at_ms: now_unix_ms(),
        screen_recording_status: permissions.screen_recording.status.clone(),
        accessibility_status: permissions.accessibility.status.clone(),
        automation_system_events_status: permissions.automation_system_events.status.clone(),
    };
    if let Err(e) = app.emit("desktop-control-audit", &event) {
        log::warn!(
            "desktop native-control audit emit failed for {}: {e}",
            decision.action
        );
    }
    log::warn!(
        "desktop native-control audit: action={} capability={} outcome={} reason={}",
        event.action,
        event.capability,
        event.outcome,
        event.reason.as_deref().unwrap_or("")
    );
}

pub(crate) fn desktop_control_allows_actuation() -> bool {
    // Legacy global gate for the gesture-cursor CGEvent path. Kept HARD-disabled
    // here: per-capability enablement (below) governs the command-boundary
    // policy, but the real gesture actuation path stays off until a reviewed
    // Phase 3 canary wires capability-aware gesture actuation. Phase 2.75 ships
    // the gate, never the CGEvent call.
    false
}

/// Returns true only when `var` is set to an explicit truthy value. Anything
/// else (unset, empty, "0", "false", junk) is false — native actuation is
/// fail-closed by default.
fn actuation_env_flag_enabled(var: &str) -> bool {
    std::env::var(var)
        .map(|raw| {
            let v = raw.trim();
            v.eq_ignore_ascii_case("true") || v == "1" || v.eq_ignore_ascii_case("yes")
        })
        .unwrap_or(false)
}

/// Per-capability native-actuation enablement (Phase 2.75). Environment-driven so
/// a shipped build can opt a single capability into a reviewed canary — or be
/// rolled back — WITHOUT a rebuild. BOTH capabilities default DISABLED, and the
/// flags are independent: enabling `LUNA_ACTUATION_POINTER_ENABLED` never makes
/// keyboard reachable, and vice-versa. This gate only feeds the command-boundary
/// policy `tier_enabled`; the pointer/keyboard Tauri commands remain
/// non-actuating stubs (denied at `has_claim_lease`) and the gesture CGEvent path
/// stays hard-disabled, so flipping a flag in this phase still posts no native
/// event — it only lets the boundary proof reach its policy decision.
pub(crate) fn desktop_control_allows_capability(
    capability: computer_use::NativeControlCapability,
) -> bool {
    match capability {
        computer_use::NativeControlCapability::Pointer => {
            actuation_env_flag_enabled("LUNA_ACTUATION_POINTER_ENABLED")
        }
        computer_use::NativeControlCapability::Keyboard => {
            actuation_env_flag_enabled("LUNA_ACTUATION_KEYBOARD_ENABLED")
        }
    }
}

fn ensure_desktop_control_allows_native_control(
    action: &str,
    capability: computer_use::NativeControlCapability,
) -> Result<(), String> {
    let mode = current_desktop_control_mode();
    let permissions = computer_use::current_permission_readiness();
    computer_use::evaluate_native_control_command_policy(
        computer_use::NativeControlCommandPolicy {
            mode,
            capability,
            has_claim_lease: false,
            // Uniform per-capability gate. Moot on this path — the policy denies
            // at `has_claim_lease: false` before the tier check — but keeps the
            // actuation gate single-sourced through `desktop_control_allows_capability`.
            tier_enabled: desktop_control_allows_capability(capability),
            envelope: None,
            now_ms: now_unix_ms(),
        },
        &permissions,
        action,
    )
    .map_err(|denial| denial.reason)
}

fn ensure_desktop_control_allows_pointer_actuation(action: &str) -> Result<(), String> {
    ensure_desktop_control_allows_native_control(
        action,
        computer_use::NativeControlCapability::Pointer,
    )
}

fn ensure_desktop_control_allows_keyboard_actuation(action: &str) -> Result<(), String> {
    ensure_desktop_control_allows_native_control(
        action,
        computer_use::NativeControlCapability::Keyboard,
    )
}

async fn current_control_safety_state() -> ControlSafetyState {
    let mode = CONTROL_MODE.load(Ordering::SeqCst);
    let last_stop = LAST_STOP_AT_MS.load(Ordering::SeqCst);
    let gesture = gesture::engine_status().await;
    let permissions = computer_use::current_permission_readiness();
    let macos_app_monitor = current_macos_app_monitor_status(mode, &permissions);
    ControlSafetyState {
        mode: control_mode_name(mode).to_string(),
        observe_enabled: mode == CONTROL_MODE_OBSERVE,
        assist_enabled: false,
        control_enabled: false,
        stopped: mode == CONTROL_MODE_STOPPED,
        control_locked: mode != CONTROL_MODE_OBSERVE,
        capture_running: CAPTURE_RUNNING.load(Ordering::SeqCst),
        gesture_state: gesture.state,
        cursor_global: gesture::global_mode(),
        can_observe: mode != CONTROL_MODE_STOPPED,
        can_assist: false,
        can_control: false,
        can_control_pointer: false,
        can_control_keyboard: false,
        alpha_kernel: discover_alpha_kernel(),
        macos_app_monitor,
        permissions,
        last_stop_at_ms: if last_stop == 0 {
            None
        } else {
            Some(last_stop)
        },
    }
}

#[tauri::command]
async fn control_get_safety_state() -> Result<ControlSafetyState, String> {
    Ok(current_control_safety_state().await)
}

#[tauri::command]
async fn control_prove_native_command_boundary(
    app: tauri::AppHandle,
    request: NativeControlBoundaryProofRequest,
) -> Result<NativeControlBoundaryProofResult, String> {
    let mode = current_desktop_control_mode();
    let permissions = computer_use::current_permission_readiness();
    let audit_event_id = uuid::Uuid::new_v4().to_string();
    let mut request =
        boundary_request_with_native_frontmost_bundle(request, frontmost_application_bundle_id());
    // Read macOS Secure Input locally at proof time — never trust the renderer.
    request.secure_input_active = Some(secure_input_is_active());
    let decision = evaluate_native_control_boundary_request(
        &request,
        mode,
        &permissions,
        now_unix_ms(),
        verify_native_control_boundary_envelope_signature,
        remember_native_boundary_nonce,
    );

    emit_native_control_audit(
        &app,
        &request,
        &decision,
        &audit_event_id,
        mode,
        &permissions,
    );

    Ok(NativeControlBoundaryProofResult {
        allowed: decision.allowed,
        outcome: decision.outcome.to_string(),
        reason: if decision.reason.is_empty() {
            format!(
                "desktop native control disabled; {} denied",
                decision.action
            )
        } else {
            decision.reason
        },
        action: decision.action,
        capability: decision.capability,
        audit_event_id,
        mode: mode.as_str().to_string(),
    })
}

#[tauri::command]
async fn control_observe_status(app: tauri::AppHandle) -> Result<ControlSafetyState, String> {
    // Decide + flip the mode under the latch lock so observe can never race past
    // a concurrent Stop. A latched Stop is preserved (no mode change, no event).
    let armed = {
        let _latch = lock_latch();
        if observe_allowed_in_mode(CONTROL_MODE.load(Ordering::SeqCst)) {
            CONTROL_MODE.store(CONTROL_MODE_OBSERVE, Ordering::SeqCst);
            true
        } else {
            false
        }
    };
    let state = current_control_safety_state().await;
    if armed {
        let _ = app.emit("control-safety-changed", state.clone());
    }
    Ok(state)
}

#[tauri::command]
async fn control_stop_all(app: tauri::AppHandle) -> Result<ControlSafetyState, String> {
    let at = now_unix_ms();
    // Hold the latch lock across the mode store + persist so a concurrent Resume
    // from another window can't interleave and leave memory STOPPED while the
    // latch file is removed (or vice versa). Persist before the fallible engine
    // teardown so the latch survives even if teardown errors; the in-memory
    // store is already authoritative. Guard dropped before the await.
    {
        let _latch = lock_latch();
        CONTROL_MODE.store(CONTROL_MODE_STOPPED, Ordering::SeqCst);
        LAST_STOP_AT_MS.store(at, Ordering::SeqCst);
        CAPTURE_RUNNING.store(false, Ordering::SeqCst);
        persist_stop_latch(&app, true, at);
    }
    gesture::set_global_mode(false);
    // Stop is already authoritative + persisted above. A gesture-teardown error
    // must not make the UI believe the safety latch failed.
    if let Err(e) = gesture::stop_engine().await {
        log::warn!("desktop control: gesture stop errored during Stop (latch already set): {e}");
    }
    let state = current_control_safety_state().await;
    let _ = app.emit("control-safety-changed", state.clone());
    Ok(state)
}

#[tauri::command]
async fn control_lock_all(app: tauri::AppHandle) -> Result<ControlSafetyState, String> {
    // Read-modify-write under the latch lock so a Lock can't race a concurrent
    // Stop and overwrite a just-set STOPPED (next_mode_for_lock preserves it).
    {
        let _latch = lock_latch();
        let next = next_mode_for_lock(CONTROL_MODE.load(Ordering::SeqCst));
        CONTROL_MODE.store(next, Ordering::SeqCst);
        CAPTURE_RUNNING.store(false, Ordering::SeqCst);
    }
    gesture::set_global_mode(false);
    // Lock should not fail just because a gesture teardown is already stopped.
    if let Err(e) = gesture::stop_engine().await {
        log::warn!("desktop control: gesture stop errored during Lock: {e}");
    }
    let state = current_control_safety_state().await;
    let _ = app.emit("control-safety-changed", state.clone());
    Ok(state)
}

/// Explicitly clear the durable Stop latch — the user-initiated "resume" out of
/// emergency Stop. This is the ONLY way out of STOPPED: relaunching no longer
/// clears it (see `restore_persisted_stop`). Drops to the safe LOCKED posture
/// (observe off, nothing armed); the user must then opt back into Observe, so a
/// resume can never silently re-arm observation.
#[tauri::command]
async fn control_clear_stop(app: tauri::AppHandle) -> Result<ControlSafetyState, String> {
    {
        let _latch = lock_latch();
        CONTROL_MODE.store(CONTROL_MODE_LOCKED, Ordering::SeqCst);
        // Clear the stop timestamp too — there is no longer a latched Stop.
        LAST_STOP_AT_MS.store(0, Ordering::SeqCst);
        CAPTURE_RUNNING.store(false, Ordering::SeqCst);
        persist_stop_latch(&app, false, 0);
    }
    let state = current_control_safety_state().await;
    let _ = app.emit("control-safety-changed", state.clone());
    Ok(state)
}

#[tauri::command]
async fn control_open_permission_setup(
    app: tauri::AppHandle,
    permission: String,
) -> Result<ControlSafetyState, String> {
    computer_use::permissions::open_permission_setup(&permission)?;
    let state = current_control_safety_state().await;
    let _ = app.emit("control-safety-changed", state.clone());
    Ok(state)
}

#[cfg(target_os = "macos")]
fn frontmost_application_bundle_id() -> Option<String> {
    use std::ffi::{c_char, c_void, CStr};

    #[link(name = "AppKit", kind = "framework")]
    extern "C" {}

    #[link(name = "objc")]
    extern "C" {
        fn objc_getClass(name: *const c_char) -> *mut c_void;
        fn sel_registerName(name: *const c_char) -> *mut c_void;
        fn objc_msgSend();
    }

    type MsgSendObject = unsafe extern "C" fn(*mut c_void, *mut c_void) -> *mut c_void;
    type MsgSendUtf8String = unsafe extern "C" fn(*mut c_void, *mut c_void) -> *const c_char;

    let class = unsafe { objc_getClass(b"NSWorkspace\0".as_ptr().cast()) };
    let shared_selector = unsafe { sel_registerName(b"sharedWorkspace\0".as_ptr().cast()) };
    let frontmost_selector = unsafe { sel_registerName(b"frontmostApplication\0".as_ptr().cast()) };
    let bundle_selector = unsafe { sel_registerName(b"bundleIdentifier\0".as_ptr().cast()) };
    let utf8_selector = unsafe { sel_registerName(b"UTF8String\0".as_ptr().cast()) };
    if class.is_null()
        || shared_selector.is_null()
        || frontmost_selector.is_null()
        || bundle_selector.is_null()
        || utf8_selector.is_null()
    {
        return None;
    }

    let send_object: MsgSendObject = unsafe { std::mem::transmute(objc_msgSend as *const ()) };
    let send_utf8: MsgSendUtf8String = unsafe { std::mem::transmute(objc_msgSend as *const ()) };
    let workspace = unsafe { send_object(class, shared_selector) };
    if workspace.is_null() {
        return None;
    }
    let app = unsafe { send_object(workspace, frontmost_selector) };
    if app.is_null() {
        return None;
    }
    let bundle = unsafe { send_object(app, bundle_selector) };
    if bundle.is_null() {
        return None;
    }
    let ptr = unsafe { send_utf8(bundle, utf8_selector) };
    if ptr.is_null() {
        return None;
    }
    unsafe { CStr::from_ptr(ptr) }
        .to_str()
        .ok()
        .map(str::trim)
        .filter(|bundle_id| !bundle_id.is_empty())
        .map(ToString::to_string)
}

#[cfg(not(target_os = "macos"))]
fn frontmost_application_bundle_id() -> Option<String> {
    None
}

#[tauri::command]
async fn control_get_frontmost_app_bundle_id() -> Result<Option<String>, String> {
    Ok(frontmost_application_bundle_id())
}

/// Resolve (and create) Luna's Tauri app-data dir for durable safety state.
fn luna_app_data_dir(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("resolve Luna app data dir: {e}"))?;
    std::fs::create_dir_all(&dir).map_err(|e| format!("create Luna app data dir: {e}"))?;
    Ok(dir)
}

/// Best-effort write/clear of the durable Stop latch. Never fails the caller:
/// the in-memory `CONTROL_MODE` is authoritative for the running session, and a
/// failed persist only means the latch won't survive relaunch (logged).
fn persist_stop_latch(app: &tauri::AppHandle, stopped: bool, at_ms: u64) {
    match luna_app_data_dir(app) {
        Ok(dir) => {
            if let Err(e) = computer_use::stop_state::persist_stop(&dir, stopped, at_ms) {
                log::warn!(
                    "desktop control: failed to persist Stop latch (stopped={stopped}): {e}"
                );
            }
        }
        Err(e) => log::warn!("desktop control: cannot resolve app data dir for Stop latch: {e}"),
    }
}

/// Restore the durable Stop latch at startup. If the user latched Stop in a
/// prior run, Luna comes back STOPPED (the safest posture) until the user
/// explicitly clears it via `control_clear_stop`. Best-effort: a resolve/read
/// failure leaves the default LOCKED mode, which is itself safe (nothing armed).
fn restore_persisted_stop(app: &tauri::AppHandle) {
    let Ok(dir) = luna_app_data_dir(app) else {
        return;
    };
    if let Some(at_ms) = computer_use::stop_state::load_stop(&dir) {
        CONTROL_MODE.store(CONTROL_MODE_STOPPED, Ordering::SeqCst);
        LAST_STOP_AT_MS.store(at_ms, Ordering::SeqCst);
        log::info!("desktop control: restored durable Stop latch from a prior session");
    }
}

/// Screenshot capture — desktop only (uses macOS screencapture binary).
/// On iOS returns an error; the frontend should use the native share sheet instead.
#[tauri::command]
async fn capture_screenshot(app: tauri::AppHandle) -> Result<String, String> {
    let audit = begin_observation_audit(
        &app,
        "capture_screenshot",
        computer_use::ObservationCapability::Screenshot,
    )?;
    #[cfg(desktop)]
    {
        use std::process::Command;

        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let path = format!("/tmp/luna-screenshot-{}.png", timestamp);

        let output = Command::new("screencapture")
            .args(["-x", "-C", &path])
            .output()
            .map_err(|e| {
                let reason = format!("Screenshot failed: {}", e);
                fail_observation_audit(&app, &audit, &reason);
                reason
            })?;

        if !output.status.success() {
            let reason = "Screenshot capture failed".to_string();
            fail_observation_audit(&app, &audit, &reason);
            return Err(reason);
        }

        let bytes = std::fs::read(&path).map_err(|e| {
            let reason = format!("Failed to read screenshot: {}", e);
            fail_observation_audit(&app, &audit, &reason);
            reason
        })?;
        let _ = std::fs::remove_file(&path);

        complete_observation_audit(&app, &audit);
        return Ok(base64_encode(&bytes));
    }

    #[cfg(mobile)]
    {
        let reason = "Screenshot not available on mobile — use the system share sheet".to_string();
        fail_observation_audit(&app, &audit, &reason);
        Err(reason)
    }
}

/// Haptic feedback trigger — mobile only, no-op on desktop.
#[tauri::command]
async fn haptic_feedback(style: String) -> Result<(), String> {
    log::info!("Haptic feedback: {}", style);
    // tauri-plugin-haptics exposes its own invoke commands (ImpactFeedback etc.)
    // This command lets the frontend check if it's on mobile before calling those.
    Ok(())
}

#[tauri::command]
async fn get_active_app(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let audit = begin_observation_audit(
        &app,
        "get_active_app",
        computer_use::ObservationCapability::ActiveApp,
    )?;
    use std::process::Command;

    let app_output = Command::new("osascript")
        .args(["-e", "tell application \"System Events\" to get name of first application process whose frontmost is true"])
        .output()
        .map_err(|e| {
            let reason = format!("Failed: {}", e);
            fail_observation_audit(&app, &audit, &reason);
            reason
        })?;
    if !app_output.status.success() {
        let reason = "Active app lookup failed".to_string();
        fail_observation_audit(&app, &audit, &reason);
        return Err(reason);
    }
    let app_name = String::from_utf8_lossy(&app_output.stdout)
        .trim()
        .to_string();

    let safe_name = app_name.replace('\\', "\\\\").replace('"', "\\\"");
    let title_output = Command::new("osascript")
        .args(["-e", &format!(
            "tell application \"System Events\" to get name of front window of application process \"{}\"",
            safe_name
        )])
        .output();

    let window_title = match title_output {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).trim().to_string(),
        _ => String::new(),
    };

    complete_observation_audit(&app, &audit);
    Ok(build_active_app_metadata(&app_name, &window_title))
}

#[tauri::command]
async fn read_clipboard(app: tauri::AppHandle) -> Result<String, String> {
    let audit = begin_observation_audit(
        &app,
        "read_clipboard",
        computer_use::ObservationCapability::ClipboardRead,
    )?;
    use std::process::Command;
    let output = Command::new("pbpaste").output().map_err(|e| {
        let reason = format!("Clipboard read failed: {}", e);
        fail_observation_audit(&app, &audit, &reason);
        reason
    })?;
    if !output.status.success() {
        let reason = "Clipboard read failed".to_string();
        fail_observation_audit(&app, &audit, &reason);
        return Err(reason);
    }
    complete_observation_audit(&app, &audit);
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

#[tauri::command]
async fn control_pointer_move(_x: f64, _y: f64) -> Result<(), String> {
    ensure_desktop_control_allows_pointer_actuation("control_pointer_move")
}

#[tauri::command]
async fn control_pointer_click(_x: f64, _y: f64, _button: Option<String>) -> Result<(), String> {
    ensure_desktop_control_allows_pointer_actuation("control_pointer_click")
}

#[tauri::command]
async fn control_keyboard_type(_text: String) -> Result<(), String> {
    ensure_desktop_control_allows_keyboard_actuation("control_keyboard_type")
}

#[tauri::command]
async fn control_keyboard_key_chord(_keys: Vec<String>) -> Result<(), String> {
    ensure_desktop_control_allows_keyboard_actuation("control_keyboard_key_chord")
}

#[tauri::command]
async fn toggle_spatial_hud(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("spatial_hud") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
            CAPTURE_RUNNING.store(false, Ordering::Relaxed);
        } else {
            ensure_desktop_control_allows_observation("toggle_spatial_hud")?;
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
    Ok(())
}

#[derive(Clone, serde::Serialize)]
struct SpatialFrame {
    width: u32,
    height: u32,
    timestamp: f64,
}

#[tauri::command]
async fn start_spatial_capture(_app: tauri::AppHandle) -> Result<(), String> {
    ensure_desktop_control_allows_observation("start_spatial_capture")?;
    // Real `spatial-frame` events are now emitted by the gesture engine
    // (`gesture::supervisor::run_engine_loop`). This command is kept as a
    // no-op for FFI compatibility with the existing frontend HUD bootstrap.
    CAPTURE_RUNNING.store(true, Ordering::Relaxed);
    Ok(())
}

#[tauri::command]
async fn stop_spatial_capture() -> Result<(), String> {
    CAPTURE_RUNNING.store(false, Ordering::Relaxed);
    Ok(())
}

// ── Gesture engine commands ─────────────────────────────────────────────────

#[tauri::command]
async fn gesture_start() -> Result<(), String> {
    ensure_desktop_control_allows_observation("gesture_start")?;
    gesture::start_engine().await
}

#[tauri::command]
async fn gesture_stop() -> Result<(), String> {
    gesture::stop_engine().await
}

#[tauri::command]
async fn gesture_pause() -> Result<(), String> {
    gesture::pause_engine().await
}

#[tauri::command]
async fn gesture_resume() -> Result<(), String> {
    ensure_desktop_control_allows_observation("gesture_resume")?;
    gesture::resume_engine().await
}

#[tauri::command]
async fn gesture_status() -> Result<gesture::EngineStatus, String> {
    Ok(gesture::engine_status().await)
}

#[tauri::command]
async fn gesture_list_cameras() -> Result<Vec<String>, String> {
    Ok(gesture::list_cameras().await)
}

#[tauri::command]
async fn gesture_set_camera_index(index: usize) -> Result<(), String> {
    gesture::set_camera_index(index).await
}

#[tauri::command]
async fn gesture_check_accessibility() -> Result<bool, String> {
    Ok(gesture::check_accessibility())
}

#[tauri::command]
async fn gesture_set_cursor_global(enabled: bool) -> Result<(), String> {
    if enabled {
        ensure_desktop_control_not_stopped("gesture_set_cursor_global")?;
        ensure_desktop_control_allows_pointer_actuation("gesture_set_cursor_global")?;
    }
    gesture::set_global_mode(enabled);
    Ok(())
}

#[tauri::command]
async fn gesture_get_cursor_global() -> Result<bool, String> {
    Ok(gesture::global_mode())
}

/// Show + focus the secondary `main` chat window (the comms panel of Luna
/// OS — the conductor's score sheet for typed dialogue).
#[tauri::command]
async fn open_main_window(app: tauri::AppHandle) -> Result<(), String> {
    show_main_window_maximized(&app)
}

/// Hide the secondary `main` chat window without quitting it.
#[tauri::command]
async fn hide_main_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
    Ok(())
}

/// Bring the Luna OS spatial podium to the foreground. Used by the
/// `nav_hud` gesture binding from any window.
#[tauri::command]
async fn focus_podium(app: tauri::AppHandle) -> Result<(), String> {
    ensure_desktop_control_not_stopped("focus_podium")?;
    if let Some(window) = app.get_webview_window("spatial_hud") {
        let _ = window.show();
        let _ = window.set_focus();
        Ok(())
    } else {
        Err("spatial_hud window not registered".into())
    }
}

/// Whether the updater is configured with a non-empty signing pubkey. When
/// false, `download_and_install` would fail at the verification step after
/// a wasteful full DMG download — `tauri-plugin-updater` calls
/// `verify_signature` unconditionally and an empty pubkey decodes to an
/// error. So we fail fast with a clear message and let the React banner
/// fall back to opening the GitHub Releases page.
///
/// The pubkey value is read from `tauri.conf.json` at build time via
/// `build.rs`, which sets `LUNA_UPDATER_PUBKEY` as a rustc env var.
fn updater_signing_configured() -> bool {
    !env!("LUNA_UPDATER_PUBKEY").trim().is_empty()
}

#[tauri::command]
async fn updater_signing_status() -> Result<bool, String> {
    Ok(updater_signing_configured())
}

/// Download and apply the latest available update, then restart the app.
/// Requires updater signing to be configured (non-empty pubkey + matching
/// `TAURI_SIGNING_PRIVATE_KEY` GitHub secret signing each release).
#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    if !updater_signing_configured() {
        log::error!("update: signing not configured — install_update will not run");
        return Err("auto-install requires updater signing to be configured \
             (set TAURI_SIGNING_PRIVATE_KEY secret and embed pubkey in \
             tauri.conf.json). Falling back to manual download."
            .to_string());
    }
    log::info!("update: install_update invoked");
    use tauri_plugin_updater::UpdaterExt;
    let updater = app.updater().map_err(|e| {
        log::error!("update: updater init failed: {e}");
        format!("updater init: {e}")
    })?;
    let update = match updater.check().await {
        Ok(Some(u)) => {
            log::info!("update: check returned version {}", u.version);
            u
        }
        Ok(None) => {
            log::info!("update: no update available");
            return Err("no update available".to_string());
        }
        Err(e) => {
            log::error!("update: check failed: {e}");
            return Err(format!("check: {e}"));
        }
    };
    let mut downloaded: usize = 0;
    if let Err(e) = update
        .download_and_install(
            |chunk_len, _content_length| {
                downloaded += chunk_len;
                log::debug!("update: downloaded {} bytes", downloaded);
            },
            || log::info!("update: download complete; installing"),
        )
        .await
    {
        // The previous version returned this error to the frontend
        // silently — that's why the user saw the button "do nothing":
        // download_and_install repeatedly succeeds at downloading but
        // the install step fails (typically code-signing mismatch on
        // macOS, or a permissions issue on /Applications/Luna.app).
        // Log it so the failure mode is visible in Luna.log.
        log::error!("update: download_and_install failed: {e}");
        return Err(format!("install: {e}"));
    }
    log::info!("update: install completed; restarting");
    app.restart();
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct ProjectionResult {
    id: String,
    x: f32,
    y: f32,
    z: f32,
}

#[tauri::command]
async fn project_embeddings(
    vectors: Vec<Vec<f32>>,
    ids: Vec<String>,
) -> Result<Vec<ProjectionResult>, String> {
    // Phase 1: deterministic scatter projection based on embedding values.
    // Full UMAP dimensionality reduction is a Phase 2 item — requires a
    // suitable Rust UMAP crate with a lib target (umap-rs has none).
    if vectors.is_empty() {
        return Ok(vec![]);
    }

    if vectors.len() != ids.len() {
        return Err("Vectors and IDs length mismatch".to_string());
    }

    let results = vectors
        .iter()
        .zip(ids.iter())
        .map(|(v, id)| {
            // Use first three principal components as a cheap approximation.
            // Scale to [-100, 100] range for the Three.js scene.
            let x = v.get(0).copied().unwrap_or(0.0) * 100.0;
            let y = v.get(1).copied().unwrap_or(0.0) * 100.0;
            let z = v.get(2).copied().unwrap_or(0.0) * 100.0;
            ProjectionResult {
                id: id.clone(),
                x,
                y,
                z,
            }
        })
        .collect();

    Ok(results)
}

/// Resolve the real tool/app from generic process names.
/// - Terminal/iTerm2: checks window title for running commands (claude, docker, npm, etc.)
/// - Electron: extracts real app name from window title
#[cfg(test)]
fn resolve_app_context(app_name: &str, window_title: &str) -> String {
    let lower_title = window_title.to_lowercase();

    // Terminal emulators: detect what's running inside
    if matches!(
        app_name,
        "Terminal" | "iTerm2" | "Alacritty" | "kitty" | "Warp" | "Hyper"
    ) {
        let tools = [
            ("claude", "Claude Code"),
            ("codex", "Codex CLI"),
            ("npm run", "npm"),
            ("pnpm", "pnpm"),
            ("cargo", "Cargo"),
            ("docker", "Docker CLI"),
            ("kubectl", "kubectl"),
            ("python", "Python"),
            ("node ", "Node.js"),
            ("vim", "Vim"),
            ("nvim", "Neovim"),
            ("ssh ", "SSH"),
            ("git ", "Git"),
            ("psql", "PostgreSQL CLI"),
        ];
        for (pattern, label) in tools {
            if lower_title.contains(pattern) {
                return format!("{} ({})", label, app_name);
            }
        }
        return app_name.to_string();
    }

    // Electron/Code editors: extract PROJECT name, not file name
    // Window titles look like: "project-name — filename.ext" or "project-name - filename"
    if matches!(app_name, "Electron" | "Code" | "Code - Insiders" | "Cursor") {
        // Extract the first segment before " — " or " - " (that's the project)
        let project = if let Some(pos) = window_title.find(" \u{2014} ") {
            // em dash (—) separator: "agentprovision-agents — file.md"
            window_title[..pos].trim()
        } else if let Some(pos) = window_title.find(" - ") {
            window_title[..pos].trim()
        } else {
            window_title.trim()
        };
        if !project.is_empty() {
            return project.to_string();
        }
    }

    // Chrome/Safari: extract just the domain or short title
    if matches!(app_name, "Google Chrome" | "Safari" | "Firefox" | "Arc") {
        if !window_title.is_empty() {
            // Truncate to just the meaningful part
            let short = if let Some(pos) = window_title.find(" - ") {
                &window_title[..pos]
            } else {
                truncate_str(&window_title, 40)
            };
            return format!("{} ({})", app_name, short.trim());
        }
    }

    app_name.to_string()
}

fn active_app_context_key(app_name: &str, window_title: &str) -> String {
    use std::hash::{Hash, Hasher};

    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    app_name.hash(&mut hasher);
    window_title.hash(&mut hasher);
    format!("{}:{:x}", app_name, hasher.finish())
}

fn build_metadata_app_switch_event(
    from_app: &str,
    to_app: &str,
    window_title: &str,
    duration_secs: u64,
    timestamp: u64,
) -> serde_json::Value {
    let active_context_id = active_app_context_key(to_app, window_title);
    serde_json::json!({
        "schema": "agentprovision.macos_app_monitor_event.v1",
        "event_id": uuid::Uuid::new_v4().to_string(),
        "type": "app_switch",
        "from_app": from_app,
        "to_app": to_app,
        "duration_secs": duration_secs,
        "timestamp": timestamp,
        "observed_at_ms": timestamp.saturating_mul(1000),
        "platform": "macos",
        "monitor_source": "tauri_activity_tracker",
        "detail_level": "metadata_only",
        "active_context_id": active_context_id,
        "window_title_present": !window_title.is_empty(),
        "window_title_chars": window_title.chars().count(),
    })
}

fn build_active_app_metadata(app_name: &str, window_title: &str) -> serde_json::Value {
    serde_json::json!({
        "app": app_name,
        "title_present": !window_title.is_empty(),
        "title_chars": window_title.chars().count(),
    })
}

/// Get deeper subprocess context: what project/repo is the user working on,
/// what commands are running in their terminal sessions.
#[cfg(test)]
#[allow(dead_code)]
fn get_subprocess_context() -> serde_json::Value {
    use std::process::Command;

    // Get foreground terminal processes (children of Terminal/iTerm)
    // `ps` shows all processes with their command, we filter for interesting ones
    let ps_output = Command::new("sh")
        .args(["-c", "ps -eo pid,ppid,comm,args 2>/dev/null | grep -E 'claude|docker|cargo|npm|node|python|git|kubectl|uvicorn|vite' | grep -v grep | head -10"])
        .output();

    let mut processes = Vec::new();
    if let Ok(output) = ps_output {
        let text = String::from_utf8_lossy(&output.stdout);
        for line in text.lines() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 4 {
                let comm = parts[2];
                let args = parts[3..].join(" ");
                // Extract project context from args (look for paths)
                let project = extract_project_from_args(&args);
                processes.push(serde_json::json!({
                    "command": comm,
                    "args": truncate_str(&args, 120),
                    "project": project,
                }));
            }
        }
    }

    // Get the current git repo if we're in one (from the most recent terminal cwd)
    let git_output = Command::new("sh")
        .args([
            "-c",
            "lsof -c Terminal -c iTerm2 -a -d cwd 2>/dev/null | tail -1 | awk '{print $NF}'",
        ])
        .output();

    let cwd = match git_output {
        Ok(o) => String::from_utf8_lossy(&o.stdout).trim().to_string(),
        _ => String::new(),
    };

    serde_json::json!({
        "active_processes": processes,
        "terminal_cwd": cwd,
    })
}

/// Extract project name from command args (looks for repo paths)
#[cfg(test)]
fn extract_project_from_args(args: &str) -> String {
    // Look for common project path patterns
    for part in args.split_whitespace() {
        if part.contains("/GitHub/") || part.contains("/Projects/") || part.contains("/src/") {
            // Extract the repo/project name from the path
            let segments: Vec<&str> = part.split('/').collect();
            for (i, seg) in segments.iter().enumerate() {
                if (*seg == "GitHub" || *seg == "Projects") && i + 1 < segments.len() {
                    return segments[i + 1].to_string();
                }
            }
        }
    }
    String::new()
}

#[cfg(test)]
fn truncate_str(s: &str, max: usize) -> &str {
    if s.len() <= max {
        s
    } else {
        &s[..max]
    }
}

fn base64_encode(data: &[u8]) -> String {
    const CHARS: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut result = String::with_capacity(data.len() * 4 / 3 + 4);
    for chunk in data.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = chunk.get(1).copied().unwrap_or(0) as u32;
        let b2 = chunk.get(2).copied().unwrap_or(0) as u32;
        let n = (b0 << 16) | (b1 << 8) | b2;
        result.push(CHARS[((n >> 18) & 63) as usize] as char);
        result.push(CHARS[((n >> 12) & 63) as usize] as char);
        if chunk.len() > 1 {
            result.push(CHARS[((n >> 6) & 63) as usize] as char);
        } else {
            result.push('=');
        }
        if chunk.len() > 2 {
            result.push(CHARS[(n & 63) as usize] as char);
        } else {
            result.push('=');
        }
    }
    result
}

#[cfg(desktop)]
fn setup_tray(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    // Chat/sessions are the primary product surface. The spatial HUD remains
    // available as an explicit Labs surface, but it should not open from the
    // default tray click.
    let open_chat = MenuItem::with_id(app, "open_chat", "Open Luna", true, None::<&str>)?;
    let open_os = MenuItem::with_id(app, "open_os", "Open Luna OS / Labs", true, None::<&str>)?;
    // Emergency Stop reachable even when the main window is hidden/unfocused.
    let stop_all = MenuItem::with_id(
        app,
        "stop_all",
        "Stop All Desktop Control",
        true,
        None::<&str>,
    )?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit Luna", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open_chat, &open_os, &stop_all, &quit_item])?;

    let _tray = TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("Luna")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open_chat" => {
                let _ = show_main_window_maximized(app);
            }
            "open_os" => {
                if let Some(window) = app.get_webview_window("spatial_hud") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            "stop_all" => {
                // Latch the emergency Stop (now durable across relaunch) and
                // surface the main window so the operator sees the stopped state.
                let handle = app.clone();
                tauri::async_runtime::spawn(async move {
                    let _ = control_stop_all(handle.clone()).await;
                    let _ = show_main_window_maximized(&handle);
                });
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let tauri::tray::TrayIconEvent::Click { .. } = event {
                let app = tray.app_handle();
                let _ = show_main_window_maximized(app);
            }
        })
        .build(app)?;

    Ok(())
}

#[cfg(desktop)]
fn setup_global_shortcut(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut};

    let palette_shortcut = Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::Space);
    let hud_shortcut = Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::KeyL);
    let gesture_killswitch = Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::KeyG);
    // Cmd+Shift+Period — global emergency Stop for all desktop control.
    let desktop_stop = Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::Period);

    app.global_shortcut()
        .on_shortcut(palette_shortcut, move |app, _shortcut, event| {
            if event.state == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                // Restore/maximize/focus even when the window is already visible:
                // macOS can report a minimized or manually resized window as
                // visible, and the palette should always open on the full chat
                // surface.
                let _ = show_main_window_maximized(app);
                // Emit to frontend — React handles showing the command palette.
                let _ = tauri::Emitter::emit(app, "toggle-palette", ());
            }
        })?;

    // Cmd+Shift+L toggles the primary `main` chat/session window.
    // Spatial HUD is an explicit Labs surface opened from the tray/menu.
    app.global_shortcut()
        .on_shortcut(hud_shortcut, move |app, _shortcut, event| {
            if event.state == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                if let Some(window) = app.get_webview_window("main") {
                    if window.is_visible().unwrap_or(false) {
                        let _ = window.hide();
                    } else {
                        let _ = show_main_window_maximized(app);
                    }
                }
            }
        })?;

    // Cmd+Shift+G — gesture engine kill-switch (toggle pause/resume).
    app.global_shortcut()
        .on_shortcut(gesture_killswitch, move |_app, _shortcut, event| {
            if event.state == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                tauri::async_runtime::spawn(async move {
                    if !crate::desktop_control_observe_enabled() {
                        let _ = crate::gesture::stop_engine().await;
                        return;
                    }
                    let status = crate::gesture::engine_status().await;
                    if status.state == "paused" {
                        let _ = crate::gesture::resume_engine().await;
                    } else {
                        let _ = crate::gesture::pause_engine().await;
                    }
                });
            }
        })?;

    // Cmd+Shift+Period — global emergency Stop. Latches the durable desktop
    // control Stop from anywhere (even when Luna is hidden/unfocused) and
    // surfaces the main window so the operator sees the stopped state.
    app.global_shortcut()
        .on_shortcut(desktop_stop, move |app, _shortcut, event| {
            if event.state == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                let handle = app.clone();
                tauri::async_runtime::spawn(async move {
                    let _ = crate::control_stop_all(handle.clone()).await;
                    let _ = show_main_window_maximized(&handle);
                });
            }
        })?;

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init());

    // Desktop-only plugins
    #[cfg(desktop)]
    {
        builder = builder
            .plugin(tauri_plugin_global_shortcut::Builder::new().build())
            .plugin(tauri_plugin_updater::Builder::new().build());
    }

    // Mobile-only plugins
    #[cfg(mobile)]
    {
        builder = builder.plugin(tauri_plugin_haptics::init());
    }

    builder
        .setup(|app| {
            // Logging in BOTH debug and release. The release build was
            // previously gated behind `cfg!(debug_assertions)`, leaving
            // production Luna completely silent — no Luna.log, no
            // stderr output, no os_log entries (Tauri's tracing
            // backend does not auto-bridge to unified logging). Field
            // diagnostics on the gesture engine, auto-updater, and
            // gemini quota fallbacks were all blocked by this gap.
            // Defaulting release to Info-level keeps the per-frame
            // gesture spam out (those are at Debug) while preserving
            // engine-status, errors, and lifecycle messages.
            let log_level = if cfg!(debug_assertions) {
                log::LevelFilter::Debug
            } else {
                log::LevelFilter::Info
            };
            app.handle().plugin(
                tauri_plugin_log::Builder::default()
                    .level(log_level)
                    // Write to the standard macOS log location plus the
                    // WebView console (so the React side can read its own
                    // logs) plus stderr (so terminal-launch shows them
                    // live without needing a file tail).
                    .targets([
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir { file_name: None }),
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Webview),
                    ])
                    .build(),
            )?;

            // Restore a durable emergency Stop latched in a prior session so
            // Luna comes back STOPPED rather than silently re-armable on launch
            // (control plan Stop Semantics invariant #5).
            restore_persisted_stop(app.handle());

            #[cfg(desktop)]
            {
                setup_tray(app)?;
                setup_global_shortcut(app)?;

                // Install the AppHandle synchronously so a fast auto-login
                // can call `gesture_start` immediately without racing the
                // setup spawn. install_app_handle is now a sync function
                // backed by a std::sync::Mutex.
                crate::gesture::install_app_handle(app.handle().clone());
                // Engine itself is NOT started here — the frontend calls
                // `gesture_start` after a successful login so we don't burn
                // camera + Apple Vision cycles on the login screen.

                // Tauri's `maximized` window config is not enough on macOS:
                // first launch can still restore or settle into the compact
                // configured size. Make the chat/sessions surface explicitly
                // fill the workspace once the native window exists.
                let startup_handle = app.handle().clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_millis(250));
                    let _ = show_main_window_maximized(&startup_handle);
                });

                // Auto-updater: check on startup + every 30 min, emit
                // `update-available` so the React banner shows. The actual
                // download + install happens in `install_update` when the
                // user clicks the banner button.
                let handle = app.handle().clone();
                std::thread::spawn(move || {
                    loop {
                        let h = handle.clone();
                        tauri::async_runtime::block_on(async move {
                            let updater = match tauri_plugin_updater::UpdaterExt::updater(&h) {
                                Ok(u) => u,
                                Err(e) => { log::warn!("Updater init failed: {}", e); return; }
                            };
                            match updater.check().await {
                                Ok(Some(update)) => {
                                    log::info!("Update available: {}", update.version);
                                    let _ = tauri::Emitter::emit(&h, "update-available", update.version.clone());
                                }
                                Ok(None) => log::info!("No update available"),
                                Err(e) => log::warn!("Update check failed: {}", e),
                            }
                        });
                        std::thread::sleep(std::time::Duration::from_secs(1800));
                    }
                });
            }

            // Clipboard watcher — emits 'clipboard-changed' when clipboard text changes
            // Uses AtomicBool so the thread can be signalled to stop on app exit.
            let clip_running = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(true));
            let clip_flag = clip_running.clone();
            let clip_handle = app.handle().clone();
            std::thread::spawn(move || {
                let mut last_content = String::new();
                while clip_flag.load(std::sync::atomic::Ordering::Relaxed) {
                    std::thread::sleep(std::time::Duration::from_secs(2));
                    if CONTROL_MODE.load(Ordering::SeqCst) != CONTROL_MODE_OBSERVE {
                        continue;
                    }
                    if !observation_policy_currently_allows(
                        "watch_clipboard",
                        computer_use::ObservationCapability::ClipboardRead,
                    ) {
                        continue;
                    }
                    if let Ok(output) = std::process::Command::new("pbpaste").output() {
                        let current = String::from_utf8_lossy(&output.stdout).to_string();
                        if current != last_content && !current.is_empty() {
                            let audit = match begin_observation_audit(
                                &clip_handle,
                                "watch_clipboard",
                                computer_use::ObservationCapability::ClipboardRead,
                            ) {
                                Ok(audit) => audit,
                                Err(_) => continue,
                            };
                            last_content = current.clone();
                            let _ = tauri::Emitter::emit(&clip_handle, "clipboard-changed", &current);
                            complete_observation_audit(&clip_handle, &audit);
                        }
                    }
                }
            });
            // Activity tracker — monitors macOS app switches in metadata-only mode.
            // Raw window titles and subprocess args stay local; emitted events include
            // only app names plus coarse title metadata.
            let activity_handle = app.handle().clone();
            let activity_running = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(true));
            let activity_flag = activity_running.clone();
            std::thread::spawn(move || {
                let mut last_context = String::new();
                let mut last_app = String::new();
                let mut last_switch = std::time::Instant::now();
                while activity_flag.load(std::sync::atomic::Ordering::Relaxed) {
                    std::thread::sleep(std::time::Duration::from_secs(5));
                    if CONTROL_MODE.load(Ordering::SeqCst) != CONTROL_MODE_OBSERVE {
                        continue;
                    }
                    if !observation_policy_currently_allows(
                        "track_active_app",
                        computer_use::ObservationCapability::ActiveApp,
                    ) {
                        continue;
                    }

                    // Get frontmost app
                    let app_name = match std::process::Command::new("osascript")
                        .args(["-e", "tell application \"System Events\" to get name of first application process whose frontmost is true"])
                        .output()
                    {
                        Ok(o) => String::from_utf8_lossy(&o.stdout).trim().to_string(),
                        Err(_) => continue,
                    };
                    if app_name.is_empty() { continue; }

                    // Get window title
                    let safe_name = app_name.replace('\\', "\\\\").replace('"', "\\\"");
                    let window_title = match std::process::Command::new("osascript")
                        .args(["-e", &format!(
                            "tell application \"System Events\" to get name of front window of application process \"{}\"",
                            safe_name
                        )])
                        .output()
                    {
                        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).trim().to_string(),
                        _ => String::new(),
                    };

                    // Only emit on context change (app + title)
                    let context_key = active_app_context_key(&app_name, &window_title);
                    if context_key != last_context {
                        let audit = match begin_observation_audit(
                            &activity_handle,
                            "track_active_app",
                            computer_use::ObservationCapability::ActiveApp,
                        ) {
                            Ok(audit) => audit,
                            Err(_) => continue,
                        };
                        let duration_secs = last_switch.elapsed().as_secs();
                        let timestamp = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)
                            .unwrap()
                            .as_secs();

                        let event = build_metadata_app_switch_event(
                            &last_app,
                            &app_name,
                            &window_title,
                            duration_secs,
                            timestamp,
                        );
                        let _ = tauri::Emitter::emit(&activity_handle, "activity-event", &event);

                        complete_observation_audit(&activity_handle, &audit);
                        last_context = context_key;
                        last_app = app_name;
                        last_switch = std::time::Instant::now();
                    }
                }
            });

            // Stop clipboard watcher + activity tracker on app exit
            if let Some(window) = app.get_webview_window("main") {
                window.on_window_event(move |event| {
                    if let tauri::WindowEvent::Destroyed = event {
                        clip_running.store(false, std::sync::atomic::Ordering::Relaxed);
                        activity_running.store(false, std::sync::atomic::Ordering::Relaxed);
                    }
                });
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_platform,
            get_arch,
            alpha_kernel_status,
            get_or_create_shell_id,
            control_get_safety_state,
            control_prove_native_command_boundary,
            control_get_frontmost_app_bundle_id,
            control_observe_status,
            control_stop_all,
            control_lock_all,
            control_clear_stop,
            control_open_permission_setup,
            capture_screenshot,
            get_active_app,
            read_clipboard,
            control_pointer_move,
            control_pointer_click,
            control_keyboard_type,
            control_keyboard_key_chord,
            haptic_feedback,
            toggle_spatial_hud,
            start_spatial_capture,
            stop_spatial_capture,
            project_embeddings,
            gesture_start,
            gesture_stop,
            gesture_pause,
            gesture_resume,
            gesture_status,
            gesture_list_cameras,
            gesture_set_camera_index,
            gesture_check_accessibility,
            gesture_set_cursor_global,
            gesture_get_cursor_global,
            install_update,
            updater_signing_status,
            open_main_window,
            hide_main_window,
            focus_podium,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Luna");
}

#[cfg(test)]
mod tests {
    //! Pure-logic unit tests for src-tauri/src/lib.rs.
    //!
    //! Only covers helpers that don't require a running tauri runtime: the
    //! `#[tauri::command]` async handlers that touch the AppHandle, system
    //! webcam, or external `osascript`/`pbpaste` processes are out of scope
    //! for default `cargo test` runs.
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use pretty_assertions::assert_eq;

    static DESKTOP_COMMAND_ENVELOPE_ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    struct EnvVarRestore {
        key: &'static str,
        previous: Option<String>,
    }

    impl EnvVarRestore {
        fn set(key: &'static str, value: Option<&str>) -> Self {
            let previous = std::env::var(key).ok();
            match value {
                Some(value) => std::env::set_var(key, value),
                None => std::env::remove_var(key),
            }
            Self { key, previous }
        }
    }

    impl Drop for EnvVarRestore {
        fn drop(&mut self) {
            match self.previous.as_deref() {
                Some(value) => std::env::set_var(self.key, value),
                None => std::env::remove_var(self.key),
            }
        }
    }

    #[test]
    fn per_capability_actuation_gate_defaults_disabled_and_isolates_capabilities() {
        let _env_lock = DESKTOP_COMMAND_ENVELOPE_ENV_LOCK.lock().expect("env lock");
        let _pointer = EnvVarRestore::set("LUNA_ACTUATION_POINTER_ENABLED", None);
        let _keyboard = EnvVarRestore::set("LUNA_ACTUATION_KEYBOARD_ENABLED", None);

        // Both capabilities are fail-closed by default, and the legacy gesture
        // CGEvent gate stays hard-disabled regardless of env.
        assert!(!desktop_control_allows_capability(
            computer_use::NativeControlCapability::Pointer
        ));
        assert!(!desktop_control_allows_capability(
            computer_use::NativeControlCapability::Keyboard
        ));
        assert!(!desktop_control_allows_actuation());

        // Enabling pointer must NOT make keyboard reachable — a mouse canary can
        // never arm the keyboard path (Phase 2.75 exit criterion #1).
        {
            let _on = EnvVarRestore::set("LUNA_ACTUATION_POINTER_ENABLED", Some("true"));
            assert!(desktop_control_allows_capability(
                computer_use::NativeControlCapability::Pointer
            ));
            assert!(!desktop_control_allows_capability(
                computer_use::NativeControlCapability::Keyboard
            ));
            // The gesture CGEvent gate is independent and stays off.
            assert!(!desktop_control_allows_actuation());
        }

        // Symmetric: enabling keyboard alone must not enable pointer.
        {
            let _on = EnvVarRestore::set("LUNA_ACTUATION_KEYBOARD_ENABLED", Some("1"));
            assert!(desktop_control_allows_capability(
                computer_use::NativeControlCapability::Keyboard
            ));
            assert!(!desktop_control_allows_capability(
                computer_use::NativeControlCapability::Pointer
            ));
        }
    }

    // ── desktop control safety ─────────────────────────────────────────────
    #[test]
    fn stopped_control_mode_blocks_control_entrypoints() {
        CONTROL_MODE.store(CONTROL_MODE_LOCKED, Ordering::SeqCst);
        assert!(ensure_desktop_control_not_stopped("gesture_start").is_ok());
        assert!(!desktop_control_allows_actuation());
        assert!(
            ensure_desktop_control_allows_pointer_actuation("gesture_set_cursor_global").is_err()
        );
        assert!(ensure_desktop_control_allows_keyboard_actuation("control_keyboard_type").is_err());

        CONTROL_MODE.store(CONTROL_MODE_STOPPED, Ordering::SeqCst);
        let err = ensure_desktop_control_not_stopped("gesture_start")
            .expect_err("stopped mode should reject control entrypoints");
        assert!(err.contains("desktop control stopped"), "got: {err}");
        assert!(err.contains("gesture_start"), "got: {err}");
        assert!(!desktop_control_allows_actuation());
        let pointer = ensure_desktop_control_allows_pointer_actuation("control_pointer_click")
            .expect_err("stopped mode should reject pointer actuation");
        assert!(
            pointer.contains("desktop control stopped"),
            "got: {pointer}"
        );

        CONTROL_MODE.store(CONTROL_MODE_LOCKED, Ordering::SeqCst);
    }

    fn native_boundary_permissions() -> computer_use::DesktopPermissionReadiness {
        use crate::computer_use::permissions::{
            DesktopPermissionReadiness, PermissionAppIdentity, PermissionProbe,
        };

        DesktopPermissionReadiness {
            app_identity: PermissionAppIdentity {
                bundle_id: Some("com.agentprovision.luna.test".to_string()),
                executable_path: None,
                app_bundle_path: None,
                code_signature_identifier: None,
                code_signature_team_identifier: None,
                code_signature_kind: None,
                permission_scope_note: "test identity".to_string(),
            },
            screen_recording: PermissionProbe::granted(&["test"], "granted"),
            accessibility: PermissionProbe::granted(&["test"], "granted"),
            automation_system_events: PermissionProbe::granted(&["test"], "granted"),
            input_monitoring: PermissionProbe::not_required(&["test"], "not required"),
            camera: PermissionProbe::unknown(&["test"], "deferred"),
            microphone: PermissionProbe::unknown(&["test"], "deferred"),
        }
    }

    fn native_boundary_request(action: &str, nonce: &str) -> NativeControlBoundaryProofRequest {
        let capability = match action {
            "pointer_move" | "pointer_click" => "pointer_control",
            "keyboard_type" | "keyboard_key_chord" => "keyboard_control",
            _ => "unknown",
        };
        let command_envelope = serde_json::json!({
            "schema": DESKTOP_COMMAND_ENVELOPE_SCHEMA,
            "signed": true,
            "signature_alg": DESKTOP_COMMAND_ENVELOPE_SIGNATURE_ALG,
            "key_id": DESKTOP_COMMAND_ENVELOPE_DEFAULT_KEY_ID,
            "signature": "valid-test-signature",
            "policy_version": computer_use::policy::CURRENT_NATIVE_CONTROL_POLICY_VERSION,
            "issuer": DESKTOP_COMMAND_ENVELOPE_ISSUER,
            "nonce": nonce,
            "expires_at_ms": 2_000,
            "desktop_command_id": "99999999-9999-9999-9999-999999999999",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "session_id": "33333333-3333-3333-3333-333333333333",
            "device_id": "88888888-8888-8888-8888-888888888888",
            "action": action,
            "capability": capability,
            "approval_id": "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
            "approval_risk_tier": DESKTOP_COMMAND_APPROVAL_RISK_NATIVE_CONTROL,
            "risk_tier": DESKTOP_COMMAND_APPROVAL_RISK_NATIVE_CONTROL,
            "policy_decision": DESKTOP_COMMAND_POLICY_DECISION_LEASE_CLAIMED,
            "target": {
                "bundle_id": "com.example.LunaCanaryTarget",
                "window_title_pattern": "Luna Canary",
                "window_title_hash": null,
                "display_id": null,
                "bounds": null,
                "observed_at": "2026-06-07T00:00:00Z",
            },
            "revoked": false,
            "replayed": false,
        });
        NativeControlBoundaryProofRequest {
            desktop_command_id: Some("99999999-9999-9999-9999-999999999999".to_string()),
            shell_id: Some("desktop-44444444-4444-4444-4444-444444444444".to_string()),
            session_id: Some("33333333-3333-3333-3333-333333333333".to_string()),
            device_id: Some("88888888-8888-8888-8888-888888888888".to_string()),
            action: action.to_string(),
            capability: Some(capability.to_string()),
            approval_id: Some("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa".to_string()),
            target: Some(NativeControlBoundaryTarget {
                bundle_id: Some("com.example.LunaCanaryTarget".to_string()),
                window_title_pattern: Some("Luna Canary".to_string()),
                window_title_hash: None,
                display_id: None,
                bounds: None,
                observed_at: Some("2026-06-07T00:00:00Z".to_string()),
            }),
            live_frontmost_bundle_id: Some("com.example.LunaCanaryTarget".to_string()),
            secure_input_active: None,
            command_envelope: Some(command_envelope),
            approval: Some(NativeControlBoundaryApproval {
                approval_id: Some("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa".to_string()),
                risk_tier: Some(DESKTOP_COMMAND_APPROVAL_RISK_NATIVE_CONTROL.to_string()),
                capability: Some(capability.to_string()),
                expires_at_ms: Some(2_000),
                revoked: Some(false),
            }),
        }
    }

    fn native_boundary_envelope_mut(
        request: &mut NativeControlBoundaryProofRequest,
    ) -> &mut serde_json::Map<String, serde_json::Value> {
        request
            .command_envelope
            .as_mut()
            .expect("envelope")
            .as_object_mut()
            .expect("envelope object")
    }

    fn native_boundary_decision(
        request: &NativeControlBoundaryProofRequest,
    ) -> NativeControlBoundaryDecision {
        let permissions = native_boundary_permissions();
        evaluate_native_control_boundary_request(
            request,
            computer_use::DesktopControlMode::ControlLocked,
            &permissions,
            1_000,
            |_| Ok(()),
            |_, _, _| true,
        )
    }

    fn sign_native_boundary_envelope_for_test(
        request: &mut NativeControlBoundaryProofRequest,
        signing_key: &SigningKey,
    ) -> String {
        let envelope = request.command_envelope.as_mut().expect("envelope");
        let signature = signing_key.sign(&canonical_envelope_payload_json(envelope).unwrap());
        native_boundary_envelope_mut(request).insert(
            "signature".to_string(),
            serde_json::json!(
                base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(signature.to_bytes())
            ),
        );
        base64::engine::general_purpose::URL_SAFE_NO_PAD
            .encode(signing_key.verifying_key().to_bytes())
    }

    #[test]
    fn canonical_envelope_payload_json_matches_api_sorted_ascii_contract() {
        let envelope = serde_json::json!({
            "z": "ultimo\u{7f}",
            "signature": "ignored",
            "nested": {
                "b": true,
                "a": null,
            },
            "emoji": "🤖",
            "accent": "último\n",
            "a": 1,
        });

        assert_eq!(
            String::from_utf8(canonical_envelope_payload_json(&envelope).unwrap()).unwrap(),
            r#"{"a":1,"accent":"\u00faltimo\n","emoji":"\ud83e\udd16","nested":{"a":null,"b":true},"z":"ultimo\u007f"}"#,
        );
    }

    #[test]
    fn native_boundary_ed25519_signature_is_independent_of_json_key_order() {
        let permissions = native_boundary_permissions();
        let signing_key = SigningKey::from_bytes(&[9u8; 32]);
        let mut request = native_boundary_request("pointer_click", "ed25519-key-order");
        let public_key = sign_native_boundary_envelope_for_test(&mut request, &signing_key);
        let signed_envelope = request.command_envelope.clone().expect("envelope");
        let mut entries: Vec<_> = signed_envelope
            .as_object()
            .expect("envelope object")
            .iter()
            .collect();
        entries.sort_by(|(left, _), (right, _)| right.cmp(left));

        let mut reordered = serde_json::Map::new();
        for (key, value) in entries {
            reordered.insert(key.clone(), value.clone());
        }
        request.command_envelope = Some(serde_json::Value::Object(reordered));

        let decision = evaluate_native_control_boundary_request(
            &request,
            computer_use::DesktopControlMode::ControlLocked,
            &permissions,
            1_000,
            |envelope| {
                verify_native_control_boundary_envelope_signature_with_public_key(
                    envelope,
                    &public_key,
                )
            },
            |_, _, _| true,
        );
        assert!(!decision.allowed);
        assert!(decision
            .reason
            .contains("desktop native control tier disabled"));
    }

    #[test]
    fn desktop_command_envelope_key_registry_selects_versioned_keys_and_fallback() {
        let default_key = "default-public-key";
        assert_eq!(
            public_key_from_desktop_command_envelope_registry(
                DESKTOP_COMMAND_ENVELOPE_DEFAULT_KEY_ID,
                None,
                Some(default_key),
            )
            .expect("default key fallback"),
            default_key
        );

        assert_eq!(
            public_key_from_desktop_command_envelope_registry(
                "agentprovision-desktop-command-ed25519-2026-06",
                Some(
                    "agentprovision-desktop-command-ed25519-v1=old-key;\
                     agentprovision-desktop-command-ed25519-2026-06=new-key",
                ),
                Some(default_key),
            )
            .expect("versioned key"),
            "new-key"
        );

        assert_eq!(
            public_key_from_desktop_command_envelope_registry(
                "unknown-key",
                None,
                Some(default_key)
            )
            .expect_err("unknown key fails closed"),
            "desktop command envelope key unknown"
        );
        assert_eq!(
            public_key_from_desktop_command_envelope_registry(
                "agentprovision-desktop-command-ed25519-2026-06",
                Some("malformed-entry"),
                Some(default_key),
            )
            .expect_err("malformed registry fails closed"),
            "desktop command envelope key registry invalid"
        );
    }

    #[test]
    fn native_boundary_verifies_versioned_key_id_through_registry_config() {
        let _env_lock = DESKTOP_COMMAND_ENVELOPE_ENV_LOCK
            .lock()
            .expect("desktop command envelope env lock");
        let _registry_restore =
            EnvVarRestore::set("LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEYS", None);
        let _default_restore =
            EnvVarRestore::set("LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY", None);

        let key_id = "agentprovision-desktop-command-ed25519-2026-06";
        let signing_key = SigningKey::from_bytes(&[11u8; 32]);
        let wrong_signing_key = SigningKey::from_bytes(&[12u8; 32]);
        let mut request = native_boundary_request("pointer_click", "ed25519-registry-key");
        native_boundary_envelope_mut(&mut request)
            .insert("key_id".to_string(), serde_json::json!(key_id));
        let public_key = sign_native_boundary_envelope_for_test(&mut request, &signing_key);
        let wrong_public_key = base64::engine::general_purpose::URL_SAFE_NO_PAD
            .encode(wrong_signing_key.verifying_key().to_bytes());
        std::env::set_var(
            "LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEYS",
            format!(
                "{default}={wrong};{key_id}={public}",
                default = DESKTOP_COMMAND_ENVELOPE_DEFAULT_KEY_ID,
                wrong = wrong_public_key,
                public = public_key,
            ),
        );

        let envelope = request.command_envelope.as_ref().expect("envelope");
        assert!(verify_native_control_boundary_envelope_signature(envelope).is_ok());

        let mut unknown = request.clone();
        native_boundary_envelope_mut(&mut unknown)
            .insert("key_id".to_string(), serde_json::json!("unknown-key"));
        assert_eq!(
            verify_native_control_boundary_envelope_signature(
                unknown.command_envelope.as_ref().expect("unknown envelope"),
            )
            .expect_err("unknown key fails closed"),
            "desktop command envelope key unknown",
        );

        std::env::set_var(
            "LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEYS",
            format!("{key_id}={wrong_public_key}"),
        );
        assert_eq!(
            verify_native_control_boundary_envelope_signature(envelope)
                .expect_err("wrong key fails closed"),
            "desktop command envelope signature invalid",
        );
    }

    #[test]
    fn native_boundary_rejects_missing_and_malformed_envelopes() {
        let mut missing = native_boundary_request("pointer_click", "missing-envelope");
        missing.command_envelope = None;
        let decision = native_boundary_decision(&missing);
        assert!(!decision.allowed);
        assert!(decision.reason.contains("desktop command envelope missing"));

        let mut malformed = native_boundary_request("pointer_click", "malformed-envelope");
        native_boundary_envelope_mut(&mut malformed).insert(
            "signature".to_string(),
            serde_json::Value::String(String::new()),
        );
        let decision = native_boundary_decision(&malformed);
        assert!(!decision.allowed);
        assert!(decision
            .reason
            .contains("desktop command envelope signature invalid"));
    }

    #[test]
    fn native_boundary_verifies_ed25519_signature_before_policy_denial() {
        let permissions = native_boundary_permissions();
        let signing_key = SigningKey::from_bytes(&[7u8; 32]);
        let mut request = native_boundary_request("pointer_click", "ed25519-valid");
        let public_key = sign_native_boundary_envelope_for_test(&mut request, &signing_key);

        let decision = evaluate_native_control_boundary_request(
            &request,
            computer_use::DesktopControlMode::ControlLocked,
            &permissions,
            1_000,
            |envelope| {
                verify_native_control_boundary_envelope_signature_with_public_key(
                    envelope,
                    &public_key,
                )
            },
            |_, _, _| true,
        );
        assert!(!decision.allowed);
        assert!(decision
            .reason
            .contains("desktop native control tier disabled"));

        let mut tampered = request.clone();
        native_boundary_envelope_mut(&mut tampered)
            .insert("action".to_string(), serde_json::json!("pointer_move"));
        let tampered_decision = evaluate_native_control_boundary_request(
            &tampered,
            computer_use::DesktopControlMode::ControlLocked,
            &permissions,
            1_000,
            |envelope| {
                verify_native_control_boundary_envelope_signature_with_public_key(
                    envelope,
                    &public_key,
                )
            },
            |_, _, _| true,
        );
        assert!(!tampered_decision.allowed);
        assert!(tampered_decision
            .reason
            .contains("desktop command envelope signature invalid"));
    }

    #[test]
    fn native_boundary_rejects_missing_live_frontmost_bundle() {
        let mut request = native_boundary_request("pointer_click", "missing-frontmost-bundle");
        request.live_frontmost_bundle_id = None;

        let decision = native_boundary_decision(&request);

        assert!(!decision.allowed);
        assert!(decision.reason.contains("active_app_drift"));
    }

    #[test]
    fn native_boundary_rejects_mismatched_live_frontmost_bundle() {
        let mut request = native_boundary_request("keyboard_type", "mismatched-frontmost-bundle");
        request.live_frontmost_bundle_id = Some("com.example.OtherApp".to_string());

        let decision = native_boundary_decision(&request);

        assert!(!decision.allowed);
        assert!(decision.reason.contains("active_app_drift"));
    }

    #[test]
    fn native_boundary_command_overrides_frontend_supplied_frontmost_bundle() {
        let mut request = native_boundary_request("pointer_click", "native-frontmost-override");
        request.live_frontmost_bundle_id = Some("com.example.SpoofedFromFrontend".to_string());

        let request = boundary_request_with_native_frontmost_bundle(
            request,
            Some("com.example.LunaCanaryTarget".to_string()),
        );
        let decision = native_boundary_decision(&request);

        assert!(!decision.allowed);
        assert!(decision
            .reason
            .contains("desktop native control tier disabled"));
    }

    #[test]
    fn native_boundary_rejects_expired_and_revoked_approvals() {
        let mut expired = native_boundary_request("keyboard_type", "expired-envelope");
        native_boundary_envelope_mut(&mut expired)
            .insert("expires_at_ms".to_string(), serde_json::json!(1_000));
        let decision = native_boundary_decision(&expired);
        assert!(!decision.allowed);
        assert!(decision.reason.contains("desktop command envelope expired"));

        let mut revoked = native_boundary_request("keyboard_type", "revoked-envelope");
        revoked.approval.as_mut().expect("approval").revoked = Some(true);
        let decision = native_boundary_decision(&revoked);
        assert!(!decision.allowed);
        assert!(decision
            .reason
            .contains("desktop command approval grant revoked"));
    }

    #[test]
    fn native_boundary_rejects_wrong_command_session_and_device_bindings() {
        let cases: Vec<(
            &str,
            Box<dyn FnOnce(&mut NativeControlBoundaryProofRequest)>,
        )> = vec![
            (
                "wrong-command",
                Box::new(|request| {
                    native_boundary_envelope_mut(request).insert(
                        "desktop_command_id".to_string(),
                        serde_json::json!("99999999-9999-9999-9999-999999999998"),
                    );
                }),
            ),
            (
                "wrong-shell",
                Box::new(|request| {
                    native_boundary_envelope_mut(request).insert(
                        "shell_id".to_string(),
                        serde_json::json!("desktop-55555555-5555-5555-5555-555555555555"),
                    );
                }),
            ),
            (
                "wrong-session",
                Box::new(|request| {
                    native_boundary_envelope_mut(request).insert(
                        "session_id".to_string(),
                        serde_json::json!("33333333-3333-3333-3333-333333333334"),
                    );
                }),
            ),
            (
                "wrong-device",
                Box::new(|request| {
                    native_boundary_envelope_mut(request).insert(
                        "device_id".to_string(),
                        serde_json::json!("88888888-8888-8888-8888-888888888887"),
                    );
                }),
            ),
        ];

        for (nonce, mutate) in cases {
            let mut request = native_boundary_request("pointer_click", nonce);
            mutate(&mut request);
            let decision = native_boundary_decision(&request);
            assert!(!decision.allowed);
            assert!(
                decision
                    .reason
                    .contains("desktop command envelope binding mismatch"),
                "case {nonce} got {}",
                decision.reason
            );
        }
    }

    #[test]
    fn test_native_boundary_denies_wrong_capability_before_adapter() {
        // Phase 2.75: a keyboard-capability envelope must never authorize a
        // pointer action (and vice-versa). The boundary denies on the capability
        // binding inside envelope validation — before the policy/adapter path —
        // so a mismatched capability can never reach a native call.
        let mut keyboard_for_pointer =
            native_boundary_request("pointer_click", "wrong-capability-pointer");
        native_boundary_envelope_mut(&mut keyboard_for_pointer)
            .insert("capability".to_string(), serde_json::json!("keyboard_control"));
        let decision = native_boundary_decision(&keyboard_for_pointer);
        assert!(!decision.allowed);
        assert!(
            decision
                .reason
                .contains("desktop command envelope binding mismatch"),
            "pointer-with-keyboard-capability got {}",
            decision.reason
        );

        let mut pointer_for_keyboard =
            native_boundary_request("keyboard_type", "wrong-capability-keyboard");
        native_boundary_envelope_mut(&mut pointer_for_keyboard)
            .insert("capability".to_string(), serde_json::json!("pointer_control"));
        let decision = native_boundary_decision(&pointer_for_keyboard);
        assert!(!decision.allowed);
        assert!(
            decision
                .reason
                .contains("desktop command envelope binding mismatch"),
            "keyboard-with-pointer-capability got {}",
            decision.reason
        );
    }

    #[test]
    fn test_native_boundary_denies_frontmost_bundle_drift_before_adapter() {
        // Phase 2.75: if the live frontmost app is not the envelope's bound
        // target at proof time, deny as active_app_drift before any native call.
        let mut request =
            native_boundary_request("pointer_click", "frontmost-drift-before-adapter");
        request.live_frontmost_bundle_id = Some("com.example.NotTheCanaryTarget".to_string());
        let decision = native_boundary_decision(&request);
        assert!(!decision.allowed);
        assert!(
            decision.reason.contains("active_app_drift"),
            "got {}",
            decision.reason
        );
    }

    #[test]
    fn test_native_boundary_denies_stale_native_approval_before_adapter() {
        // Phase 2.75: a stale (expired) native approval/envelope denies before
        // any native call. now_ms is 1_000 in native_boundary_decision; an
        // envelope that already expired at 1_000 is rejected during validation.
        let mut request =
            native_boundary_request("keyboard_type", "stale-approval-before-adapter");
        native_boundary_envelope_mut(&mut request)
            .insert("expires_at_ms".to_string(), serde_json::json!(1_000));
        let decision = native_boundary_decision(&request);
        assert!(!decision.allowed);
        assert!(
            decision.reason.contains("desktop command envelope expired"),
            "got {}",
            decision.reason
        );
    }

    #[test]
    fn test_native_boundary_denies_secure_input_keyboard_before_adapter() {
        // Phase 2.75: with macOS Secure Input active, a keyboard native action is
        // denied before any adapter call — no synthetic keystrokes can land in a
        // password/secure field. Pointer is unaffected (secure input only gates
        // keyboard), so it falls through to the (disabled) tier check instead.
        let mut keyboard = native_boundary_request("keyboard_type", "secure-input-keyboard");
        keyboard.secure_input_active = Some(true);
        let decision = native_boundary_decision(&keyboard);
        assert!(!decision.allowed);
        assert!(
            decision.reason.contains("secure_input_active"),
            "keyboard got {}",
            decision.reason
        );

        let mut pointer = native_boundary_request("pointer_click", "secure-input-pointer");
        pointer.secure_input_active = Some(true);
        let decision = native_boundary_decision(&pointer);
        assert!(
            !decision.reason.contains("secure_input_active"),
            "pointer should not be secure-input-denied, got {}",
            decision.reason
        );
    }

    #[test]
    fn native_boundary_rejects_replayed_envelope_nonces() {
        let permissions = native_boundary_permissions();
        let mut seen = std::collections::HashSet::new();
        let request = native_boundary_request("pointer_click", "replayed-envelope");

        let first = evaluate_native_control_boundary_request(
            &request,
            computer_use::DesktopControlMode::ControlLocked,
            &permissions,
            1_000,
            |_| Ok(()),
            |nonce, _, _| seen.insert(nonce.to_string()),
        );
        assert!(!first.allowed);
        assert!(first
            .reason
            .contains("desktop native control tier disabled"));

        let replayed = evaluate_native_control_boundary_request(
            &request,
            computer_use::DesktopControlMode::ControlLocked,
            &permissions,
            1_000,
            |_| Ok(()),
            |nonce, _, _| seen.insert(nonce.to_string()),
        );
        assert!(!replayed.allowed);
        assert!(replayed
            .reason
            .contains("desktop command envelope replayed"));
    }

    #[test]
    fn native_boundary_still_denies_valid_native_claims_before_actuation() {
        let request = native_boundary_request("pointer_click", "valid-but-disabled");
        let decision = native_boundary_decision(&request);
        assert!(!decision.allowed);
        assert!(decision
            .reason
            .contains("desktop native control tier disabled"));
        assert_eq!(decision.capability, "pointer_control");
    }

    #[test]
    fn locked_control_mode_blocks_observation_entrypoints() {
        CONTROL_MODE.store(CONTROL_MODE_LOCKED, Ordering::SeqCst);
        let locked = ensure_desktop_control_allows_observation("capture_screenshot")
            .expect_err("locked mode should reject observation");
        assert!(locked.contains("desktop observe locked"), "got: {locked}");
        assert!(locked.contains("capture_screenshot"), "got: {locked}");

        CONTROL_MODE.store(CONTROL_MODE_OBSERVE, Ordering::SeqCst);
        assert!(ensure_desktop_control_allows_observation("capture_screenshot").is_ok());

        CONTROL_MODE.store(CONTROL_MODE_STOPPED, Ordering::SeqCst);
        let stopped = ensure_desktop_control_allows_observation("capture_screenshot")
            .expect_err("stopped mode should reject observation");
        assert!(
            stopped.contains("desktop control stopped"),
            "got: {stopped}"
        );

        CONTROL_MODE.store(CONTROL_MODE_LOCKED, Ordering::SeqCst);
    }

    // ── durable-Stop transition guards (Stop Semantics #5) ──────────────
    #[test]
    fn lock_request_preserves_stopped() {
        // A Lock must never silently leave a latched Stop — only an explicit
        // Resume (control_clear_stop) may. This pins the AuthContext
        // logout/stale-token control_lock_all path against un-stopping.
        assert_eq!(
            next_mode_for_lock(CONTROL_MODE_STOPPED),
            CONTROL_MODE_STOPPED
        );
        assert_eq!(
            next_mode_for_lock(CONTROL_MODE_OBSERVE),
            CONTROL_MODE_LOCKED
        );
        assert_eq!(next_mode_for_lock(CONTROL_MODE_LOCKED), CONTROL_MODE_LOCKED);
    }

    #[test]
    fn observe_request_denied_only_when_stopped() {
        assert!(!observe_allowed_in_mode(CONTROL_MODE_STOPPED));
        assert!(observe_allowed_in_mode(CONTROL_MODE_LOCKED));
        assert!(observe_allowed_in_mode(CONTROL_MODE_OBSERVE));
    }

    // ── platform / arch ─────────────────────────────────────────────────
    #[test]
    fn get_platform_returns_non_empty() {
        let p = get_platform();
        assert!(!p.is_empty(), "platform string should not be empty");
        // OS family must be one of the standard Rust constants — guards
        // against accidental hard-coding.
        assert!(
            matches!(
                p.as_str(),
                "macos"
                    | "linux"
                    | "windows"
                    | "ios"
                    | "android"
                    | "freebsd"
                    | "netbsd"
                    | "openbsd"
                    | "dragonfly"
                    | "solaris"
            ),
            "unexpected platform: {p}",
        );
    }

    #[test]
    fn get_arch_returns_non_empty() {
        let a = get_arch();
        assert!(!a.is_empty(), "arch string should not be empty");
    }

    // ── truncate_str ────────────────────────────────────────────────────
    #[test]
    fn truncate_str_passes_short_through() {
        assert_eq!(truncate_str("hello", 10), "hello");
    }

    #[test]
    fn truncate_str_clips_long_to_max() {
        assert_eq!(truncate_str("abcdefghij", 4), "abcd");
    }

    #[test]
    fn truncate_str_handles_exact_length() {
        assert_eq!(truncate_str("abc", 3), "abc");
    }

    // ── base64_encode ───────────────────────────────────────────────────
    #[test]
    fn base64_encode_empty_input() {
        assert_eq!(base64_encode(&[]), "");
    }

    #[test]
    fn base64_encode_known_vectors() {
        // RFC 4648 test vectors.
        assert_eq!(base64_encode(b"f"), "Zg==");
        assert_eq!(base64_encode(b"fo"), "Zm8=");
        assert_eq!(base64_encode(b"foo"), "Zm9v");
        assert_eq!(base64_encode(b"foob"), "Zm9vYg==");
        assert_eq!(base64_encode(b"fooba"), "Zm9vYmE=");
        assert_eq!(base64_encode(b"foobar"), "Zm9vYmFy");
    }

    #[test]
    fn base64_encode_binary_bytes() {
        // 0x00 0xFF 0x10
        //  = 00000000 11111111 00010000
        //  = 000000 001111 111100 010000
        //  = 0 15 60 16
        //  = A  P  8  Q
        let bytes: [u8; 3] = [0x00, 0xFF, 0x10];
        let encoded = base64_encode(&bytes);
        assert_eq!(encoded, "AP8Q");
    }

    // ── extract_project_from_args ───────────────────────────────────────
    #[test]
    fn extract_project_from_github_path() {
        let got = extract_project_from_args(
            "claude /Users/me/Documents/GitHub/agentprovision-agents/apps",
        );
        assert_eq!(got, "agentprovision-agents");
    }

    #[test]
    fn extract_project_from_projects_path() {
        let got = extract_project_from_args("npm run dev /Users/me/Projects/luna-os");
        assert_eq!(got, "luna-os");
    }

    #[test]
    fn extract_project_returns_empty_for_no_match() {
        assert_eq!(extract_project_from_args("npm install"), "");
        assert_eq!(extract_project_from_args(""), "");
    }

    // ── resolve_app_context ─────────────────────────────────────────────
    #[test]
    fn resolve_terminal_with_known_tool() {
        let got = resolve_app_context("Terminal", "claude --some-flag");
        assert_eq!(got, "Claude Code (Terminal)");
    }

    #[test]
    fn resolve_terminal_with_docker() {
        let got = resolve_app_context("iTerm2", "docker ps -a");
        assert_eq!(got, "Docker CLI (iTerm2)");
    }

    #[test]
    fn resolve_terminal_with_unknown_tool_returns_app_name() {
        let got = resolve_app_context("Terminal", "ls -la");
        assert_eq!(got, "Terminal");
    }

    #[test]
    fn resolve_electron_extracts_project_with_em_dash() {
        // U+2014 em-dash is the canonical separator in VS Code titles.
        let got = resolve_app_context("Code", "agentprovision-agents \u{2014} CLAUDE.md");
        assert_eq!(got, "agentprovision-agents");
    }

    #[test]
    fn resolve_electron_extracts_project_with_hyphen() {
        let got = resolve_app_context("Cursor", "luna-os - lib.rs");
        assert_eq!(got, "luna-os");
    }

    #[test]
    fn resolve_chrome_includes_window_short_title() {
        let got = resolve_app_context("Google Chrome", "Test page - Chromium docs");
        assert!(got.starts_with("Google Chrome"));
        assert!(got.contains("Test page"));
    }

    #[test]
    fn resolve_unknown_app_returns_app_name() {
        let got = resolve_app_context("Slack", "general | acme");
        assert_eq!(got, "Slack");
    }

    #[test]
    fn metadata_app_switch_event_omits_raw_window_and_subprocess_context() {
        let event = build_metadata_app_switch_event(
            "Terminal",
            "Luna",
            "secret repo window title",
            12,
            12345,
        );

        assert_eq!(event["type"], "app_switch");
        assert_eq!(event["from_app"], "Terminal");
        assert_eq!(event["to_app"], "Luna");
        assert_eq!(event["detail_level"], "metadata_only");
        assert_eq!(event["schema"], "agentprovision.macos_app_monitor_event.v1");
        assert!(uuid::Uuid::parse_str(event["event_id"].as_str().unwrap()).is_ok());
        assert_eq!(event["observed_at_ms"], 12345000);
        assert!(event["active_context_id"]
            .as_str()
            .unwrap()
            .starts_with("Luna:"));
        assert_eq!(event["window_title_present"], true);
        assert_eq!(event["window_title_chars"], 24);
        assert!(event.get("window_title").is_none());
        assert!(event.get("subprocess").is_none());
        assert!(!event["active_context_id"]
            .as_str()
            .unwrap()
            .contains("secret repo"));
    }

    #[test]
    fn active_app_metadata_omits_raw_window_title() {
        let event = build_active_app_metadata("Code", "secret repo window title");

        assert_eq!(event["app"], "Code");
        assert_eq!(event["title_present"], true);
        assert_eq!(event["title_chars"], 24);
        assert!(event.get("title").is_none());
    }

    // ── ProjectionResult / project_embeddings logic ─────────────────────
    //
    // `project_embeddings` is `async fn` but does no IO — we drive it with
    // `futures::executor::block_on` would require an extra dep, so use the
    // tokio-free trick of polling once via `pollster`-style hack: call the
    // future on a stub executor. The simpler path is to extract the logic
    // by hand, but that requires touching prod code — instead we reuse the
    // tauri-async runtime which is already pulled in by tauri itself.
    //
    // Tauri exposes `tauri::async_runtime::block_on` for this exact purpose.
    #[test]
    fn project_embeddings_empty_input_returns_empty_vec() {
        let result = tauri::async_runtime::block_on(project_embeddings(vec![], vec![]))
            .expect("empty input should not error");
        assert!(result.is_empty());
    }

    #[test]
    fn project_embeddings_length_mismatch_errors() {
        let result = tauri::async_runtime::block_on(project_embeddings(
            vec![vec![0.1, 0.2, 0.3]],
            vec!["a".into(), "b".into()],
        ));
        match result {
            Err(msg) => assert!(msg.contains("length mismatch"), "got: {msg}"),
            Ok(_) => panic!("expected length-mismatch error"),
        }
    }

    #[test]
    fn project_embeddings_scales_first_three_dims() {
        let result = tauri::async_runtime::block_on(project_embeddings(
            vec![vec![0.1, 0.2, 0.3, 0.4]],
            vec!["entity-1".into()],
        ))
        .expect("ok");
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].id, "entity-1");
        // Scale factor is *100 in the implementation.
        assert!((result[0].x - 10.0).abs() < 1e-4);
        assert!((result[0].y - 20.0).abs() < 1e-4);
        assert!((result[0].z - 30.0).abs() < 1e-4);
    }

    #[test]
    fn project_embeddings_handles_short_vectors() {
        // Vectors with fewer than 3 dims should pad with 0 not panic.
        let result =
            tauri::async_runtime::block_on(project_embeddings(vec![vec![0.5]], vec!["x".into()]))
                .expect("ok");
        assert_eq!(result[0].x, 50.0);
        assert_eq!(result[0].y, 0.0);
        assert_eq!(result[0].z, 0.0);
    }
}
