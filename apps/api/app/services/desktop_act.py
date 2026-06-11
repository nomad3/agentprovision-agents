"""Luna P5.4b — agent-facing pending desktop approval requests (thin act surface).

This is the *pending-approval branch* of the agent act surface: an agent (Luna)
records a request to run a native desktop action and polls its status; a human
approves it later (P5.5). Fail-closed and intrinsically safe:

* It NEVER enqueues a command, signs an envelope, or calls a native actuator.
* It NEVER mints an approval grant — grant creation stays internal-key-only in
  ``desktop_control_service.create_desktop_approval_grant`` (untouched). A pending
  request lives in its own table (``desktop_approval_requests``) and is invisible
  to the claim path (which only consumes grants with ``status == 'active'``), so it
  can never authorize a native action.
* Requests are accepted only for the native-control action class — the actions
  that will need a user grant. Observe/dry-run need no grant and are rejected.

Kept deliberately separate from the 3k-line ``desktop_control_service.py`` (D5
split pending): it only *imports* the shared display-safe + scoping helpers.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.desktop_approval_request import DesktopApprovalRequest
from app.models.desktop_command_approval_grant import DesktopCommandApprovalGrant
from app.services import rl_experience_service
from app.services.desktop_control_codes import DesktopDenialCode
from app.services.desktop_control_service import (
    _COMMAND_TOOL_ACTIONS,
    _NATIVE_CONTROL_CAPABILITIES,
    _capability_matches_risk_tier,
    _ensure_desktop_control_enabled,
    _ensure_session_owned_by_user,
    _ensure_user_for_tenant,
    _publish_display_safe_session_event,
    _require_native_control_target_binding,
    _select_connected_shell,
    DesktopCommandEnqueue,
    enqueue_desktop_command,
)
from app.services.perception_storage import _BUNDLE_ID_RE

# Only the native-control actions are grant-requestable: observe + dry-run need no
# grant, so a request for them is a category error (fail-closed 422).
REQUESTABLE_ACTIONS: frozenset[str] = frozenset(
    {"pointer_move", "pointer_click", "keyboard_type", "keyboard_key_chord"}
)

_REASON_MAX_LEN = 280
_DEFAULT_TTL_SECONDS = 300
_MIN_TTL_SECONDS = 60
_MAX_TTL_SECONDS = 3600

logger = logging.getLogger(__name__)

_RL_DECISION_POINT = "desktop_control_decision"


class DesktopGrantRequestDenialCode(str, Enum):
    """Closed, display-safe denial codes for the grant-request surface. Mirrored by
    the Alpha CLI typed contract (``DesktopGrantRequestDenialCode`` in
    ``apps/agentprovision-core/src/desktop.rs``)."""

    DESKTOP_CONTROL_DISABLED = "desktop_control_disabled"
    ACTION_NOT_REQUESTABLE = "action_not_requestable"
    INVALID_TARGET_BUNDLE = "invalid_target_bundle"
    REQUEST_NOT_FOUND = "request_not_found"
    # P5.5 approve/deny lifecycle: a request that is not still pending (already
    # approved/denied/cancelled) or that has lapsed past its TTL.
    REQUEST_NOT_PENDING = "request_not_pending"
    REQUEST_EXPIRED = "request_expired"


_DENIAL_HTTP_STATUS = {
    DesktopGrantRequestDenialCode.DESKTOP_CONTROL_DISABLED: 403,
    DesktopGrantRequestDenialCode.ACTION_NOT_REQUESTABLE: 422,
    DesktopGrantRequestDenialCode.INVALID_TARGET_BUNDLE: 422,
    DesktopGrantRequestDenialCode.REQUEST_NOT_FOUND: 404,
    DesktopGrantRequestDenialCode.REQUEST_NOT_PENDING: 409,
    DesktopGrantRequestDenialCode.REQUEST_EXPIRED: 409,
}


def _deny(code: DesktopGrantRequestDenialCode, reason: str) -> None:
    """Raise a structured display-safe denial (fixed strings only)."""
    raise HTTPException(
        status_code=_DENIAL_HTTP_STATUS[code],
        detail={"code": code.value, "reason": reason},
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _effective_status(request: DesktopApprovalRequest, *, now: datetime) -> str:
    """Treat a still-`pending` request past its TTL as `expired` for display
    (the stored row is swept/decided lazily; the projection never lies)."""
    if request.status == "pending":
        expires_at = _as_aware_utc(request.expires_at)
        if expires_at is not None and expires_at <= now:
            return "expired"
    return request.status


def _display_safe_request(request: DesktopApprovalRequest, *, now: datetime) -> dict[str, Any]:
    target = request.target_binding or {}
    # Normalize ALL timestamps to aware UTC so they serialize identically (with a
    # +00:00 offset) on every backend — SQLite round-trips DateTime(timezone=True)
    # as naive, which would otherwise drop the offset inconsistently across fields.
    created_at = _as_aware_utc(request.created_at)
    expires_at = _as_aware_utc(request.expires_at)
    decided_at = _as_aware_utc(request.decided_at)
    return {
        "request_id": str(request.id),
        "session_id": str(request.session_id),
        "shell_id": request.shell_id,
        "action": request.action,
        "capability": request.capability,
        "status": _effective_status(request, now=now),
        "target_bundle_id": target.get("bundle_id"),
        "reason": request.reason,
        "created_at": created_at.isoformat() if created_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        # Whether a human has minted a grant for this request yet (P5.5). Never the
        # grant payload — just presence.
        "grant_present": request.grant_id is not None,
        # The minted grant's id once a human has approved this request (P5.4c).
        # null while pending/denied/expired. Owner-scoped (this projection is
        # filtered by tenant_id AND user_id), so only the requesting owner ever
        # sees it — the same owner already receives it in the approve response.
        # It is an approval *reference*, not authorization: `actuate` still
        # re-validates owner/session/expiry/revocation + the default-off native
        # flag, so the id alone enqueues nothing. It lets a CLI-subprocess agent
        # (which polls tools, not SSE) actuate against a human-approved grant.
        "grant_id": str(request.grant_id) if request.grant_id else None,
        "decided_at": decided_at.isoformat() if decided_at else None,
    }


def _log_desktop_rl_decision(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    surface: str,
    outcome: str,
    source: str | None = None,
    action: str | None = None,
    capability: str | None = None,
    request_id: uuid.UUID | str | None = None,
    grant_id: uuid.UUID | str | None = None,
    command_id: uuid.UUID | str | None = None,
    denial_code: str | None = None,
    status_code: int | None = None,
    shell_id: str | None = None,
    target_bundle_id: str | None = None,
    desktop_event_id: str | None = None,
    session_event_id: str | None = None,
) -> None:
    """Best-effort RL trace for desktop decisions.

    Byte-free by construction: no args, reason, OCR/window/clipboard/typed text,
    screen content, page text, AX tree, or envelopes are accepted by this helper.
    """
    state = {
        "surface": surface,
        "session_id": str(session_id),
        "source": source or "unknown",
    }
    action_payload = {
        "outcome": outcome,
        "action": action,
        "capability": capability,
        "request_id": str(request_id) if request_id else None,
        "grant_id": str(grant_id) if grant_id else None,
        "command_id": str(command_id) if command_id else None,
        "denial_code": denial_code,
        "status_code": status_code,
        "shell_id": shell_id,
        "target_bundle_id": target_bundle_id,
        "desktop_event_id": desktop_event_id,
        "session_event_id": session_event_id,
    }
    try:
        rl_experience_service.log_experience(
            db,
            tenant_id=tenant_id,
            trajectory_id=session_id,
            step_index=0,
            decision_point=_RL_DECISION_POINT,
            state=state,
            action={k: v for k, v in action_payload.items() if v is not None},
            alternatives=[],
            explanation={"policy": "byte_free_desktop_control"},
            policy_version="p5.5",
            exploration=False,
            state_text=None,
        )
    except Exception:
        db.rollback()
        logger.warning("desktop RL decision logging failed", exc_info=True)


def _denial_code_from_http_exception(exc: HTTPException) -> str | None:
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code")
        return str(code) if code is not None else None
    return None


def request_desktop_grant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    action: str,
    target_bundle_id: str,
    shell_id: str | None = None,
    reason: str | None = None,
    # Reserved for the P5.5 approval surface (which may set a shorter/longer
    # window when it mints the grant); no current caller passes it, so requests
    # default to a 5-minute pending window.
    ttl_seconds: int | None = None,
    source: str = "alpha",
) -> dict[str, Any]:
    """Record a PENDING approval request for a native desktop action.

    Fail-closed: master flag re-checked, session ownership enforced, action limited
    to the native-control class, target bundle validated. Creates NO grant, NO
    command, NO envelope, and triggers NO actuation.
    """
    # 1. master capability gate (fail-closed, re-checked here)
    _ensure_desktop_control_enabled(db, tenant_id)
    # 2. user + session ownership (matching the real grant minting path)
    _ensure_user_for_tenant(db, user_id, tenant_id)
    _ensure_session_owned_by_user(db, session_id, tenant_id, user_id)
    # 3. action must be grant-requestable (native-control class only)
    if action not in REQUESTABLE_ACTIONS:
        _deny(
            DesktopGrantRequestDenialCode.ACTION_NOT_REQUESTABLE,
            "action is not a grant-requestable native-control action",
        )
    capability = _NATIVE_CONTROL_CAPABILITIES[action]
    # 4. reduced, validated target bundle (no payload bag, no raw content)
    if not isinstance(target_bundle_id, str) or not _BUNDLE_ID_RE.match(target_bundle_id):
        _deny(
            DesktopGrantRequestDenialCode.INVALID_TARGET_BUNDLE,
            "target_bundle_id is not a valid bundle identifier",
        )
    # 5. bind to a connected shell + device (same proof as observe-request)
    selected_shell, _caps, device_id = _select_connected_shell(tenant_id, shell_id)

    clean_reason: str | None = None
    if reason is not None:
        clean_reason = str(reason).strip()[:_REASON_MAX_LEN] or None

    ttl = ttl_seconds if ttl_seconds is not None else _DEFAULT_TTL_SECONDS
    ttl = max(_MIN_TTL_SECONDS, min(int(ttl), _MAX_TTL_SECONDS))
    now = _utcnow()

    request = DesktopApprovalRequest(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        shell_id=selected_shell,
        device_id=device_id,
        action=action,
        capability=capability,
        target_binding={"bundle_id": target_bundle_id},
        reason=clean_reason,
        status="pending",
        requested_by_user_id=user_id,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl),
    )
    db.add(request)
    db.flush()

    # Byte-free, display-safe session event so a human/other agent can watch the
    # pending request appear (the P5.5 approval surface subscribes to this).
    _publish_display_safe_session_event(
        session_id,
        "desktop_grant_requested",
        {
            "request_id": str(request.id),
            "action": action,
            "capability": capability,
            "status": "pending",
            "shell_id": selected_shell,
            "target_bundle_id": target_bundle_id,
            "expires_at": request.expires_at.isoformat(),
            "requested_via": source,
        },
        tenant_id=tenant_id,
    )
    db.commit()
    db.refresh(request)
    _log_desktop_rl_decision(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        surface="desktop_request_grant",
        outcome="pending",
        source=source,
        action=action,
        capability=capability,
        request_id=request.id,
        shell_id=selected_shell,
        target_bundle_id=target_bundle_id,
    )
    return _display_safe_request(request, now=now)


def get_desktop_grant_request_status(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Display-safe status of one pending approval request (tenant+owner scoped).
    A wrong tenant, wrong owner, or unknown id are all the same uniform not-found
    (no cross-scope existence oracle)."""
    request = (
        db.query(DesktopApprovalRequest)
        .filter(
            DesktopApprovalRequest.id == request_id,
            DesktopApprovalRequest.tenant_id == tenant_id,
            DesktopApprovalRequest.user_id == user_id,
        )
        .first()
    )
    if request is None:
        _deny(
            DesktopGrantRequestDenialCode.REQUEST_NOT_FOUND,
            "desktop approval request not found",
        )
    return _display_safe_request(request, now=now or _utcnow())


# ── P5.5 user approval surface (list / approve / deny) ────────────────────────
#
# The HUMAN half: an authenticated user converts a pending request into exactly
# one bounded active DesktopCommandApprovalGrant (approve) or terminally denies
# it (deny). No agent/MCP path reaches these — the routes are user-JWT only and
# the owner is the authenticated principal, never a caller-supplied header.

_GRANT_DEFAULT_EXPIRES_SECONDS = 60
_GRANT_MIN_EXPIRES_SECONDS = 5
_GRANT_MAX_EXPIRES_SECONDS = 600
_GRANT_MIN_ACTIONS = 1
_GRANT_MAX_ACTIONS = 20


def _grant_summary(grant: DesktopCommandApprovalGrant) -> dict[str, Any]:
    """Display-safe projection of the minted grant: ids/status/expiry/bounds
    only — never the target binding internals beyond the bundle, never an
    envelope (none exists; envelopes are signed later at claim)."""
    expires_at = _as_aware_utc(grant.expires_at)
    target = grant.target_binding or {}
    return {
        "grant_id": str(grant.id),
        "grant_status": grant.status,
        "risk_tier": grant.risk_tier,
        "capability": grant.capability,
        "max_actions": int(grant.max_actions),
        "remaining_actions": int(grant.remaining_actions),
        "grant_expires_at": expires_at.isoformat() if expires_at else None,
        "target_bundle_id": target.get("bundle_id"),
    }


def list_pending_approval_requests(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    now: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Display-safe list of the authenticated user's still-actionable (pending,
    not lapsed) approval requests, optionally scoped to one session. Tenant +
    owner scoped — a user only ever sees their own requests."""
    cutoff = now or _utcnow()
    query = db.query(DesktopApprovalRequest).filter(
        DesktopApprovalRequest.tenant_id == tenant_id,
        DesktopApprovalRequest.user_id == user_id,
        DesktopApprovalRequest.status == "pending",
        DesktopApprovalRequest.expires_at > cutoff,
    )
    if session_id is not None:
        query = query.filter(DesktopApprovalRequest.session_id == session_id)
    rows = query.order_by(DesktopApprovalRequest.created_at.desc()).limit(
        max(1, min(int(limit), 500))
    ).all()
    return [_display_safe_request(r, now=cutoff) for r in rows]


def _load_decidable_request(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    now: datetime,
) -> DesktopApprovalRequest:
    """Row-lock + validate a request for an approve/deny decision. Fail-closed:
    wrong tenant/owner/id → uniform not-found; already-decided → not-pending;
    lapsed past TTL → expired. The ``SELECT … FOR UPDATE`` serializes concurrent
    decisions so a duplicate approve can never mint a second grant (it sees the
    row already non-pending)."""
    request = (
        db.query(DesktopApprovalRequest)
        .filter(
            DesktopApprovalRequest.id == request_id,
            DesktopApprovalRequest.tenant_id == tenant_id,
            DesktopApprovalRequest.user_id == user_id,
        )
        .with_for_update()
        .first()
    )
    if request is None:
        _deny(
            DesktopGrantRequestDenialCode.REQUEST_NOT_FOUND,
            "desktop approval request not found",
        )
    if request.status != "pending":
        _deny(
            DesktopGrantRequestDenialCode.REQUEST_NOT_PENDING,
            "desktop approval request is no longer pending",
        )
    expires_at = _as_aware_utc(request.expires_at)
    if expires_at is None or expires_at <= now:
        _deny(
            DesktopGrantRequestDenialCode.REQUEST_EXPIRED,
            "desktop approval request has expired",
        )
    return request


def approve_desktop_grant_request(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    max_actions: int = 1,
    expires_in_seconds: int = _GRANT_DEFAULT_EXPIRES_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Approve a pending request → mint exactly ONE bounded active grant and mark
    the request approved, atomically. The grant owner is the authenticated
    ``user_id`` (never a caller-supplied header). Mints no envelope and triggers
    no actuation — the grant is inert until the (default-off) per-capability flag
    + an enqueue/claim, none of which this touches."""
    cutoff = now or _utcnow()
    # Master flag re-checked at decision time (fail-closed).
    _ensure_desktop_control_enabled(db, tenant_id)
    request = _load_decidable_request(
        db, tenant_id=tenant_id, user_id=user_id, request_id=request_id, now=cutoff
    )
    # The session must still be owned by the approving user.
    _ensure_session_owned_by_user(db, request.session_id, tenant_id, user_id)

    capability = request.capability
    if not _capability_matches_risk_tier(capability, "native_control"):
        # Defensive: requests are only ever created for native-control actions.
        _deny(
            DesktopGrantRequestDenialCode.ACTION_NOT_REQUESTABLE,
            "request capability is not a native-control capability",
        )

    # Resolve shell + device from LIVE presence (binds the device that is
    # connected now). A disconnected shell fails closed (409) inside the helper.
    selected_shell, _caps, device_id = _select_connected_shell(tenant_id, request.shell_id)
    if device_id is None:
        _deny(
            DesktopGrantRequestDenialCode.REQUEST_NOT_PENDING,
            "desktop shell device is not bound",
        )

    # Build + validate the native-control target binding (allowlist-gated). The
    # bundle is the one the user is approving; the action is the requested action.
    target = (request.target_binding or {}).copy()
    target["action"] = request.action
    target_binding = _require_native_control_target_binding(
        target, action=request.action, db=db, tenant_id=tenant_id
    )

    max_actions = max(_GRANT_MIN_ACTIONS, min(int(max_actions), _GRANT_MAX_ACTIONS))
    expires_in = max(
        _GRANT_MIN_EXPIRES_SECONDS, min(int(expires_in_seconds), _GRANT_MAX_EXPIRES_SECONDS)
    )

    grant = DesktopCommandApprovalGrant(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=request.session_id,
        shell_id=selected_shell,
        device_id=device_id,
        desktop_command_id=None,
        risk_tier="native_control",
        capability=capability,
        status="active",
        target_binding=target_binding,
        max_actions=max_actions,
        remaining_actions=max_actions,
        approved_by_user_id=user_id,
        approved_at=cutoff,
        expires_at=cutoff + timedelta(seconds=expires_in),
        created_at=cutoff,
        updated_at=cutoff,
    )
    db.add(grant)
    db.flush()  # assign grant.id without committing yet

    request.status = "approved"
    request.grant_id = grant.id
    request.decided_by_user_id = user_id
    request.decided_at = cutoff
    db.add(request)

    _publish_display_safe_session_event(
        request.session_id,
        "desktop_grant_approved",
        {
            "request_id": str(request.id),
            "grant_id": str(grant.id),
            "action": request.action,
            "capability": capability,
            "status": "approved",
            "shell_id": selected_shell,
            "target_bundle_id": target_binding.get("bundle_id"),
            "grant_expires_at": grant.expires_at.isoformat(),
        },
        tenant_id=tenant_id,
    )
    # One commit: grant + request update land together (atomic).
    db.commit()
    db.refresh(request)
    db.refresh(grant)
    out = _display_safe_request(request, now=cutoff)
    out.update(_grant_summary(grant))
    _log_desktop_rl_decision(
        db,
        tenant_id=tenant_id,
        session_id=request.session_id,
        surface="desktop_grant_decision",
        outcome="approved",
        source="user_jwt",
        action=request.action,
        capability=capability,
        request_id=request.id,
        grant_id=grant.id,
        shell_id=selected_shell,
        target_bundle_id=target_binding.get("bundle_id"),
    )
    return out


def deny_desktop_grant_request(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Terminally deny a pending request. Creates NO grant. Audit-visible via a
    display-safe ``desktop_grant_denied`` event. Fail-closed: only a pending,
    unexpired, owned request can be denied."""
    cutoff = now or _utcnow()
    request = _load_decidable_request(
        db, tenant_id=tenant_id, user_id=user_id, request_id=request_id, now=cutoff
    )
    request.status = "denied"
    request.decided_by_user_id = user_id
    request.decided_at = cutoff
    db.add(request)

    deny_reason: str | None = None
    if reason is not None:
        deny_reason = str(reason).strip()[:_REASON_MAX_LEN] or None

    _publish_display_safe_session_event(
        request.session_id,
        "desktop_grant_denied",
        {
            "request_id": str(request.id),
            "action": request.action,
            "capability": request.capability,
            "status": "denied",
            "shell_id": request.shell_id,
            # the human's deny reason is display-safe + capped; never raw content
            "deny_reason": deny_reason,
        },
        tenant_id=tenant_id,
    )
    db.commit()
    db.refresh(request)
    target = request.target_binding or {}
    _log_desktop_rl_decision(
        db,
        tenant_id=tenant_id,
        session_id=request.session_id,
        surface="desktop_grant_decision",
        outcome="denied",
        source="user_jwt",
        action=request.action,
        capability=request.capability,
        request_id=request.id,
        shell_id=request.shell_id,
        target_bundle_id=target.get("bundle_id"),
    )
    return _display_safe_request(request, now=cutoff)


# ── P5.4b desktop_actuate — grant-gated agent act (no minting) ────────────────
#
# Given an EXISTING active grant (minted by a human via P5.5), enqueue exactly
# one bounded native command through the shared `enqueue_desktop_command`
# lifecycle, bound to that grant. No grant -> approval_required, NO command.
# Wrong/expired/revoked/exhausted/wrong-session grant -> structured deny, NO
# command. Mints no grant, signs no envelope, calls no native API. The grant is
# consumed at CLAIM (unchanged); actuate only enqueues.

# action -> tool_name (invert the canonical tool->action map).
_ACTION_TO_TOOL = {action: tool for tool, action in _COMMAND_TOOL_ACTIONS.items()}


def _deny_canonical(code: DesktopDenialCode, reason: str, *, status_code: int = 409) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code.value, "reason": reason})


def _actuate_grant_state_denial(grant: DesktopCommandApprovalGrant, *, now: datetime) -> None:
    """Raise the canonical structured denial for a non-actionable grant. A grant
    that passes all checks here returns None (actionable)."""
    if grant.status == "revoked" or grant.revoked_at is not None:
        _deny_canonical(DesktopDenialCode.APPROVAL_REVOKED, "approval grant revoked")
    expires_at = _as_aware_utc(grant.expires_at)
    if grant.status == "expired" or expires_at is None or expires_at <= now:
        _deny_canonical(DesktopDenialCode.APPROVAL_EXPIRED, "approval grant expired")
    if grant.status == "consumed" or int(grant.remaining_actions or 0) <= 0:
        _deny_canonical(DesktopDenialCode.APPROVAL_EXHAUSTED, "approval grant exhausted")
    if grant.status != "active":
        _deny_canonical(DesktopDenialCode.APPROVAL_BINDING_MISMATCH, "approval grant not active")


def _display_safe_command(
    command: Any,
    *,
    status: str,
    event: Any = None,
    session_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Display-safe actuate projection: command id/status/action/capability/
    approval ref/bundle + audit refs. NEVER the actuation args, target internals
    beyond the bundle, screen bytes, or envelope."""
    payload = command.payload or {}
    target = payload.get("target") or {}
    return {
        "status": status,  # "queued" | "approval_required"
        "command_id": str(command.id) if command is not None else None,
        "command_status": command.status if command is not None else None,
        "action": payload.get("action"),
        "capability": command.capability if command is not None else None,
        "approval_id": str(command.approval_id) if (command is not None and command.approval_id) else None,
        "shell_id": command.shell_id if command is not None else None,
        "target_bundle_id": target.get("bundle_id"),
        "desktop_event_id": str(event.id) if event is not None else None,
        "session_event_id": session_event.get("event_id") if session_event else None,
        "session_seq_no": session_event.get("seq_no") if session_event else None,
    }


def _approval_required_response(session_id: uuid.UUID) -> dict[str, Any]:
    return {
        "status": "approval_required",
        "command_id": None,
        "command_status": None,
        "action": None,
        "capability": None,
        "approval_id": None,
        "shell_id": None,
        "target_bundle_id": None,
        "desktop_event_id": None,
        "session_event_id": None,
        "session_seq_no": None,
    }


def _actuate_command_inner(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    grant_id: uuid.UUID,
    args: dict[str, Any] | None = None,
    nonce: str | None = None,
    source: str = "alpha",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Enqueue ONE bounded native command against an existing active grant.

    Fail-closed: master flag re-checked; a grant that does not resolve in the
    caller's (tenant, user) scope -> approval_required (NO command); a resolved
    grant that is for another session / not native_control / revoked / expired /
    exhausted -> structured deny (NO command). A valid grant delegates to the
    shared `enqueue_desktop_command`, which runs every native-control gate
    (default-off per-capability flag, allowlist, shell-connected, args) and binds
    the command to ``approval_id=grant.id``. The grant is consumed at CLAIM.
    """
    cutoff = now or _utcnow()
    # Master capability gate (fail-closed) — also confirms the user/tenant.
    _ensure_desktop_control_enabled(db, tenant_id)
    _ensure_user_for_tenant(db, user_id, tenant_id)

    # Scope the lookup to the tenant (not the user) so a grant owned by another
    # user in the SAME tenant denies as a wrong-owner (per spec), while a
    # cross-tenant or nonexistent id stays a uniform approval_required (no
    # cross-tenant existence oracle). Grant ids are uuid4 (unguessable).
    grant = (
        db.query(DesktopCommandApprovalGrant)
        .filter(
            DesktopCommandApprovalGrant.id == grant_id,
            DesktopCommandApprovalGrant.tenant_id == tenant_id,
        )
        .first()
    )
    # Missing grant in the tenant => approval_required, NO command.
    if grant is None:
        return _approval_required_response(session_id)

    # Wrong owner => structured deny (the grant belongs to a different user).
    if str(grant.user_id) != str(user_id):
        _deny_canonical(
            DesktopDenialCode.APPROVAL_BINDING_MISMATCH,
            "approval grant is not owned by the caller",
        )

    # Wrong session / not a native-control grant => structured deny.
    if str(grant.session_id) != str(session_id):
        _deny_canonical(
            DesktopDenialCode.APPROVAL_BINDING_MISMATCH,
            "approval grant is not for this session",
        )
    if grant.risk_tier != "native_control":
        _deny_canonical(
            DesktopDenialCode.APPROVAL_BINDING_MISMATCH,
            "approval grant is not a native-control grant",
        )
    # Revoked / expired / exhausted / not-active => structured deny.
    _actuate_grant_state_denial(grant, now=cutoff)

    # Derive the bounded action/target from the grant — the agent cannot pick a
    # different action or target than the human approved.
    target = grant.target_binding or {}
    action = target.get("action")
    if not action or action not in _NATIVE_CONTROL_CAPABILITIES:
        _deny_canonical(
            DesktopDenialCode.APPROVAL_BINDING_MISMATCH,
            "approval grant has no actionable native-control action",
        )
    capability = _NATIVE_CONTROL_CAPABILITIES[action]
    if grant.capability != capability or not _capability_matches_risk_tier(capability, "native_control"):
        _deny_canonical(
            DesktopDenialCode.APPROVAL_BINDING_MISMATCH,
            "approval grant capability does not match its action",
        )
    tool_name = _ACTION_TO_TOOL.get(action)
    if tool_name is None:
        _deny_canonical(
            DesktopDenialCode.APPROVAL_BINDING_MISMATCH,
            "approval grant action is not actuatable",
        )

    request = DesktopCommandEnqueue(
        session_id=grant.session_id,
        action=action,
        tool_name=tool_name,
        shell_id=grant.shell_id,
        payload={"target": dict(target), "args": args or {}},
        nonce=nonce,
        approval_id=grant.id,
    )
    # Delegate to the shared lifecycle — runs the native-control gates
    # (per-capability flag default-off, allowlist, shell-connected, args
    # validation) and creates a pending command bound to the grant. Any gate
    # failure propagates as a display-safe denial; no command is created.
    try:
        command, event, session_event = enqueue_desktop_command(
            db, tenant_id=tenant_id, user_id=user_id, request=request
        )
    except ValueError:
        # Malformed actuation args (e.g. over-long text, out-of-range coords, a
        # non-allowlisted key chord) raise a bare ValueError from the shared arg
        # normalizer → no command is created. Convert it to a structured 422
        # deny (the agent-facing surface never returns an opaque 500), with a
        # FIXED reason — the args themselves are never echoed.
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_actuation_args",
                "reason": "actuation args are invalid for the granted action",
            },
        )
    return _display_safe_command(
        command, status="queued", event=event, session_event=session_event
    )


def actuate_command(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    grant_id: uuid.UUID,
    args: dict[str, Any] | None = None,
    nonce: str | None = None,
    source: str = "alpha",
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        out = _actuate_command_inner(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            grant_id=grant_id,
            args=args,
            nonce=nonce,
            source=source,
            now=now,
        )
    except HTTPException as exc:
        db.rollback()
        _log_desktop_rl_decision(
            db,
            tenant_id=tenant_id,
            session_id=session_id,
            surface="desktop_actuate",
            outcome="denied",
            source=source,
            grant_id=grant_id,
            denial_code=_denial_code_from_http_exception(exc),
            status_code=exc.status_code,
        )
        raise
    _log_desktop_rl_decision(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        surface="desktop_actuate",
        outcome=out.get("status") or "unknown",
        source=source,
        action=out.get("action"),
        capability=out.get("capability"),
        grant_id=grant_id,
        command_id=out.get("command_id"),
        shell_id=out.get("shell_id"),
        target_bundle_id=out.get("target_bundle_id"),
        desktop_event_id=out.get("desktop_event_id"),
        session_event_id=out.get("session_event_id"),
    )
    return out
