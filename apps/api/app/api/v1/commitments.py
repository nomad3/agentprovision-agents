"""Tenant-scoped commitment record API endpoints."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.commitment_record import (
    CommitmentRecordCreate,
    CommitmentRecordInDB,
    CommitmentRecordUpdate,
)
from app.services import commitment_service, red_flag_engine

router = APIRouter()


class CommitmentCompleteIn(BaseModel):
    """Proof-gated completion payload (plan §6/§14)."""

    proof_refs: List[str] = []
    user_confirmed: bool = False


@router.get("", response_model=List[CommitmentRecordInDB])
def list_commitments(
    owner_agent_slug: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    goal_id: Optional[uuid.UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List commitments for the current tenant."""
    return commitment_service.list_commitments(
        db,
        tenant_id=current_user.tenant_id,
        owner_agent_slug=owner_agent_slug,
        state=state,
        goal_id=goal_id,
        limit=limit,
    )


@router.get("/overdue", response_model=List[CommitmentRecordInDB])
def list_overdue_commitments(
    owner_agent_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List commitments that are past their due date and still open."""
    return commitment_service.list_overdue_commitments(
        db,
        tenant_id=current_user.tenant_id,
        owner_agent_slug=owner_agent_slug,
    )


# Literal sub-paths MUST precede the /{commitment_id} matcher below.
@router.get("/open", response_model=List[CommitmentRecordInDB])
def list_open_commitments(
    session_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Open/live commitments for the tenant, optionally scoped to a session."""
    return commitment_service.list_open_commitments(
        db, current_user.tenant_id, session_id=session_id
    )


@router.get("/red-flags")
def list_red_flags(
    session_id: Optional[str] = Query(default=None),
    min_level: str = Query(default="warn"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Red-flag scan over open commitments. Killswitch-gated: empty if the
    engine is disabled for this tenant (fail-closed)."""
    flags = red_flag_engine.scan_open_commitments(
        db, current_user.tenant_id, session_id=session_id, min_level=min_level
    )
    return [f.__dict__ for f in flags]


@router.post("", response_model=CommitmentRecordInDB, status_code=status.HTTP_201_CREATED)
def create_commitment(
    commitment_in: CommitmentRecordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new commitment record."""
    try:
        return commitment_service.create_commitment(
            db,
            tenant_id=current_user.tenant_id,
            commitment_in=commitment_in,
            created_by=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{commitment_id}", response_model=CommitmentRecordInDB)
def get_commitment(
    commitment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single commitment by ID."""
    commitment = commitment_service.get_commitment(db, current_user.tenant_id, commitment_id)
    if not commitment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commitment not found")
    return commitment


@router.patch("/{commitment_id}", response_model=CommitmentRecordInDB)
def update_commitment(
    commitment_id: uuid.UUID,
    commitment_in: CommitmentRecordUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a commitment (state transitions, progress, etc.)."""
    try:
        commitment = commitment_service.update_commitment(
            db, current_user.tenant_id, commitment_id, commitment_in
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not commitment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commitment not found")
    return commitment


@router.delete("/{commitment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_commitment(
    commitment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a commitment record."""
    deleted = commitment_service.delete_commitment(db, current_user.tenant_id, commitment_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commitment not found")
    return None


@router.post("/{commitment_id}/complete", response_model=CommitmentRecordInDB)
def complete_commitment(
    commitment_id: uuid.UUID,
    body: CommitmentCompleteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Proof-gated completion (plan §6/§14): 409 unless proof_refs are supplied
    or the user explicitly confirms completion."""
    try:
        commitment = commitment_service.complete_commitment_with_proof(
            db,
            current_user.tenant_id,
            commitment_id,
            proof_refs=body.proof_refs,
            user_confirmed=body.user_confirmed,
        )
    except commitment_service.CommitmentProofRequired as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not commitment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commitment not found")
    return commitment
