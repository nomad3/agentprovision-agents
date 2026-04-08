from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.api import deps
from app.services import agent_kits as agent_kit_service
from app.models.user import User
import uuid

router = APIRouter()

@router.get("", response_model=List[schemas.agent_kit.AgentKit])
def read_agent_kits(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve agent kits for the current tenant.
    """
    agent_kits = agent_kit_service.get_agent_kits_by_tenant(
        db, tenant_id=current_user.tenant_id, skip=skip, limit=limit
    )
    return agent_kits


@router.post("", response_model=schemas.agent_kit.AgentKit, status_code=status.HTTP_201_CREATED)
def create_agent_kit(
    *,
    db: Session = Depends(deps.get_db),
    item_in: schemas.agent_kit.AgentKitCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Create new agent kit for the current tenant.
    """
    item = agent_kit_service.create_tenant_agent_kit(db=db, item_in=item_in, tenant_id=current_user.tenant_id)
    return item

@router.get("/{agent_kit_id}", response_model=schemas.agent_kit.AgentKit)
def read_agent_kit_by_id(
    agent_kit_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve a specific agent kit by ID for the current tenant.
    """
    agent_kit = agent_kit_service.get_agent_kit(db, agent_kit_id=agent_kit_id)
    if not agent_kit or str(agent_kit.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent kit not found")
    return agent_kit

@router.put("/{agent_kit_id}", response_model=schemas.agent_kit.AgentKit)
def update_agent_kit(
    *,
    db: Session = Depends(deps.get_db),
    agent_kit_id: uuid.UUID,
    item_in: schemas.agent_kit.AgentKitUpdate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Update an existing agent kit for the current tenant.
    """
    agent_kit = agent_kit_service.get_agent_kit(db, agent_kit_id=agent_kit_id)
    if not agent_kit or str(agent_kit.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent kit not found")
    item = agent_kit_service.update_agent_kit(db=db, db_obj=agent_kit, obj_in=item_in)
    return item

@router.delete("/{agent_kit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_kit(
    *,
    db: Session = Depends(deps.get_db),
    agent_kit_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Delete an agent kit for the current tenant.
    """
    agent_kit = agent_kit_service.get_agent_kit(db, agent_kit_id=agent_kit_id)
    if not agent_kit or str(agent_kit.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent kit not found")
    agent_kit_service.delete_agent_kit(db=db, agent_kit_id=agent_kit_id)
    return {"message": "Agent kit deleted successfully"}


@router.post("/{agent_kit_id}/simulate", response_model=schemas.agent_kit.AgentKitSimulation)
def simulate_agent_kit(
    *,
    db: Session = Depends(deps.get_db),
    agent_kit_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
):
    agent_kit = agent_kit_service.get_agent_kit(db, agent_kit_id=agent_kit_id)
    if not agent_kit or str(agent_kit.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent kit not found")
    try:
        return agent_kit_service.simulate_agent_kit(db=db, agent_kit=agent_kit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
