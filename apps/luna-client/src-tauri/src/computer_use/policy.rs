//! Read-only computer-use policy gate.
//!
//! Phase 1 observations are still local-user initiated, but they are no
//! longer raw helper commands. Every observation must pass the same mode and
//! permission policy before it can touch screen, app/window, or clipboard data.

use serde::Serialize;

use super::DesktopPermissionReadiness;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopControlMode {
    ControlLocked,
    Observe,
    Stopped,
}

impl DesktopControlMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ControlLocked => "control_locked",
            Self::Observe => "observe",
            Self::Stopped => "stopped",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ObservationCapability {
    Screenshot,
    ActiveApp,
    ClipboardRead,
}

impl ObservationCapability {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Screenshot => "screenshot",
            Self::ActiveApp => "active_app",
            Self::ClipboardRead => "clipboard_read",
        }
    }

    fn required_grants(self) -> &'static [&'static str] {
        match self {
            Self::Screenshot => &["screen_recording"],
            Self::ActiveApp => &["accessibility", "automation_system_events"],
            Self::ClipboardRead => &[],
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObservationPolicyDenial {
    pub action: String,
    pub capability: ObservationCapability,
    pub reason: String,
}

impl std::fmt::Display for ObservationPolicyDenial {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.reason)
    }
}

impl std::error::Error for ObservationPolicyDenial {}

pub fn evaluate_observation_policy(
    mode: DesktopControlMode,
    permissions: &DesktopPermissionReadiness,
    capability: ObservationCapability,
    action: &str,
) -> Result<(), ObservationPolicyDenial> {
    if mode == DesktopControlMode::Stopped {
        return Err(denial(
            action,
            capability,
            format!("desktop control stopped; {action} denied"),
        ));
    }

    if mode != DesktopControlMode::Observe {
        return Err(denial(
            action,
            capability,
            format!("desktop observe locked; {action} denied"),
        ));
    }

    for required in capability.required_grants() {
        let status = permission_status(permissions, required);
        if status != Some("granted") && status != Some("not_required") {
            return Err(denial(
                action,
                capability,
                format!(
                    "desktop observation permission '{required}' is {}; {action} denied",
                    status.unwrap_or("unknown")
                ),
            ));
        }
    }

    Ok(())
}

fn denial(
    action: &str,
    capability: ObservationCapability,
    reason: String,
) -> ObservationPolicyDenial {
    ObservationPolicyDenial {
        action: action.to_string(),
        capability,
        reason,
    }
}

fn permission_status<'a>(
    permissions: &'a DesktopPermissionReadiness,
    key: &str,
) -> Option<&'a str> {
    match key {
        "screen_recording" => Some(permissions.screen_recording.status.as_str()),
        "accessibility" => Some(permissions.accessibility.status.as_str()),
        "automation_system_events" => Some(permissions.automation_system_events.status.as_str()),
        "input_monitoring" => Some(permissions.input_monitoring.status.as_str()),
        "camera" => Some(permissions.camera.status.as_str()),
        "microphone" => Some(permissions.microphone.status.as_str()),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::computer_use::permissions::{DesktopPermissionReadiness, PermissionProbe};

    fn readiness(screen: &str, ax: &str, automation: &str) -> DesktopPermissionReadiness {
        DesktopPermissionReadiness {
            screen_recording: probe(screen),
            accessibility: probe(ax),
            automation_system_events: probe(automation),
            input_monitoring: PermissionProbe::not_required(&["keyboard observation"], "unused"),
            camera: PermissionProbe::unknown(&["gesture"], "deferred"),
            microphone: PermissionProbe::unknown(&["voice"], "deferred"),
        }
    }

    fn probe(status: &str) -> PermissionProbe {
        match status {
            "granted" => PermissionProbe::granted(&["test"], "granted"),
            "not_required" => PermissionProbe::not_required(&["test"], "not required"),
            "denied" => PermissionProbe::denied(&["test"], "denied"),
            _ => PermissionProbe::unknown(&["test"], "unknown"),
        }
    }

    #[test]
    fn stopped_and_locked_modes_deny_every_observation() {
        let ready = readiness("granted", "granted", "granted");

        let stopped = evaluate_observation_policy(
            DesktopControlMode::Stopped,
            &ready,
            ObservationCapability::ClipboardRead,
            "read_clipboard",
        )
        .expect_err("stopped mode must deny");
        assert!(stopped.reason.contains("desktop control stopped"));

        let locked = evaluate_observation_policy(
            DesktopControlMode::ControlLocked,
            &ready,
            ObservationCapability::ClipboardRead,
            "read_clipboard",
        )
        .expect_err("locked mode must deny");
        assert!(locked.reason.contains("desktop observe locked"));
    }

    #[test]
    fn screenshot_requires_screen_recording_grant() {
        let denied = readiness("denied", "granted", "granted");
        let err = evaluate_observation_policy(
            DesktopControlMode::Observe,
            &denied,
            ObservationCapability::Screenshot,
            "capture_screenshot",
        )
        .expect_err("screen capture without Screen Recording must be denied");
        assert!(err.reason.contains("screen_recording"));

        let granted = readiness("granted", "granted", "granted");
        assert!(evaluate_observation_policy(
            DesktopControlMode::Observe,
            &granted,
            ObservationCapability::Screenshot,
            "capture_screenshot",
        )
        .is_ok());
    }

    #[test]
    fn active_app_requires_accessibility_grant() {
        let denied = readiness("granted", "denied", "granted");
        let err = evaluate_observation_policy(
            DesktopControlMode::Observe,
            &denied,
            ObservationCapability::ActiveApp,
            "get_active_app",
        )
        .expect_err("active app context uses System Events/AX");
        assert!(err.reason.contains("accessibility"));
    }

    #[test]
    fn active_app_requires_system_events_automation_grant() {
        let unknown = readiness("granted", "granted", "unknown");
        let err = evaluate_observation_policy(
            DesktopControlMode::Observe,
            &unknown,
            ObservationCapability::ActiveApp,
            "get_active_app",
        )
        .expect_err("active app context uses System Events automation");
        assert!(err.reason.contains("automation_system_events"));
    }

    #[test]
    fn clipboard_read_has_no_tcc_dependency_but_still_requires_observe_mode() {
        let denied_tcc = readiness("denied", "denied", "denied");
        assert!(evaluate_observation_policy(
            DesktopControlMode::Observe,
            &denied_tcc,
            ObservationCapability::ClipboardRead,
            "read_clipboard",
        )
        .is_ok());
    }
}
