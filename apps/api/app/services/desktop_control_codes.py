"""Phase 2.75 / PR-C: stable desktop-control denial-code contract.

A *closed* set of stable, display-safe denial/error codes for desktop control,
plus a pure mapping from the canonical human reason strings (the display-safe
output of ``_safe_reason`` / ``_safe_command_reason`` and the Tauri native
boundary) to exactly one code, and the pure decision helpers used by the
Phase 2.75 single-owner / pacing / secure-input / stale-approval gates.

Design rules:

* Codes are lowercase snake_case tokens — never raw screen, app, window, or
  clipboard content. Safe to emit in ``session_events`` and audit metadata.
* ``code_for_reason`` derives the code from the *already display-safe* reason, so
  the code is guaranteed display-safe too and there is exactly one code per
  canonical reason (PR-C exit #1).
* This module is a leaf: it imports nothing from ``desktop_control_service`` to
  avoid an import cycle (the service imports this).
* Nothing here enables actuation, posts CGEvent/AX input, or flips a capability
  flag. These are pure data + pure decisions.

The Tauri side mirrors the same string values in
``apps/luna-client/src-tauri/src/computer_use/denial_codes.rs``. The canonical
typed contract for Alpha CLI/core is owned by lane B (PR-D); this module is the
server-side source of truth those types must match.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


class DesktopDenialCode(str, Enum):
    # Local mode / kill switch
    STOPPED = "stopped"
    OBSERVE_LOCKED = "observe_locked"

    # Native control hard gates (actuation stays closed)
    NATIVE_CONTROL_DISABLED = "native_control_disabled"
    NATIVE_CONTROL_TIER_DISABLED = "native_control_tier_disabled"
    NATIVE_CONTROL_ACTION_UNSUPPORTED = "native_control_action_unsupported"
    PERMISSION_NOT_READY = "permission_not_ready"

    # Observation
    OBSERVATION_PERMISSION_DENIED = "observation_permission_denied"
    OBSERVATION_DENIED = "observation_denied"
    OBSERVATION_FAILED = "observation_failed"
    DOWN_CHANNEL_UNAVAILABLE = "down_channel_unavailable"
    SHELL_CANNOT_OBSERVE = "shell_cannot_observe"

    # Signed command envelope
    ENVELOPE_MISSING = "envelope_missing"
    ENVELOPE_REQUIRED = "envelope_required"
    ENVELOPE_UNSIGNED = "envelope_unsigned"
    ENVELOPE_NONCE_MISSING = "envelope_nonce_missing"
    ENVELOPE_NONCE_MISMATCH = "envelope_nonce_mismatch"
    ENVELOPE_SIGNATURE_INVALID = "envelope_signature_invalid"
    ENVELOPE_PUBLIC_KEY_INVALID = "envelope_public_key_invalid"
    ENVELOPE_KEY_UNKNOWN = "envelope_key_unknown"
    ENVELOPE_KEY_REGISTRY_INVALID = "envelope_key_registry_invalid"
    ENVELOPE_EXPIRED = "envelope_expired"
    ENVELOPE_BINDING_MISMATCH = "envelope_binding_mismatch"
    ENVELOPE_POLICY_UNSUPPORTED = "envelope_policy_unsupported"
    ENVELOPE_REPLAYED = "envelope_replayed"

    # Claim / lease lifecycle
    CLAIM_REQUIRED = "claim_required"
    LEASE_EXPIRED = "lease_expired"
    PENDING_TTL_EXPIRED = "pending_ttl_expired"
    PREEMPTED = "preempted"

    # Approval grants
    APPROVAL_MISSING = "approval_missing"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_REVOKED = "approval_revoked"
    APPROVAL_EXHAUSTED = "approval_exhausted"
    APPROVAL_BINDING_MISMATCH = "approval_binding_mismatch"
    APPROVAL_REPLAY_DENIED = "approval_replay_denied"

    # Phase 2.5 / 2.75 target + actuation gates
    TARGET_NOT_ALLOWLISTED = "target_not_allowlisted"
    ACTIVE_APP_DRIFT = "active_app_drift"
    TARGET_DRIFT = "target_drift"
    SECURE_INPUT_ACTIVE = "secure_input_active"
    ACTUATION_OWNER_CONFLICT = "actuation_owner_conflict"
    RATE_CAPPED = "rate_capped"

    # Generic terminal outcomes (used only when no specific reason applies)
    COMMAND_DENIED = "command_denied"
    COMMAND_FAILED = "command_failed"

    # Catch-all for an unmapped reason. A denial mapping to this is a contract
    # gap to fix, not a normal outcome.
    UNSPECIFIED = "unspecified"


# Ordered (prefix, code) table. Checked most-specific first against the
# whitespace-normalized reason; `startswith` absorbs the `; {action} denied`
# suffixes the runtime appends. Exact tokens (drift/secure-input/etc.) are also
# matched by `startswith` because they carry no suffix.
_REASON_PREFIXES: tuple[tuple[str, DesktopDenialCode], ...] = (
    # stop / lock (stop must win over a trailing "preempted")
    ("desktop control stopped", DesktopDenialCode.STOPPED),
    ("operator stop", DesktopDenialCode.STOPPED),
    ("local stop latched", DesktopDenialCode.STOPPED),
    ("desktop observe locked", DesktopDenialCode.OBSERVE_LOCKED),
    # native control gates
    ("desktop native control tier disabled", DesktopDenialCode.NATIVE_CONTROL_TIER_DISABLED),
    ("desktop native control action unsupported", DesktopDenialCode.NATIVE_CONTROL_ACTION_UNSUPPORTED),
    ("desktop native control disabled", DesktopDenialCode.NATIVE_CONTROL_DISABLED),
    ("desktop permission readiness", DesktopDenialCode.PERMISSION_NOT_READY),
    # observation
    ("desktop observation permission", DesktopDenialCode.OBSERVATION_PERMISSION_DENIED),
    ("desktop observation down-channel unavailable", DesktopDenialCode.DOWN_CHANNEL_UNAVAILABLE),
    ("desktop observation denied", DesktopDenialCode.OBSERVATION_DENIED),
    ("desktop observation failed", DesktopDenialCode.OBSERVATION_FAILED),
    ("desktop shell cannot observe", DesktopDenialCode.SHELL_CANNOT_OBSERVE),
    # envelope (full distinguishing prefixes; no generic "envelope" catch)
    ("desktop command envelope missing", DesktopDenialCode.ENVELOPE_MISSING),
    ("desktop command envelope required", DesktopDenialCode.ENVELOPE_REQUIRED),
    ("desktop command envelope unsigned", DesktopDenialCode.ENVELOPE_UNSIGNED),
    ("desktop command envelope nonce missing", DesktopDenialCode.ENVELOPE_NONCE_MISSING),
    ("desktop command envelope nonce mismatch", DesktopDenialCode.ENVELOPE_NONCE_MISMATCH),
    ("desktop command envelope signature invalid", DesktopDenialCode.ENVELOPE_SIGNATURE_INVALID),
    ("desktop command envelope public key invalid", DesktopDenialCode.ENVELOPE_PUBLIC_KEY_INVALID),
    ("desktop command envelope public key missing", DesktopDenialCode.ENVELOPE_PUBLIC_KEY_INVALID),
    ("desktop command envelope key unknown", DesktopDenialCode.ENVELOPE_KEY_UNKNOWN),
    ("desktop command envelope key registry invalid", DesktopDenialCode.ENVELOPE_KEY_REGISTRY_INVALID),
    ("desktop command envelope expired", DesktopDenialCode.ENVELOPE_EXPIRED),
    ("desktop command envelope binding mismatch", DesktopDenialCode.ENVELOPE_BINDING_MISMATCH),
    ("desktop command envelope policy unsupported", DesktopDenialCode.ENVELOPE_POLICY_UNSUPPORTED),
    ("desktop command envelope replay denied", DesktopDenialCode.ENVELOPE_REPLAYED),
    ("desktop command envelope replayed", DesktopDenialCode.ENVELOPE_REPLAYED),
    # claim / lease
    ("desktop command claim required", DesktopDenialCode.CLAIM_REQUIRED),
    ("desktop command lease expired", DesktopDenialCode.LEASE_EXPIRED),
    ("desktop command pending ttl expired", DesktopDenialCode.PENDING_TTL_EXPIRED),
    ("desktop command preempted", DesktopDenialCode.PREEMPTED),
    # approval grants
    ("desktop command approval grant missing", DesktopDenialCode.APPROVAL_MISSING),
    ("desktop command approval grant expired", DesktopDenialCode.APPROVAL_EXPIRED),
    ("desktop command approval grant revoked", DesktopDenialCode.APPROVAL_REVOKED),
    ("desktop command approval grant exhausted", DesktopDenialCode.APPROVAL_EXHAUSTED),
    ("desktop command approval grant binding mismatch", DesktopDenialCode.APPROVAL_BINDING_MISMATCH),
    ("desktop command approval grant replay denied", DesktopDenialCode.APPROVAL_REPLAY_DENIED),
    # phase 2.5 / 2.75 target + actuation tokens
    ("desktop command target not allowlisted", DesktopDenialCode.TARGET_NOT_ALLOWLISTED),
    ("desktop command target not allow-listed", DesktopDenialCode.TARGET_NOT_ALLOWLISTED),
    ("target_not_allowlisted", DesktopDenialCode.TARGET_NOT_ALLOWLISTED),
    ("active_app_drift", DesktopDenialCode.ACTIVE_APP_DRIFT),
    ("target_drift", DesktopDenialCode.TARGET_DRIFT),
    ("secure_input_active", DesktopDenialCode.SECURE_INPUT_ACTIVE),
    ("actuation_owner_conflict", DesktopDenialCode.ACTUATION_OWNER_CONFLICT),
    ("rate_capped", DesktopDenialCode.RATE_CAPPED),
    # generic terminal outcomes (least specific — keep last)
    ("desktop command denied", DesktopDenialCode.COMMAND_DENIED),
    ("desktop command failed", DesktopDenialCode.COMMAND_FAILED),
)


def code_for_reason(reason: str | None) -> DesktopDenialCode:
    """Map a canonical display-safe reason to exactly one stable code.

    Returns ``UNSPECIFIED`` for an empty or unmapped reason. Never raises.
    """
    if not reason:
        return DesktopDenialCode.UNSPECIFIED
    normalized = " ".join(reason.split()).lower()
    for prefix, code in _REASON_PREFIXES:
        if normalized.startswith(prefix):
            return code
    return DesktopDenialCode.UNSPECIFIED


# --------------------------------------------------------------- pure 2.75 gates


def secure_input_decision(
    secure_input_active: bool, capability: str
) -> DesktopDenialCode | None:
    """Keyboard input is fail-closed while macOS Secure Input is active.

    Secure Input (``IsSecureEventInputEnabled``) is a *process-global* signal,
    not per-field; we deliberately do not claim per-field password detection.
    Pointer actions are unaffected.
    """
    if secure_input_active and capability == "keyboard_control":
        return DesktopDenialCode.SECURE_INPUT_ACTIVE
    return None


def pacing_decision(
    last_action_at_ms: int | None, now_ms: int, min_interval_ms: int
) -> DesktopDenialCode | None:
    """Deny if a native action would fire faster than the minimum interval.

    Stops a large ``max_actions`` budget from firing as a burst. The first
    action (no prior timestamp) is always allowed.
    """
    if last_action_at_ms is None or min_interval_ms <= 0:
        return None
    if now_ms - last_action_at_ms < min_interval_ms:
        return DesktopDenialCode.RATE_CAPPED
    return None


def single_owner_decision(
    current_owner_shell_id: str | None, requester_shell_id: str
) -> DesktopDenialCode | None:
    """Only one shell/device may hold the live actuation lease at a time."""
    if current_owner_shell_id and current_owner_shell_id != requester_shell_id:
        return DesktopDenialCode.ACTUATION_OWNER_CONFLICT
    return None


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def stale_approval_decision(
    status: str,
    expires_at: datetime | None,
    now: datetime,
    remaining_actions: int,
) -> DesktopDenialCode | None:
    """Classify a stale/unusable approval grant, in the same order the service
    uses: revoked, then expired, then exhausted. Returns ``None`` for a usable
    active grant.
    """
    if status == "revoked":
        return DesktopDenialCode.APPROVAL_REVOKED
    expires = _as_aware_utc(expires_at)
    now_aware = _as_aware_utc(now)
    if status == "expired" or expires is None or (now_aware is not None and expires <= now_aware):
        return DesktopDenialCode.APPROVAL_EXPIRED
    if status == "consumed" or int(remaining_actions or 0) <= 0:
        return DesktopDenialCode.APPROVAL_EXHAUSTED
    return None
