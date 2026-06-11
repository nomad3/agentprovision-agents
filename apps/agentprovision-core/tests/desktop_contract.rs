//! PR-D desktop-control contract parity — core mirror (typed deserialization).
//!
//! Deserializes the shared golden fixtures into the strongly-typed
//! `agentprovision_core::desktop` models. Fail-closed: raw screenshot / clipboard
//! / OCR / window-title / signature fields cannot deserialize into the
//! display-safe structs (`deny_unknown_fields`). A recursive `Value` scan
//! complements the typed checks by also covering the opaque action `args`.
//!
//! Scope: contract/parity only. No native actuation.

use agentprovision_core::desktop::{
    DesktopActionKind, DesktopCapability, DesktopCommandClaim, DesktopCommandDenied,
    DesktopCommandStatus, DesktopControlMode, DesktopDenialCode, DesktopRiskTier, EnvelopeAlg,
    PerceptionArtifactStatus, PerceptionFetchDenial, PerceptionFetchDenialCode,
    PerceptionRedactionStatus,
};
use serde_json::Value;

const CLAIM: &str =
    include_str!("../../../docs/contracts/desktop-control/pointer_command_claim.display_safe.json");
const DENY_BUNDLE: &str =
    include_str!("../../../docs/contracts/desktop-control/deny.missing_target_bundle_id.json");
const DENY_CAP: &str =
    include_str!("../../../docs/contracts/desktop-control/deny.capability_mismatch.json");
const OBSERVATION_STATUS: &str =
    include_str!("../../../docs/contracts/desktop-control/observation_status.planner_safe.json");
const OBSERVATION_FETCH_DENIED: &str =
    include_str!("../../../docs/contracts/desktop-control/observation_fetch.denied.json");

const FORBIDDEN: &[&str] = &[
    "window_title",
    "screenshot",
    "screenshot_b64",
    "screenshot_bytes",
    "clipboard",
    "clipboard_text",
    "ocr_text",
    "ax_tree",
    "page_text",
    "signature",
    "private_key",
    "raw_title",
    "title",
];

fn forbidden_hits(v: &Value, path: &str, out: &mut Vec<String>) {
    match v {
        Value::Object(map) => {
            for (k, val) in map {
                if FORBIDDEN.contains(&k.as_str()) {
                    out.push(format!("{path}.{k}"));
                }
                forbidden_hits(val, &format!("{path}.{k}"), out);
            }
        }
        Value::Array(arr) => {
            for (i, val) in arr.iter().enumerate() {
                forbidden_hits(val, &format!("{path}[{i}]"), out);
            }
        }
        _ => {}
    }
}

#[test]
fn claim_deserializes_typed() {
    let c: DesktopCommandClaim = serde_json::from_str(CLAIM).expect("typed claim");
    assert_eq!(c.capability, DesktopCapability::PointerControl);
    assert_eq!(c.risk_tier, DesktopRiskTier::NativeControl);
    assert_eq!(c.status, DesktopCommandStatus::Claimed);
    assert_eq!(c.control_mode, DesktopControlMode::ControlLocked);
    assert_eq!(c.envelope.signature_alg, EnvelopeAlg::Ed25519);
    assert!(c.envelope.signature_present);
    assert_eq!(
        c.envelope.schema,
        "agentprovision.desktop_command_envelope.v1"
    );
    assert!(!c.envelope.key_id.is_empty()); // opaque, registry-resolved
    assert_eq!(c.action.name, DesktopActionKind::PointerClick);
}

#[test]
fn denies_deserialize_typed_with_canonical_codes() {
    let d1: DesktopCommandDenied = serde_json::from_str(DENY_BUNDLE).expect("typed deny (bundle)");
    assert_eq!(d1.code, DesktopDenialCode::TargetNotAllowlisted);
    assert_eq!(d1.status, "denied");
    assert!(!d1.down_channel_available);
    assert_eq!(d1.capability, DesktopCapability::PointerControl);

    let d2: DesktopCommandDenied = serde_json::from_str(DENY_CAP).expect("typed deny (cap)");
    assert_eq!(d2.code, DesktopDenialCode::ApprovalBindingMismatch);
}

#[test]
fn injected_raw_window_title_fails_typed_deserialize() {
    let mut v: Value = serde_json::from_str(CLAIM).unwrap();
    v["target"]["window_title"] = Value::String("super secret window".into());
    let s = serde_json::to_string(&v).unwrap();
    assert!(
        serde_json::from_str::<DesktopCommandClaim>(&s).is_err(),
        "deny_unknown_fields must reject an injected raw window_title"
    );
}

#[test]
fn injected_raw_signature_fails_typed_deserialize() {
    let mut v: Value = serde_json::from_str(CLAIM).unwrap();
    v["envelope"]["signature"] = Value::String("RAWSIG==".into());
    let s = serde_json::to_string(&v).unwrap();
    assert!(
        serde_json::from_str::<DesktopCommandClaim>(&s).is_err(),
        "deny_unknown_fields must reject a raw envelope signature"
    );
}

#[test]
fn fixtures_are_display_safe_recursive() {
    // Catch-all incl. the opaque action.args Value (not covered by typed structs).
    for (name, raw) in [
        ("claim", CLAIM),
        ("deny_bundle", DENY_BUNDLE),
        ("deny_cap", DENY_CAP),
        ("observation_status", OBSERVATION_STATUS),
        ("observation_fetch_denied", OBSERVATION_FETCH_DENIED),
    ] {
        let v: Value = serde_json::from_str(raw).unwrap();
        let mut hits = Vec::new();
        forbidden_hits(&v, "$", &mut hits);
        assert!(hits.is_empty(), "{name} leaks forbidden field(s): {hits:?}");
    }
}

#[test]
fn observation_fixtures_deserialize_typed() {
    // P5.3b planner-safe delivery: status + denial parse through the core types.
    let status: PerceptionArtifactStatus =
        serde_json::from_str(OBSERVATION_STATUS).expect("typed observation status");
    assert_eq!(
        status.redaction_status,
        PerceptionRedactionStatus::PlannerSafe
    );
    assert!(status.redacted_available && status.raw_deleted && !status.expired);

    let denial = PerceptionFetchDenial::from_error_body(OBSERVATION_FETCH_DENIED)
        .expect("typed fetch denial");
    assert_eq!(
        denial.code,
        PerceptionFetchDenialCode::ArtifactNotPlannerSafe
    );
}

#[test]
fn injected_storage_path_fails_observation_status_deserialize() {
    for key in ["storage_path", "redacted_storage_path", "ocr_text"] {
        let mut v: Value = serde_json::from_str(OBSERVATION_STATUS).unwrap();
        v[key] = Value::String("tenant/session/artifact.png".into());
        let s = serde_json::to_string(&v).unwrap();
        assert!(
            serde_json::from_str::<PerceptionArtifactStatus>(&s).is_err(),
            "{key} must be rejected by PerceptionArtifactStatus"
        );
    }
}
