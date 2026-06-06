"""Governed Luna desktop-control audit helpers."""
from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.chat import ChatSession
from app.models.desktop_command import DesktopCommand
from app.models.desktop_command_event import DesktopCommandEvent
from app.models.device_registry import DeviceRegistry
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


@dataclass(frozen=True)
class CommandClaim:
    command_id: uuid.UUID
    lease_id: str
    lease_expires_at: datetime
    action: str
    capability: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class CommandAck:
    command_id: uuid.UUID
    lease_id: str
    outcome: str
    reason: str | None = None


_CLAIMABLE_STATUSES = ("pending",)
_ACKABLE_STATUSES = ("claimed", "running")
_STOP_PREEMPTABLE_STATUSES = ("pending", "claimed", "running")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _command_action(command: DesktopCommand) -> str:
    payload = command.payload or {}
    action = payload.get("action")
    if isinstance(action, str) and action in _OBSERVATION_CAPABILITIES:
        return action
    if command.capability == "screenshot":
        return "capture_screenshot"
    if command.capability == "active_app":
        return "get_active_app"
    if command.capability == "clipboard_read":
        return "read_clipboard"
    raise HTTPException(status_code=409, detail="Desktop command action is invalid")


def _safe_ack_outcome(outcome: str) -> tuple[str, str]:
    if outcome == "running":
        return "running", "desktop_command_started"
    if outcome == "succeeded":
        return "succeeded", "desktop_command_completed"
    if outcome == "failed":
        return "failed", "desktop_command_failed"
    if outcome == "denied":
        return "denied", "desktop_command_denied"
    raise HTTPException(status_code=422, detail="Invalid command outcome")


def _command_payload(command: DesktopCommand) -> dict[str, Any]:
    payload = dict(command.payload or {})
    payload.setdefault("action", _command_action(command))
    payload.setdefault("capability", command.capability)
    return payload


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


def _bound_device_for_shell(snapshot: dict[str, Any], shell_id: str) -> uuid.UUID:
    raw_device_id = (snapshot.get("shell_devices") or {}).get(shell_id)
    if not raw_device_id:
        raise HTTPException(status_code=409, detail="Desktop shell device is not bound")
    try:
        return uuid.UUID(str(raw_device_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=409, detail="Desktop shell device binding is invalid")


def _ensure_shell_bound(shell_id: str, user: User) -> uuid.UUID:
    snapshot = _presence_for_tenant(user.tenant_id)
    connected_shells = set(snapshot.get("connected_shells") or [])
    if shell_id not in connected_shells:
        raise HTTPException(status_code=409, detail="Desktop shell is not connected")
    return _bound_device_for_shell(snapshot, shell_id)


def _select_connected_shell(
    tenant_id: uuid.UUID,
    requested_shell_id: str | None,
) -> tuple[str, dict[str, Any], uuid.UUID]:
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
    device_id = _bound_device_for_shell(snapshot, selected)
    return selected, capabilities, device_id


def _display_safe_payload(event: DesktopCommandEvent) -> dict[str, Any]:
    return {
        "desktop_event_id": str(event.id),
        "local_event_id": event.event_metadata.get("local_event_id"),
        "shell_id": event.shell_id,
        "device_id": str(event.device_id) if event.device_id else None,
        "source": event.source,
        "action": event.action,
        "capability": event.capability,
        "outcome": event.outcome,
        "mode": event.mode,
        "reason": event.reason,
        "permissions": event.event_metadata.get("permissions", {}),
        "created_at_ms": event.event_metadata.get("created_at_ms"),
    }


def _display_safe_command_payload(command: DesktopCommand, event_type: str, outcome: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "desktop_command_id": str(command.id),
        "correlation_id": str(command.correlation_id),
        "shell_id": command.shell_id,
        "device_id": str(command.device_id) if command.device_id else None,
        "action": _command_action(command),
        "capability": command.capability,
        "status": command.status,
        "outcome": outcome,
        "reason": reason,
        "event_type": event_type,
    }


def _record_command_event(
    db: Session,
    command: DesktopCommand,
    *,
    event_type: str,
    outcome: str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    source: str | None = None,
    mode: str = "observe",
) -> tuple[DesktopCommandEvent, dict[str, Any] | None]:
    action = _command_action(command)
    event = DesktopCommandEvent(
        tenant_id=command.tenant_id,
        user_id=command.user_id,
        session_id=command.session_id,
        desktop_command_id=command.id,
        correlation_id=command.correlation_id,
        event_type=event_type,
        source=source or command.source,
        action=action,
        capability=command.capability,
        outcome=outcome,
        reason=reason,
        mode=mode,
        shell_id=command.shell_id,
        device_id=command.device_id,
        event_metadata={
            "device_id": str(command.device_id) if command.device_id else None,
            **(metadata or {}),
        },
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    session_event = None
    try:
        session_event = publish_session_event(
            str(command.session_id),
            event_type,
            _display_safe_command_payload(command, event_type, outcome, reason),
            tenant_id=str(command.tenant_id),
        )
    except Exception:
        logger.exception(
            "desktop-control: failed to mirror command event %s into session_events",
            event.id,
        )
    return event, session_event


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
    device_id = _ensure_shell_bound(audit.shell_id, user)

    metadata = {
        "local_event_id": str(audit.event_id),
        "created_at_ms": audit.created_at_ms,
        "permissions": {
            "screen_recording": audit.screen_recording_status,
            "accessibility": audit.accessibility_status,
            "automation_system_events": audit.automation_system_events_status,
        },
        "device_id": str(device_id),
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
        device_id=device_id,
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

    The server never executes the command directly. It only enqueues an
    observation command for the bound desktop shell to claim with a lease.
    """
    _ensure_user_for_tenant(db, user_id, tenant_id)
    _ensure_session_owned_by_user(db, request.session_id, tenant_id, user_id)
    shell_id, shell_capabilities, device_id = _select_connected_shell(tenant_id, request.shell_id)

    capability = _OBSERVATION_CAPABILITIES[request.action]
    if not bool(shell_capabilities.get("can_observe")):
        reason = f"desktop shell cannot observe; {request.action} request denied"
        command = DesktopCommand(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=request.session_id,
            shell_id=shell_id,
            device_id=device_id,
            capability=capability,
            status="denied",
            source="mcp",
            payload={
                "action": request.action,
                "tool_name": request.tool_name,
                "down_channel": {
                    "available": False,
                    "reason": "shell_not_observable",
                },
                "shell_capabilities": shell_capabilities,
            },
            completed_at=_utcnow(),
        )
        db.add(command)
        db.commit()
        db.refresh(command)
        return _record_command_event(
            db,
            command,
            event_type="desktop_observation_denied",
            outcome="denied",
            reason=reason,
            metadata={
                "down_channel": {
                    "available": False,
                    "reason": "shell_not_observable",
                },
                "shell_capabilities": shell_capabilities,
            },
            mode="control_locked",
        )

    command = DesktopCommand(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=request.session_id,
        shell_id=shell_id,
        device_id=device_id,
        capability=capability,
        status="pending",
        source="mcp",
        payload={
            "action": request.action,
            "tool_name": request.tool_name,
            "down_channel": {
                "available": True,
                "claim_required": True,
            },
            "shell_capabilities": shell_capabilities,
        },
    )
    db.add(command)
    db.commit()
    db.refresh(command)

    return _record_command_event(
        db,
        command,
        event_type="desktop_command_requested",
        outcome="requested",
        metadata={"down_channel": {"available": True}},
    )


def _require_desktop_device_shell(device: DeviceRegistry, shell_id: str) -> None:
    if device.device_type != "desktop":
        raise HTTPException(status_code=403, detail="Device is not a desktop shell")
    if str(device.config.get("shell_id")) != shell_id:
        raise HTTPException(status_code=403, detail="Device token is not bound to shell")


def _expire_stale_leases(db: Session, *, tenant_id: uuid.UUID, shell_id: str, now: datetime) -> int:
    updated = db.query(DesktopCommand).filter(
        DesktopCommand.tenant_id == tenant_id,
        DesktopCommand.shell_id == shell_id,
        DesktopCommand.status.in_(("claimed", "running")),
        DesktopCommand.lease_expires_at < now,
    ).update(
        {
            DesktopCommand.status: "expired",
            DesktopCommand.completed_at: now,
            DesktopCommand.updated_at: now,
        },
        synchronize_session=False,
    )
    if updated:
        db.commit()
    return int(updated or 0)


def claim_next_desktop_command(
    db: Session,
    *,
    device: DeviceRegistry,
    shell_id: str,
    lease_ms: int,
) -> CommandClaim | None:
    """Claim the oldest pending command for this shell using a CAS update.

    If another client wins the race, the status update affects zero rows and
    this call returns no command; nothing executes without a successful claim.
    """
    _require_desktop_device_shell(device, shell_id)
    now = _utcnow()
    _expire_stale_leases(db, tenant_id=device.tenant_id, shell_id=shell_id, now=now)

    command = db.query(DesktopCommand).filter(
        DesktopCommand.tenant_id == device.tenant_id,
        DesktopCommand.shell_id == shell_id,
        DesktopCommand.device_id == device.id,
        DesktopCommand.status.in_(_CLAIMABLE_STATUSES),
    ).order_by(DesktopCommand.created_at.asc()).first()
    if command is None:
        return None

    lease_id = secrets.token_urlsafe(24)
    expires_at = now + timedelta(milliseconds=max(1_000, min(lease_ms, 30_000)))
    updated = db.query(DesktopCommand).filter(
        DesktopCommand.id == command.id,
        DesktopCommand.tenant_id == device.tenant_id,
        DesktopCommand.status == "pending",
    ).update(
        {
            DesktopCommand.status: "claimed",
            DesktopCommand.nonce: lease_id,
            DesktopCommand.lease_owner_shell_id: shell_id,
            DesktopCommand.lease_expires_at: expires_at,
            DesktopCommand.claimed_at: now,
            DesktopCommand.updated_at: now,
        },
        synchronize_session=False,
    )
    if updated != 1:
        db.rollback()
        return None

    db.commit()
    db.refresh(command)
    _record_command_event(
        db,
        command,
        event_type="desktop_command_claimed",
        outcome="started",
        metadata={"lease_expires_at": expires_at.isoformat()},
    )
    return CommandClaim(
        command_id=command.id,
        lease_id=lease_id,
        lease_expires_at=expires_at,
        action=_command_action(command),
        capability=command.capability,
        payload=_command_payload(command),
    )


def ack_desktop_command(
    db: Session,
    *,
    device: DeviceRegistry,
    shell_id: str,
    ack: CommandAck,
) -> DesktopCommand:
    _require_desktop_device_shell(device, shell_id)
    now = _utcnow()
    command = db.query(DesktopCommand).filter(
        DesktopCommand.id == ack.command_id,
        DesktopCommand.tenant_id == device.tenant_id,
        DesktopCommand.shell_id == shell_id,
        DesktopCommand.device_id == device.id,
    ).first()
    if command is None:
        raise HTTPException(status_code=404, detail="Desktop command not found")
    if command.status not in _ACKABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Desktop command is {command.status}")
    if command.nonce != ack.lease_id or command.lease_owner_shell_id != shell_id:
        raise HTTPException(status_code=409, detail="Desktop command lease mismatch")
    if command.lease_expires_at and command.lease_expires_at < now:
        command.status = "expired"
        command.completed_at = now
        command.updated_at = now
        db.commit()
        raise HTTPException(status_code=409, detail="Desktop command lease expired")

    status_value, event_type = _safe_ack_outcome(ack.outcome)
    update_values = {
        DesktopCommand.status: status_value,
        DesktopCommand.updated_at: now,
    }
    if status_value in {"succeeded", "failed", "denied"}:
        update_values[DesktopCommand.completed_at] = now

    updated = db.query(DesktopCommand).filter(
        DesktopCommand.id == command.id,
        DesktopCommand.status.in_(_ACKABLE_STATUSES),
        DesktopCommand.nonce == ack.lease_id,
        DesktopCommand.lease_owner_shell_id == shell_id,
    ).update(update_values, synchronize_session=False)
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Desktop command CAS failed")

    db.commit()
    db.refresh(command)
    _record_command_event(
        db,
        command,
        event_type=event_type,
        outcome="started" if status_value == "running" else status_value,
        reason=ack.reason,
        source="tauri",
    )
    return command


def stop_desktop_commands(
    db: Session,
    *,
    device: DeviceRegistry,
    shell_id: str,
    reason: str = "desktop stop preempted command queue",
) -> int:
    _require_desktop_device_shell(device, shell_id)
    now = _utcnow()
    commands = db.query(DesktopCommand).filter(
        DesktopCommand.tenant_id == device.tenant_id,
        DesktopCommand.shell_id == shell_id,
        DesktopCommand.device_id == device.id,
        DesktopCommand.status.in_(_STOP_PREEMPTABLE_STATUSES),
    ).all()
    count = 0
    for command in commands:
        updated = db.query(DesktopCommand).filter(
            DesktopCommand.id == command.id,
            DesktopCommand.status.in_(_STOP_PREEMPTABLE_STATUSES),
        ).update(
            {
                DesktopCommand.status: "preempted",
                DesktopCommand.completed_at: now,
                DesktopCommand.updated_at: now,
            },
            synchronize_session=False,
        )
        if updated == 1:
            count += 1
            command.status = "preempted"
            _record_command_event(
                db,
                command,
                event_type="desktop_command_preempted",
                outcome="preempted",
                reason=reason,
            )
        else:
            db.rollback()
    if count:
        db.commit()
    return count
