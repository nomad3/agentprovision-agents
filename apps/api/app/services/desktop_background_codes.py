"""SP1.5 — Luna secondary-pointer / background-control denial codes + pure gates.

Contract/security layer for the background app-control path
(``docs/plans/2026-06-11-luna-secondary-pointer-background-control.md``). It adds
the §5.3 stable byte-free denial vocabulary for actuation that targets a
**non-frontmost** app, plus the pure security *decisions* SP2+ will call before
any native AX/CGEvent work exists.

Design rules (mirrors the PR-C ``desktop_control_codes`` leaf module):

* Nothing here moves a cursor, posts CGEvent/AX input, resolves a real window, or
  flips a capability flag. Pure data + pure decisions only — fully unit-testable
  with no DB and no native APIs.
* Codes are lowercase snake_case tokens, safe to emit in ``session_events`` and
  audit metadata — never raw screen / app / window / message content.
* This is a leaf: it imports only the canonical PR-C codes (for the two reused
  tokens ``stopped`` / ``secure_input_active``) and nothing from
  ``desktop_control_service`` — no import cycle.
* The new *background* vocabulary is kept in its own enum rather than mutating the
  frozen PR-C ``DesktopDenialCode`` (schema-freeze + same-PR mirror-parity rule).
  The strongly-typed core/Tauri mirror of these new codes is owned by lane B
  (PR-D) and tracked as a follow-up, not reached into from this lane.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.services.desktop_control_codes import DesktopDenialCode


class BackgroundControlDenialCode(str, Enum):
    """The §5.3 byte-free denial codes new to the background-control path.

    ``stopped`` and ``secure_input_active`` are intentionally NOT duplicated here
    — the background path reuses the canonical PR-C codes for those concepts (see
    ``ALLOWED_BACKGROUND_DENIAL_CODES``).
    """

    # target identity beyond PID
    WRONG_BUNDLE = "wrong_bundle"
    STALE_PID = "stale_pid"
    PID_REUSED = "pid_reused"
    MISSING_WINDOW = "missing_window"
    SIGNING_IDENTITY_MISMATCH = "signing_identity_mismatch"
    # window drift / coordinate (points)
    BOUNDS_DRIFT = "bounds_drift"
    DISPLAY_DRIFT = "display_drift"
    TITLE_HASH_DRIFT = "title_hash_drift"
    # lease / ownership / lock
    LEASE_LOST = "lease_lost"
    LOCKED = "locked"
    FLAG_DISABLED = "flag_disabled"
    # primitive / fallback
    FALLBACK_NOT_ALLOWED = "fallback_not_allowed"
    # verification / privacy / overlay
    READBACK_FAILED = "readback_failed"
    RAW_BYTES_BLOCKED = "raw_bytes_blocked"
    OVERLAY_NOT_AUTHORITATIVE = "overlay_not_authoritative"


class BackgroundPrimitiveAction(str, Enum):
    """The bounded primitive actions a signed background envelope resolves to.

    App-level intents (``whatsapp_send_message``) still resolve to exactly one of
    these; each is independently gated (§5).
    """

    AX_SET_VALUE = "ax_set_value"
    AX_PRESS = "ax_press"
    PID_POST_KEY = "pid_post_key"
    PID_POST_CLICK = "pid_post_click"


AX_PRIMITIVES: frozenset[str] = frozenset(
    {BackgroundPrimitiveAction.AX_SET_VALUE.value, BackgroundPrimitiveAction.AX_PRESS.value}
)
PID_PRIMITIVES: frozenset[str] = frozenset(
    {BackgroundPrimitiveAction.PID_POST_KEY.value, BackgroundPrimitiveAction.PID_POST_CLICK.value}
)
# Text-entry primitives are the ones macOS Secure Input must fail closed on.
KEYBOARD_LIKE_PRIMITIVES: frozenset[str] = frozenset(
    {BackgroundPrimitiveAction.AX_SET_VALUE.value, BackgroundPrimitiveAction.PID_POST_KEY.value}
)

# The complete background denial vocabulary = the new §5.3 tokens + the two reused
# canonical PR-C codes. A background deny `code` must be a member of this set.
ALLOWED_BACKGROUND_DENIAL_CODES: frozenset[str] = frozenset(
    {c.value for c in BackgroundControlDenialCode}
    | {DesktopDenialCode.STOPPED.value, DesktopDenialCode.SECURE_INPUT_ACTIVE.value}
)


# ── byte-free event shape (Invariant 10/13; §5.3) ────────────────────────────
# Keys that must NEVER appear at any depth in a background-control event, log, SSE
# frame, audit row, or chat message. Hashed / reduced variants (`*_hash`,
# `*_chars`, `*_present`, `content_hash_match`) are allowed.
#
# DESIGN NOTE (key-only, by intent): this is a structural KEY denylist, not a
# value scanner — a value scanner would false-positive on legitimate hashes and
# category strings. The real guarantee is emitter discipline (events are
# constructed byte-free, with the typed SP2 mirror enforcing the shape); this set
# is a backstop for the common "raw content under an obvious key" mistake. Raw
# content smuggled as a VALUE under a benign key is intentionally NOT caught here.
# Matching is case-insensitive (see ``byte_free_violations``) so casing variants
# like ``AXValue`` / ``Window_Title`` cannot slip past the lowercase tokens.
FORBIDDEN_EVENT_FIELDS: frozenset[str] = frozenset(
    {
        # raw window / screen / clipboard capture
        "window_title", "raw_title", "title",
        "screenshot", "screenshot_b64", "screenshot_bytes",
        "clipboard", "clipboard_text", "ocr_text", "ax_tree", "page_text",
        # secrets
        "signature", "private_key",
        # raw message / contact / row content (WhatsApp-specific privacy, §8)
        "message_text", "message_body", "body_text", "message_preview",
        "contact_name", "sender_name", "display_name", "chat_title", "chat_name",
        "group_subject", "row_text", "visible_text", "last_message",
        "quoted_message", "caption", "preview", "snippet", "notification_text",
        # raw identifiers that double as contact PII
        "phone_number", "msisdn", "jid",
        # raw AX element content — both snake_case and the macOS camelCase forms
        # (AXValue/AXTitle/AXDescription/AXLabel) which have no underscore to
        # lowercase into the snake tokens.
        "ax_label", "ax_value", "ax_title", "ax_description", "accessibility_label",
        "axlabel", "axvalue", "axtitle", "axdescription",
        "element_text", "element_label", "label", "placeholder", "tooltip",
        # raw text/value carriers
        "text", "value", "selected_text", "input_text", "transcript",
    }
)
# Pre-lowered for case-insensitive membership (AXValue, Window_Title, … all caught).
_FORBIDDEN_LOWER: frozenset[str] = frozenset(k.lower() for k in FORBIDDEN_EVENT_FIELDS)

# ── overlay authority (Invariant 11/12; §9) ──────────────────────────────────
OVERLAY_ALLOWED_INTENTS: frozenset[str] = frozenset(
    {"subscribe", "display", "hud_update", "stop", "stop_request"}
)
OVERLAY_FORBIDDEN_INTENTS: frozenset[str] = frozenset(
    {"resume", "approve", "replay", "mutate", "mutate_envelope",
     "extend", "extend_lease", "unlock", "issue", "generate"}
)


@dataclass(frozen=True)
class TargetIdentity:
    """A signed-or-observed target identity. PID alone is never identity (Inv. 6)."""

    bundle_id: str
    pid: int
    window_id: str | None
    signing_id: str | None  # team-id / signing-identity hash, or None if unavailable
    launch_token: str | None  # audit-token / proc-launch identity hash, or None


# ── §5.3 canonical reasons → code (display-safe, one code per reason) ─────────
# (canonical_reason, code_value). The runtime may append a "; {action} denied"
# suffix; matching is prefix-based so the suffix is absorbed. The bare token also
# maps to itself (some boundaries emit the token directly).
CANONICAL_BACKGROUND_REASONS: tuple[tuple[str, str], ...] = (
    ("desktop background control wrong bundle", BackgroundControlDenialCode.WRONG_BUNDLE.value),
    ("desktop background control stale pid", BackgroundControlDenialCode.STALE_PID.value),
    ("desktop background control pid reused", BackgroundControlDenialCode.PID_REUSED.value),
    ("desktop background control missing window", BackgroundControlDenialCode.MISSING_WINDOW.value),
    ("desktop background control signing identity mismatch", BackgroundControlDenialCode.SIGNING_IDENTITY_MISMATCH.value),
    ("desktop background control bounds drift", BackgroundControlDenialCode.BOUNDS_DRIFT.value),
    ("desktop background control display drift", BackgroundControlDenialCode.DISPLAY_DRIFT.value),
    ("desktop background control title hash drift", BackgroundControlDenialCode.TITLE_HASH_DRIFT.value),
    ("desktop background control lease lost", BackgroundControlDenialCode.LEASE_LOST.value),
    ("desktop background control locked", BackgroundControlDenialCode.LOCKED.value),
    ("desktop background control flag disabled", BackgroundControlDenialCode.FLAG_DISABLED.value),
    ("desktop background control fallback not allowed", BackgroundControlDenialCode.FALLBACK_NOT_ALLOWED.value),
    ("desktop background control readback failed", BackgroundControlDenialCode.READBACK_FAILED.value),
    ("desktop background control raw bytes blocked", BackgroundControlDenialCode.RAW_BYTES_BLOCKED.value),
    ("desktop background control overlay not authoritative", BackgroundControlDenialCode.OVERLAY_NOT_AUTHORITATIVE.value),
)

# The two reused PR-C codes also route through the background mapper, so a
# background `stopped` / `secure_input_active` deny reason round-trips here too
# (they are NOT redefined — they keep their canonical PR-C values).
_REUSED_BACKGROUND_REASONS: tuple[tuple[str, str], ...] = (
    ("desktop background control stopped", DesktopDenialCode.STOPPED.value),
    ("desktop background control secure input", DesktopDenialCode.SECURE_INPUT_ACTIVE.value),
)

# prefix table: each canonical reason AND its bare token map to the same code.
_BACKGROUND_REASON_PREFIXES: tuple[tuple[str, str], ...] = tuple(
    pair
    for reason, code in (*CANONICAL_BACKGROUND_REASONS, *_REUSED_BACKGROUND_REASONS)
    for pair in ((reason, code), (code, code))
)


def background_code_for_reason(reason: str | None) -> str | None:
    """Map a canonical display-safe background reason to its stable code value.

    Returns ``None`` for an empty or unmapped reason (an unmapped background
    reason is a contract gap to fill, never a silent fallthrough). Never raises.
    """
    if not reason:
        return None
    normalized = " ".join(str(reason).split()).lower()
    for prefix, code in _BACKGROUND_REASON_PREFIXES:
        if normalized.startswith(prefix):
            return code
    return None


# ── pure decisions (each returns a code value string or None) ─────────────────


def target_identity_decision(
    signed: TargetIdentity,
    observed: TargetIdentity | None,
    *,
    app_alive: bool,
    signing_required: bool,
) -> str | None:
    """Bind an action to the full signed target identity, not the PID (Inv. 6).

    Order: app-alive → pid-relaunch → bundle → window → signing → pid-reuse. The
    allow path requires a matching window id AND a present, matching proc/launch
    identity (so PID alone can never authorize).
    """
    if not app_alive or observed is None:
        return BackgroundControlDenialCode.STALE_PID.value
    if observed.pid != signed.pid:
        # the signed pid no longer hosts the target — app relaunched under a new pid
        return BackgroundControlDenialCode.STALE_PID.value
    # Every identity proof is treated as *missing* when falsy ("" is morally
    # absent), not just when None — an empty/placeholder proof can never authorize.
    if not signed.bundle_id or not observed.bundle_id or observed.bundle_id != signed.bundle_id:
        return BackgroundControlDenialCode.WRONG_BUNDLE.value
    if not signed.window_id or not observed.window_id or observed.window_id != signed.window_id:
        return BackgroundControlDenialCode.MISSING_WINDOW.value
    if signing_required and (not signed.signing_id or observed.signing_id != signed.signing_id):
        return BackgroundControlDenialCode.SIGNING_IDENTITY_MISMATCH.value
    # same pid number: require a present, matching proc-launch identity, else reuse.
    if not signed.launch_token or not observed.launch_token or observed.launch_token != signed.launch_token:
        return BackgroundControlDenialCode.PID_REUSED.value
    return None


def _is_quad_int_points(bounds) -> bool:
    """True iff ``bounds`` is exactly four integer POINTS (rejects bool/float/short)."""
    return (
        isinstance(bounds, (list, tuple))
        and len(bounds) == 4
        and all(isinstance(v, int) and not isinstance(v, bool) for v in bounds)
    )


def points_drift(signed_bounds: list[int], observed_bounds: list[int]) -> int:
    """Max absolute per-component delta, in POINTS (Inv. 4; §5.2).

    Callers must pass two equal-length, validated point quads (see
    ``_is_quad_int_points`` / ``window_drift_decision``).
    """
    return max(abs(int(a) - int(b)) for a, b in zip(signed_bounds, observed_bounds))


def window_drift_decision(
    *,
    signed_bounds: list[int],
    observed_bounds: list[int],
    tolerance_points: int,
    signed_display_id: int,
    observed_display_id: int,
    signed_title_hash: str | None = None,
    observed_title_hash: str | None = None,
) -> str | None:
    """Deny on malformed bounds, display change, points bounds drift, or title drift.

    Bounds shape is validated FIRST and fails closed — a truncated / non-integer
    bounds array can never pass the drift gate via zip-truncation. Title is only
    checked when a title binding was signed (§11).
    """
    if not _is_quad_int_points(signed_bounds) or not _is_quad_int_points(observed_bounds):
        return BackgroundControlDenialCode.BOUNDS_DRIFT.value
    if signed_display_id != observed_display_id:
        return BackgroundControlDenialCode.DISPLAY_DRIFT.value
    if points_drift(signed_bounds, observed_bounds) > tolerance_points:
        return BackgroundControlDenialCode.BOUNDS_DRIFT.value
    if signed_title_hash is not None and observed_title_hash != signed_title_hash:
        return BackgroundControlDenialCode.TITLE_HASH_DRIFT.value
    return None


def window_relative_points_ok(point: dict, window_bounds: list[int]) -> bool:
    """True iff ``point`` is integer, window-relative, and inside the window.

    Rejects floats (no Retina pixel/point ambiguity) and out-of-window coords.
    ``window_bounds`` is ``[x, y, width, height]`` in points.
    """
    if not _is_quad_int_points(window_bounds):
        return False
    x, y = point.get("x"), point.get("y")
    if isinstance(x, bool) or isinstance(y, bool):
        return False
    if not isinstance(x, int) or not isinstance(y, int):
        return False
    width, height = window_bounds[2], window_bounds[3]
    return 0 <= x <= width and 0 <= y <= height


def lease_decision(
    *,
    lease_present: bool,
    lease_expired: bool,
    lease_replayed: bool,
    lease_consumed: bool,
    command_id_match: bool,
    app_alive: bool,
    stop_latched: bool,
    lock_latched: bool,
    tenant_flag_enabled: bool,
    capability_flag_enabled: bool,
) -> str | None:
    """Re-check lease/ownership immediately before a native action (§5.1, Inv. 7/8).

    Order: Stop (kill switch wins) → Lock → flags → lease integrity / app-alive.
    """
    if stop_latched:
        return DesktopDenialCode.STOPPED.value
    if lock_latched:
        return BackgroundControlDenialCode.LOCKED.value
    if not tenant_flag_enabled or not capability_flag_enabled:
        return BackgroundControlDenialCode.FLAG_DISABLED.value
    if (
        not lease_present
        or lease_expired
        or lease_replayed
        or lease_consumed
        or not command_id_match
        or not app_alive
    ):
        return BackgroundControlDenialCode.LEASE_LOST.value
    return None


def primitive_fallback_decision(
    primitive: str,
    *,
    ax_set_value_allowed: bool,
    ax_press_allowed: bool,
    pid_post_key_allowed: bool,
    pid_post_click_allowed: bool,
) -> str | None:
    """Each primitive is independently gated; AX approval never authorizes PID (§5).

    A disallowed AX primitive denies as ``flag_disabled``; a disallowed PID
    primitive denies as ``fallback_not_allowed`` (PID fallback does not inherit AX
    approval). An unknown primitive fails closed as ``fallback_not_allowed``.
    """
    gate: dict[str, tuple[bool, str]] = {
        BackgroundPrimitiveAction.AX_SET_VALUE.value: (ax_set_value_allowed, BackgroundControlDenialCode.FLAG_DISABLED.value),
        BackgroundPrimitiveAction.AX_PRESS.value: (ax_press_allowed, BackgroundControlDenialCode.FLAG_DISABLED.value),
        BackgroundPrimitiveAction.PID_POST_KEY.value: (pid_post_key_allowed, BackgroundControlDenialCode.FALLBACK_NOT_ALLOWED.value),
        BackgroundPrimitiveAction.PID_POST_CLICK.value: (pid_post_click_allowed, BackgroundControlDenialCode.FALLBACK_NOT_ALLOWED.value),
    }
    allowed, deny_code = gate.get(primitive, (False, BackgroundControlDenialCode.FALLBACK_NOT_ALLOWED.value))
    return None if allowed else deny_code


def readback_decision(
    *, readback_available: bool, content_hash_match: bool, structural_state_ok: bool
) -> str | None:
    """Background actuation must verify-readback; any failure fails closed (Inv. 9)."""
    if not readback_available or not content_hash_match or not structural_state_ok:
        return BackgroundControlDenialCode.READBACK_FAILED.value
    return None


def overlay_authority_decision(intent: str) -> str | None:
    """The overlay/HUD is display-only; only Stop flows to the kill path (Inv. 11/12).

    Any non-allowlisted intent (resume/approve/replay/mutate/extend/unlock/…) and
    any unknown intent fail closed.
    """
    if intent in OVERLAY_ALLOWED_INTENTS:
        return None
    return BackgroundControlDenialCode.OVERLAY_NOT_AUTHORITATIVE.value


def secure_input_background_decision(secure_input_active: bool, primitive: str) -> str | None:
    """Secure Input is process-global: fail closed for text-entry primitives even
    when the target app is not frontmost (§10). Press/click primitives are
    unaffected, mirroring the PR-C pointer rule."""
    if secure_input_active and primitive in KEYBOARD_LIKE_PRIMITIVES:
        return DesktopDenialCode.SECURE_INPUT_ACTIVE.value
    return None


def byte_free_violations(node, path: str = "") -> list[str]:
    """Recursively collect paths whose KEY is a forbidden raw-content field.

    Case-insensitive (``AXValue`` / ``Window_Title`` are caught). Structural
    key-only by design — see ``FORBIDDEN_EVENT_FIELDS``.
    """
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN_LOWER:
                hits.append(f"{path}.{key}")
            hits.extend(byte_free_violations(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            hits.extend(byte_free_violations(value, f"{path}[{i}]"))
    return hits


def raw_bytes_decision(event) -> str | None:
    """Deny (``raw_bytes_blocked``) if an event would leak any raw content field."""
    return BackgroundControlDenialCode.RAW_BYTES_BLOCKED.value if byte_free_violations(event) else None
