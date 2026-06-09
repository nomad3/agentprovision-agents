//! PR-D: typed desktop-control contract mirror (lane B, core).
//!
//! Strongly-typed, fail-closed Rust mirror of the API-owned desktop-control
//! contract (canonical source: `apps/api/app/services/desktop_control_service.py`
//! + `desktop_control_codes.py`; golden fixtures in
//! `docs/contracts/desktop-control/`). The CLI and Luna's kernel adapter consume
//! these types instead of hand-rolling their own.
//!
//! Fail-closed deserialization:
//! * Every display-safe / observed payload struct is `#[serde(deny_unknown_fields)]`,
//!   so a raw `screenshot` / `clipboard_text` / `ocr_text` / `window_title` /
//!   raw `signature` field FAILS to deserialize — it can never surface through a
//!   typed value.
//! * Enums reject unknown string values (serde's default), so an unknown
//!   capability / action / status / denial code fails closed.
//!
//! Scope: pure data only. Nothing here enables actuation, posts CGEvent/AX
//! input, or flips a capability flag. `key_id` is an opaque string (registry-
//! resolved), never a typed constant.

use serde::{Deserialize, Serialize};

// ── enums (mirror the canonical string values) ───────────────────────────

/// Stable, display-safe denial/error codes. Byte-identical to the PR-C
/// `DesktopDenialCode` (Python) and the Tauri `DenialCode` (Rust). An unknown
/// code string fails to deserialize (fail-closed).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopDenialCode {
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopCapability {
    Screenshot,
    ActiveApp,
    ClipboardRead,
    PointerControl,
    KeyboardControl,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopActionKind {
    CaptureScreenshot,
    GetActiveApp,
    ReadClipboard,
    PointerMove,
    PointerClick,
    KeyboardType,
    KeyboardKeyChord,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopCommandStatus {
    Pending,
    Claimed,
    Running,
    Succeeded,
    Failed,
    Denied,
    Preempted,
    Expired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopRiskTier {
    Observe,
    NativeControl,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopControlMode {
    ControlLocked,
    Observe,
    Stopped,
}

/// Envelope signature algorithm. Values are NOT snake_case, so renamed explicitly.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EnvelopeAlg {
    #[serde(rename = "HMAC-SHA256")]
    HmacSha256,
    #[serde(rename = "Ed25519")]
    Ed25519,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResultKind {
    Binary,
    String,
    Json,
    Error,
    Unsupported,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResultField {
    App,
    TitleChars,
    TitlePresent,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuditEventKind {
    DesktopCommandQueued,
    DesktopCommandClaimed,
    DesktopCommandApprovalConsumed,
    DesktopCommandApprovalDenied,
    DesktopCommandCompleted,
    DesktopCommandPreempted,
    DesktopCommandExpired,
    DesktopCommandEnvelopeDenied,
    DesktopObservationDenied,
}

// ── display-safe payload structs (fail-closed) ───────────────────────────

/// Display-safe envelope summary. `deny_unknown_fields` rejects a raw
/// `signature` (Tauri-only) and any other unexpected field.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopCommandEnvelope {
    pub schema: String,
    pub signature_alg: EnvelopeAlg,
    /// Opaque, registry-resolved key id — never a typed constant.
    pub key_id: String,
    pub policy_version: String,
    pub issuer: String,
    pub nonce: String,
    pub seq_no: u64,
    pub issued_at: String,
    pub expires_at: String,
    pub envelope_hash: String,
    pub signature_present: bool,
}

/// Display-safe target summary. `deny_unknown_fields` rejects raw `window_title`
/// / `screenshot` / etc.; only the hashed/reduced variants exist as fields.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopTarget {
    pub bundle_id: String,
    pub app: String,
    pub window_title_hash: String,
    pub title_present: bool,
    pub title_chars: u32,
    pub display_id: i64,
    pub scale_factor: f64,
    pub bounds: Vec<i64>,
    pub screenshot_hash: String,
    pub observed_at: String,
}

/// Agent-requested action. `args` are the agent's own parameters (e.g. pointer
/// x/y) — not observed content — kept opaque per action kind.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopActionRequest {
    pub name: DesktopActionKind,
    pub args: serde_json::Value,
}

/// Display-safe observation result. `deny_unknown_fields` rejects raw
/// screenshot/clipboard/OCR content; only the reduced fields exist.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopObservationResult {
    pub result_kind: ResultKind,
    #[serde(default)]
    pub result_fields: Vec<ResultField>,
    #[serde(default)]
    pub result_size_bytes: u64,
    #[serde(default)]
    pub result_size_chars: u64,
}

// ── top-level contract artifacts ─────────────────────────────────────────

/// A claimed native-control command (contract skeleton — typing only; native
/// actuation stays disabled). `deny_unknown_fields` + nested display-safe structs
/// make raw content unrepresentable.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopCommandClaim {
    pub contract: String,
    pub kind: String,
    #[serde(rename = "_note", default)]
    pub note: Option<String>,
    pub desktop_command_id: String,
    pub correlation_id: String,
    pub tenant_id: String,
    #[serde(default)]
    pub user_id: Option<String>,
    pub session_id: String,
    pub shell_id: String,
    #[serde(default)]
    pub device_id: Option<String>,
    pub source: String,
    pub capability: DesktopCapability,
    pub risk_tier: DesktopRiskTier,
    pub status: DesktopCommandStatus,
    pub control_mode: DesktopControlMode,
    #[serde(default)]
    pub approval_id: Option<String>,
    pub approval_risk_tier: DesktopRiskTier,
    pub approval_remaining_actions: u32,
    pub lease_expires_at: String,
    pub created_at: String,
    pub updated_at: String,
    pub envelope: DesktopCommandEnvelope,
    pub target: DesktopTarget,
    pub action: DesktopActionRequest,
}

/// A denial result. `code` is a typed `DesktopDenialCode`, so an unknown code
/// fails to deserialize. `deny_unknown_fields` rejects unexpected fields.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopCommandDenied {
    pub contract: String,
    pub kind: String,
    #[serde(rename = "_note", default)]
    pub note: Option<String>,
    pub status: String,
    pub event_type: AuditEventKind,
    pub action: DesktopActionKind,
    pub capability: DesktopCapability,
    pub risk_tier: DesktopRiskTier,
    pub code: DesktopDenialCode,
    pub reason: String,
    pub down_channel_available: bool,
    pub desktop_command_id: String,
    pub correlation_id: String,
    pub session_id: String,
    pub shell_id: String,
    pub created_at: String,
}

/// One check in a desktop-control preflight result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesktopPreflightCheck {
    pub name: String,
    pub ok: bool,
    #[serde(default)]
    pub detail: String,
}

/// Result of `alpha desktop preflight run` — the API's
/// `run_desktop_preflight()` projection: desktop-control envelope signing
/// config validation. Control-plane data only; carries no key material.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesktopPreflight {
    pub ok: bool,
    pub algorithm: String,
    #[serde(default)]
    pub checks: Vec<DesktopPreflightCheck>,
    #[serde(default)]
    pub error: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn denial_code_roundtrips_canonical_strings() {
        // A representative spread of the PR-C string values must deserialize.
        for s in [
            "target_not_allowlisted",
            "approval_binding_mismatch",
            "native_control_tier_disabled",
            "envelope_key_registry_invalid",
            "pending_ttl_expired",
            "unspecified",
        ] {
            let v: DesktopDenialCode =
                serde_json::from_value(serde_json::Value::String(s.into())).expect(s);
            assert_eq!(serde_json::to_value(v).unwrap(), serde_json::json!(s));
        }
    }

    #[test]
    fn unknown_denial_code_fails_closed() {
        let r: Result<DesktopDenialCode, _> =
            serde_json::from_value(serde_json::json!("totally_made_up_code"));
        assert!(r.is_err(), "unknown denial code must fail to deserialize");
    }

    #[test]
    fn raw_content_cannot_deserialize_into_display_safe_structs() {
        // Raw window title into the target → rejected by deny_unknown_fields.
        let target = serde_json::json!({
            "bundle_id": "x", "app": "X", "window_title_hash": "sha256:0",
            "title_present": true, "title_chars": 3, "display_id": 1,
            "scale_factor": 2.0, "bounds": [0,0,1,1], "screenshot_hash": "sha256:0",
            "observed_at": "t", "window_title": "SECRET TITLE"
        });
        assert!(serde_json::from_value::<DesktopTarget>(target).is_err());

        // Raw signature into the envelope → rejected.
        let env = serde_json::json!({
            "schema": "agentprovision.desktop_command_envelope.v1",
            "signature_alg": "Ed25519", "key_id": "k", "policy_version": "v",
            "issuer": "agentprovision-api", "nonce": "n", "seq_no": 1,
            "issued_at": "t", "expires_at": "t", "envelope_hash": "sha256:0",
            "signature_present": true, "signature": "RAWSIG=="
        });
        assert!(serde_json::from_value::<DesktopCommandEnvelope>(env).is_err());

        // Raw clipboard/screenshot into an observation result → rejected.
        for raw in ["clipboard_text", "screenshot", "ocr_text"] {
            let mut obs = serde_json::json!({"result_kind": "json"});
            obs[raw] = serde_json::json!("SECRET");
            assert!(
                serde_json::from_value::<DesktopObservationResult>(obs).is_err(),
                "{raw} must be rejected by the observation result type"
            );
        }
    }
}
