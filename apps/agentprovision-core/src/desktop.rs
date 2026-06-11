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
    BackgroundControl,
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
    BackgroundAppControlDryRun,
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
    NoOp,
    Preempted,
    Expired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopCommandStopStatus {
    Preempted,
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
    BackgroundControlDryRun,
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

/// Operator bootstrap state for the current tenant. This is control-plane
/// configuration only; it is not an approval grant or an actuation command.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopControlEnablement {
    pub desktop_control_enabled: bool,
    pub pointer_control_enabled: bool,
    pub keyboard_control_enabled: bool,
    pub background_control_enabled: bool,
    #[serde(default)]
    pub native_control_target_allowlist: Vec<String>,
    #[serde(default)]
    pub platform_bundle_allowlist: Vec<String>,
    #[serde(default)]
    pub effective_native_control_allowlist: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopControlEnablementUpdate {
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(default)]
    pub background_control_enabled: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopControlAllowlistUpdate {
    pub bundle_ids: Vec<String>,
}

/// Narrow Alpha/Luna user-facing dry-run request. It intentionally omits a raw
/// payload bag so the CLI cannot smuggle pointer/keyboard args or approval data
/// through the working dry-run path.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopBackgroundDryRunTarget {
    pub bundle_id: String,
    #[serde(default = "default_background_dry_run_action")]
    pub action: DesktopActionKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(default)]
    pub window_title_pattern: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(default)]
    pub display_id: Option<i64>,
}

fn default_background_dry_run_action() -> DesktopActionKind {
    DesktopActionKind::BackgroundAppControlDryRun
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopBackgroundDryRunRequest {
    pub session_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(default)]
    pub shell_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(default)]
    pub nonce: Option<String>,
    pub target: DesktopBackgroundDryRunTarget,
}

/// `POST /api/v1/desktop-control/commands/background-dry-run` response.
/// Payload remains opaque because it is the caller's reduced command metadata,
/// not observed screen/clipboard content. Status reporting uses the stricter
/// display-safe summary below.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopCommandResponse {
    pub desktop_command_id: String,
    #[serde(default)]
    pub desktop_event_id: Option<String>,
    #[serde(default)]
    pub session_event_id: Option<String>,
    #[serde(default)]
    pub session_seq_no: Option<i64>,
    pub status: DesktopCommandStatus,
    pub shell_id: String,
    #[serde(default)]
    pub device_id: Option<String>,
    #[serde(default)]
    pub approval_id: Option<String>,
    pub capability: DesktopCapability,
    #[serde(default)]
    pub lease_expires_at: Option<String>,
    #[serde(default)]
    pub payload: Option<serde_json::Value>,
    #[serde(default)]
    pub idempotent: bool,
}

/// Display-safe command summary returned by `desktop_command_status`.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopCommandStatusCommand {
    pub desktop_command_id: String,
    #[serde(default)]
    pub correlation_id: Option<String>,
    pub action: DesktopActionKind,
    #[serde(default)]
    pub tool_name: Option<String>,
    pub shell_id: String,
    #[serde(default)]
    pub device_id: Option<String>,
    #[serde(default)]
    pub approval_id: Option<String>,
    pub source: String,
    pub capability: DesktopCapability,
    pub status: DesktopCommandStatus,
    #[serde(default)]
    pub lease_expires_at: Option<String>,
    #[serde(default)]
    pub claimed_at: Option<String>,
    #[serde(default)]
    pub completed_at: Option<String>,
    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopCommandStatusEvent {
    pub desktop_event_id: String,
    #[serde(default)]
    pub desktop_command_id: Option<String>,
    #[serde(default)]
    pub approval_id: Option<String>,
    #[serde(default)]
    pub correlation_id: Option<String>,
    pub event_type: AuditEventKind,
    pub source: String,
    pub action: DesktopActionKind,
    pub capability: DesktopCapability,
    pub outcome: String,
    #[serde(default)]
    pub reason: Option<String>,
    #[serde(default)]
    pub mode: Option<DesktopControlMode>,
    pub shell_id: String,
    #[serde(default)]
    pub device_id: Option<String>,
    #[serde(default)]
    pub metadata: serde_json::Value,
    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub code: Option<DesktopDenialCode>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopCommandStatusSnapshot {
    pub command: DesktopCommandStatusCommand,
    #[serde(default)]
    pub events: Vec<DesktopCommandStatusEvent>,
    pub terminal: bool,
}

/// `POST /api/v1/desktop-control/commands/stop` request body. This is a
/// safety/preemption command: it revokes active grants and preempts queued or
/// running desktop commands for one owned session and one connected shell.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopCommandStopRequest {
    pub session_id: String,
    pub shell_id: String,
    pub reason: String,
}

/// Display-safe response for a desktop Stop/preempt request.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopCommandStopResponse {
    pub status: DesktopCommandStopStatus,
    pub preempted_count: u64,
    #[serde(default)]
    pub desktop_event_ids: Vec<String>,
}

// ── P5.3b planner-safe observation delivery (`alpha desktop observe`) ─────

/// Perception artifact redaction state. Unknown values fail closed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PerceptionRedactionStatus {
    NotPlannerSafe,
    Redacting,
    PlannerSafe,
}

/// Observation action an Alpha caller may request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopObserveAction {
    CaptureScreenshot,
    GetActiveApp,
    ReadClipboard,
}

/// Observation request acknowledgements are denial-only in P5.3b: they are
/// display-safe audit envelopes and never carry observed content.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopObservationRequestStatus {
    Denied,
}

/// Display-safe denial codes for planner-safe artifact delivery. Mirrors
/// `PerceptionFetchDenialCode` in
/// `apps/api/app/services/perception_delivery.py` — an unknown code fails to
/// deserialize (fail-closed).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PerceptionFetchDenialCode {
    DesktopControlDisabled,
    ArtifactNotFound,
    ArtifactExpired,
    ArtifactNotPlannerSafe,
    ArtifactRawNotDeleted,
    ArtifactBytesUnavailable,
    ArtifactIntegrityMismatch,
}

/// Structured delivery denial (`{"detail": {"code": ..., "reason": ...}}`).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PerceptionFetchDenial {
    pub code: PerceptionFetchDenialCode,
    pub reason: String,
}

impl PerceptionFetchDenial {
    /// Parse a FastAPI error body into a typed denial, if it is one. Returns
    /// `None` for any other error shape (the caller falls back to the generic
    /// API error path). Unknown codes fail closed to `None`.
    pub fn from_error_body(body: &str) -> Option<Self> {
        #[derive(Deserialize)]
        struct Envelope {
            detail: PerceptionFetchDenial,
        }
        serde_json::from_str::<Envelope>(body)
            .ok()
            .map(|e| e.detail)
    }
}

/// `POST /api/v1/desktop-control/observations/request` body
/// (`alpha desktop observe request`).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopObservationRequestBody {
    pub session_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(default)]
    pub shell_id: Option<String>,
    pub action: DesktopObserveAction,
}

/// Acknowledgement for an observation request — a display-safe audit
/// envelope, never observed content. `deny_unknown_fields` rejects a raw
/// `screenshot` / `clipboard_text` / `ocr_text` field outright.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopObservationRequestAck {
    pub status: DesktopObservationRequestStatus,
    pub desktop_event_id: String,
    #[serde(default)]
    pub session_event_id: Option<String>,
    #[serde(default)]
    pub session_seq_no: Option<i64>,
    pub shell_id: String,
    pub action: DesktopObserveAction,
    pub capability: DesktopCapability,
    #[serde(default)]
    pub reason: Option<String>,
    pub down_channel_available: bool,
}

/// Display-safe perception artifact status (`alpha desktop observe status`).
/// Byte-free by construction: `deny_unknown_fields` rejects `storage_path`,
/// `redacted_storage_path`, `ocr_text`, `window_title`, or any content field.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PerceptionArtifactStatus {
    pub artifact_id: String,
    pub session_id: String,
    pub shell_id: String,
    pub artifact_type: String,
    pub redaction_status: PerceptionRedactionStatus,
    pub size_bytes: u64,
    pub sha256: String,
    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub expires_at: Option<String>,
    pub expired: bool,
    pub raw_deleted: bool,
    pub redacted_available: bool,
    #[serde(default)]
    pub source_window_bundle_id: Option<String>,
    #[serde(default)]
    pub redaction_verdict: Option<String>,
    #[serde(default)]
    pub redaction_reasons: Vec<String>,
}

// ── P5.4b pending desktop approval requests (`alpha desktop grant request|status`) ──

/// The four native-control actions an agent may request approval for. Observe /
/// dry-run need no grant, so they are not requestable. Unknown values fail closed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopRequestableAction {
    PointerMove,
    PointerClick,
    KeyboardType,
    KeyboardKeyChord,
}

/// Lifecycle of a pending desktop approval request. Unknown values fail closed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopGrantRequestStatus {
    Pending,
    Approved,
    Denied,
    Expired,
    Cancelled,
}

/// Display-safe denial codes for the grant-request surface. Mirrors
/// `DesktopGrantRequestDenialCode` in `apps/api/app/services/desktop_act.py` — an
/// unknown code fails to deserialize (fail-closed).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopGrantRequestDenialCode {
    DesktopControlDisabled,
    ActionNotRequestable,
    InvalidTargetBundle,
    RequestNotFound,
}

/// Structured grant-request denial (`{"detail": {"code": ..., "reason": ...}}`).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopGrantRequestDenial {
    pub code: DesktopGrantRequestDenialCode,
    pub reason: String,
}

impl DesktopGrantRequestDenial {
    /// Parse a FastAPI error body into a typed denial, if it is one. Returns
    /// `None` for any other error shape (unknown codes fail closed to `None`).
    pub fn from_error_body(body: &str) -> Option<Self> {
        #[derive(Deserialize)]
        struct Envelope {
            detail: DesktopGrantRequestDenial,
        }
        serde_json::from_str::<Envelope>(body)
            .ok()
            .map(|e| e.detail)
    }
}

/// `POST /api/v1/desktop-control/grants/request` body
/// (`alpha desktop grant request`). Reduced metadata only — no payload bag.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopGrantRequestBody {
    pub session_id: String,
    pub action: DesktopRequestableAction,
    pub target_bundle_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(default)]
    pub shell_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(default)]
    pub reason: Option<String>,
}

/// Display-safe pending-approval-request projection. `deny_unknown_fields`
/// rejects any raw payload / screenshot / ocr / window-title field outright.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopGrantRequest {
    pub request_id: String,
    pub session_id: String,
    pub shell_id: String,
    pub action: DesktopRequestableAction,
    pub capability: DesktopCapability,
    pub status: DesktopGrantRequestStatus,
    #[serde(default)]
    pub target_bundle_id: Option<String>,
    #[serde(default)]
    pub reason: Option<String>,
    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub expires_at: Option<String>,
    /// Whether a human has minted a grant for this request yet (P5.5). Never the
    /// grant payload — just presence.
    pub grant_present: bool,
    #[serde(default)]
    pub decided_at: Option<String>,
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
    fn background_dry_run_contract_values_roundtrip() {
        assert_eq!(
            serde_json::to_value(DesktopActionKind::BackgroundAppControlDryRun).unwrap(),
            serde_json::json!("background_app_control_dry_run")
        );
        assert_eq!(
            serde_json::to_value(DesktopCapability::BackgroundControl).unwrap(),
            serde_json::json!("background_control")
        );
        assert_eq!(
            serde_json::to_value(DesktopCommandStatus::NoOp).unwrap(),
            serde_json::json!("no_op")
        );
    }

    #[test]
    fn command_status_rejects_raw_payload_fields() {
        let mut status = serde_json::json!({
            "command": {
                "desktop_command_id": "99999999-9999-9999-9999-999999999999",
                "correlation_id": "77777777-7777-7777-7777-777777777777",
                "action": "background_app_control_dry_run",
                "tool_name": "desktop_background_app_control_dry_run",
                "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
                "device_id": "88888888-8888-8888-8888-888888888888",
                "approval_id": null,
                "source": "mcp",
                "capability": "background_control",
                "status": "no_op",
                "lease_expires_at": null,
                "claimed_at": "2026-06-11T13:00:00+00:00",
                "completed_at": "2026-06-11T13:00:00+00:00",
                "created_at": "2026-06-11T12:59:59+00:00",
                "updated_at": "2026-06-11T13:00:00+00:00"
            },
            "events": [{
                "desktop_event_id": "66666666-6666-6666-6666-666666666666",
                "desktop_command_id": "99999999-9999-9999-9999-999999999999",
                "approval_id": null,
                "correlation_id": "77777777-7777-7777-7777-777777777777",
                "event_type": "desktop_command_completed",
                "source": "api",
                "action": "background_app_control_dry_run",
                "capability": "background_control",
                "outcome": "no_op",
                "reason": null,
                "mode": "background_control_dry_run",
                "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
                "device_id": "88888888-8888-8888-8888-888888888888",
                "metadata": {"dry_run": true, "native_envelope": false},
                "created_at": "2026-06-11T13:00:00+00:00"
            }],
            "terminal": true
        });
        serde_json::from_value::<DesktopCommandStatusSnapshot>(status.clone()).unwrap();
        status["command"]["payload"] = serde_json::json!({"args": {"text": "SECRET"}});
        assert!(serde_json::from_value::<DesktopCommandStatusSnapshot>(status).is_err());
    }

    #[test]
    fn command_stop_response_is_display_safe_and_closed() {
        let mut response = serde_json::json!({
            "status": "preempted",
            "preempted_count": 2,
            "desktop_event_ids": [
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
            ]
        });
        let decoded: DesktopCommandStopResponse =
            serde_json::from_value(response.clone()).expect("stop response decode");
        assert_eq!(decoded.status, DesktopCommandStopStatus::Preempted);
        assert_eq!(decoded.preempted_count, 2);

        response["payload"] = serde_json::json!({"args": {"text": "SECRET"}});
        assert!(serde_json::from_value::<DesktopCommandStopResponse>(response).is_err());
    }

    #[test]
    fn unknown_denial_code_fails_closed() {
        let r: Result<DesktopDenialCode, _> =
            serde_json::from_value(serde_json::json!("totally_made_up_code"));
        assert!(r.is_err(), "unknown denial code must fail to deserialize");
    }

    fn artifact_status_json() -> serde_json::Value {
        serde_json::json!({
            "artifact_id": "77777777-7777-7777-7777-777777777777",
            "session_id": "33333333-3333-3333-3333-333333333333",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "artifact_type": "screenshot",
            "redaction_status": "planner_safe",
            "size_bytes": 1024,
            "sha256": "ab".repeat(32),
            "created_at": "2026-06-11T12:00:00+00:00",
            "expires_at": "2026-06-11T12:15:00+00:00",
            "expired": false,
            "raw_deleted": true,
            "redacted_available": true,
            "source_window_bundle_id": "com.apple.TextEdit",
            "redaction_verdict": "planner_safe",
            "redaction_reasons": []
        })
    }

    #[test]
    fn perception_artifact_status_roundtrips() {
        let status: PerceptionArtifactStatus =
            serde_json::from_value(artifact_status_json()).expect("status decode");
        assert_eq!(
            status.redaction_status,
            PerceptionRedactionStatus::PlannerSafe
        );
        assert!(status.redacted_available);
        assert!(status.raw_deleted);
    }

    #[test]
    fn perception_artifact_status_rejects_path_and_content_fields() {
        // The status is byte-free/path-free by construction: a server (or MITM)
        // response smuggling a path or raw content field must fail to decode.
        for (key, value) in [
            ("storage_path", serde_json::json!("t/s/a.png")),
            (
                "redacted_storage_path",
                serde_json::json!("t/s/a.redacted.png"),
            ),
            ("ocr_text", serde_json::json!("SECRET")),
            ("window_title", serde_json::json!("SECRET TITLE")),
            ("content_base64", serde_json::json!("aGVsbG8=")),
        ] {
            let mut status = artifact_status_json();
            status[key] = value;
            assert!(
                serde_json::from_value::<PerceptionArtifactStatus>(status).is_err(),
                "{key} must be rejected by PerceptionArtifactStatus"
            );
        }
    }

    #[test]
    fn unknown_redaction_status_fails_closed() {
        let mut status = artifact_status_json();
        status["redaction_status"] = serde_json::json!("totally_new_state");
        assert!(serde_json::from_value::<PerceptionArtifactStatus>(status).is_err());
    }

    #[test]
    fn fetch_denial_codes_roundtrip_canonical_strings() {
        for s in [
            "desktop_control_disabled",
            "artifact_not_found",
            "artifact_expired",
            "artifact_not_planner_safe",
            "artifact_raw_not_deleted",
            "artifact_bytes_unavailable",
            "artifact_integrity_mismatch",
        ] {
            let v: PerceptionFetchDenialCode =
                serde_json::from_value(serde_json::Value::String(s.into())).expect(s);
            assert_eq!(serde_json::to_value(v).unwrap(), serde_json::json!(s));
        }
    }

    fn grant_request_json() -> serde_json::Value {
        serde_json::json!({
            "request_id": "55555555-5555-5555-5555-555555555555",
            "session_id": "33333333-3333-3333-3333-333333333333",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "action": "keyboard_type",
            "capability": "keyboard_control",
            "status": "pending",
            "target_bundle_id": "net.whatsapp.WhatsApp",
            "reason": "send a message",
            "created_at": "2026-06-11T12:00:00+00:00",
            "expires_at": "2026-06-11T12:05:00+00:00",
            "grant_present": false,
            "decided_at": null
        })
    }

    #[test]
    fn grant_request_roundtrips_and_is_pending() {
        let req: DesktopGrantRequest =
            serde_json::from_value(grant_request_json()).expect("grant request decode");
        assert_eq!(req.status, DesktopGrantRequestStatus::Pending);
        assert_eq!(req.action, DesktopRequestableAction::KeyboardType);
        assert_eq!(req.capability, DesktopCapability::KeyboardControl);
        assert!(!req.grant_present);
    }

    #[test]
    fn grant_request_rejects_payload_and_content_fields() {
        // The request projection is reduced/display-safe: a server (or MITM)
        // response smuggling a payload bag or raw content must fail to decode.
        for (key, value) in [
            ("payload", serde_json::json!({"args": {"text": "SECRET"}})),
            ("text", serde_json::json!("SECRET")),
            ("screenshot", serde_json::json!("RAW")),
            ("window_title", serde_json::json!("SECRET TITLE")),
        ] {
            let mut req = grant_request_json();
            req[key] = value;
            assert!(
                serde_json::from_value::<DesktopGrantRequest>(req).is_err(),
                "{key} must be rejected by DesktopGrantRequest"
            );
        }
    }

    #[test]
    fn grant_request_unknown_status_and_action_fail_closed() {
        let mut bad_status = grant_request_json();
        bad_status["status"] = serde_json::json!("escalated");
        assert!(serde_json::from_value::<DesktopGrantRequest>(bad_status).is_err());

        // Observe/dry-run actions are NOT requestable — they fail the enum.
        for action in ["capture_screenshot", "background_app_control_dry_run"] {
            let mut bad_action = grant_request_json();
            bad_action["action"] = serde_json::json!(action);
            assert!(
                serde_json::from_value::<DesktopGrantRequest>(bad_action).is_err(),
                "{action} must not be a requestable action"
            );
        }
    }

    #[test]
    fn grant_request_body_serializes_requestable_actions_only() {
        let body = DesktopGrantRequestBody {
            session_id: "33333333-3333-3333-3333-333333333333".into(),
            action: DesktopRequestableAction::PointerClick,
            target_bundle_id: "net.whatsapp.WhatsApp".into(),
            shell_id: None,
            reason: None,
        };
        let v = serde_json::to_value(&body).unwrap();
        assert_eq!(v["action"], serde_json::json!("pointer_click"));
        // omitted optional fields are not serialized
        assert!(v.get("shell_id").is_none());
        assert!(v.get("reason").is_none());
    }

    #[test]
    fn grant_request_denial_codes_roundtrip() {
        for s in [
            "desktop_control_disabled",
            "action_not_requestable",
            "invalid_target_bundle",
            "request_not_found",
        ] {
            let v: DesktopGrantRequestDenialCode =
                serde_json::from_value(serde_json::Value::String(s.into())).expect(s);
            assert_eq!(serde_json::to_value(v).unwrap(), serde_json::json!(s));
        }
    }

    #[test]
    fn fetch_denial_parses_from_error_body_and_fails_closed_on_unknown() {
        let denial = PerceptionFetchDenial::from_error_body(
            r#"{"detail": {"code": "artifact_expired", "reason": "perception artifact has expired"}}"#,
        )
        .expect("typed denial");
        assert_eq!(denial.code, PerceptionFetchDenialCode::ArtifactExpired);

        // unknown code / non-denial error shapes → None (fail closed)
        assert!(PerceptionFetchDenial::from_error_body(
            r#"{"detail": {"code": "made_up", "reason": "x"}}"#
        )
        .is_none());
        assert!(
            PerceptionFetchDenial::from_error_body(r#"{"detail": "Session not found"}"#).is_none()
        );
    }

    #[test]
    fn observation_request_ack_rejects_raw_content() {
        let ack = serde_json::json!({
            "status": "denied",
            "desktop_event_id": "66666666-6666-6666-6666-666666666666",
            "session_event_id": null,
            "session_seq_no": null,
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "action": "capture_screenshot",
            "capability": "screenshot",
            "reason": "desktop observation down-channel unavailable; capture_screenshot request denied",
            "down_channel_available": false
        });
        let decoded: DesktopObservationRequestAck =
            serde_json::from_value(ack.clone()).expect("ack decode");
        assert_eq!(decoded.status, DesktopObservationRequestStatus::Denied);
        for raw in ["screenshot", "clipboard_text", "ocr_text"] {
            let mut bad = ack.clone();
            bad[raw] = serde_json::json!("SECRET");
            assert!(
                serde_json::from_value::<DesktopObservationRequestAck>(bad).is_err(),
                "{raw} must be rejected by DesktopObservationRequestAck"
            );
        }
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
