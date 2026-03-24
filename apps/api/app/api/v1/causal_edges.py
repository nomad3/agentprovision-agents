"""Causal edge API endpoints."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.causal_edge import CausalEdgeCreate, CausalEdgeInDB
from app.services import causal_edge_service

router = APIRouter()


@router.get("", response_model=List[CausalEdgeInDB])
def list_causal_edges(
    cause_type: Optional[str] = Query(default=None),
    effect_type: Optional[str] = Query(default=None),
    edge_status: Optional[str] = Query(default=None, alias="status"),
    agent_slug: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List causal edges, ordered by confidence."""
    return causal_edge_service.list_causal_edges(
        db,
        tenant_id=current_user.tenant_id,
        cause_type=cause_type,
        effect_type=effect_type,
        status=edge_status,
        agent_slug=agent_slug,
        limit=limit,
    )


@router.post("", response_model=CausalEdgeInDB, status_code=status.HTTP_201_CREATED)
def record_causal_edge(
    edge_in: CausalEdgeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record a causal hypothesis. Corroborates if matching cause→effect exists."""
    return causal_edge_service.record_causal_edge(
        db,
        tenant_id=current_user.tenant_id,
        edge_in=edge_in,
    )


@router.get("/causes", response_model=List[CausalEdgeInDB])
def get_causes_for_effect(
    effect_summary: str = Query(...),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Find what actions likely caused a given outcome."""
    return causal_edge_service.get_causes_for_effect(
        db,
        tenant_id=current_user.tenant_id,
        effect_summary=effect_summary,
        limit=limit,
    )


@router.get("/effects", response_model=List[CausalEdgeInDB])
def get_effects_for_cause(
    cause_summary: str = Query(...),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Predict what outcomes a given action might produce."""
    return causal_edge_service.get_effects_for_cause(
        db,
        tenant_id=current_user.tenant_id,
        cause_summary=cause_summary,
        limit=limit,
    )


@router.get("/{edge_id}", response_model=CausalEdgeInDB)
def get_causal_edge(
    edge_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single causal edge."""
    edge = causal_edge_service.get_causal_edge(db, current_user.tenant_id, edge_id)
    if not edge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Causal edge not found")
    return edge


@router.post("/{edge_id}/disprove", response_model=CausalEdgeInDB)
def disprove_causal_edge(
    edge_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a causal hypothesis as disproven."""
    edge = causal_edge_service.disprove_edge(db, current_user.tenant_id, edge_id)
    if not edge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Causal edge not found")
    return edge
