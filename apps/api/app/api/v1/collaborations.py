"""Collaboration session API endpoints."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.collaboration import (
    AdvancePhaseRequest,
    CollaborationSessionCreate,
    CollaborationSessionInDB,
)
from app.services import collaboration_service

router = APIRouter()


@router.get("", response_model=List[CollaborationSessionInDB])
def list_sessions(
    session_status: Optional[str] = Query(default=None, alias="status"),
    blackboard_id: Optional[uuid.UUID] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List collaboration sessions."""
    return collaboration_service.list_sessions(
        db, current_user.tenant_id,
        status=session_status,
        blackboard_id=blackboard_id,
        limit=limit,
    )


@router.post("", response_model=CollaborationSessionInDB, status_code=status.HTTP_201_CREATED)
def create_session(
    session_in: CollaborationSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new collaboration session on an existing blackboard."""
    try:
        return collaboration_service.create_session(db, current_user.tenant_id, session_in)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{session_id}", response_model=CollaborationSessionInDB)
def get_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a collaboration session."""
    session = collaboration_service.get_session(db, current_user.tenant_id, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


@router.post("/{session_id}/advance", response_model=dict)
def advance_phase(
    session_id: uuid.UUID,
    request: AdvancePhaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Contribute to the current phase and advance the collaboration.

    Each agent posts their contribution for their role's phase. The session
    advances through the pattern's phases and can loop for multiple rounds
    when disagreements arise.
    """
    try:
        result = collaboration_service.advance_phase(
            db, current_user.tenant_id, session_id,
            agent_slug=request.agent_slug,
            contribution=request.contribution,
            evidence=request.evidence,
            confidence=request.confidence,
            agrees_with_previous=request.agrees_with_previous,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session not active or not found",
        )
    return result
