"""Luna desktop-control API.

This phase only ingests metadata-only local observation audit events. Command
claiming/execution remains intentionally unimplemented until signed envelopes
and approval consumption ship.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.core.rate_limit import limiter
from app.models.user import User as UserModel
from app.services.desktop_control_service import (
    LocalObservationAudit,
    record_local_observation_event,
)

router = APIRouter(prefix="/desktop-control", tags=["desktop-control"])


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
