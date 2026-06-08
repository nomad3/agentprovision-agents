"""Tenant-scoped learning-artifact read API (plan 2026-06-08 §7/§12).

Learning artifacts are stored in agent_memory (memory_type='learning_artifact');
this router exposes the read/query surface for operator views and reviewers.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.services import learning_artifact_io

router = APIRouter()


@router.get("/failed-assumptions")
def list_failed_assumptions(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """De-duplicated failed assumptions for the tenant (surface on similar tasks)."""
    return {
        "failed_assumptions": learning_artifact_io.query_failed_assumptions(
            db, current_user.tenant_id, limit=limit
        )
    }


@router.get("")
def list_learning_artifacts(
    agent_id: Optional[uuid.UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recent learning artifacts for the tenant."""
    return learning_artifact_io.list_learning_artifacts(
        db, current_user.tenant_id, agent_id=agent_id, limit=limit
    )
