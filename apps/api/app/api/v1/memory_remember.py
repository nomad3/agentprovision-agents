"""POST /api/v1/memory/remember — tenant-scoped free-form fact ingestion.

Backs the `alpha remember "<fact>"` CLI subcommand from Phase 2 of the
CLI differentiation roadmap (#179). Thin wrapper around
`app/services/knowledge.py::create_observation` so the rich
auto-embedding + memory_activity logging happens automatically.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_active_user
from app.models.user import User
from app.services.knowledge import create_observation

router = APIRouter()


class RememberRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
    entity_id: Optional[uuid.UUID] = None
    observation_type: str = "fact"


class RememberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    text: str
    entity_id: Optional[uuid.UUID] = None
    observation_type: str


@router.post("/remember", response_model=RememberResponse, status_code=201)
def remember(
    payload: RememberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Write a free-form fact to the caller's tenant memory.

    Auto-embeds the text via the embedding service and stores in both
    the knowledge_observations table (for entity-graph queries) and
    the shared vector_store (for cross-content semantic recall —
    `alpha recall` picks it up).
    """
    try:
        obs = create_observation(
            db,
            tenant_id=current_user.tenant_id,
            observation_text=payload.text,
            observation_type=payload.observation_type or "fact",
            source_type="cli",
            source_platform="alpha",
            source_agent=current_user.email,
            entity_id=payload.entity_id,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"failed to record observation: {e}")
    return RememberResponse(
        id=obs.id,
        text=obs.observation_text,
        entity_id=obs.entity_id,
        observation_type=obs.observation_type,
    )
