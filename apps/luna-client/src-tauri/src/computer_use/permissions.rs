use serde::Serialize;

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct PermissionAppIdentity {
    pub bundle_id: Option<String>,
    pub executable_path: Option<String>,
    pub app_bundle_path: Option<String>,
    pub code_signature_identifier: Option<String>,
    pub code_signature_team_identifier: Option<String>,
    pub code_signature_kind: Option<String>,
    pub permission_scope_note: String,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct PermissionProbe {
    pub status: String,
    pub required_for: Vec<String>,
    pub reason: String,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct DesktopPermissionReadiness {
    pub app_identity: PermissionAppIdentity,
    pub screen_recording: PermissionProbe,
    pub accessibility: PermissionProbe,
    pub automation_system_events: PermissionProbe,
    pub input_monitoring: PermissionProbe,
    pub camera: PermissionProbe,
    pub microphone: PermissionProbe,
}

impl PermissionProbe {
    pub(crate) fn granted(required_for: &[&str], reason: &str) -> Self {
        Self::new("granted", required_for, reason)
    }

    pub(crate) fn denied(required_for: &[&str], reason: &str) -> Self {
        Self::new("denied", required_for, reason)
    }

    pub(crate) fn unknown(required_for: &[&str], reason: &str) -> Self {
        Self::new("unknown", required_for, reason)
    }

    pub(crate) fn not_required(required_for: &[&str], reason: &str) -> Self {
        Self::new("not_required", required_for, reason)
    }

    fn new(status: &str, required_for: &[&str], reason: &str) -> Self {
        Self {
            status: status.to_string(),
            required_for: required_for.iter().map(|value| value.to_string()).collect(),
            reason: reason.to_string(),
        }
    }
}

pub fn current_permission_readiness() -> DesktopPermissionReadiness {
    DesktopPermissionReadiness {
        app_identity: current_app_identity(),
        screen_recording: screen_recording_readiness(),
        accessibility: accessibility_readiness(),
        automation_system_events: automation_system_events_readiness(),
        input_monitoring: input_monitoring_readiness(),
        camera: camera_readiness(),
        microphone: microphone_readiness(),
    }
}

fn current_app_identity() -> PermissionAppIdentity {
    current_app_identity_impl()
}

#[cfg(target_os = "macos")]
fn current_app_identity_impl() -> PermissionAppIdentity {
    use once_cell::sync::OnceCell;

    static IDENTITY: OnceCell<PermissionAppIdentity> = OnceCell::new();
    IDENTITY.get_or_init(read_current_app_identity).clone()
}

#[cfg(not(target_os = "macos"))]
fn current_app_identity_impl() -> PermissionAppIdentity {
    PermissionAppIdentity {
        bundle_id: None,
        executable_path: std::env::current_exe()
            .ok()
            .map(|path| path.to_string_lossy().to_string()),
        app_bundle_path: None,
        code_signature_identifier: None,
        code_signature_team_identifier: None,
        code_signature_kind: None,
        permission_scope_note: "macOS TCC identity diagnostics are macOS-only.".to_string(),
    }
}

#[cfg(target_os = "macos")]
fn read_current_app_identity() -> PermissionAppIdentity {
    let executable = std::env::current_exe().ok();
    let app_bundle = executable
        .as_deref()
        .and_then(app_bundle_path_for_executable);
    let bundle_id = app_bundle.as_deref().and_then(read_bundle_identifier);
    let signature = app_bundle
        .as_deref()
        .or(executable.as_deref())
        .and_then(read_code_signature_summary);

    let running_outside_applications = app_bundle
        .as_deref()
        .and_then(|path| path.to_str())
        .is_some_and(|path| !path.starts_with("/Applications/"));
    let permission_scope_note = if running_outside_applications {
        "macOS grants TCC permissions to the running app identity. This Luna is not running from /Applications, so grants for the installed release may not apply to this development build."
    } else {
        "macOS grants TCC permissions to the running app identity. If an unsigned or ad-hoc build changes code identity, Privacy & Security may need a fresh Luna entry."
    };

    PermissionAppIdentity {
        bundle_id,
        executable_path: executable.map(|path| path.to_string_lossy().to_string()),
        app_bundle_path: app_bundle.map(|path| path.to_string_lossy().to_string()),
        code_signature_identifier: signature
            .as_ref()
            .and_then(|summary| summary.identifier.clone()),
        code_signature_team_identifier: signature
            .as_ref()
            .and_then(|summary| summary.team_identifier.clone()),
        code_signature_kind: signature.and_then(|summary| summary.kind),
        permission_scope_note: permission_scope_note.to_string(),
    }
}

#[cfg(target_os = "macos")]
fn app_bundle_path_for_executable(executable: &std::path::Path) -> Option<std::path::PathBuf> {
    let macos_dir = executable.parent()?;
    if macos_dir.file_name()? != "MacOS" {
        return None;
    }
    let contents_dir = macos_dir.parent()?;
    if contents_dir.file_name()? != "Contents" {
        return None;
    }
    let app_dir = contents_dir.parent()?;
    if app_dir.extension().is_some_and(|ext| ext == "app") {
        Some(app_dir.to_path_buf())
    } else {
        None
    }
}

#[cfg(target_os = "macos")]
fn read_bundle_identifier(app_bundle: &std::path::Path) -> Option<String> {
    let output = std::process::Command::new("plutil")
        .args(["-extract", "CFBundleIdentifier", "raw", "-o", "-"])
        .arg(app_bundle.join("Contents/Info.plist"))
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if value.is_empty() {
        None
    } else {
        Some(value)
    }
}

#[cfg(target_os = "macos")]
#[derive(Clone, Debug)]
struct CodeSignatureSummary {
    identifier: Option<String>,
    team_identifier: Option<String>,
    kind: Option<String>,
}

#[cfg(target_os = "macos")]
fn read_code_signature_summary(path: &std::path::Path) -> Option<CodeSignatureSummary> {
    let output = std::process::Command::new("codesign")
        .args(["-dv"])
        .arg(path)
        .output()
        .ok()?;
    let text = String::from_utf8_lossy(&output.stderr);
    Some(CodeSignatureSummary {
        identifier: parse_codesign_value(&text, "Identifier"),
        team_identifier: parse_codesign_value(&text, "TeamIdentifier"),
        kind: parse_signature_kind(&text),
    })
}

#[cfg(target_os = "macos")]
fn parse_codesign_value(text: &str, key: &str) -> Option<String> {
    let prefix = format!("{key}=");
    text.lines()
        .find_map(|line| line.strip_prefix(&prefix))
        .map(str::trim)
        .filter(|value| !value.is_empty() && *value != "not set")
        .map(ToString::to_string)
}

#[cfg(target_os = "macos")]
fn parse_signature_kind(text: &str) -> Option<String> {
    let signature = parse_codesign_value(text, "Signature")?;
    if text.contains("(adhoc") || signature.eq_ignore_ascii_case("adhoc") {
        Some("ad-hoc".to_string())
    } else {
        Some(signature)
    }
}

pub fn open_permission_setup(permission: &str) -> Result<(), String> {
    let Some(url) = privacy_pane_url(permission) else {
        return Err(format!(
            "unsupported desktop permission setup: {permission}"
        ));
    };

    #[cfg(target_os = "macos")]
    {
        maybe_request_permission_prompt(permission);
        let status = std::process::Command::new("open")
            .arg(url)
            .status()
            .map_err(|e| format!("open macOS permission pane for {permission}: {e}"))?;
        if status.success() {
            Ok(())
        } else {
            Err(format!(
                "open macOS permission pane for {permission} exited with {status}",
            ))
        }
    }

    #[cfg(not(target_os = "macos"))]
    {
        let _ = url;
        Err("desktop permission setup is macOS-only in this phase".to_string())
    }
}

fn privacy_pane_url(permission: &str) -> Option<&'static str> {
    match permission {
        "screen_recording" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")
        }
        "accessibility" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        }
        "automation_system_events" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_Automation")
        }
        "input_monitoring" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")
        }
        "camera" => Some("x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"),
        "microphone" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")
        }
        _ => None,
    }
}

#[cfg(target_os = "macos")]
fn maybe_request_permission_prompt(permission: &str) {
    match permission {
        "screen_recording" => request_screen_capture_prompt(),
        "accessibility" => request_accessibility_prompt(),
        "automation_system_events" => request_system_events_automation_prompt(),
        _ => {}
    }
}

#[cfg(target_os = "macos")]
fn request_screen_capture_prompt() {
    extern "C" {
        fn CGRequestScreenCaptureAccess() -> bool;
    }
    let _ = unsafe { CGRequestScreenCaptureAccess() };
}

#[cfg(target_os = "macos")]
fn request_accessibility_prompt() {
    use std::ffi::c_void;

    type CFDictionaryRef = *const c_void;

    #[link(name = "ApplicationServices", kind = "framework")]
    extern "C" {
        static kAXTrustedCheckOptionPrompt: *const c_void;
        fn AXIsProcessTrustedWithOptions(options: CFDictionaryRef) -> bool;
    }

    #[link(name = "CoreFoundation", kind = "framework")]
    extern "C" {
        static kCFBooleanTrue: *const c_void;
        fn CFDictionaryCreate(
            allocator: *const c_void,
            keys: *const *const c_void,
            values: *const *const c_void,
            num_values: isize,
            key_callbacks: *const c_void,
            value_callbacks: *const c_void,
        ) -> CFDictionaryRef;
        fn CFRelease(value: *const c_void);
    }

    let keys = [unsafe { kAXTrustedCheckOptionPrompt }];
    let values = [unsafe { kCFBooleanTrue }];
    let options = unsafe {
        CFDictionaryCreate(
            std::ptr::null(),
            keys.as_ptr(),
            values.as_ptr(),
            1,
            std::ptr::null(),
            std::ptr::null(),
        )
    };
    if options.is_null() {
        return;
    }

    let _ = unsafe { AXIsProcessTrustedWithOptions(options) };
    unsafe { CFRelease(options) };
}

#[cfg(target_os = "macos")]
fn screen_recording_readiness() -> PermissionProbe {
    extern "C" {
        fn CGPreflightScreenCaptureAccess() -> bool;
    }
    let granted = unsafe { CGPreflightScreenCaptureAccess() };
    if granted {
        PermissionProbe::granted(
            &["screenshot", "screen observation"],
            "macOS Screen Recording preflight is granted.",
        )
    } else {
        PermissionProbe::denied(
            &["screenshot", "screen observation"],
            "macOS Screen Recording preflight is denied or not yet granted.",
        )
    }
}

#[cfg(not(target_os = "macos"))]
fn screen_recording_readiness() -> PermissionProbe {
    PermissionProbe::not_required(&["screenshot"], "Screen Recording is macOS-specific.")
}

/// True when this process holds macOS Accessibility (AX) trust — the TCC
/// permission that gates synthetic CGEvent pointer/keyboard actuation. Uses the
/// real `AXIsProcessTrusted()` API, NOT an `osascript`/System Events probe (which
/// reflects Automation, a different permission). This is the correct gate for
/// the Phase 3 pointer canary.
#[cfg(target_os = "macos")]
pub fn accessibility_trusted() -> bool {
    #[link(name = "ApplicationServices", kind = "framework")]
    extern "C" {
        fn AXIsProcessTrusted() -> bool;
    }
    unsafe { AXIsProcessTrusted() }
}

#[cfg(not(target_os = "macos"))]
pub fn accessibility_trusted() -> bool {
    false
}

#[cfg(target_os = "macos")]
fn accessibility_readiness() -> PermissionProbe {
    if accessibility_trusted() {
        PermissionProbe::granted(
            &["active app", "pointer control", "keyboard control"],
            "macOS Accessibility trust preflight is granted.",
        )
    } else {
        PermissionProbe::denied(
            &["active app", "pointer control", "keyboard control"],
            "macOS Accessibility trust preflight is denied or not yet granted.",
        )
    }
}

#[cfg(not(target_os = "macos"))]
fn accessibility_readiness() -> PermissionProbe {
    PermissionProbe::not_required(
        &["pointer control"],
        "Accessibility probing is macOS-specific.",
    )
}

#[cfg(target_os = "macos")]
fn automation_system_events_readiness() -> PermissionProbe {
    match system_events_automation_status() {
        MacAutomationStatus::Granted => PermissionProbe::granted(
            &["active app", "window title"],
            "macOS Automation permission for System Events is granted.",
        ),
        MacAutomationStatus::NeedsConsent => PermissionProbe::denied(
            &["active app", "window title"],
            "macOS Automation permission for System Events is not granted to this Luna identity.",
        ),
        MacAutomationStatus::Denied => PermissionProbe::denied(
            &["active app", "window title"],
            "macOS Automation permission for System Events is denied.",
        ),
        MacAutomationStatus::Unknown(reason) => {
            PermissionProbe::unknown(&["active app", "window title"], &reason)
        }
    }
}

#[cfg(not(target_os = "macos"))]
fn automation_system_events_readiness() -> PermissionProbe {
    PermissionProbe::not_required(&["active app"], "System Events is macOS-specific.")
}

fn input_monitoring_readiness() -> PermissionProbe {
    PermissionProbe::not_required(
        &["keyboard observation"],
        "Luna does not monitor keyboard input in this phase.",
    )
}

#[cfg(target_os = "macos")]
fn camera_readiness() -> PermissionProbe {
    media_permission_readiness(
        MacMediaKind::Camera,
        &["gesture calibration", "gesture settings"],
    )
}

#[cfg(not(target_os = "macos"))]
fn camera_readiness() -> PermissionProbe {
    PermissionProbe::not_required(
        &["gesture calibration"],
        "Camera probing is macOS-specific.",
    )
}

#[cfg(target_os = "macos")]
fn microphone_readiness() -> PermissionProbe {
    media_permission_readiness(MacMediaKind::Microphone, &["push-to-talk"])
}

#[cfg(not(target_os = "macos"))]
fn microphone_readiness() -> PermissionProbe {
    PermissionProbe::not_required(&["push-to-talk"], "Microphone probing is macOS-specific.")
}

#[cfg(target_os = "macos")]
enum MacMediaKind {
    Camera,
    Microphone,
}

#[cfg(target_os = "macos")]
fn media_permission_readiness(kind: MacMediaKind, required_for: &[&str]) -> PermissionProbe {
    let status = media_authorization_status(&kind);
    let name = match kind {
        MacMediaKind::Camera => "Camera",
        MacMediaKind::Microphone => "Microphone",
    };
    match status {
        MacMediaAuthorizationStatus::Authorized => PermissionProbe::granted(
            required_for,
            &format!("macOS {name} authorization is granted."),
        ),
        MacMediaAuthorizationStatus::Denied => PermissionProbe::denied(
            required_for,
            &format!("macOS {name} authorization is denied."),
        ),
        MacMediaAuthorizationStatus::Restricted => PermissionProbe::denied(
            required_for,
            &format!("macOS {name} authorization is restricted by system policy."),
        ),
        MacMediaAuthorizationStatus::NotDetermined => PermissionProbe::unknown(
            required_for,
            &format!("macOS {name} authorization has not been requested for this Luna identity."),
        ),
    }
}

#[cfg(target_os = "macos")]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum MacMediaAuthorizationStatus {
    NotDetermined,
    Restricted,
    Denied,
    Authorized,
}

#[cfg(target_os = "macos")]
fn media_authorization_status(kind: &MacMediaKind) -> MacMediaAuthorizationStatus {
    use std::ffi::{c_char, c_void};

    #[link(name = "AVFoundation", kind = "framework")]
    extern "C" {
        static AVMediaTypeVideo: *mut c_void;
        static AVMediaTypeAudio: *mut c_void;
    }

    #[link(name = "objc")]
    extern "C" {
        fn objc_getClass(name: *const c_char) -> *mut c_void;
        fn sel_registerName(name: *const c_char) -> *mut c_void;
        fn objc_msgSend();
    }

    let media_type = match kind {
        MacMediaKind::Camera => unsafe { AVMediaTypeVideo },
        MacMediaKind::Microphone => unsafe { AVMediaTypeAudio },
    };

    type AuthorizationStatusForMediaType =
        unsafe extern "C" fn(*mut c_void, *mut c_void, *mut c_void) -> isize;

    let class_name = b"AVCaptureDevice\0";
    let selector_name = b"authorizationStatusForMediaType:\0";
    let class = unsafe { objc_getClass(class_name.as_ptr().cast()) };
    let selector = unsafe { sel_registerName(selector_name.as_ptr().cast()) };
    if class.is_null() || selector.is_null() || media_type.is_null() {
        return MacMediaAuthorizationStatus::NotDetermined;
    }

    let send: AuthorizationStatusForMediaType =
        unsafe { std::mem::transmute(objc_msgSend as *const ()) };
    let status = unsafe { send(class, selector, media_type) };
    match status {
        1 => MacMediaAuthorizationStatus::Restricted,
        2 => MacMediaAuthorizationStatus::Denied,
        3 => MacMediaAuthorizationStatus::Authorized,
        _ => MacMediaAuthorizationStatus::NotDetermined,
    }
}

#[cfg(target_os = "macos")]
enum MacAutomationStatus {
    Granted,
    NeedsConsent,
    Denied,
    Unknown(String),
}

#[cfg(target_os = "macos")]
fn system_events_automation_status() -> MacAutomationStatus {
    determine_system_events_automation_status(false)
}

#[cfg(target_os = "macos")]
fn request_system_events_automation_prompt() {
    let _ = determine_system_events_automation_status(true);
}

#[cfg(target_os = "macos")]
fn determine_system_events_automation_status(ask_user_if_needed: bool) -> MacAutomationStatus {
    use std::ffi::c_void;

    type OSStatus = i32;
    type OSType = u32;

    #[repr(C)]
    struct AEDesc {
        descriptor_type: OSType,
        data_handle: *mut c_void,
    }

    const NO_ERR: OSStatus = 0;
    const PROC_NOT_FOUND: OSStatus = -600;
    const ERR_AE_EVENT_NOT_PERMITTED: OSStatus = -1743;
    const ERR_AE_EVENT_WOULD_REQUIRE_USER_CONSENT: OSStatus = -1744;
    const TYPE_APPLICATION_BUNDLE_ID: OSType = fourcc("bund");
    const TYPE_WILDCARD: OSType = fourcc("****");

    #[link(name = "CoreServices", kind = "framework")]
    extern "C" {
        fn AECreateDesc(
            type_code: OSType,
            data_ptr: *const c_void,
            data_size: isize,
            result: *mut AEDesc,
        ) -> OSStatus;
        fn AEDisposeDesc(desc: *mut AEDesc) -> OSStatus;
        fn AEDeterminePermissionToAutomateTarget(
            target: *const AEDesc,
            event_class: OSType,
            event_id: OSType,
            ask_user_if_needed: bool,
        ) -> OSStatus;
    }

    let target_bundle_id = b"com.apple.systemevents";
    let mut target = AEDesc {
        descriptor_type: 0,
        data_handle: std::ptr::null_mut(),
    };
    let create_status = unsafe {
        AECreateDesc(
            TYPE_APPLICATION_BUNDLE_ID,
            target_bundle_id.as_ptr().cast(),
            target_bundle_id.len() as isize,
            &mut target,
        )
    };
    if create_status != NO_ERR {
        return MacAutomationStatus::Unknown(format!(
            "Could not build System Events automation target descriptor (OSStatus {create_status}).",
        ));
    }

    let status = unsafe {
        AEDeterminePermissionToAutomateTarget(
            &target,
            TYPE_WILDCARD,
            TYPE_WILDCARD,
            ask_user_if_needed,
        )
    };
    let _ = unsafe { AEDisposeDesc(&mut target) };

    match status {
        NO_ERR => MacAutomationStatus::Granted,
        ERR_AE_EVENT_NOT_PERMITTED => MacAutomationStatus::Denied,
        ERR_AE_EVENT_WOULD_REQUIRE_USER_CONSENT => MacAutomationStatus::NeedsConsent,
        PROC_NOT_FOUND => MacAutomationStatus::Unknown(
            "System Events is not running, so macOS cannot passively determine Automation permission."
                .to_string(),
        ),
        other => MacAutomationStatus::Unknown(format!(
            "macOS Automation readiness returned OSStatus {other}.",
        )),
    }
}

#[cfg(target_os = "macos")]
const fn fourcc(value: &str) -> u32 {
    let bytes = value.as_bytes();
    ((bytes[0] as u32) << 24)
        | ((bytes[1] as u32) << 16)
        | ((bytes[2] as u32) << 8)
        | (bytes[3] as u32)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn readiness_contains_all_phase_one_permission_keys() {
        let readiness = current_permission_readiness();
        let statuses = [
            readiness.screen_recording.status,
            readiness.accessibility.status,
            readiness.automation_system_events.status,
            readiness.input_monitoring.status,
            readiness.camera.status,
            readiness.microphone.status,
        ];

        for status in statuses {
            assert!(
                matches!(
                    status.as_str(),
                    "granted" | "denied" | "unknown" | "not_required"
                ),
                "unexpected permission status: {status}",
            );
        }
    }

    #[test]
    fn media_probes_return_permission_contract_statuses() {
        assert!(matches!(
            camera_readiness().status.as_str(),
            "granted" | "denied" | "unknown" | "not_required"
        ));
        assert!(matches!(
            microphone_readiness().status.as_str(),
            "granted" | "denied" | "unknown" | "not_required"
        ));
        assert_eq!(input_monitoring_readiness().status, "not_required");
    }

    #[test]
    fn automation_probe_returns_permission_contract_status() {
        #[cfg(target_os = "macos")]
        assert!(matches!(
            automation_system_events_readiness().status.as_str(),
            "granted" | "denied" | "unknown"
        ));

        #[cfg(not(target_os = "macos"))]
        assert_eq!(automation_system_events_readiness().status, "not_required");
    }

    #[test]
    fn app_identity_explains_tcc_scope() {
        let identity = current_app_identity();
        assert!(identity.permission_scope_note.contains("TCC"));
    }

    #[test]
    fn permission_setup_urls_cover_tcc_readiness_keys() {
        assert!(privacy_pane_url("screen_recording")
            .expect("screen URL")
            .contains("Privacy_ScreenCapture"));
        assert!(privacy_pane_url("accessibility")
            .expect("accessibility URL")
            .contains("Privacy_Accessibility"));
        assert!(privacy_pane_url("automation_system_events")
            .expect("automation URL")
            .contains("Privacy_Automation"));
        assert!(privacy_pane_url("input_monitoring")
            .expect("input monitoring URL")
            .contains("Privacy_ListenEvent"));
        assert!(privacy_pane_url("camera")
            .expect("camera URL")
            .contains("Privacy_Camera"));
        assert!(privacy_pane_url("microphone")
            .expect("microphone URL")
            .contains("Privacy_Microphone"));
        assert!(privacy_pane_url("full_disk_access").is_none());
    }
}
