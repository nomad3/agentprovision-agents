"""Luna desktop-control API.

This phase only ingests metadata-only local observation audit events. Command
claiming/execution remains intentionally unimplemented until signed envelopes
and approval consumption ship.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.user import User as UserModel
from app.services.desktop_control_service import (
    LocalObservationAudit,
    McpObservationRequest,
    record_local_observation_event,
    record_mcp_observation_request,
)

router = APIRouter(prefix="/desktop-control", tags=["desktop-control"])

_TOOL_ACTIONS = {
    "desktop_observe_screen": "capture_screenshot",
    "desktop_get_active_app": "get_active_app",
    "desktop_read_clipboard": "read_clipboard",
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
        expected = _TOOL_ACTIONS[self.tool_name]
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


@router.post(
    "/observations/request",
    response_model=DesktopObservationRequestOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("120/minute")
def request_desktop_observation(
    request: Request,
    payload: DesktopObservationRequestIn,
    db: Session = Depends(deps.get_db),
    tenant_id: uuid.UUID = Depends(_resolve_internal_tenant_id),
    user_id: uuid.UUID = Depends(_resolve_internal_user_id),
    _auth: None = Depends(_verify_internal_key),
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
