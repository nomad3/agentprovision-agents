"""Governed Luna desktop-control audit helpers."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.chat import ChatSession
from app.models.desktop_command_event import DesktopCommandEvent
from app.models.user import User
from app.services.collaboration_events import publish_session_event
from app.services import luna_presence_service

logger = logging.getLogger(__name__)

_SAFE_FAILURE_REASONS = (
    "Screenshot capture failed",
    "Clipboard read failed",
    "Active app lookup failed",
)

_SAFE_DENIAL_REASONS = (
    "desktop observation down-channel unavailable;",
    "desktop shell cannot observe;",
)

_PERMISSION_STATUS_FIELDS = (
    ("screen_recording", "screen_recording_status"),
    ("accessibility", "accessibility_status"),
    ("automation_system_events", "automation_system_events_status"),
)

_OBSERVATION_CAPABILITIES = {
    "capture_screenshot": "screenshot",
    "get_active_app": "active_app",
    "read_clipboard": "clipboard_read",
}


@dataclass(frozen=True)
class LocalObservationAudit:
    session_id: uuid.UUID
    shell_id: str
    event_id: uuid.UUID
    event_type: str
    source: str
    action: str
    capability: str
    outcome: str
    mode: str
    created_at_ms: int | None
    reason: str | None
    screen_recording_status: str | None
    accessibility_status: str | None
    automation_system_events_status: str | None


@dataclass(frozen=True)
class McpObservationRequest:
    session_id: uuid.UUID
    action: str
    shell_id: str | None
    tool_name: str


def _get_session_for_tenant(db: Session, session_id: uuid.UUID, tenant_id: uuid.UUID) -> ChatSession:
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.tenant_id == tenant_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _ensure_session_owned_by_user(
    db: Session,
    session_id: uuid.UUID,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    session = _get_session_for_tenant(db, session_id, tenant_id)
    owner_user_id = getattr(session, "owner_user_id", None)
    if owner_user_id is None:
        raise HTTPException(
            status_code=403,
            detail="Desktop session owner is not established",
        )
    if str(owner_user_id) != str(user_id):
        raise HTTPException(
            status_code=403,
            detail="Desktop session is not owned by user",
        )


def _ensure_session_owned(db: Session, session_id: uuid.UUID, user: User) -> None:
    _ensure_session_owned_by_user(db, session_id, user.tenant_id, user.id)


def _ensure_user_for_tenant(db: Session, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    exists = db.query(User.id).filter(
        User.id == user_id,
        User.tenant_id == tenant_id,
    ).first()
    if not exists:
        raise HTTPException(status_code=404, detail="User not found")


def _presence_for_tenant(tenant_id: uuid.UUID) -> dict[str, Any]:
    return luna_presence_service.get_presence(tenant_id)


def _ensure_shell_connected(shell_id: str, user: User) -> None:
    snapshot = _presence_for_tenant(user.tenant_id)
    connected_shells = set(snapshot.get("connected_shells") or [])
    if shell_id not in connected_shells:
        raise HTTPException(status_code=409, detail="Desktop shell is not connected")


def _select_connected_shell(
    tenant_id: uuid.UUID,
    requested_shell_id: str | None,
) -> tuple[str, dict[str, Any]]:
    snapshot = _presence_for_tenant(tenant_id)
    connected_shells = list(snapshot.get("connected_shells") or [])
    connected = set(connected_shells)
    if requested_shell_id:
        if requested_shell_id not in connected:
            raise HTTPException(status_code=409, detail="Desktop shell is not connected")
        selected = requested_shell_id
    else:
        active_shell = snapshot.get("active_shell")
        if active_shell in connected:
            selected = active_shell
        elif len(connected_shells) == 1:
            selected = connected_shells[0]
        else:
            raise HTTPException(status_code=409, detail="No connected desktop shell")

    raw_caps = (snapshot.get("shell_capabilities") or {}).get(selected) or {}
    capabilities = {
        key: bool(value)
        for key, value in raw_caps.items()
        if key.startswith("can_") and isinstance(value, bool)
    }
    return selected, capabilities


def _display_safe_payload(event: DesktopCommandEvent) -> dict[str, Any]:
    return {
        "desktop_event_id": str(event.id),
        "local_event_id": event.event_metadata.get("local_event_id"),
        "shell_id": event.shell_id,
        "source": event.source,
        "action": event.action,
        "capability": event.capability,
        "outcome": event.outcome,
        "mode": event.mode,
        "reason": event.reason,
        "permissions": event.event_metadata.get("permissions", {}),
        "created_at_ms": event.event_metadata.get("created_at_ms"),
    }


def _safe_reason(audit: LocalObservationAudit) -> str | None:
    if not audit.reason:
        return None
    normalized = " ".join(audit.reason.split())
    if normalized.startswith("desktop control stopped;"):
        return f"desktop control stopped; {audit.action} denied"
    if normalized.startswith("desktop observe locked;"):
        return f"desktop observe locked; {audit.action} denied"
    if normalized.startswith("desktop observation permission "):
        for permission, attr in _PERMISSION_STATUS_FIELDS:
            status = getattr(audit, attr)
            if status not in (None, "granted", "not_required"):
                return (
                    f"desktop observation permission '{permission}' is {status}; "
                    f"{audit.action} denied"
                )
        return "desktop observation denied"
    for prefix in _SAFE_FAILURE_REASONS:
        if normalized.startswith(prefix):
            return prefix
    for prefix in _SAFE_DENIAL_REASONS:
        if normalized.startswith(prefix):
            return f"{prefix} {audit.action} request denied"
    if audit.outcome == "denied":
        return "desktop observation denied"
    if audit.outcome == "failed":
        return "desktop observation failed"
    return None


def record_local_observation_event(
    db: Session,
    user: User,
    audit: LocalObservationAudit,
) -> tuple[DesktopCommandEvent, dict[str, Any] | None]:
    """Persist a local metadata-only observation audit event.

    The caller schema rejects unknown fields. This function stores only the
    allow-listed metadata needed for replay; raw screenshot pixels, clipboard
    text, OCR text, and window contents have no accepted field here.
    """
    _ensure_session_owned(db, audit.session_id, user)
    _ensure_shell_connected(audit.shell_id, user)

    metadata = {
        "local_event_id": str(audit.event_id),
        "created_at_ms": audit.created_at_ms,
        "permissions": {
            "screen_recording": audit.screen_recording_status,
            "accessibility": audit.accessibility_status,
            "automation_system_events": audit.automation_system_events_status,
        },
    }
    event = DesktopCommandEvent(
        tenant_id=user.tenant_id,
        user_id=user.id,
        session_id=audit.session_id,
        event_type=audit.event_type,
        source=audit.source,
        action=audit.action,
        capability=audit.capability,
        outcome=audit.outcome,
        reason=_safe_reason(audit),
        mode=audit.mode,
        shell_id=audit.shell_id,
        event_metadata=metadata,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    session_event = None
    try:
        session_event = publish_session_event(
            str(audit.session_id),
            audit.event_type,
            _display_safe_payload(event),
            tenant_id=str(user.tenant_id),
        )
    except Exception:
        logger.exception(
            "desktop-control: failed to mirror event %s into session_events",
            event.id,
        )

    return event, session_event


def record_mcp_observation_request(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request: McpObservationRequest,
) -> tuple[DesktopCommandEvent, dict[str, Any] | None]:
    """Record an MCP/API-governed observation request.

    This phase intentionally does not execute desktop observations from the
    server side: Tauri has no command-claim down-channel yet. Recording a
    denied event keeps the MCP tool honest while preserving tenant/session/shell
    auditability and display-safe session replay.
    """
    _ensure_user_for_tenant(db, user_id, tenant_id)
    _ensure_session_owned_by_user(db, request.session_id, tenant_id, user_id)
    shell_id, shell_capabilities = _select_connected_shell(tenant_id, request.shell_id)

    capability = _OBSERVATION_CAPABILITIES[request.action]
    can_observe = bool(shell_capabilities.get("can_observe"))
    if can_observe:
        reason = f"desktop observation down-channel unavailable; {request.action} request denied"
        mode = "observe"
        down_channel_reason = "not_implemented"
    else:
        reason = f"desktop shell cannot observe; {request.action} request denied"
        mode = "control_locked"
        down_channel_reason = "shell_not_observable"

    event = DesktopCommandEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=request.session_id,
        event_type="desktop_observation_denied",
        source="mcp",
        action=request.action,
        capability=capability,
        outcome="denied",
        reason=reason,
        mode=mode,
        shell_id=shell_id,
        event_metadata={
            "request_id": str(uuid.uuid4()),
            "tool_name": request.tool_name,
            "down_channel": {
                "available": False,
                "reason": down_channel_reason,
            },
            "shell_capabilities": shell_capabilities,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    session_event = None
    try:
        session_event = publish_session_event(
            str(request.session_id),
            event.event_type,
            _display_safe_payload(event),
            tenant_id=str(tenant_id),
        )
    except Exception:
        logger.exception(
            "desktop-control: failed to mirror MCP request event %s into session_events",
            event.id,
        )

    return event, session_event
