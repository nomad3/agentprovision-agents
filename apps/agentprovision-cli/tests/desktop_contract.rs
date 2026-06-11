//! PR-D desktop-control contract parity — CLI consumes-core-only.
//!
//! The CLI defines NO desktop-control types of its own; it deserializes the
//! shared golden fixtures THROUGH the `agentprovision_core::desktop` types
//! (path dependency). This proves the consumes-core rule and that core's
//! fail-closed `deny_unknown_fields` boundary protects the CLI too.
//!
//! Scope: contract/parity only. No native actuation; no `alpha desktop` command.

use agentprovision_core::desktop::{
    DesktopCommandClaim, DesktopCommandDenied, DesktopDenialCode, DesktopGrantRequest,
    DesktopGrantRequestStatus, PerceptionArtifactStatus, PerceptionFetchDenial,
    PerceptionFetchDenialCode, PerceptionRedactionStatus,
};

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
const GRANT_REQUEST: &str =
    include_str!("../../../docs/contracts/desktop-control/grant_request.pending.json");

#[test]
fn cli_deserializes_fixtures_via_core_types() {
    // Claim + both denials parse through the core types — the CLI owns no schema.
    let _claim: DesktopCommandClaim = serde_json::from_str(CLAIM).expect("core claim type");
    let d1: DesktopCommandDenied = serde_json::from_str(DENY_BUNDLE).expect("core deny type");
    assert_eq!(d1.code, DesktopDenialCode::TargetNotAllowlisted);
    let d2: DesktopCommandDenied = serde_json::from_str(DENY_CAP).expect("core deny type");
    assert_eq!(d2.code, DesktopDenialCode::ApprovalBindingMismatch);
}

#[test]
fn cli_rejects_raw_content_via_core_types() {
    // The core type's deny_unknown_fields protects the CLI: raw screenshot in the
    // target cannot deserialize, so it can never surface in the CLI.
    let mut v: serde_json::Value = serde_json::from_str(CLAIM).unwrap();
    v["target"]["screenshot"] = serde_json::json!("RAW-BYTES");
    let s = serde_json::to_string(&v).unwrap();
    assert!(
        serde_json::from_str::<DesktopCommandClaim>(&s).is_err(),
        "raw screenshot must be rejected by the core display-safe type"
    );
}

#[test]
fn cli_deserializes_observation_fixtures_via_core_types() {
    // P5.3b planner-safe delivery: the status fixture parses through the core
    // type, and the denial fixture parses through the typed denial helper.
    let status: PerceptionArtifactStatus =
        serde_json::from_str(OBSERVATION_STATUS).expect("core observation status type");
    assert_eq!(
        status.redaction_status,
        PerceptionRedactionStatus::PlannerSafe
    );
    assert!(status.redacted_available && status.raw_deleted);

    let denial = PerceptionFetchDenial::from_error_body(OBSERVATION_FETCH_DENIED)
        .expect("typed fetch denial");
    assert_eq!(
        denial.code,
        PerceptionFetchDenialCode::ArtifactNotPlannerSafe
    );
}

#[test]
fn cli_rejects_storage_paths_in_observation_status() {
    // Raw storage paths are not part of the observe contract — a server (or
    // MITM) response that includes one must fail to deserialize.
    for key in ["storage_path", "redacted_storage_path", "ocr_text"] {
        let mut v: serde_json::Value = serde_json::from_str(OBSERVATION_STATUS).unwrap();
        v[key] = serde_json::json!("tenant/session/artifact.png");
        let s = serde_json::to_string(&v).unwrap();
        assert!(
            serde_json::from_str::<PerceptionArtifactStatus>(&s).is_err(),
            "{key} must be rejected by the core observation status type"
        );
    }
}

#[test]
fn cli_deserializes_grant_request_via_core_type() {
    let req: DesktopGrantRequest =
        serde_json::from_str(GRANT_REQUEST).expect("core grant request type");
    assert_eq!(req.status, DesktopGrantRequestStatus::Pending);
    assert!(!req.grant_present);
}
