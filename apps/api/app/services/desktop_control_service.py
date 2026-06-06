"""Governed Luna desktop-control audit helpers."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
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

_TERMINAL_COMMAND_STATUSES = {
    "succeeded",
    "failed",
    "denied",
    "preempted",
    "expired",
}

_CLAIMABLE_COMMAND_STATUSES = {
    "pending",
    "claimed",
    "running",
}

_COMMAND_ACTION_CAPABILITIES = {
    "capture_screenshot": "screenshot",
    "get_active_app": "active_app",
    "read_clipboard": "clipboard_read",
}

_COMMAND_TOOL_ACTIONS = {
    "desktop_observe_screen": "capture_screenshot",
    "desktop_get_active_app": "get_active_app",
    "desktop_read_clipboard": "read_clipboard",
}

_SAFE_METADATA_KEYS = {
    "can_observe",
    "control_mode",
    "payload_key_count",
    "result_fields",
    "result_kind",
    "result_size_bytes",
    "result_size_chars",
    "tool_name",
}

_SAFE_RESULT_KINDS = {"binary", "string", "json", "error", "unsupported", "unknown"}
_SAFE_RESULT_FIELDS = {"app", "title"}
_SAFE_CONTROL_MODES = {"control_locked", "observe", "stopped"}

DEFAULT_COMMAND_LEASE_SECONDS = 30
DEFAULT_COMMAND_PENDING_TTL_SECONDS = 300


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
class DesktopCommandEnqueue:
    session_id: uuid.UUID
    action: str
    tool_name: str
    shell_id: str | None
    payload: dict[str, Any]
    nonce: str | None = None


@dataclass(frozen=True)
class DesktopCommandClaim:
    session_id: uuid.UUID
    shell_id: str
    lease_seconds: int = DEFAULT_COMMAND_LEASE_SECONDS


@dataclass(frozen=True)
class DesktopCommandCompletion:
    command_id: uuid.UUID
    shell_id: str
    status: Literal["succeeded", "failed", "denied", "preempted"]
    reason: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class DesktopCommandStop:
    session_id: uuid.UUID
    shell_id: str
    reason: str = "desktop control stopped"


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


def _utcnow() -> datetime:
    return datetime.utcnow()


def _safe_metadata(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    safe: dict[str, Any] = {}
    for key, value in raw.items():
        normalized_key = str(key)
        if normalized_key not in _SAFE_METADATA_KEYS:
            continue
        if normalized_key == "tool_name" and value in _COMMAND_TOOL_ACTIONS:
            safe[normalized_key] = value
        elif normalized_key == "result_kind" and value in _SAFE_RESULT_KINDS:
            safe[normalized_key] = value
        elif normalized_key in {
            "payload_key_count",
            "result_size_bytes",
            "result_size_chars",
        } and isinstance(value, int):
            safe[normalized_key] = max(0, value)
        elif normalized_key == "control_mode" and value in _SAFE_CONTROL_MODES:
            safe[normalized_key] = value
        elif normalized_key == "can_observe" and isinstance(value, bool):
            safe[normalized_key] = value
        elif normalized_key == "result_fields" and isinstance(value, list):
            safe[normalized_key] = [
                item
                for item in value
                if isinstance(item, str) and item in _SAFE_RESULT_FIELDS
            ][:20]
    return safe


def _safe_request_metadata(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    return {"payload_key_count": len(raw)}


def _safe_command_reason(action: str, outcome: str, reason: str | None) -> str | None:
    if not reason:
        return None
    normalized = " ".join(reason.split())
    if normalized.startswith("desktop control stopped;"):
        return f"desktop control stopped; {action} preempted"
    if normalized.startswith("desktop observe locked;"):
        return f"desktop observe locked; {action} denied"
    if normalized.startswith("desktop observation permission "):
        return f"desktop observation permission denied; {action} denied"
    if normalized.startswith("unsupported desktop command action:"):
        return "unsupported desktop command action"
    if normalized == "desktop command pending ttl expired":
        return normalized
    if normalized in {"operator Stop", "local Stop latched", "desktop control stopped"}:
        return normalized
    if outcome == "expired":
        return "desktop command lease expired"
    if outcome == "preempted":
        return "desktop command preempted"
    if outcome == "denied":
        return "desktop command denied"
    if outcome == "failed":
        return "desktop command failed"
    return None


def _display_safe_command_payload(command: DesktopCommand) -> dict[str, Any]:
    return {
        "desktop_command_id": str(command.id),
        "correlation_id": str(command.correlation_id) if command.correlation_id else None,
        "shell_id": command.shell_id,
        "device_id": str(command.device_id) if command.device_id else None,
        "source": command.source,
        "capability": command.capability,
        "status": command.status,
        "lease_expires_at": (
            command.lease_expires_at.isoformat() if command.lease_expires_at else None
        ),
        "created_at": command.created_at.isoformat() if command.created_at else None,
        "updated_at": command.updated_at.isoformat() if command.updated_at else None,
    }


def _publish_display_safe_session_event(
    session_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    *,
    tenant_id: uuid.UUID,
) -> dict[str, Any] | None:
    try:
        return publish_session_event(
            str(session_id),
            event_type,
            payload,
            tenant_id=str(tenant_id),
        )
    except Exception:
        logger.exception(
            "desktop-control: failed to mirror %s into session_events",
            event_type,
        )
        return None


def _record_command_event(
    db: Session,
    command: DesktopCommand,
    *,
    event_type: str,
    source: str,
    outcome: str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DesktopCommandEvent:
    action = str((command.payload or {}).get("action") or "desktop_command")
    event = DesktopCommandEvent(
        tenant_id=command.tenant_id,
        user_id=command.user_id,
        session_id=command.session_id,
        desktop_command_id=command.id,
        correlation_id=command.correlation_id,
        event_type=event_type,
        source=source,
        action=action,
        capability=command.capability,
        outcome=outcome,
        reason=_safe_command_reason(action, outcome, reason),
        mode=(command.payload or {}).get("mode"),
        shell_id=command.shell_id,
        device_id=command.device_id,
        event_metadata={
            "desktop_command_id": str(command.id),
            "status": command.status,
            **_safe_metadata(metadata),
        },
    )
    db.add(event)
    return event


def _matching_enqueued_command_for_nonce(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request: DesktopCommandEnqueue,
) -> DesktopCommand | None:
    if not request.nonce:
        return None
    existing = db.query(DesktopCommand).filter(
        DesktopCommand.tenant_id == tenant_id,
        DesktopCommand.nonce == request.nonce,
    ).first()
    if not existing:
        return None
    payload = existing.payload or {}
    if (
        existing.user_id == user_id
        and existing.session_id == request.session_id
        and payload.get("action") == request.action
        and payload.get("tool_name") == request.tool_name
        and (request.shell_id is None or existing.shell_id == request.shell_id)
    ):
        return existing
    raise HTTPException(status_code=409, detail="Desktop command nonce already used")


def _queued_event_for_command(
    db: Session,
    command: DesktopCommand,
    *,
    tool_name: str,
) -> DesktopCommandEvent:
    event = db.query(DesktopCommandEvent).filter(
        DesktopCommandEvent.tenant_id == command.tenant_id,
        DesktopCommandEvent.desktop_command_id == command.id,
        DesktopCommandEvent.event_type == "desktop_command_queued",
    ).order_by(DesktopCommandEvent.created_at.asc()).first()
    if event:
        return event
    event = _record_command_event(
        db,
        command,
        event_type="desktop_command_queued",
        source="mcp",
        outcome="requested",
        metadata={"tool_name": tool_name},
    )
    db.commit()
    db.refresh(event)
    return event


def _device_for_user_shell(
    db: Session,
    *,
    user: User,
    shell_id: str,
    device_token: str | None,
) -> uuid.UUID:
    if not device_token:
        raise HTTPException(status_code=401, detail="X-Device-Token required")
    import hashlib

    token_hash = hashlib.sha256(device_token.encode()).hexdigest()
    device = db.query(DeviceRegistry).filter(
        DeviceRegistry.tenant_id == user.tenant_id,
        DeviceRegistry.device_type == "desktop",
        DeviceRegistry.device_token_hash == token_hash,
    ).first()
    if not device:
        raise HTTPException(status_code=401, detail="Invalid desktop device token")
    if (device.config or {}).get("shell_id") != shell_id:
        raise HTTPException(status_code=403, detail="Device is not bound to shell")
    return device.id


def _expire_stale_leases(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    now: datetime,
    session_id: uuid.UUID | None = None,
    shell_id: str | None = None,
    device_id: uuid.UUID | None = None,
) -> list[DesktopCommandEvent]:
    query = db.query(DesktopCommand).filter(
        DesktopCommand.tenant_id == tenant_id,
        DesktopCommand.status.in_(("claimed", "running")),
        DesktopCommand.lease_expires_at.is_not(None),
        DesktopCommand.lease_expires_at <= now,
    )
    if session_id:
        query = query.filter(DesktopCommand.session_id == session_id)
    if shell_id:
        query = query.filter(DesktopCommand.shell_id == shell_id)
    if device_id:
        query = query.filter(DesktopCommand.device_id == device_id)

    events: list[DesktopCommandEvent] = []
    for command in query.order_by(DesktopCommand.created_at.asc()).all():
        result = db.execute(
            update(DesktopCommand)
            .where(
                DesktopCommand.id == command.id,
                DesktopCommand.tenant_id == tenant_id,
                DesktopCommand.status.in_(("claimed", "running")),
                DesktopCommand.lease_expires_at.is_not(None),
                DesktopCommand.lease_expires_at <= now,
            )
            .values(
                status="expired",
                completed_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            continue
        command.status = "expired"
        command.completed_at = now
        command.updated_at = now
        events.append(
            _record_command_event(
                db,
                command,
                event_type="desktop_command_expired",
                source="api",
                outcome="expired",
                reason="desktop command lease expired",
            )
        )
    return events


def _expire_stale_pending_commands(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    now: datetime,
    session_id: uuid.UUID | None = None,
    shell_id: str | None = None,
    device_id: uuid.UUID | None = None,
    ttl_seconds: int = DEFAULT_COMMAND_PENDING_TTL_SECONDS,
) -> list[DesktopCommandEvent]:
    cutoff = now - timedelta(seconds=max(1, int(ttl_seconds)))
    query = db.query(DesktopCommand).filter(
        DesktopCommand.tenant_id == tenant_id,
        DesktopCommand.status == "pending",
        DesktopCommand.created_at <= cutoff,
    )
    if session_id:
        query = query.filter(DesktopCommand.session_id == session_id)
    if shell_id:
        query = query.filter(DesktopCommand.shell_id == shell_id)
    if device_id:
        query = query.filter(DesktopCommand.device_id == device_id)

    events: list[DesktopCommandEvent] = []
    for command in query.order_by(DesktopCommand.created_at.asc()).all():
        result = db.execute(
            update(DesktopCommand)
            .where(
                DesktopCommand.id == command.id,
                DesktopCommand.tenant_id == tenant_id,
                DesktopCommand.status == "pending",
                DesktopCommand.created_at <= cutoff,
            )
            .values(
                status="expired",
                completed_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            continue
        command.status = "expired"
        command.completed_at = now
        command.updated_at = now
        events.append(
            _record_command_event(
                db,
                command,
                event_type="desktop_command_expired",
                source="api",
                outcome="expired",
                reason="desktop command pending ttl expired",
            )
        )
    return events


def _publish_display_safe_command_event(
    event: DesktopCommandEvent,
    *,
    status: str,
    tenant_id: uuid.UUID,
) -> dict[str, Any] | None:
    return _publish_display_safe_session_event(
        event.session_id,
        event.event_type,
        {
            "desktop_event_id": str(event.id),
            "desktop_command_id": str(event.desktop_command_id),
            "shell_id": event.shell_id,
            "device_id": str(event.device_id) if event.device_id else None,
            "capability": event.capability,
            "status": status,
            "outcome": event.outcome,
            "reason": event.reason,
        },
        tenant_id=tenant_id,
    )


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

    This phase intentionally does not execute desktop observations from the
    server side: Tauri has no command-claim down-channel yet. Recording a
    denied event keeps the MCP tool honest while preserving tenant/session/shell
    auditability and display-safe session replay.
    """
    _ensure_user_for_tenant(db, user_id, tenant_id)
    _ensure_session_owned_by_user(db, request.session_id, tenant_id, user_id)
    shell_id, shell_capabilities, device_id = _select_connected_shell(tenant_id, request.shell_id)

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
        device_id=device_id,
        event_metadata={
            "request_id": str(uuid.uuid4()),
            "tool_name": request.tool_name,
            "device_id": str(device_id),
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


def enqueue_desktop_command(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request: DesktopCommandEnqueue,
) -> tuple[DesktopCommand, DesktopCommandEvent, dict[str, Any] | None]:
    """Create a pending command for a connected Luna desktop shell.

    This is only a down-channel queue contract. Tauri still decides locally
    whether a claimed command can execute, and pointer/keyboard actuation is
    not introduced here.
    """
    _ensure_user_for_tenant(db, user_id, tenant_id)
    _ensure_session_owned_by_user(db, request.session_id, tenant_id, user_id)
    expected_action = _COMMAND_TOOL_ACTIONS[request.tool_name]
    if request.action != expected_action:
        raise HTTPException(status_code=422, detail="tool_name does not match action")

    existing = _matching_enqueued_command_for_nonce(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        request=request,
    )
    if existing:
        return existing, _queued_event_for_command(
            db,
            existing,
            tool_name=request.tool_name,
        ), None

    shell_id, shell_capabilities, device_id = _select_connected_shell(tenant_id, request.shell_id)
    capability = _COMMAND_ACTION_CAPABILITIES[request.action]
    required_capability = "can_observe"
    if not bool(shell_capabilities.get(required_capability)):
        raise HTTPException(status_code=409, detail="Desktop shell cannot observe")

    now = _utcnow()
    command = DesktopCommand(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=request.session_id,
        shell_id=shell_id,
        device_id=device_id,
        capability=capability,
        status="pending",
        source="mcp",
        nonce=request.nonce,
        payload={
            "action": request.action,
            "tool_name": request.tool_name,
            "mode": "observe",
            "request": _safe_request_metadata(request.payload),
        },
        created_at=now,
        updated_at=now,
    )
    db.add(command)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = _matching_enqueued_command_for_nonce(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            request=request,
        )
        if existing:
            return existing, _queued_event_for_command(
                db,
                existing,
                tool_name=request.tool_name,
            ), None
        raise HTTPException(status_code=409, detail="Desktop command nonce already used")
    event = _record_command_event(
        db,
        command,
        event_type="desktop_command_queued",
        source="mcp",
        outcome="requested",
        metadata={
            "tool_name": request.tool_name,
            **_safe_request_metadata(request.payload),
        },
    )
    db.commit()
    db.refresh(command)
    db.refresh(event)

    session_event = _publish_display_safe_session_event(
        request.session_id,
        event.event_type,
        {
            **_display_safe_command_payload(command),
            "desktop_event_id": str(event.id),
            "outcome": event.outcome,
        },
        tenant_id=tenant_id,
    )
    return command, event, session_event


def claim_next_desktop_command(
    db: Session,
    *,
    user: User,
    device_token: str | None,
    claim: DesktopCommandClaim,
) -> tuple[DesktopCommand | None, DesktopCommandEvent | None, dict[str, Any] | None]:
    _ensure_session_owned(db, claim.session_id, user)
    connected_device_id = _ensure_shell_bound(claim.shell_id, user)
    token_device_id = _device_for_user_shell(
        db,
        user=user,
        shell_id=claim.shell_id,
        device_token=device_token,
    )
    if str(connected_device_id) != str(token_device_id):
        raise HTTPException(status_code=403, detail="Device token does not match active shell")

    now = _utcnow()
    expired_events = _expire_stale_leases(
        db,
        tenant_id=user.tenant_id,
        now=now,
        session_id=claim.session_id,
        shell_id=claim.shell_id,
        device_id=token_device_id,
    )
    expired_events.extend(
        _expire_stale_pending_commands(
            db,
            tenant_id=user.tenant_id,
            now=now,
            session_id=claim.session_id,
            shell_id=claim.shell_id,
            device_id=token_device_id,
        )
    )
    lease_seconds = max(5, min(int(claim.lease_seconds), 120))
    lease_expires_at = now + timedelta(seconds=lease_seconds)

    command = db.query(DesktopCommand).filter(
        DesktopCommand.tenant_id == user.tenant_id,
        DesktopCommand.session_id == claim.session_id,
        DesktopCommand.shell_id == claim.shell_id,
        DesktopCommand.device_id == token_device_id,
        DesktopCommand.status == "pending",
    ).order_by(DesktopCommand.created_at.asc()).first()
    if not command:
        db.commit()
        for event in expired_events:
            _publish_display_safe_command_event(
                event,
                status="expired",
                tenant_id=user.tenant_id,
            )
        return None, None, None

    result = db.execute(
        update(DesktopCommand)
        .where(
            DesktopCommand.id == command.id,
            DesktopCommand.tenant_id == user.tenant_id,
            DesktopCommand.status == "pending",
        )
        .values(
            status="claimed",
            lease_owner_shell_id=claim.shell_id,
            lease_expires_at=lease_expires_at,
            claimed_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Desktop command was claimed by another worker")

    command.status = "claimed"
    command.lease_owner_shell_id = claim.shell_id
    command.lease_expires_at = lease_expires_at
    command.claimed_at = now
    command.updated_at = now
    event = _record_command_event(
        db,
        command,
        event_type="desktop_command_claimed",
        source="tauri",
        outcome="started",
        metadata={"lease_expires_at": lease_expires_at.isoformat()},
    )
    db.commit()
    db.refresh(command)
    db.refresh(event)
    for expired_event in expired_events:
        _publish_display_safe_command_event(
            expired_event,
            status="expired",
            tenant_id=user.tenant_id,
        )
    session_event = _publish_display_safe_session_event(
        command.session_id,
        event.event_type,
        {
            **_display_safe_command_payload(command),
            "desktop_event_id": str(event.id),
            "outcome": event.outcome,
        },
        tenant_id=user.tenant_id,
    )
    return command, event, session_event


def complete_desktop_command(
    db: Session,
    *,
    user: User,
    device_token: str | None,
    completion: DesktopCommandCompletion,
) -> tuple[DesktopCommand, DesktopCommandEvent | None, dict[str, Any] | None, bool]:
    command = db.query(DesktopCommand).filter(
        DesktopCommand.id == completion.command_id,
        DesktopCommand.tenant_id == user.tenant_id,
    ).first()
    if not command:
        raise HTTPException(status_code=404, detail="Desktop command not found")
    _ensure_session_owned(db, command.session_id, user)
    token_device_id = _device_for_user_shell(
        db,
        user=user,
        shell_id=completion.shell_id,
        device_token=device_token,
    )
    if str(command.shell_id) != completion.shell_id or str(command.device_id) != str(token_device_id):
        raise HTTPException(status_code=403, detail="Desktop command is not owned by this shell")
    if command.status in _TERMINAL_COMMAND_STATUSES:
        return command, None, None, True
    connected_device_id = _ensure_shell_bound(completion.shell_id, user)
    if str(connected_device_id) != str(token_device_id):
        raise HTTPException(status_code=403, detail="Device token does not match active shell")
    if command.status not in ("claimed", "running"):
        raise HTTPException(status_code=409, detail="Desktop command is not claimed")

    now = _utcnow()
    if command.lease_expires_at and command.lease_expires_at <= now:
        command.status = "expired"
        command.completed_at = now
        command.updated_at = now
        event = _record_command_event(
            db,
            command,
            event_type="desktop_command_expired",
            source="api",
            outcome="expired",
            reason="desktop command lease expired",
        )
        db.commit()
        db.refresh(command)
        db.refresh(event)
        session_event = _publish_display_safe_session_event(
            command.session_id,
            event.event_type,
            {
                **_display_safe_command_payload(command),
                "desktop_event_id": str(event.id),
                "outcome": event.outcome,
                "reason": event.reason,
            },
            tenant_id=user.tenant_id,
        )
        return command, event, session_event, False

    result = db.execute(
        update(DesktopCommand)
        .where(
            DesktopCommand.id == command.id,
            DesktopCommand.tenant_id == user.tenant_id,
            DesktopCommand.status.in_(("claimed", "running")),
            DesktopCommand.lease_owner_shell_id == completion.shell_id,
            or_(
                DesktopCommand.lease_expires_at.is_(None),
                DesktopCommand.lease_expires_at > now,
            ),
        )
        .values(
            status=completion.status,
            completed_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Desktop command lease is no longer valid")

    command.status = completion.status
    command.completed_at = now
    command.updated_at = now
    event_type = "desktop_command_preempted" if completion.status == "preempted" else "desktop_command_completed"
    event = _record_command_event(
        db,
        command,
        event_type=event_type,
        source="tauri",
        outcome=completion.status,
        reason=completion.reason,
        metadata=completion.metadata,
    )
    db.commit()
    db.refresh(command)
    db.refresh(event)
    session_event = _publish_display_safe_session_event(
        command.session_id,
        event.event_type,
        {
            **_display_safe_command_payload(command),
            "desktop_event_id": str(event.id),
            "outcome": event.outcome,
            "reason": event.reason,
        },
        tenant_id=user.tenant_id,
    )
    return command, event, session_event, False


def preempt_desktop_commands_for_stop(
    db: Session,
    *,
    user: User,
    device_token: str | None,
    stop: DesktopCommandStop,
) -> tuple[int, list[DesktopCommandEvent], list[dict[str, Any] | None]]:
    _ensure_session_owned(db, stop.session_id, user)
    connected_device_id = _ensure_shell_bound(stop.shell_id, user)
    token_device_id = _device_for_user_shell(
        db,
        user=user,
        shell_id=stop.shell_id,
        device_token=device_token,
    )
    if str(connected_device_id) != str(token_device_id):
        raise HTTPException(status_code=403, detail="Device token does not match active shell")

    now = _utcnow()
    expired_events = _expire_stale_leases(
        db,
        tenant_id=user.tenant_id,
        now=now,
        session_id=stop.session_id,
        shell_id=stop.shell_id,
        device_id=token_device_id,
    )
    commands = db.query(DesktopCommand).filter(
        DesktopCommand.tenant_id == user.tenant_id,
        DesktopCommand.session_id == stop.session_id,
        DesktopCommand.shell_id == stop.shell_id,
        DesktopCommand.device_id == token_device_id,
        DesktopCommand.status.in_(tuple(_CLAIMABLE_COMMAND_STATUSES)),
    ).order_by(DesktopCommand.created_at.asc()).all()

    events: list[DesktopCommandEvent] = []
    for command in commands:
        result = db.execute(
            update(DesktopCommand)
            .where(
                DesktopCommand.id == command.id,
                DesktopCommand.tenant_id == user.tenant_id,
                DesktopCommand.status.in_(tuple(_CLAIMABLE_COMMAND_STATUSES)),
            )
            .values(
                status="preempted",
                completed_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            continue
        command.status = "preempted"
        command.completed_at = now
        command.updated_at = now
        events.append(
            _record_command_event(
                db,
                command,
                event_type="desktop_command_preempted",
                source="tauri",
                outcome="preempted",
                reason=stop.reason,
            )
        )

    db.commit()
    for expired_event in expired_events:
        _publish_display_safe_command_event(
            expired_event,
            status="expired",
            tenant_id=user.tenant_id,
        )
    session_events = [
        _publish_display_safe_command_event(
            event,
            status="preempted",
            tenant_id=user.tenant_id,
        )
        for event in events
    ]
    return len(events), events, session_events
