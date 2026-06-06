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

_PERMISSION_STATUS_FIELDS = (
    ("screen_recording", "screen_recording_status"),
    ("accessibility", "accessibility_status"),
    ("automation_system_events", "automation_system_events_status"),
)


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


def _ensure_session_owned(db: Session, session_id: uuid.UUID, user: User) -> None:
    exists = db.query(ChatSession.id).filter(
        ChatSession.id == session_id,
        ChatSession.tenant_id == user.tenant_id,
    ).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Session not found")


def _ensure_shell_connected(shell_id: str, user: User) -> None:
    snapshot = luna_presence_service.get_presence(user.tenant_id)
    connected_shells = set(snapshot.get("connected_shells") or [])
    if shell_id not in connected_shells:
        raise HTTPException(status_code=409, detail="Desktop shell is not connected")


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
