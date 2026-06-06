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
            Self::ActiveApp => &["accessibility"],
            Self::ClipboardRead => &[],
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeControlCapability {
    Pointer,
    Keyboard,
}

impl NativeControlCapability {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Pointer => "pointer_control",
            Self::Keyboard => "keyboard_control",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct NativeControlCommandEnvelope {
    /// Placeholder for the future signature-verification result. This must be
    /// set only by a real AgentProvision signature verifier before native
    /// actuation is enabled; screen or LLM-supplied data must never set it.
    pub signed: bool,
    pub policy_version: u16,
    pub expires_at_ms: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct NativeControlCommandPolicy {
    pub mode: DesktopControlMode,
    pub capability: NativeControlCapability,
    pub has_claim_lease: bool,
    pub tier_enabled: bool,
    pub envelope: Option<NativeControlCommandEnvelope>,
    pub now_ms: u64,
}

pub const CURRENT_NATIVE_CONTROL_POLICY_VERSION: u16 = 1;

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

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NativeControlPolicyDenial {
    pub action: String,
    pub capability: NativeControlCapability,
    pub reason: String,
}

impl std::fmt::Display for NativeControlPolicyDenial {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.reason)
    }
}

impl std::error::Error for NativeControlPolicyDenial {}

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

pub fn evaluate_native_control_policy(
    mode: DesktopControlMode,
    _permissions: &DesktopPermissionReadiness,
    capability: NativeControlCapability,
    action: &str,
) -> Result<(), NativeControlPolicyDenial> {
    if mode == DesktopControlMode::Stopped {
        return Err(native_control_denial(
            action,
            capability,
            format!("desktop control stopped; {action} denied"),
        ));
    }

    Err(native_control_denial(
        action,
        capability,
        format!("desktop native control disabled; {action} denied"),
    ))
}

pub fn evaluate_native_control_command_policy(
    policy: NativeControlCommandPolicy,
    permissions: &DesktopPermissionReadiness,
    action: &str,
) -> Result<(), NativeControlPolicyDenial> {
    if policy.mode == DesktopControlMode::Stopped {
        return Err(native_control_denial(
            action,
            policy.capability,
            format!("desktop control stopped; {action} denied"),
        ));
    }

    if !policy.has_claim_lease {
        return Err(native_control_denial(
            action,
            policy.capability,
            format!("desktop command claim required; {action} denied"),
        ));
    }

    let Some(envelope) = policy.envelope else {
        return Err(native_control_denial(
            action,
            policy.capability,
            format!("desktop command envelope required; {action} denied"),
        ));
    };

    if !envelope.signed {
        return Err(native_control_denial(
            action,
            policy.capability,
            format!("desktop command envelope unsigned; {action} denied"),
        ));
    }

    if envelope.policy_version != CURRENT_NATIVE_CONTROL_POLICY_VERSION {
        return Err(native_control_denial(
            action,
            policy.capability,
            format!("desktop command envelope policy unsupported; {action} denied"),
        ));
    }

    if envelope.expires_at_ms <= policy.now_ms {
        return Err(native_control_denial(
            action,
            policy.capability,
            format!("desktop command envelope expired; {action} denied"),
        ));
    }

    if !policy.tier_enabled {
        return Err(native_control_denial(
            action,
            policy.capability,
            format!("desktop native control tier disabled; {action} denied"),
        ));
    }

    evaluate_native_control_policy(policy.mode, permissions, policy.capability, action)
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

fn native_control_denial(
    action: &str,
    capability: NativeControlCapability,
    reason: String,
) -> NativeControlPolicyDenial {
    NativeControlPolicyDenial {
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
    use crate::computer_use::permissions::{
        DesktopPermissionReadiness, PermissionAppIdentity, PermissionProbe,
    };

    fn readiness(screen: &str, ax: &str, automation: &str) -> DesktopPermissionReadiness {
        DesktopPermissionReadiness {
            app_identity: PermissionAppIdentity {
                bundle_id: Some("com.agentprovision.luna.test".to_string()),
                executable_path: None,
                app_bundle_path: None,
                code_signature_identifier: None,
                code_signature_team_identifier: None,
                code_signature_kind: None,
                permission_scope_note: "test TCC identity".to_string(),
            },
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
    fn active_app_allows_passive_system_events_probe_unknown() {
        let unknown = readiness("granted", "granted", "unknown");
        assert!(evaluate_observation_policy(
            DesktopControlMode::Observe,
            &unknown,
            ObservationCapability::ActiveApp,
            "get_active_app",
        )
        .is_ok());
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

    #[test]
    fn native_pointer_and_keyboard_control_stay_disabled() {
        let ready = readiness("granted", "granted", "granted");

        let pointer = evaluate_native_control_policy(
            DesktopControlMode::Observe,
            &ready,
            NativeControlCapability::Pointer,
            "control_pointer_click",
        )
        .expect_err("pointer control must remain disabled");
        assert!(pointer.reason.contains("desktop native control disabled"));
        assert_eq!(pointer.capability, NativeControlCapability::Pointer);

        let keyboard = evaluate_native_control_policy(
            DesktopControlMode::ControlLocked,
            &ready,
            NativeControlCapability::Keyboard,
            "control_keyboard_type",
        )
        .expect_err("keyboard control must remain disabled");
        assert!(keyboard.reason.contains("desktop native control disabled"));
        assert_eq!(keyboard.capability, NativeControlCapability::Keyboard);
    }

    #[test]
    fn stopped_mode_preempts_native_control_before_disabled_reason() {
        let ready = readiness("granted", "granted", "granted");

        let stopped = evaluate_native_control_policy(
            DesktopControlMode::Stopped,
            &ready,
            NativeControlCapability::Pointer,
            "control_pointer_move",
        )
        .expect_err("stopped mode must preempt native control");
        assert!(stopped.reason.contains("desktop control stopped"));
    }

    fn command_policy(
        mode: DesktopControlMode,
        capability: NativeControlCapability,
    ) -> NativeControlCommandPolicy {
        NativeControlCommandPolicy {
            mode,
            capability,
            has_claim_lease: true,
            tier_enabled: false,
            envelope: Some(NativeControlCommandEnvelope {
                signed: true,
                policy_version: CURRENT_NATIVE_CONTROL_POLICY_VERSION,
                expires_at_ms: 2_000,
            }),
            now_ms: 1_000,
        }
    }

    #[test]
    fn native_command_policy_stop_preempts_claim_and_envelope_checks() {
        let ready = readiness("granted", "granted", "granted");
        let mut policy = command_policy(
            DesktopControlMode::Stopped,
            NativeControlCapability::Pointer,
        );
        policy.has_claim_lease = false;
        policy.tier_enabled = true;
        policy.envelope = None;

        let err = evaluate_native_control_command_policy(policy, &ready, "control_pointer_click")
            .expect_err("Stop must be the first native-control denial");

        assert!(err.reason.contains("desktop control stopped"));
        assert_eq!(err.capability, NativeControlCapability::Pointer);
    }

    #[test]
    fn native_command_policy_requires_claim_lease_before_envelope() {
        let ready = readiness("granted", "granted", "granted");
        let mut policy = command_policy(
            DesktopControlMode::ControlLocked,
            NativeControlCapability::Keyboard,
        );
        policy.has_claim_lease = false;
        policy.envelope = None;

        let err = evaluate_native_control_command_policy(policy, &ready, "control_keyboard_type")
            .expect_err("native control needs a claimed command lease");

        assert!(err.reason.contains("desktop command claim required"));
    }

    #[test]
    fn native_command_policy_requires_signed_current_unexpired_envelope() {
        let ready = readiness("granted", "granted", "granted");

        let mut unsigned = command_policy(
            DesktopControlMode::ControlLocked,
            NativeControlCapability::Pointer,
        );
        unsigned.envelope.as_mut().expect("envelope").signed = false;
        let unsigned_err =
            evaluate_native_control_command_policy(unsigned, &ready, "control_pointer_move")
                .expect_err("unsigned envelopes must deny");
        assert!(unsigned_err.reason.contains("envelope unsigned"));

        let mut unsupported = command_policy(
            DesktopControlMode::ControlLocked,
            NativeControlCapability::Pointer,
        );
        unsupported
            .envelope
            .as_mut()
            .expect("envelope")
            .policy_version = CURRENT_NATIVE_CONTROL_POLICY_VERSION + 1;
        let unsupported_err =
            evaluate_native_control_command_policy(unsupported, &ready, "control_pointer_move")
                .expect_err("unsupported policy versions must deny");
        assert!(unsupported_err.reason.contains("policy unsupported"));

        let mut expired = command_policy(
            DesktopControlMode::ControlLocked,
            NativeControlCapability::Pointer,
        );
        expired.envelope.as_mut().expect("envelope").expires_at_ms = expired.now_ms;
        let expired_err =
            evaluate_native_control_command_policy(expired, &ready, "control_pointer_move")
                .expect_err("expired envelopes must deny");
        assert!(expired_err.reason.contains("envelope expired"));
    }

    #[test]
    fn native_command_policy_denies_when_tier_disabled() {
        let ready = readiness("granted", "granted", "granted");
        let policy = command_policy(
            DesktopControlMode::ControlLocked,
            NativeControlCapability::Keyboard,
        );

        let err =
            evaluate_native_control_command_policy(policy, &ready, "control_keyboard_key_chord")
                .expect_err("current native-control tier must stay off");

        assert!(err.reason.contains("native control tier disabled"));
    }

    #[test]
    fn native_command_policy_still_denies_with_all_current_preconditions_met() {
        let ready = readiness("granted", "granted", "granted");
        let mut policy = command_policy(
            DesktopControlMode::Observe,
            NativeControlCapability::Pointer,
        );
        policy.tier_enabled = true;

        let err = evaluate_native_control_command_policy(policy, &ready, "control_pointer_click")
            .expect_err("native actuation remains disabled until future approval path ships");

        assert!(err.reason.contains("desktop native control disabled"));
    }
}
