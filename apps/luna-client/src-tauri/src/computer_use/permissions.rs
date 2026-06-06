use serde::Serialize;

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct PermissionProbe {
    pub status: String,
    pub required_for: Vec<String>,
    pub reason: String,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct DesktopPermissionReadiness {
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
        screen_recording: screen_recording_readiness(),
        accessibility: accessibility_readiness(),
        automation_system_events: automation_system_events_readiness(),
        input_monitoring: input_monitoring_readiness(),
        camera: camera_readiness(),
        microphone: microphone_readiness(),
    }
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

#[cfg(target_os = "macos")]
fn accessibility_readiness() -> PermissionProbe {
    #[link(name = "ApplicationServices", kind = "framework")]
    extern "C" {
        fn AXIsProcessTrusted() -> bool;
    }

    let granted = unsafe { AXIsProcessTrusted() };
    if granted {
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
    PermissionProbe::not_required(&["pointer control"], "Accessibility probing is macOS-specific.")
}

#[cfg(target_os = "macos")]
fn automation_system_events_readiness() -> PermissionProbe {
    PermissionProbe::unknown(
        &["active app", "window title"],
        "System Events automation is checked only from an explicit permissions setup flow.",
    )
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

fn camera_readiness() -> PermissionProbe {
    PermissionProbe::unknown(
        &["gesture calibration", "gesture settings"],
        "Camera permission is checked only when the user explicitly opens a gesture feature.",
    )
}

fn microphone_readiness() -> PermissionProbe {
    PermissionProbe::unknown(
        &["push-to-talk"],
        "Microphone permission is checked only when the user explicitly opens a voice feature.",
    )
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
                matches!(status.as_str(), "granted" | "denied" | "unknown" | "not_required"),
                "unexpected permission status: {status}",
            );
        }
    }

    #[test]
    fn unknown_media_probes_do_not_claim_permission() {
        assert_eq!(camera_readiness().status, "unknown");
        assert_eq!(microphone_readiness().status, "unknown");
        assert_eq!(input_monitoring_readiness().status, "not_required");
    }

    #[test]
    fn automation_probe_is_passive_until_explicit_setup() {
        #[cfg(target_os = "macos")]
        assert_eq!(automation_system_events_readiness().status, "unknown");

        #[cfg(not(target_os = "macos"))]
        assert_eq!(automation_system_events_readiness().status, "not_required");
    }
}
