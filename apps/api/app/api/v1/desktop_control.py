"""Luna desktop-control API.

This phase ingests metadata-only local observation audit events and exposes the
first API-to-Tauri command queue contract: enqueue, claim lease, complete, and
Stop preemption. Native pointer/keyboard actuation remains disabled until
signed envelopes and approval consumption ship.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.user import User as UserModel
from app.services.desktop_control_service import (
    DesktopCommandClaim,
    DesktopCommandApprovalGrantCreate,
    DesktopCommandCompletion,
    DesktopCommandEnqueue,
    DesktopCommandStop,
    LocalObservationAudit,
    McpObservationRequest,
    claim_next_desktop_command,
    complete_desktop_command,
    create_desktop_approval_grant,
    enqueue_desktop_command,
    preempt_desktop_commands_for_stop,
    record_local_observation_event,
    record_mcp_observation_request,
    record_observation_artifact,
    run_desktop_preflight,
)

router = APIRouter(prefix="/desktop-control", tags=["desktop-control"])

_TOOL_ACTIONS = {
    "desktop_observe_screen": "capture_screenshot",
    "desktop_get_active_app": "get_active_app",
    "desktop_read_clipboard": "read_clipboard",
    "desktop_pointer_move": "pointer_move",
    "desktop_pointer_click": "pointer_click",
    "desktop_keyboard_type": "keyboard_type",
    "desktop_keyboard_key_chord": "keyboard_key_chord",
}

_OBSERVATION_TOOL_ACTIONS = {
    key: value
    for key, value in _TOOL_ACTIONS.items()
    if key in {
        "desktop_observe_screen",
        "desktop_get_active_app",
        "desktop_read_clipboard",
    }
}


class LocalObservationEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    shell_id: str = Field(
        ...,
        pattern=(
            r"^desktop-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
        max_length=96,
    )
    event_id: uuid.UUID
    event_type: Literal[
        "desktop_observation_started",
        "desktop_observation_completed",
        "desktop_observation_failed",
        "desktop_observation_denied",
    ]
    source: Literal["tauri_local"] = "tauri_local"
    action: Literal[
        "capture_screenshot",
        "get_active_app",
        "read_clipboard",
        "watch_clipboard",
        "track_active_app",
    ]
    capability: Literal["screenshot", "active_app", "clipboard_read"]
    outcome: Literal["started", "succeeded", "failed", "denied"]
    mode: Literal["control_locked", "observe", "stopped"]
    created_at_ms: int | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=512)
    screen_recording_status: Literal["granted", "denied", "unknown", "not_required"] | None = None
    accessibility_status: Literal["granted", "denied", "unknown", "not_required"] | None = None
    automation_system_events_status: Literal["granted", "denied", "unknown", "not_required"] | None = None


class LocalObservationEventOut(BaseModel):
    desktop_event_id: uuid.UUID
    session_event_id: str | None = None
    session_seq_no: int | None = None


class DesktopObservationRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    shell_id: str | None = Field(
        default=None,
        pattern=(
            r"^desktop-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
        max_length=96,
    )
    action: Literal["capture_screenshot", "get_active_app", "read_clipboard"]
    tool_name: Literal[
        "desktop_observe_screen",
        "desktop_get_active_app",
        "desktop_read_clipboard",
    ]

    @model_validator(mode="after")
    def tool_matches_action(self):
        expected = _OBSERVATION_TOOL_ACTIONS[self.tool_name]
        if self.action != expected:
            raise ValueError("tool_name does not match action")
        return self


class DesktopObservationRequestOut(BaseModel):
    status: Literal["denied"] = "denied"
    desktop_event_id: uuid.UUID
    session_event_id: str | None = None
    session_seq_no: int | None = None
    shell_id: str
    action: str
    capability: str
    reason: str | None = None
    down_channel_available: bool = False


class DesktopCommandEnqueueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    shell_id: str | None = Field(
        default=None,
        pattern=(
            r"^desktop-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
        max_length=96,
    )
    action: Literal[
        "capture_screenshot",
        "get_active_app",
        "read_clipboard",
        "pointer_move",
        "pointer_click",
        "keyboard_type",
        "keyboard_key_chord",
    ]
    tool_name: Literal[
        "desktop_observe_screen",
        "desktop_get_active_app",
        "desktop_read_clipboard",
        "desktop_pointer_move",
        "desktop_pointer_click",
        "desktop_keyboard_type",
        "desktop_keyboard_key_chord",
    ]
    nonce: str | None = Field(default=None, max_length=96)
    approval_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def tool_matches_action(self):
        expected = _TOOL_ACTIONS[self.tool_name]
        if self.action != expected:
            raise ValueError("tool_name does not match action")
        return self


class DesktopCommandOut(BaseModel):
    desktop_command_id: uuid.UUID
    desktop_event_id: uuid.UUID | None = None
    session_event_id: str | None = None
    session_seq_no: int | None = None
    status: str
    shell_id: str
    device_id: uuid.UUID | None = None
    approval_id: uuid.UUID | None = None
    capability: str
    lease_expires_at: str | None = None
    payload: dict[str, Any] | None = None
    idempotent: bool = False


class DesktopCommandClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    shell_id: str = Field(
        ...,
        pattern=(
            r"^desktop-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
        max_length=96,
    )
    lease_seconds: int = Field(default=30, ge=5, le=120)


class DesktopCommandClaimOut(BaseModel):
    status: Literal["claimed", "empty"]
    command: DesktopCommandOut | None = None


class DesktopCommandCompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shell_id: str = Field(
        ...,
        pattern=(
            r"^desktop-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
        max_length=96,
    )
    status: Literal["succeeded", "failed", "denied", "preempted"]
    reason: str | None = Field(default=None, max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DesktopCommandStopIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    shell_id: str = Field(
        ...,
        pattern=(
            r"^desktop-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
        max_length=96,
    )
    reason: str = Field(default="desktop control stopped", max_length=512)


class DesktopApprovalGrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    shell_id: str | None = Field(
        default=None,
        pattern=(
            r"^desktop-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
        max_length=96,
    )
    desktop_command_id: uuid.UUID | None = None
    risk_tier: Literal["observe", "native_control"]
    capability: Literal[
        "screenshot",
        "active_app",
        "clipboard_read",
        "pointer_control",
        "keyboard_control",
    ]
    max_actions: int = Field(default=1, ge=1, le=20)
    expires_in_seconds: int = Field(default=60, ge=5, le=600)
    target_binding: dict[str, Any] = Field(default_factory=dict)


class DesktopApprovalGrantOut(BaseModel):
    approval_id: uuid.UUID
    session_id: uuid.UUID
    shell_id: str
    device_id: uuid.UUID | None = None
    desktop_command_id: uuid.UUID | None = None
    risk_tier: str
    capability: str
    status: str
    remaining_actions: int
    expires_at: str
    expires_at_ms: int


class DesktopCommandStopOut(BaseModel):
    status: Literal["preempted"] = "preempted"
    preempted_count: int
    desktop_event_ids: list[uuid.UUID]


def _command_out(command, event=None, session_event=None, *, idempotent: bool = False) -> DesktopCommandOut:
    return DesktopCommandOut(
        desktop_command_id=command.id,
        desktop_event_id=event.id if event else None,
        session_event_id=session_event.get("event_id") if session_event else None,
        session_seq_no=session_event.get("seq_no") if session_event else None,
        status=command.status,
        shell_id=command.shell_id,
        device_id=command.device_id,
        approval_id=command.approval_id,
        capability=command.capability,
        lease_expires_at=command.lease_expires_at.isoformat() if command.lease_expires_at else None,
        payload=command.payload or None,
        idempotent=idempotent,
    )


def _verify_internal_key(
    x_internal_key: str | None = Header(None, alias="X-Internal-Key"),
) -> None:
    if x_internal_key not in (settings.API_INTERNAL_KEY, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")


def _resolve_internal_tenant_id(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
) -> uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id required")
    try:
        return uuid.UUID(x_tenant_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="X-Tenant-Id not a valid UUID")


def _resolve_internal_user_id(
    x_user_id: str | None = Header(None, alias="X-User-Id"),
) -> uuid.UUID:
    if not x_user_id:
        raise HTTPException(status_code=400, detail="X-User-Id required")
    try:
        return uuid.UUID(x_user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="X-User-Id not a valid UUID")


@router.get("/preflight")
def desktop_control_preflight(
    _user: UserModel = Depends(deps.require_superuser),
) -> dict[str, Any]:
    """``alpha desktop preflight run`` — validate the desktop-control envelope
    signing config (fail-fast surface for operators). Superuser-only; a thin
    delegation to ``run_desktop_preflight`` with no business logic in the route.
    """
    return run_desktop_preflight()


@router.post(
    "/events/local-observation",
    response_model=LocalObservationEventOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("240/minute")
def create_local_observation_event(
    request: Request,
    payload: LocalObservationEventIn,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    event, session_event = record_local_observation_event(
        db,
        current_user,
        LocalObservationAudit(**payload.model_dump()),
    )
    return LocalObservationEventOut(
        desktop_event_id=event.id,
        session_event_id=session_event.get("event_id") if session_event else None,
        session_seq_no=session_event.get("seq_no") if session_event else None,
    )


class ObservationArtifactOut(BaseModel):
    artifact_id: uuid.UUID
    expires_at: str
    redaction_status: str
    size_bytes: int
    session_event_id: str | None = None
    session_seq_no: int | None = None


@router.post(
    "/observations",
    response_model=ObservationArtifactOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("120/minute")
async def upload_observation(
    request: Request,
    file: UploadFile = File(...),
    session_id: uuid.UUID = Form(...),
    shell_id: str = Form(...),
    source_window_bundle_id: str | None = Form(None),
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
    x_device_token: str | None = Header(None, alias="X-Device-Token"),
):
    """Phase 5.2 governed perception transport — the Luna client uploads a
    captured, window-scoped, redacted screenshot. The bytes land in an API-only
    quarantine under a hard TTL; a BYTE-FREE reference is emitted on the single
    session SSE. There is intentionally NO endpoint that returns the bytes —
    nothing reads them in P5.2 (transport only, until the P5.3 validator/redactor).
    """
    from app.services.perception_storage import MAX_SCREENSHOT_SIZE

    content_type = (file.content_type or "").lower()
    if content_type not in ("image/png", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported observation media type: {file.content_type}. Must be PNG.",
        )
    # Reject an oversized DECLARED body early, then BOUND the actual read so a
    # spoofed/absent Content-Length can't make us buffer an unbounded body. The
    # PNG magic + the final size are re-checked authoritatively in
    # perception_storage (content-type is never trusted as the gate).
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_SCREENSHOT_SIZE + 4096:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Observation too large",
        )
    data = await file.read(MAX_SCREENSHOT_SIZE + 1)
    if len(data) > MAX_SCREENSHOT_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Observation too large",
        )
    artifact, session_event = record_observation_artifact(
        db,
        user=current_user,
        device_token=x_device_token,
        session_id=session_id,
        shell_id=shell_id,
        data=data,
        source_window_bundle_id=source_window_bundle_id,
    )
    return ObservationArtifactOut(
        artifact_id=artifact.id,
        expires_at=artifact.expires_at.isoformat(),
        redaction_status=artifact.redaction_status,
        size_bytes=artifact.size_bytes,
        session_event_id=session_event.get("event_id") if session_event else None,
        session_seq_no=session_event.get("seq_no") if session_event else None,
    )


@router.post(
    "/internal/observations/request",
    response_model=DesktopObservationRequestOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("120/minute")
def request_desktop_observation(
    request: Request,
    payload: DesktopObservationRequestIn,
    db: Session = Depends(deps.get_db),
    _auth: None = Depends(_verify_internal_key),
    tenant_id: uuid.UUID = Depends(_resolve_internal_tenant_id),
    user_id: uuid.UUID = Depends(_resolve_internal_user_id),
):
    event, session_event = record_mcp_observation_request(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        request=McpObservationRequest(**payload.model_dump()),
    )
    down_channel = event.event_metadata.get("down_channel", {})
    return DesktopObservationRequestOut(
        desktop_event_id=event.id,
        session_event_id=session_event.get("event_id") if session_event else None,
        session_seq_no=session_event.get("seq_no") if session_event else None,
        shell_id=event.shell_id,
        action=event.action,
        capability=event.capability,
        reason=event.reason,
        down_channel_available=bool(down_channel.get("available")),
    )


@router.post(
    "/internal/approval-grants",
    response_model=DesktopApprovalGrantOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("120/minute")
def create_approval_grant(
    request: Request,
    payload: DesktopApprovalGrantIn,
    db: Session = Depends(deps.get_db),
    _auth: None = Depends(_verify_internal_key),
    tenant_id: uuid.UUID = Depends(_resolve_internal_tenant_id),
    user_id: uuid.UUID = Depends(_resolve_internal_user_id),
):
    grant = create_desktop_approval_grant(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        request=DesktopCommandApprovalGrantCreate(**payload.model_dump()),
    )
    return DesktopApprovalGrantOut(
        approval_id=grant.id,
        session_id=grant.session_id,
        shell_id=grant.shell_id,
        device_id=grant.device_id,
        desktop_command_id=grant.desktop_command_id,
        risk_tier=grant.risk_tier,
        capability=grant.capability,
        status=grant.status,
        remaining_actions=grant.remaining_actions,
        expires_at=grant.expires_at.isoformat(),
        expires_at_ms=int(grant.expires_at.timestamp() * 1000),
    )


@router.post(
    "/internal/commands",
    response_model=DesktopCommandOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("120/minute")
def enqueue_command(
    request: Request,
    payload: DesktopCommandEnqueueIn,
    db: Session = Depends(deps.get_db),
    _auth: None = Depends(_verify_internal_key),
    tenant_id: uuid.UUID = Depends(_resolve_internal_tenant_id),
    user_id: uuid.UUID = Depends(_resolve_internal_user_id),
):
    command, event, session_event = enqueue_desktop_command(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        request=DesktopCommandEnqueue(**payload.model_dump()),
    )
    return _command_out(command, event, session_event)


@router.post(
    "/commands/claim",
    response_model=DesktopCommandClaimOut,
)
@limiter.limit("240/minute")
def claim_command(
    request: Request,
    payload: DesktopCommandClaimIn,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
    x_device_token: str | None = Header(None, alias="X-Device-Token"),
):
    command, event, session_event = claim_next_desktop_command(
        db,
        user=current_user,
        device_token=x_device_token,
        claim=DesktopCommandClaim(**payload.model_dump()),
    )
    if command is None:
        return DesktopCommandClaimOut(status="empty", command=None)
    return DesktopCommandClaimOut(
        status="claimed",
        command=_command_out(command, event, session_event),
    )


@router.post(
    "/commands/{command_id}/complete",
    response_model=DesktopCommandOut,
)
@limiter.limit("240/minute")
def complete_command(
    request: Request,
    command_id: uuid.UUID,
    payload: DesktopCommandCompleteIn,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
    x_device_token: str | None = Header(None, alias="X-Device-Token"),
):
    command, event, session_event, idempotent = complete_desktop_command(
        db,
        user=current_user,
        device_token=x_device_token,
        completion=DesktopCommandCompletion(
            command_id=command_id,
            **payload.model_dump(),
        ),
    )
    return _command_out(command, event, session_event, idempotent=idempotent)


@router.post(
    "/commands/stop",
    response_model=DesktopCommandStopOut,
)
@limiter.limit("120/minute")
def stop_commands(
    request: Request,
    payload: DesktopCommandStopIn,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
    x_device_token: str | None = Header(None, alias="X-Device-Token"),
):
    count, events, _session_events = preempt_desktop_commands_for_stop(
        db,
        user=current_user,
        device_token=x_device_token,
        stop=DesktopCommandStop(**payload.model_dump()),
    )
    return DesktopCommandStopOut(
        preempted_count=count,
        desktop_event_ids=[event.id for event in events],
    )
