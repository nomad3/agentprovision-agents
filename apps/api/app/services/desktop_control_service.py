"""Governed Luna desktop-control audit helpers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fastapi import HTTPException
from sqlalchemy import case, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat import ChatSession
from app.models.desktop_command import DesktopCommand
from app.models.desktop_command_approval_grant import DesktopCommandApprovalGrant
from app.models.desktop_command_envelope_nonce import DesktopCommandEnvelopeNonce
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

_NATIVE_CONTROL_CAPABILITIES = {
    "pointer_move": "pointer_control",
    "pointer_click": "pointer_control",
    "keyboard_type": "keyboard_control",
    "keyboard_key_chord": "keyboard_control",
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

_REVOKED_DESKTOP_DEVICE_STATUSES = {"revoked", "disabled"}

_COMMAND_ACTION_CAPABILITIES = {
    **_OBSERVATION_CAPABILITIES,
    **_NATIVE_CONTROL_CAPABILITIES,
}

_COMMAND_TOOL_ACTIONS = {
    "desktop_observe_screen": "capture_screenshot",
    "desktop_get_active_app": "get_active_app",
    "desktop_read_clipboard": "read_clipboard",
    "desktop_pointer_move": "pointer_move",
    "desktop_pointer_click": "pointer_click",
    "desktop_keyboard_type": "keyboard_type",
    "desktop_keyboard_key_chord": "keyboard_key_chord",
}

_DISABLED_NATIVE_CONTROL_ACTIONS = frozenset(_NATIVE_CONTROL_CAPABILITIES)

_SAFE_METADATA_KEYS = {
    "can_observe",
    "control_mode",
    "envelope_hash",
    "envelope_nonce",
    "envelope_policy_version",
    "approval_id",
    "approval_remaining_actions",
    "approval_risk_tier",
    "payload_key_count",
    "result_fields",
    "result_kind",
    "result_size_bytes",
    "result_size_chars",
    "tool_name",
}

_SAFE_RESULT_KINDS = {"binary", "string", "json", "error", "unsupported", "unknown"}
_SAFE_RESULT_FIELDS = {"app", "title_chars", "title_present"}
_SAFE_CONTROL_MODES = {"control_locked", "observe", "stopped"}

DEFAULT_COMMAND_LEASE_SECONDS = 30
DEFAULT_COMMAND_PENDING_TTL_SECONDS = 300
CURRENT_DESKTOP_COMMAND_ENVELOPE_POLICY_VERSION = 1
DESKTOP_COMMAND_ENVELOPE_SCHEMA = "agentprovision.desktop_command_envelope.v1"
DESKTOP_COMMAND_ENVELOPE_ALGORITHM = "HMAC-SHA256"
DESKTOP_COMMAND_ENVELOPE_ED25519_ALGORITHM = "Ed25519"
DESKTOP_COMMAND_ENVELOPE_KEY_ID = "agentprovision-desktop-command-hmac-v1"
DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID = "agentprovision-desktop-command-ed25519-v1"


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
    approval_id: uuid.UUID | None = None


@dataclass(frozen=True)
class DesktopCommandApprovalGrantCreate:
    session_id: uuid.UUID
    risk_tier: Literal["observe", "native_control"]
    capability: str
    shell_id: str | None = None
    desktop_command_id: uuid.UUID | None = None
    max_actions: int = 1
    expires_in_seconds: int = 60
    target_binding: dict[str, Any] | None = None


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


def _ensure_desktop_shell_id(shell_id: str) -> None:
    if not isinstance(shell_id, str) or not shell_id.startswith("desktop-"):
        raise HTTPException(status_code=409, detail="Desktop shell id is invalid")


def _bound_device_for_shell(snapshot: dict[str, Any], shell_id: str) -> uuid.UUID:
    _ensure_desktop_shell_id(shell_id)
    raw_device_id = (snapshot.get("shell_devices") or {}).get(shell_id)
    if not raw_device_id:
        raise HTTPException(status_code=409, detail="Desktop shell device is not bound")
    try:
        return uuid.UUID(str(raw_device_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=409, detail="Desktop shell device binding is invalid")


def _ensure_shell_bound(shell_id: str, user: User) -> uuid.UUID:
    _ensure_desktop_shell_id(shell_id)
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
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
        elif normalized_key in {"envelope_hash", "envelope_nonce"} and isinstance(value, str):
            safe[normalized_key] = value[:96]
        elif normalized_key == "envelope_policy_version" and isinstance(value, int):
            safe[normalized_key] = value
        elif normalized_key == "approval_id" and isinstance(value, str):
            try:
                safe[normalized_key] = str(uuid.UUID(value))
            except (TypeError, ValueError):
                continue
        elif normalized_key == "approval_risk_tier" and value in {"observe", "native_control"}:
            safe[normalized_key] = value
        elif normalized_key == "approval_remaining_actions" and isinstance(value, int):
            safe[normalized_key] = max(0, value)
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
    if normalized.startswith("desktop native control disabled;"):
        return f"desktop native control disabled; {action} denied"
    if normalized.startswith("desktop observation permission "):
        return f"desktop observation permission denied; {action} denied"
    if normalized.startswith("unsupported desktop command action:"):
        return "unsupported desktop command action"
    if normalized in {
        "desktop command envelope missing",
        "desktop command envelope nonce missing",
        "desktop command envelope nonce mismatch",
        "desktop command envelope expired",
        "desktop command envelope replay denied",
        "desktop command envelope signature invalid",
        "desktop command envelope binding mismatch",
        "desktop command approval grant missing",
        "desktop command approval grant expired",
        "desktop command approval grant revoked",
        "desktop command approval grant exhausted",
        "desktop command approval grant binding mismatch",
        "desktop command approval grant replay denied",
    }:
        return normalized
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
        "approval_id": str(command.approval_id) if command.approval_id else None,
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
        approval_id=command.approval_id,
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
        and (request.approval_id is None or existing.approval_id == request.approval_id)
    ):
        return existing
    raise HTTPException(status_code=409, detail="Desktop command nonce already used")


def _event_for_existing_command(
    db: Session,
    command: DesktopCommand,
    *,
    tool_name: str,
) -> DesktopCommandEvent:
    event = db.query(DesktopCommandEvent).filter(
        DesktopCommandEvent.tenant_id == command.tenant_id,
        DesktopCommandEvent.desktop_command_id == command.id,
    ).order_by(DesktopCommandEvent.created_at.asc()).first()
    if event:
        return event
    if command.status != "pending":
        event = _record_command_event(
            db,
            command,
            event_type="desktop_command_completed",
            source="api",
            outcome=command.status,
            reason=(
                "desktop native control disabled; "
                f"{(command.payload or {}).get('action') or 'command'} denied"
            ),
            metadata={"tool_name": tool_name},
        )
        db.commit()
        db.refresh(event)
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


def _enqueue_disabled_native_control_command(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request: DesktopCommandEnqueue,
    shell_id: str,
    device_id: uuid.UUID,
) -> tuple[DesktopCommand, DesktopCommandEvent, dict[str, Any] | None]:
    now = _utcnow()
    capability = _COMMAND_ACTION_CAPABILITIES[request.action]
    reason = f"desktop native control disabled; {request.action} denied"
    command = DesktopCommand(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=request.session_id,
        shell_id=shell_id,
        device_id=device_id,
        approval_id=request.approval_id,
        capability=capability,
        status="denied",
        source="mcp",
        nonce=request.nonce,
        payload={
            "action": request.action,
            "tool_name": request.tool_name,
            "mode": "control_locked",
            "request": _safe_request_metadata(request.payload),
            "native_control": {
                "enabled": False,
                "reason": "signed envelopes and approval grants required",
            },
        },
        completed_at=now,
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
            return existing, _event_for_existing_command(
                db,
                existing,
                tool_name=request.tool_name,
            ), None
        raise HTTPException(status_code=409, detail="Desktop command nonce already used")

    event = _record_command_event(
        db,
        command,
        event_type="desktop_command_completed",
        source="api",
        outcome="denied",
        reason=reason,
        metadata={
            "tool_name": request.tool_name,
            **_safe_request_metadata(request.payload),
            "result_kind": "unsupported",
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
            "reason": event.reason,
        },
        tenant_id=tenant_id,
    )
    return command, event, session_event


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
    if str(device.status or "").lower() in _REVOKED_DESKTOP_DEVICE_STATUSES:
        raise HTTPException(status_code=403, detail="Desktop device is revoked")
    if (device.config or {}).get("shell_id") != shell_id:
        raise HTTPException(status_code=403, detail="Device is not bound to shell")
    return device.id


def _risk_tier_for_action(action: str) -> Literal["observe", "native_control"]:
    return "native_control" if action in _NATIVE_CONTROL_CAPABILITIES else "observe"


def _capability_matches_risk_tier(capability: str, risk_tier: str) -> bool:
    if risk_tier == "observe":
        return capability in set(_OBSERVATION_CAPABILITIES.values())
    if risk_tier == "native_control":
        return capability in set(_NATIVE_CONTROL_CAPABILITIES.values())
    return False


def _approval_metadata(grant: DesktopCommandApprovalGrant | None) -> dict[str, Any]:
    if grant is None:
        return {}
    return {
        "approval_id": str(grant.id),
        "approval_risk_tier": grant.risk_tier,
        "approval_remaining_actions": int(grant.remaining_actions or 0),
    }


def _approval_payload(grant: DesktopCommandApprovalGrant) -> dict[str, Any]:
    return {
        "approval_id": str(grant.id),
        "risk_tier": grant.risk_tier,
        "capability": grant.capability,
        "remaining_actions": int(grant.remaining_actions or 0),
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
    }


def _deny_pending_command_for_approval_failure(
    db: Session,
    command: DesktopCommand,
    *,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[DesktopCommand, DesktopCommandEvent, dict[str, Any] | None]:
    now = _utcnow()
    result = db.execute(
        update(DesktopCommand)
        .where(
            DesktopCommand.id == command.id,
            DesktopCommand.tenant_id == command.tenant_id,
            DesktopCommand.status == "pending",
        )
        .values(
            status="denied",
            completed_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Desktop command approval claim is no longer valid")
    command.status = "denied"
    command.completed_at = now
    command.updated_at = now
    event = _record_command_event(
        db,
        command,
        event_type="desktop_command_approval_denied",
        source="api",
        outcome="denied",
        reason=reason,
        metadata=metadata,
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
        tenant_id=command.tenant_id,
    )
    return command, event, session_event


def _matching_approval_grant(
    db: Session,
    command: DesktopCommand,
    *,
    user: User,
    token_device_id: uuid.UUID,
    action: str,
    risk_tier: str,
    now: datetime,
) -> DesktopCommandApprovalGrant | None:
    query = db.query(DesktopCommandApprovalGrant).filter(
        DesktopCommandApprovalGrant.tenant_id == command.tenant_id,
        DesktopCommandApprovalGrant.user_id == user.id,
        DesktopCommandApprovalGrant.session_id == command.session_id,
        DesktopCommandApprovalGrant.shell_id == command.shell_id,
        DesktopCommandApprovalGrant.device_id == token_device_id,
        DesktopCommandApprovalGrant.risk_tier == risk_tier,
        DesktopCommandApprovalGrant.capability == command.capability,
        DesktopCommandApprovalGrant.status == "active",
        DesktopCommandApprovalGrant.remaining_actions > 0,
        DesktopCommandApprovalGrant.expires_at > now,
    )
    if command.approval_id:
        query = query.filter(DesktopCommandApprovalGrant.id == command.approval_id)
    else:
        query = query.filter(
            or_(
                DesktopCommandApprovalGrant.desktop_command_id == command.id,
                DesktopCommandApprovalGrant.desktop_command_id.is_(None),
            )
        )
    grant = query.order_by(
        DesktopCommandApprovalGrant.desktop_command_id.desc(),
        DesktopCommandApprovalGrant.created_at.asc(),
    ).first()
    if grant is None:
        return None
    if grant.desktop_command_id and str(grant.desktop_command_id) != str(command.id):
        return None
    target_action = (grant.target_binding or {}).get("action")
    if target_action and target_action != action:
        return None
    return grant


def _approval_denial_reason(
    db: Session,
    command: DesktopCommand,
    *,
    now: datetime,
) -> str:
    if not command.approval_id:
        command_bound_exists = db.query(DesktopCommandApprovalGrant.id).filter(
            DesktopCommandApprovalGrant.tenant_id == command.tenant_id,
            DesktopCommandApprovalGrant.desktop_command_id == command.id,
        ).first()
        if not command_bound_exists:
            return "desktop command approval grant missing"
    candidate = None
    if command.approval_id:
        candidate = db.query(DesktopCommandApprovalGrant).filter(
            DesktopCommandApprovalGrant.tenant_id == command.tenant_id,
            DesktopCommandApprovalGrant.id == command.approval_id,
        ).first()
    else:
        candidate = db.query(DesktopCommandApprovalGrant).filter(
            DesktopCommandApprovalGrant.tenant_id == command.tenant_id,
            DesktopCommandApprovalGrant.desktop_command_id == command.id,
        ).first()
    if not candidate:
        return "desktop command approval grant missing"
    expires_at = _as_aware_utc(candidate.expires_at)
    if candidate.status == "revoked":
        return "desktop command approval grant revoked"
    if expires_at is None or expires_at <= now or candidate.status == "expired":
        return "desktop command approval grant expired"
    if candidate.status == "consumed" or int(candidate.remaining_actions or 0) <= 0:
        return "desktop command approval grant exhausted"
    return "desktop command approval grant binding mismatch"


def _consume_approval_grant_or_deny(
    db: Session,
    command: DesktopCommand,
    *,
    user: User,
    token_device_id: uuid.UUID,
    now: datetime,
) -> tuple[DesktopCommand, DesktopCommandEvent, dict[str, Any] | None] | DesktopCommandApprovalGrant | None:
    action = str((command.payload or {}).get("action") or "desktop_command")
    risk_tier = _risk_tier_for_action(action)
    grant = _matching_approval_grant(
        db,
        command,
        user=user,
        token_device_id=token_device_id,
        action=action,
        risk_tier=risk_tier,
        now=now,
    )
    if grant is None:
        reason = _approval_denial_reason(db, command, now=now)
        if reason == "desktop command approval grant missing" and command.approval_id is None:
            return None
        return _deny_pending_command_for_approval_failure(
            db,
            command,
            reason=reason,
        )

    result = db.execute(
        update(DesktopCommandApprovalGrant)
        .where(
            DesktopCommandApprovalGrant.id == grant.id,
            DesktopCommandApprovalGrant.tenant_id == command.tenant_id,
            DesktopCommandApprovalGrant.user_id == user.id,
            DesktopCommandApprovalGrant.session_id == command.session_id,
            DesktopCommandApprovalGrant.shell_id == command.shell_id,
            DesktopCommandApprovalGrant.device_id == token_device_id,
            DesktopCommandApprovalGrant.risk_tier == risk_tier,
            DesktopCommandApprovalGrant.capability == command.capability,
            DesktopCommandApprovalGrant.status == "active",
            DesktopCommandApprovalGrant.remaining_actions > 0,
            DesktopCommandApprovalGrant.expires_at > now,
            or_(
                DesktopCommandApprovalGrant.desktop_command_id == command.id,
                DesktopCommandApprovalGrant.desktop_command_id.is_(None),
            ),
        )
        .values(
            remaining_actions=DesktopCommandApprovalGrant.remaining_actions - 1,
            status=case(
                (DesktopCommandApprovalGrant.remaining_actions <= 1, "consumed"),
                else_=DesktopCommandApprovalGrant.status,
            ),
            consumed_at=case(
                (DesktopCommandApprovalGrant.remaining_actions <= 1, now),
                else_=DesktopCommandApprovalGrant.consumed_at,
            ),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        return _deny_pending_command_for_approval_failure(
            db,
            command,
            reason="desktop command approval grant replay denied",
            metadata=_approval_metadata(grant),
        )
    db.flush()
    db.refresh(grant)
    command.approval_id = grant.id
    return grant


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _desktop_command_envelope_secret() -> bytes:
    # First trust-edge slice: API-issued envelopes are verified server-side and
    # Tauri native actuation still denies by default. Public-key/Ed25519 client
    # verification is the next slice once the envelope contract is stable.
    secret = settings.JWT_AGENT_TOKEN_SECRET or settings.SECRET_KEY
    return secret.encode("utf-8")


def _decode_envelope_key_material(value: str) -> bytes:
    key = value.strip()
    if key.startswith("base64url:"):
        key = key.removeprefix("base64url:")
    elif key.startswith("base64:"):
        key = key.removeprefix("base64:")
    elif key.startswith("hex:"):
        return bytes.fromhex(key.removeprefix("hex:"))
    padding = "=" * (-len(key) % 4)
    return base64.urlsafe_b64decode(f"{key}{padding}")


def _desktop_command_envelope_algorithm() -> str:
    algorithm = (settings.DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM or "").strip()
    if algorithm == DESKTOP_COMMAND_ENVELOPE_ALGORITHM:
        return DESKTOP_COMMAND_ENVELOPE_ALGORITHM
    if algorithm == DESKTOP_COMMAND_ENVELOPE_ED25519_ALGORITHM:
        if not settings.DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY:
            raise RuntimeError("DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY is required for Ed25519 envelopes")
        return DESKTOP_COMMAND_ENVELOPE_ED25519_ALGORITHM
    raise RuntimeError(f"unsupported desktop command envelope signing algorithm: {algorithm!r}")


def _desktop_command_envelope_key_id(algorithm: str) -> str:
    if algorithm == DESKTOP_COMMAND_ENVELOPE_ED25519_ALGORITHM:
        return DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID
    return DESKTOP_COMMAND_ENVELOPE_KEY_ID


def _desktop_command_envelope_ed25519_private_key() -> Ed25519PrivateKey:
    raw = _decode_envelope_key_material(settings.DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY or "")
    if len(raw) != 32:
        raise RuntimeError("DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY must decode to 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _desktop_command_envelope_ed25519_public_key() -> Ed25519PublicKey:
    return _desktop_command_envelope_ed25519_private_key().public_key()


def _sign_hmac_envelope_payload(payload: dict[str, Any]) -> str:
    digest = hmac.new(
        _desktop_command_envelope_secret(),
        _canonical_json(payload),
        hashlib.sha256,
    ).digest()
    return _b64url(digest)


def _sign_ed25519_envelope_payload(payload: dict[str, Any]) -> str:
    signature = _desktop_command_envelope_ed25519_private_key().sign(_canonical_json(payload))
    return _b64url(signature)


def _sign_envelope_payload(payload: dict[str, Any], algorithm: str) -> str:
    if algorithm == DESKTOP_COMMAND_ENVELOPE_ED25519_ALGORITHM:
        return _sign_ed25519_envelope_payload(payload)
    return _sign_hmac_envelope_payload(payload)


def _envelope_hash(envelope: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(envelope)).hexdigest()


def _unsigned_envelope_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in envelope.items()
        if key != "signature"
    }


def _verify_envelope_signature(envelope: dict[str, Any]) -> bool:
    signature = envelope.get("signature")
    if not isinstance(signature, str) or not signature:
        return False
    payload = _unsigned_envelope_payload(envelope)
    algorithm = envelope.get("signature_alg")
    if algorithm == DESKTOP_COMMAND_ENVELOPE_ALGORITHM:
        expected = _sign_hmac_envelope_payload(payload)
        return hmac.compare_digest(signature, expected)
    if algorithm == DESKTOP_COMMAND_ENVELOPE_ED25519_ALGORITHM:
        try:
            _desktop_command_envelope_ed25519_public_key().verify(
                _decode_envelope_key_material(signature),
                _canonical_json(payload),
            )
            return True
        except (InvalidSignature, RuntimeError, ValueError):
            return False
    return False


def _build_signed_command_envelope(
    command: DesktopCommand,
    *,
    user: User,
    issued_at: datetime,
    expires_at: datetime,
) -> tuple[dict[str, Any], str]:
    action = str((command.payload or {}).get("action") or "desktop_command")
    tool_name = str((command.payload or {}).get("tool_name") or "")
    mode = str((command.payload or {}).get("mode") or "control_locked")
    risk_tier = _risk_tier_for_action(action)
    algorithm = _desktop_command_envelope_algorithm()
    envelope = {
        "schema": DESKTOP_COMMAND_ENVELOPE_SCHEMA,
        "signed": True,
        "signature_alg": algorithm,
        "key_id": _desktop_command_envelope_key_id(algorithm),
        "policy_version": CURRENT_DESKTOP_COMMAND_ENVELOPE_POLICY_VERSION,
        "issuer": "agentprovision-api",
        "tenant_id": str(command.tenant_id),
        "user_id": str(user.id),
        "session_id": str(command.session_id),
        "desktop_command_id": str(command.id),
        "correlation_id": str(command.correlation_id) if command.correlation_id else None,
        "shell_id": command.shell_id,
        "device_id": str(command.device_id) if command.device_id else None,
        "action": action,
        "tool_name": tool_name,
        "capability": command.capability,
        "mode": mode,
        "risk_tier": risk_tier,
        "approval_id": str(command.approval_id) if command.approval_id else None,
        "approval_risk_tier": risk_tier,
        "policy_decision": "lease_claimed",
        "nonce": str(uuid.uuid4()),
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "expires_at_ms": int(expires_at.timestamp() * 1000),
    }
    envelope["signature"] = _sign_envelope_payload(envelope, algorithm)
    return envelope, _envelope_hash(envelope)


def _persist_command_envelope_nonce(
    db: Session,
    command: DesktopCommand,
    *,
    envelope: dict[str, Any],
    envelope_hash: str,
    issued_at: datetime,
    expires_at: datetime,
) -> DesktopCommandEnvelopeNonce:
    nonce_row = DesktopCommandEnvelopeNonce(
        tenant_id=command.tenant_id,
        desktop_command_id=command.id,
        session_id=command.session_id,
        shell_id=command.shell_id,
        device_id=command.device_id,
        nonce=envelope["nonce"],
        envelope_hash=envelope_hash,
        status="issued",
        issued_at=issued_at,
        expires_at=expires_at,
        created_at=issued_at,
        updated_at=issued_at,
    )
    db.add(nonce_row)
    return nonce_row


def _envelope_metadata(envelope: dict[str, Any] | None, envelope_hash: str | None = None) -> dict[str, Any]:
    if not envelope:
        return {}
    metadata: dict[str, Any] = {
        "envelope_nonce": envelope.get("nonce"),
        "envelope_policy_version": envelope.get("policy_version"),
    }
    if envelope_hash:
        metadata["envelope_hash"] = envelope_hash
    return metadata


def _deny_command_for_envelope_failure(
    db: Session,
    command: DesktopCommand,
    *,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[DesktopCommand, DesktopCommandEvent, dict[str, Any] | None, bool]:
    now = _utcnow()
    result = db.execute(
        update(DesktopCommand)
        .where(
            DesktopCommand.id == command.id,
            DesktopCommand.tenant_id == command.tenant_id,
            DesktopCommand.status.in_(("claimed", "running")),
        )
        .values(
            status="denied",
            completed_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Desktop command lease is no longer valid")
    command.status = "denied"
    command.completed_at = now
    command.updated_at = now
    event = _record_command_event(
        db,
        command,
        event_type="desktop_command_envelope_denied",
        source="api",
        outcome="denied",
        reason=reason,
        metadata=metadata,
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
        tenant_id=command.tenant_id,
    )
    return command, event, session_event, False


def _consume_command_envelope_or_deny(
    db: Session,
    command: DesktopCommand,
    *,
    user: User,
    completion: DesktopCommandCompletion,
    token_device_id: uuid.UUID,
    now: datetime,
) -> tuple[DesktopCommand, DesktopCommandEvent | None, dict[str, Any] | None, bool] | None:
    envelope = (command.payload or {}).get("command_envelope")
    if not isinstance(envelope, dict):
        return _deny_command_for_envelope_failure(
            db,
            command,
            reason="desktop command envelope missing",
        )

    completion_nonce = (completion.metadata or {}).get("envelope_nonce")
    metadata = _envelope_metadata(envelope, _envelope_hash(envelope))
    if not isinstance(completion_nonce, str) or not completion_nonce:
        return _deny_command_for_envelope_failure(
            db,
            command,
            reason="desktop command envelope nonce missing",
            metadata=metadata,
        )
    if completion_nonce != envelope.get("nonce"):
        return _deny_command_for_envelope_failure(
            db,
            command,
            reason="desktop command envelope nonce mismatch",
            metadata={**metadata, "envelope_nonce": completion_nonce},
        )
    if not _verify_envelope_signature(envelope):
        return _deny_command_for_envelope_failure(
            db,
            command,
            reason="desktop command envelope signature invalid",
            metadata=metadata,
        )

    expires_at = _as_aware_utc(_parse_iso_datetime(envelope.get("expires_at")))
    if expires_at is None or expires_at <= now:
        return _deny_command_for_envelope_failure(
            db,
            command,
            reason="desktop command envelope expired",
            metadata=metadata,
        )

    expected = {
        "tenant_id": str(command.tenant_id),
        "user_id": str(user.id),
        "session_id": str(command.session_id),
        "desktop_command_id": str(command.id),
        "shell_id": command.shell_id,
        "device_id": str(token_device_id),
        "capability": command.capability,
        "action": str((command.payload or {}).get("action") or "desktop_command"),
        "policy_version": CURRENT_DESKTOP_COMMAND_ENVELOPE_POLICY_VERSION,
        "approval_id": str(command.approval_id) if command.approval_id else None,
        "approval_risk_tier": _risk_tier_for_action(str((command.payload or {}).get("action") or "desktop_command")),
    }
    if any(envelope.get(key) != value for key, value in expected.items()):
        return _deny_command_for_envelope_failure(
            db,
            command,
            reason="desktop command envelope binding mismatch",
            metadata=metadata,
        )

    nonce_row = db.query(DesktopCommandEnvelopeNonce).filter(
        DesktopCommandEnvelopeNonce.tenant_id == command.tenant_id,
        DesktopCommandEnvelopeNonce.nonce == completion_nonce,
    ).first()
    if not nonce_row or str(nonce_row.desktop_command_id) != str(command.id):
        return _deny_command_for_envelope_failure(
            db,
            command,
            reason="desktop command envelope binding mismatch",
            metadata=metadata,
        )
    nonce_expires_at = _as_aware_utc(nonce_row.expires_at)
    if nonce_expires_at is None or nonce_expires_at <= now:
        nonce_row.status = "expired"
        nonce_row.updated_at = now
        return _deny_command_for_envelope_failure(
            db,
            command,
            reason="desktop command envelope expired",
            metadata=metadata,
        )
    if nonce_row.status != "issued":
        nonce_row.status = "replayed"
        nonce_row.updated_at = now
        return _deny_command_for_envelope_failure(
            db,
            command,
            reason="desktop command envelope replay denied",
            metadata=metadata,
        )

    result = db.execute(
        update(DesktopCommandEnvelopeNonce)
        .where(
            DesktopCommandEnvelopeNonce.id == nonce_row.id,
            DesktopCommandEnvelopeNonce.tenant_id == command.tenant_id,
            DesktopCommandEnvelopeNonce.status == "issued",
        )
        .values(
            status="consumed",
            consumed_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        return _deny_command_for_envelope_failure(
            db,
            command,
            reason="desktop command envelope replay denied",
            metadata=metadata,
        )
    return None


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
            "approval_id": str(event.approval_id) if event.approval_id else None,
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


def create_desktop_approval_grant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request: DesktopCommandApprovalGrantCreate,
) -> DesktopCommandApprovalGrant:
    _ensure_user_for_tenant(db, user_id, tenant_id)
    _ensure_session_owned_by_user(db, request.session_id, tenant_id, user_id)
    if request.risk_tier not in {"observe", "native_control"}:
        raise HTTPException(status_code=422, detail="Unsupported desktop approval risk tier")
    if not _capability_matches_risk_tier(request.capability, request.risk_tier):
        raise HTTPException(status_code=422, detail="Desktop approval capability does not match risk tier")
    max_actions = max(1, min(int(request.max_actions), 20))
    expires_in_seconds = max(5, min(int(request.expires_in_seconds), 600))
    now = _utcnow()

    command: DesktopCommand | None = None
    if request.desktop_command_id:
        command = db.query(DesktopCommand).filter(
            DesktopCommand.id == request.desktop_command_id,
            DesktopCommand.tenant_id == tenant_id,
            DesktopCommand.session_id == request.session_id,
        ).first()
        if not command:
            raise HTTPException(status_code=404, detail="Desktop command not found")
        if str(command.user_id) != str(user_id):
            raise HTTPException(status_code=403, detail="Desktop command is not owned by user")
        if command.status in _TERMINAL_COMMAND_STATUSES:
            raise HTTPException(status_code=409, detail="Desktop command is already terminal")
        action = str((command.payload or {}).get("action") or "desktop_command")
        if _risk_tier_for_action(action) != request.risk_tier:
            raise HTTPException(status_code=422, detail="Desktop approval risk tier does not match command")
        if command.capability != request.capability:
            raise HTTPException(status_code=422, detail="Desktop approval capability does not match command")
        shell_id = command.shell_id
        device_id = command.device_id
    else:
        if request.capability not in set(_COMMAND_ACTION_CAPABILITIES.values()):
            raise HTTPException(status_code=422, detail="Unsupported desktop approval capability")
        shell_id, _shell_capabilities, device_id = _select_connected_shell(tenant_id, request.shell_id)

    if device_id is None:
        raise HTTPException(status_code=409, detail="Desktop shell device is not bound")
    grant = DesktopCommandApprovalGrant(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=request.session_id,
        shell_id=shell_id,
        device_id=device_id,
        desktop_command_id=request.desktop_command_id,
        risk_tier=request.risk_tier,
        capability=request.capability,
        status="active",
        target_binding=request.target_binding or {},
        max_actions=max_actions,
        remaining_actions=max_actions,
        approved_by_user_id=user_id,
        approved_at=now,
        expires_at=now + timedelta(seconds=expires_in_seconds),
        created_at=now,
        updated_at=now,
    )
    db.add(grant)
    db.flush()
    if command is not None:
        command.approval_id = grant.id
        command.updated_at = now
    db.commit()
    db.refresh(grant)
    return grant


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
        return existing, _event_for_existing_command(
            db,
            existing,
            tool_name=request.tool_name,
        ), None

    shell_id, shell_capabilities, device_id = _select_connected_shell(tenant_id, request.shell_id)
    capability = _COMMAND_ACTION_CAPABILITIES[request.action]
    if request.action in _DISABLED_NATIVE_CONTROL_ACTIONS:
        return _enqueue_disabled_native_control_command(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            request=request,
            shell_id=shell_id,
            device_id=device_id,
        )

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
        approval_id=request.approval_id,
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
            return existing, _event_for_existing_command(
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

    approval_result = _consume_approval_grant_or_deny(
        db,
        command,
        user=user,
        token_device_id=token_device_id,
        now=now,
    )
    if approval_result is None:
        db.commit()
        for expired_event in expired_events:
            _publish_display_safe_command_event(
                expired_event,
                status="expired",
                tenant_id=user.tenant_id,
            )
        return None, None, None
    if isinstance(approval_result, tuple):
        _denied_command, denied_event, denied_session_event = approval_result
        for expired_event in expired_events:
            _publish_display_safe_command_event(
                expired_event,
                status="expired",
                tenant_id=user.tenant_id,
            )
        return None, denied_event, denied_session_event
    approval_grant = approval_result

    payload = dict(command.payload or {})
    payload["approval"] = _approval_payload(approval_grant)
    envelope, envelope_hash = _build_signed_command_envelope(
        command,
        user=user,
        issued_at=now,
        expires_at=lease_expires_at,
    )
    payload["command_envelope"] = envelope
    _persist_command_envelope_nonce(
        db,
        command,
        envelope=envelope,
        envelope_hash=envelope_hash,
        issued_at=now,
        expires_at=lease_expires_at,
    )
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
            approval_id=approval_grant.id,
            payload=payload,
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
    command.approval_id = approval_grant.id
    command.payload = payload
    command.updated_at = now
    _record_command_event(
        db,
        command,
        event_type="desktop_command_approval_consumed",
        source="api",
        outcome="approved",
        metadata=_approval_metadata(approval_grant),
    )
    event = _record_command_event(
        db,
        command,
        event_type="desktop_command_claimed",
        source="tauri",
        outcome="started",
        metadata={
            "lease_expires_at": lease_expires_at.isoformat(),
            **_approval_metadata(approval_grant),
            **_envelope_metadata(envelope, envelope_hash),
        },
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
    lease_expires_at = _as_aware_utc(command.lease_expires_at)
    if lease_expires_at and lease_expires_at <= now:
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

    envelope_denial = _consume_command_envelope_or_deny(
        db,
        command,
        user=user,
        completion=completion,
        token_device_id=token_device_id,
        now=now,
    )
    if envelope_denial is not None:
        return envelope_denial

    envelope = (command.payload or {}).get("command_envelope")
    completion_metadata = {
        **(completion.metadata or {}),
        **_envelope_metadata(
            envelope if isinstance(envelope, dict) else None,
            _envelope_hash(envelope) if isinstance(envelope, dict) else None,
        ),
    }
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
        metadata=completion_metadata,
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
    db.execute(
        update(DesktopCommandApprovalGrant)
        .where(
            DesktopCommandApprovalGrant.tenant_id == user.tenant_id,
            DesktopCommandApprovalGrant.session_id == stop.session_id,
            DesktopCommandApprovalGrant.shell_id == stop.shell_id,
            DesktopCommandApprovalGrant.device_id == token_device_id,
            DesktopCommandApprovalGrant.status == "active",
        )
        .values(
            status="revoked",
            revoked_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
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
