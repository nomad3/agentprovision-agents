//! Phase 3 / PR-C: pure native-actuation lease + actuation-attempt decision.
//!
//! The command-boundary proof (`evaluate_native_control_boundary_request`)
//! decides whether a native action MAY be granted. When it grants, the caller
//! CLAIMS a short-lived `ActuationLease`. Every subsequent native event (a
//! pointer move/click) must then pass `lease_actuation_decision` immediately
//! before the adapter call — re-checking the same target, a per-grant action
//! budget, pacing, and a short TTL at the instant the event would post (TOCTOU).
//!
//! This module is pure data + a pure decision: nothing here posts CGEvent/AX
//! input, enables actuation, or flips a capability flag. The `Stopped` /
//! `ObserveLocked` kill switches and the per-capability enablement flag are
//! checked by the caller (they read live process state); this module owns only
//! the lease-bound checks so they can be exhaustively unit-tested.

use crate::computer_use::denial_codes::DenialCode;
use crate::computer_use::policy::NativeControlCapability;

/// A claimed, short-lived grant to post native actuation events at one target.
/// Claimed only when a boundary proof is allowed; consumed (and its budget
/// decremented) by each native event. Single-owner: only `owner_shell_id` may
/// consume it — a second shell's proof is denied at claim time, not here.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActuationLease {
    /// The shell that holds the live lease. Only this shell may actuate.
    pub owner_shell_id: String,
    /// The bound frontmost-app bundle id the actuation is scoped to. The live
    /// frontmost app must still equal this at every native event.
    pub target_bundle_id: String,
    /// The single capability this lease authorizes. A pointer lease can never
    /// authorize a keyboard event, and vice-versa.
    pub capability: NativeControlCapability,
    /// Absolute wall-clock expiry (ms). A short TTL; past it the lease is dead.
    pub expires_at_ms: u64,
    /// Per-grant action budget. A large budget cannot fire as a burst — pacing
    /// still applies between actions.
    pub max_actions: u32,
    /// How many native events this lease has already posted.
    pub actions_used: u32,
    /// Wall-clock (ms) of the last posted native event, for pacing. `None`
    /// before the first action.
    pub last_action_at_ms: Option<u64>,
}

impl ActuationLease {
    /// True when the lease still has wall-clock life left.
    pub fn is_live(&self, now_ms: u64) -> bool {
        now_ms < self.expires_at_ms
    }

    /// True when the lease still has action budget left.
    pub fn has_budget(&self) -> bool {
        self.actions_used < self.max_actions
    }
}

/// The live inputs for one native event, gathered immediately before the
/// adapter call. `live_frontmost_bundle` and `point_in_bounds` are read/computed
/// Rust-side at actuation time (never trusted from JS).
pub struct ActuationAttempt<'a> {
    pub capability: NativeControlCapability,
    pub now_ms: u64,
    pub live_frontmost_bundle: Option<&'a str>,
    /// Whether the requested coordinates fall inside the lease's signed
    /// display/global-coordinate bound. Computed by the caller from the active
    /// display; a non-match is target drift.
    pub point_in_bounds: bool,
    pub min_interval_ms: u64,
}

/// Decide whether a single native event may post against `lease`. Returns the
/// stable denial code to fail closed with, or `None` to proceed to the adapter.
///
/// Order matters — most-fundamental first, so the surfaced reason is the
/// earliest gate that fails:
///   1. no lease claimed                  → `claim_required`
///   2. lease scoped to another capability → `approval_binding_mismatch`
///   3. lease past its TTL                 → `approval_expired`
///   4. per-grant budget exhausted         → `approval_exhausted`
///   5. fired within the pacing interval   → `rate_capped`
///   6. frontmost no longer the target     → `active_app_drift`
///   7. point outside the signed bound     → `target_drift`
pub fn lease_actuation_decision(
    lease: Option<&ActuationLease>,
    attempt: &ActuationAttempt,
) -> Option<DenialCode> {
    let Some(lease) = lease else {
        return Some(DenialCode::ClaimRequired);
    };
    if lease.capability != attempt.capability {
        return Some(DenialCode::ApprovalBindingMismatch);
    }
    if !lease.is_live(attempt.now_ms) {
        return Some(DenialCode::ApprovalExpired);
    }
    if !lease.has_budget() {
        return Some(DenialCode::ApprovalExhausted);
    }
    if let Some(last) = lease.last_action_at_ms {
        if attempt.min_interval_ms > 0
            && attempt.now_ms.saturating_sub(last) < attempt.min_interval_ms
        {
            return Some(DenialCode::RateCapped);
        }
    }
    match attempt.live_frontmost_bundle {
        Some(live) if live == lease.target_bundle_id => {}
        _ => return Some(DenialCode::ActiveAppDrift),
    }
    if !attempt.point_in_bounds {
        return Some(DenialCode::TargetDrift);
    }
    None
}

/// A normalized [0, 1] pointer coordinate is in-bounds only when both axes are
/// finite and within the unit square (the active display's signed bound). NaN /
/// infinity / out-of-range fail closed.
pub fn normalized_point_in_bounds(norm_x: f64, norm_y: f64) -> bool {
    norm_x.is_finite()
        && norm_y.is_finite()
        && (0.0..=1.0).contains(&norm_x)
        && (0.0..=1.0).contains(&norm_y)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lease() -> ActuationLease {
        ActuationLease {
            owner_shell_id: "desktop-aaaa".to_string(),
            target_bundle_id: "com.example.LunaCanaryTarget".to_string(),
            capability: NativeControlCapability::Pointer,
            expires_at_ms: 10_000,
            max_actions: 4,
            actions_used: 0,
            last_action_at_ms: None,
        }
    }

    fn attempt<'a>(frontmost: Option<&'a str>) -> ActuationAttempt<'a> {
        ActuationAttempt {
            capability: NativeControlCapability::Pointer,
            now_ms: 1_000,
            live_frontmost_bundle: frontmost,
            point_in_bounds: true,
            min_interval_ms: 250,
        }
    }

    #[test]
    fn no_lease_requires_claim() {
        assert_eq!(
            lease_actuation_decision(None, &attempt(Some("com.example.LunaCanaryTarget"))),
            Some(DenialCode::ClaimRequired)
        );
    }

    #[test]
    fn capability_mismatch_is_binding_mismatch() {
        let mut a = attempt(Some("com.example.LunaCanaryTarget"));
        a.capability = NativeControlCapability::Keyboard;
        assert_eq!(
            lease_actuation_decision(Some(&lease()), &a),
            Some(DenialCode::ApprovalBindingMismatch)
        );
    }

    #[test]
    fn expired_lease_denies() {
        let mut l = lease();
        l.expires_at_ms = 500; // now_ms is 1_000
        assert_eq!(
            lease_actuation_decision(Some(&l), &attempt(Some("com.example.LunaCanaryTarget"))),
            Some(DenialCode::ApprovalExpired)
        );
    }

    #[test]
    fn exhausted_budget_denies() {
        let mut l = lease();
        l.max_actions = 2;
        l.actions_used = 2;
        assert_eq!(
            lease_actuation_decision(Some(&l), &attempt(Some("com.example.LunaCanaryTarget"))),
            Some(DenialCode::ApprovalExhausted)
        );
    }

    #[test]
    fn pacing_violation_is_rate_capped() {
        let mut l = lease();
        l.last_action_at_ms = Some(900); // 1_000 - 900 = 100ms < 250ms
        assert_eq!(
            lease_actuation_decision(Some(&l), &attempt(Some("com.example.LunaCanaryTarget"))),
            Some(DenialCode::RateCapped)
        );
    }

    #[test]
    fn pacing_satisfied_when_interval_elapsed() {
        let mut l = lease();
        l.last_action_at_ms = Some(700); // 1_000 - 700 = 300ms >= 250ms
        assert_eq!(
            lease_actuation_decision(Some(&l), &attempt(Some("com.example.LunaCanaryTarget"))),
            None
        );
    }

    #[test]
    fn frontmost_drift_denies() {
        assert_eq!(
            lease_actuation_decision(Some(&lease()), &attempt(Some("com.example.SomethingElse"))),
            Some(DenialCode::ActiveAppDrift)
        );
        // A missing frontmost reading fails closed as drift.
        assert_eq!(
            lease_actuation_decision(Some(&lease()), &attempt(None)),
            Some(DenialCode::ActiveAppDrift)
        );
    }

    #[test]
    fn out_of_bounds_point_is_target_drift() {
        let mut a = attempt(Some("com.example.LunaCanaryTarget"));
        a.point_in_bounds = false;
        assert_eq!(
            lease_actuation_decision(Some(&lease()), &a),
            Some(DenialCode::TargetDrift)
        );
    }

    #[test]
    fn fully_valid_attempt_is_allowed() {
        assert_eq!(
            lease_actuation_decision(Some(&lease()), &attempt(Some("com.example.LunaCanaryTarget"))),
            None
        );
    }

    #[test]
    fn normalized_bounds_rejects_out_of_range_and_non_finite() {
        assert!(normalized_point_in_bounds(0.0, 0.0));
        assert!(normalized_point_in_bounds(1.0, 1.0));
        assert!(normalized_point_in_bounds(0.5, 0.5));
        assert!(!normalized_point_in_bounds(-0.01, 0.5));
        assert!(!normalized_point_in_bounds(0.5, 1.01));
        assert!(!normalized_point_in_bounds(f64::NAN, 0.5));
        assert!(!normalized_point_in_bounds(0.5, f64::INFINITY));
    }
}
