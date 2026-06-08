//! Phase 2.75 / PR-C: stable desktop-control denial codes (Tauri mirror).
//!
//! Mirrors the string values of the server contract in
//! `apps/api/app/services/desktop_control_codes.py`. Pure data + pure decisions;
//! nothing here posts CGEvent/AX input, enables actuation, or flips a capability
//! flag.

use crate::computer_use::policy::NativeControlCapability;

/// Closed set of stable, display-safe desktop-control denial codes. Mirrors
/// `DesktopDenialCode` in the server contract; `as_str()` values must stay
/// byte-identical across both sides.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DenialCode {
    Stopped,
    ObserveLocked,
    NativeControlDisabled,
    NativeControlTierDisabled,
    NativeControlActionUnsupported,
    ObservationPermissionDenied,
    ObservationDenied,
    ObservationFailed,
    DownChannelUnavailable,
    ShellCannotObserve,
    EnvelopeMissing,
    EnvelopeRequired,
    EnvelopeUnsigned,
    EnvelopeNonceMissing,
    EnvelopeNonceMismatch,
    EnvelopeSignatureInvalid,
    EnvelopePublicKeyInvalid,
    EnvelopeKeyUnknown,
    EnvelopeKeyRegistryInvalid,
    EnvelopeExpired,
    EnvelopeBindingMismatch,
    EnvelopePolicyUnsupported,
    EnvelopeReplayed,
    ClaimRequired,
    LeaseExpired,
    PendingTtlExpired,
    Preempted,
    ApprovalMissing,
    ApprovalExpired,
    ApprovalRevoked,
    ApprovalExhausted,
    ApprovalBindingMismatch,
    ApprovalReplayDenied,
    TargetNotAllowlisted,
    ActiveAppDrift,
    TargetDrift,
    SecureInputActive,
    ActuationOwnerConflict,
    RateCapped,
    CommandDenied,
    CommandFailed,
    Unspecified,
}

impl DenialCode {
    /// Every variant, for exhaustive validation/iteration.
    pub const ALL: [DenialCode; 42] = [
        DenialCode::Stopped,
        DenialCode::ObserveLocked,
        DenialCode::NativeControlDisabled,
        DenialCode::NativeControlTierDisabled,
        DenialCode::NativeControlActionUnsupported,
        DenialCode::ObservationPermissionDenied,
        DenialCode::ObservationDenied,
        DenialCode::ObservationFailed,
        DenialCode::DownChannelUnavailable,
        DenialCode::ShellCannotObserve,
        DenialCode::EnvelopeMissing,
        DenialCode::EnvelopeRequired,
        DenialCode::EnvelopeUnsigned,
        DenialCode::EnvelopeNonceMissing,
        DenialCode::EnvelopeNonceMismatch,
        DenialCode::EnvelopeSignatureInvalid,
        DenialCode::EnvelopePublicKeyInvalid,
        DenialCode::EnvelopeKeyUnknown,
        DenialCode::EnvelopeKeyRegistryInvalid,
        DenialCode::EnvelopeExpired,
        DenialCode::EnvelopeBindingMismatch,
        DenialCode::EnvelopePolicyUnsupported,
        DenialCode::EnvelopeReplayed,
        DenialCode::ClaimRequired,
        DenialCode::LeaseExpired,
        DenialCode::PendingTtlExpired,
        DenialCode::Preempted,
        DenialCode::ApprovalMissing,
        DenialCode::ApprovalExpired,
        DenialCode::ApprovalRevoked,
        DenialCode::ApprovalExhausted,
        DenialCode::ApprovalBindingMismatch,
        DenialCode::ApprovalReplayDenied,
        DenialCode::TargetNotAllowlisted,
        DenialCode::ActiveAppDrift,
        DenialCode::TargetDrift,
        DenialCode::SecureInputActive,
        DenialCode::ActuationOwnerConflict,
        DenialCode::RateCapped,
        DenialCode::CommandDenied,
        DenialCode::CommandFailed,
        DenialCode::Unspecified,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            DenialCode::Stopped => "stopped",
            DenialCode::ObserveLocked => "observe_locked",
            DenialCode::NativeControlDisabled => "native_control_disabled",
            DenialCode::NativeControlTierDisabled => "native_control_tier_disabled",
            DenialCode::NativeControlActionUnsupported => "native_control_action_unsupported",
            DenialCode::ObservationPermissionDenied => "observation_permission_denied",
            DenialCode::ObservationDenied => "observation_denied",
            DenialCode::ObservationFailed => "observation_failed",
            DenialCode::DownChannelUnavailable => "down_channel_unavailable",
            DenialCode::ShellCannotObserve => "shell_cannot_observe",
            DenialCode::EnvelopeMissing => "envelope_missing",
            DenialCode::EnvelopeRequired => "envelope_required",
            DenialCode::EnvelopeUnsigned => "envelope_unsigned",
            DenialCode::EnvelopeNonceMissing => "envelope_nonce_missing",
            DenialCode::EnvelopeNonceMismatch => "envelope_nonce_mismatch",
            DenialCode::EnvelopeSignatureInvalid => "envelope_signature_invalid",
            DenialCode::EnvelopePublicKeyInvalid => "envelope_public_key_invalid",
            DenialCode::EnvelopeKeyUnknown => "envelope_key_unknown",
            DenialCode::EnvelopeKeyRegistryInvalid => "envelope_key_registry_invalid",
            DenialCode::EnvelopeExpired => "envelope_expired",
            DenialCode::EnvelopeBindingMismatch => "envelope_binding_mismatch",
            DenialCode::EnvelopePolicyUnsupported => "envelope_policy_unsupported",
            DenialCode::EnvelopeReplayed => "envelope_replayed",
            DenialCode::ClaimRequired => "claim_required",
            DenialCode::LeaseExpired => "lease_expired",
            DenialCode::PendingTtlExpired => "pending_ttl_expired",
            DenialCode::Preempted => "preempted",
            DenialCode::ApprovalMissing => "approval_missing",
            DenialCode::ApprovalExpired => "approval_expired",
            DenialCode::ApprovalRevoked => "approval_revoked",
            DenialCode::ApprovalExhausted => "approval_exhausted",
            DenialCode::ApprovalBindingMismatch => "approval_binding_mismatch",
            DenialCode::ApprovalReplayDenied => "approval_replay_denied",
            DenialCode::TargetNotAllowlisted => "target_not_allowlisted",
            DenialCode::ActiveAppDrift => "active_app_drift",
            DenialCode::TargetDrift => "target_drift",
            DenialCode::SecureInputActive => "secure_input_active",
            DenialCode::ActuationOwnerConflict => "actuation_owner_conflict",
            DenialCode::RateCapped => "rate_capped",
            DenialCode::CommandDenied => "command_denied",
            DenialCode::CommandFailed => "command_failed",
            DenialCode::Unspecified => "unspecified",
        }
    }
}

/// Ordered (prefix, code) table, most-specific first. Mirrors `_REASON_PREFIXES`
/// in the server contract. `starts_with` absorbs the `; {action} denied`
/// suffixes the runtime appends.
const REASON_PREFIXES: &[(&str, DenialCode)] = &[
    ("desktop control stopped", DenialCode::Stopped),
    ("operator stop", DenialCode::Stopped),
    ("local stop latched", DenialCode::Stopped),
    ("desktop observe locked", DenialCode::ObserveLocked),
    (
        "desktop native control tier disabled",
        DenialCode::NativeControlTierDisabled,
    ),
    (
        "desktop native control action unsupported",
        DenialCode::NativeControlActionUnsupported,
    ),
    (
        "desktop native control disabled",
        DenialCode::NativeControlDisabled,
    ),
    (
        "desktop observation permission",
        DenialCode::ObservationPermissionDenied,
    ),
    (
        "desktop observation down-channel unavailable",
        DenialCode::DownChannelUnavailable,
    ),
    ("desktop observation denied", DenialCode::ObservationDenied),
    ("desktop observation failed", DenialCode::ObservationFailed),
    (
        "desktop shell cannot observe",
        DenialCode::ShellCannotObserve,
    ),
    (
        "desktop command envelope missing",
        DenialCode::EnvelopeMissing,
    ),
    (
        "desktop command envelope required",
        DenialCode::EnvelopeRequired,
    ),
    (
        "desktop command envelope unsigned",
        DenialCode::EnvelopeUnsigned,
    ),
    (
        "desktop command envelope nonce missing",
        DenialCode::EnvelopeNonceMissing,
    ),
    (
        "desktop command envelope nonce mismatch",
        DenialCode::EnvelopeNonceMismatch,
    ),
    (
        "desktop command envelope signature invalid",
        DenialCode::EnvelopeSignatureInvalid,
    ),
    (
        "desktop command envelope public key invalid",
        DenialCode::EnvelopePublicKeyInvalid,
    ),
    (
        "desktop command envelope public key missing",
        DenialCode::EnvelopePublicKeyInvalid,
    ),
    (
        "desktop command envelope key unknown",
        DenialCode::EnvelopeKeyUnknown,
    ),
    (
        "desktop command envelope key registry invalid",
        DenialCode::EnvelopeKeyRegistryInvalid,
    ),
    (
        "desktop command envelope expired",
        DenialCode::EnvelopeExpired,
    ),
    (
        "desktop command envelope binding mismatch",
        DenialCode::EnvelopeBindingMismatch,
    ),
    (
        "desktop command envelope policy unsupported",
        DenialCode::EnvelopePolicyUnsupported,
    ),
    (
        "desktop command envelope replay denied",
        DenialCode::EnvelopeReplayed,
    ),
    (
        "desktop command envelope replayed",
        DenialCode::EnvelopeReplayed,
    ),
    ("desktop command claim required", DenialCode::ClaimRequired),
    ("desktop command lease expired", DenialCode::LeaseExpired),
    (
        "desktop command pending ttl expired",
        DenialCode::PendingTtlExpired,
    ),
    ("desktop command preempted", DenialCode::Preempted),
    (
        "desktop command approval grant missing",
        DenialCode::ApprovalMissing,
    ),
    (
        "desktop command approval grant expired",
        DenialCode::ApprovalExpired,
    ),
    (
        "desktop command approval grant revoked",
        DenialCode::ApprovalRevoked,
    ),
    (
        "desktop command approval grant exhausted",
        DenialCode::ApprovalExhausted,
    ),
    (
        "desktop command approval grant binding mismatch",
        DenialCode::ApprovalBindingMismatch,
    ),
    (
        "desktop command approval grant replay denied",
        DenialCode::ApprovalReplayDenied,
    ),
    (
        "desktop command target not allowlisted",
        DenialCode::TargetNotAllowlisted,
    ),
    (
        "desktop command target not allow-listed",
        DenialCode::TargetNotAllowlisted,
    ),
    ("target_not_allowlisted", DenialCode::TargetNotAllowlisted),
    ("active_app_drift", DenialCode::ActiveAppDrift),
    ("target_drift", DenialCode::TargetDrift),
    ("secure_input_active", DenialCode::SecureInputActive),
    (
        "actuation_owner_conflict",
        DenialCode::ActuationOwnerConflict,
    ),
    ("rate_capped", DenialCode::RateCapped),
    ("desktop command denied", DenialCode::CommandDenied),
    ("desktop command failed", DenialCode::CommandFailed),
];

/// Map a canonical display-safe reason to exactly one stable code.
/// Returns `Unspecified` for empty/unmapped input. Never panics.
pub fn code_for_reason(reason: &str) -> DenialCode {
    let normalized = reason
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_lowercase();
    if normalized.is_empty() {
        return DenialCode::Unspecified;
    }
    for (prefix, code) in REASON_PREFIXES {
        if normalized.starts_with(prefix) {
            return *code;
        }
    }
    DenialCode::Unspecified
}

/// Keyboard input is fail-closed while macOS Secure Input is active. Secure
/// Input is a process-global signal, not per-field; pointer is unaffected.
pub fn secure_input_decision(
    secure_input_active: bool,
    capability: NativeControlCapability,
) -> Option<DenialCode> {
    if secure_input_active && capability == NativeControlCapability::Keyboard {
        Some(DenialCode::SecureInputActive)
    } else {
        None
    }
}

/// Deny if a native action would fire faster than the minimum interval. The
/// first action (no prior timestamp) is always allowed.
pub fn pacing_decision(
    last_action_at_ms: Option<u64>,
    now_ms: u64,
    min_interval_ms: u64,
) -> Option<DenialCode> {
    match last_action_at_ms {
        Some(last) if min_interval_ms > 0 && now_ms.saturating_sub(last) < min_interval_ms => {
            Some(DenialCode::RateCapped)
        }
        _ => None,
    }
}

/// Only one shell/device may hold the live actuation lease at a time.
pub fn single_owner_decision(
    current_owner_shell_id: Option<&str>,
    requester_shell_id: &str,
) -> Option<DenialCode> {
    match current_owner_shell_id {
        Some(owner) if owner != requester_shell_id => Some(DenialCode::ActuationOwnerConflict),
        _ => None,
    }
}

/// An envelope scoped to one capability must never authorize another. A keyboard
/// envelope used for a pointer action (or vice versa) is an envelope-binding
/// mismatch and must deny before any native call. (Reuses the existing
/// `EnvelopeBindingMismatch` code; a distinct `capability_mismatch` token, if the
/// B-lane contract introduces one, is handled in that lane — this lane only
/// proves the denial occurs.)
pub fn capability_match_decision(
    envelope_capability: NativeControlCapability,
    requested_capability: NativeControlCapability,
) -> Option<DenialCode> {
    if envelope_capability != requested_capability {
        Some(DenialCode::EnvelopeBindingMismatch)
    } else {
        None
    }
}

/// The live frontmost app bundle id must equal the envelope's target bundle id
/// immediately before a native action. A missing/unreadable frontmost app fails
/// closed as drift.
pub fn frontmost_app_decision(
    live_frontmost_bundle: Option<&str>,
    target_bundle: &str,
) -> Option<DenialCode> {
    match live_frontmost_bundle {
        Some(live) if live == target_bundle => None,
        _ => Some(DenialCode::ActiveAppDrift),
    }
}

/// The focused window/element must still match the envelope target (title hash /
/// bounds / display id are compared by the caller; this maps the precomputed
/// match result to a code). A non-match denies as target drift.
pub fn target_window_decision(live_window_matches_target: bool) -> Option<DenialCode> {
    if live_window_matches_target {
        None
    } else {
        Some(DenialCode::TargetDrift)
    }
}

/// Classify a stale/unusable approval grant in the same order the server uses:
/// revoked, then expired, then exhausted. `None` means the grant is usable.
/// Mirrors `stale_approval_decision` in the server contract
/// (`apps/api/app/services/desktop_control_codes.py`).
pub fn stale_approval_decision(
    status: &str,
    expires_at_ms: u64,
    now_ms: u64,
    remaining_actions: i64,
) -> Option<DenialCode> {
    if status == "revoked" {
        return Some(DenialCode::ApprovalRevoked);
    }
    if status == "expired" || expires_at_ms <= now_ms {
        return Some(DenialCode::ApprovalExpired);
    }
    if status == "consumed" || remaining_actions <= 0 {
        return Some(DenialCode::ApprovalExhausted);
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::computer_use::policy::NativeControlCapability;

    #[test]
    fn code_for_reason_maps_canonical_reasons() {
        assert_eq!(
            code_for_reason("desktop control stopped; pointer_click denied"),
            DenialCode::Stopped
        );
        assert_eq!(
            code_for_reason("desktop observe locked; get_active_app denied"),
            DenialCode::ObserveLocked
        );
        assert_eq!(
            code_for_reason("desktop native control tier disabled; pointer_move denied"),
            DenialCode::NativeControlTierDisabled
        );
        assert_eq!(
            code_for_reason("desktop native control disabled; pointer_click denied"),
            DenialCode::NativeControlDisabled
        );
        assert_eq!(
            code_for_reason("desktop command envelope signature invalid"),
            DenialCode::EnvelopeSignatureInvalid
        );
        assert_eq!(
            code_for_reason("desktop command envelope key unknown"),
            DenialCode::EnvelopeKeyUnknown
        );
        assert_eq!(
            code_for_reason("desktop command envelope replayed"),
            DenialCode::EnvelopeReplayed
        );
        assert_eq!(
            code_for_reason("desktop command approval grant revoked"),
            DenialCode::ApprovalRevoked
        );
        assert_eq!(
            code_for_reason("desktop command lease expired"),
            DenialCode::LeaseExpired
        );
        assert_eq!(
            code_for_reason("active_app_drift"),
            DenialCode::ActiveAppDrift
        );
        assert_eq!(code_for_reason("target_drift"), DenialCode::TargetDrift);
        assert_eq!(
            code_for_reason("secure_input_active"),
            DenialCode::SecureInputActive
        );
        assert_eq!(code_for_reason("rate_capped"), DenialCode::RateCapped);
        assert_eq!(
            code_for_reason("actuation_owner_conflict"),
            DenialCode::ActuationOwnerConflict
        );
    }

    #[test]
    fn unknown_reason_maps_to_unspecified() {
        assert_eq!(
            code_for_reason("nobody planned for this"),
            DenialCode::Unspecified
        );
        assert_eq!(code_for_reason(""), DenialCode::Unspecified);
    }

    #[test]
    fn active_app_drift_and_target_drift_are_distinct() {
        assert_ne!(DenialCode::ActiveAppDrift, DenialCode::TargetDrift);
    }

    #[test]
    fn every_code_value_is_a_display_safe_token() {
        for code in DenialCode::ALL {
            let value = code.as_str();
            assert_eq!(value, value.to_ascii_lowercase());
            assert!(!value.contains(' '));
            assert!(!value.contains(';'));
            assert!(!value.contains(':'));
            assert!(value
                .chars()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_'));
        }
    }

    #[test]
    fn secure_input_blocks_keyboard_only() {
        assert_eq!(
            secure_input_decision(true, NativeControlCapability::Keyboard),
            Some(DenialCode::SecureInputActive)
        );
        assert_eq!(
            secure_input_decision(true, NativeControlCapability::Pointer),
            None
        );
        assert_eq!(
            secure_input_decision(false, NativeControlCapability::Keyboard),
            None
        );
    }

    #[test]
    fn pacing_denies_inside_interval_only() {
        assert_eq!(
            pacing_decision(Some(1000), 1100, 200),
            Some(DenialCode::RateCapped)
        );
        assert_eq!(pacing_decision(Some(1000), 1300, 200), None);
        assert_eq!(pacing_decision(None, 1300, 200), None);
    }

    #[test]
    fn single_owner_conflict_only_for_other_shell() {
        assert_eq!(
            single_owner_decision(Some("desktop-aaa"), "desktop-bbb"),
            Some(DenialCode::ActuationOwnerConflict)
        );
        assert_eq!(
            single_owner_decision(Some("desktop-aaa"), "desktop-aaa"),
            None
        );
        assert_eq!(single_owner_decision(None, "desktop-aaa"), None);
    }

    // ---- Phase 2.75 native-boundary denial matrix (prove deny BEFORE any native call) ----
    // 1 wrong-capability ......... wrong_capability_envelope_denies / capability_match_decision
    // 2 target drift ............. frontmost_app_drift_denies + target_window_drift_denies
    // 3 secure-input keyboard .... secure_input_blocks_keyboard_only (above)
    // 4 single-owner conflict .... single_owner_conflict_only_for_other_shell (above)
    // 5 pacing violation ......... pacing_denies_inside_interval_only (above)
    // 6 stale approval ........... stale_approval_denies_by_state
    // 7 Stop ..................... policy.rs::native_command_policy_stop_preempts_claim_and_envelope_checks
    // 8 Lock .................... policy.rs::stopped_and_locked_modes_deny_every_observation
    // (7 & 8 already proven in computer_use::policy; mirrored here only by reason->code mapping)

    #[test]
    fn wrong_capability_envelope_denies() {
        // A keyboard-scoped envelope must never authorize a pointer action (and vice versa).
        assert_eq!(
            capability_match_decision(
                NativeControlCapability::Keyboard,
                NativeControlCapability::Pointer,
            ),
            Some(DenialCode::EnvelopeBindingMismatch)
        );
        assert_eq!(
            capability_match_decision(
                NativeControlCapability::Pointer,
                NativeControlCapability::Keyboard,
            ),
            Some(DenialCode::EnvelopeBindingMismatch)
        );
        assert_eq!(
            capability_match_decision(
                NativeControlCapability::Pointer,
                NativeControlCapability::Pointer,
            ),
            None
        );
    }

    #[test]
    fn frontmost_app_drift_denies() {
        assert_eq!(
            frontmost_app_decision(Some("com.example.Other"), "com.example.Target"),
            Some(DenialCode::ActiveAppDrift)
        );
        // No readable frontmost app fails closed as drift.
        assert_eq!(
            frontmost_app_decision(None, "com.example.Target"),
            Some(DenialCode::ActiveAppDrift)
        );
        assert_eq!(
            frontmost_app_decision(Some("com.example.Target"), "com.example.Target"),
            None
        );
    }

    #[test]
    fn target_window_drift_denies() {
        assert_eq!(target_window_decision(false), Some(DenialCode::TargetDrift));
        assert_eq!(target_window_decision(true), None);
    }

    #[test]
    fn stale_approval_denies_by_state() {
        // revoked beats everything
        assert_eq!(
            stale_approval_decision("revoked", 10_000, 5_000, 1),
            Some(DenialCode::ApprovalRevoked)
        );
        // expired by time, and by explicit status
        assert_eq!(
            stale_approval_decision("active", 5_000, 5_000, 1),
            Some(DenialCode::ApprovalExpired)
        );
        assert_eq!(
            stale_approval_decision("expired", 10_000, 5_000, 1),
            Some(DenialCode::ApprovalExpired)
        );
        // exhausted by remaining count and by explicit status
        assert_eq!(
            stale_approval_decision("active", 10_000, 5_000, 0),
            Some(DenialCode::ApprovalExhausted)
        );
        assert_eq!(
            stale_approval_decision("consumed", 10_000, 5_000, 1),
            Some(DenialCode::ApprovalExhausted)
        );
        // a fresh, active, unexhausted grant is allowed
        assert_eq!(stale_approval_decision("active", 10_000, 5_000, 1), None);
    }
}
