from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import uuid

from app.api import deps
from app.models.user import User
from app.services.orchestration.skill_router import SkillRouter

router = APIRouter()


class SkillExecuteRequest(BaseModel):
    skill_name: str
    payload: dict
    task_id: Optional[uuid.UUID] = None
    agent_id: Optional[uuid.UUID] = None


@router.post("/execute")
def execute_skill(
    request: SkillExecuteRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Execute a skill through the tenant's OpenClaw instance."""
    import logging
    logger = logging.getLogger(__name__)
    skill_router = SkillRouter(db=db, tenant_id=current_user.tenant_id)
    result = skill_router.execute_skill(
        skill_name=request.skill_name,
        payload=request.payload,
        task_id=request.task_id,
        agent_id=request.agent_id,
    )
    if result.get("status") == "error":
        error_detail = result.get("error", "Unknown error")
        logger.error("Skill execution failed for '%s': %s", request.skill_name, error_detail)
        raise HTTPException(status_code=502, detail=error_detail)
    return result


@router.get("/health")
def skill_health(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Check health of tenant's OpenClaw instance."""
    skill_router = SkillRouter(db=db, tenant_id=current_user.tenant_id)
    return skill_router.health_check()
