from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.api import deps
from app.services import deployments as deployment_service
from app.models.user import User
import uuid

router = APIRouter()

@router.get("", response_model=List[schemas.deployment.Deployment])
def read_deployments(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve deployments for the current tenant.
    """
    deployments = deployment_service.get_deployments_by_tenant(
        db, tenant_id=current_user.tenant_id, skip=skip, limit=limit
    )
    return deployments


@router.post("", response_model=schemas.deployment.Deployment, status_code=status.HTTP_201_CREATED)
def create_deployment(
    *,
    db: Session = Depends(deps.get_db),
    item_in: schemas.deployment.DeploymentCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Create new deployment for the current tenant.
    """
    item = deployment_service.create_tenant_deployment(db=db, item_in=item_in, tenant_id=current_user.tenant_id)
    return item

@router.get("/{deployment_id}", response_model=schemas.deployment.Deployment)
def read_deployment_by_id(
    deployment_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve a specific deployment by ID for the current tenant.
    """
    deployment = deployment_service.get_deployment(db, deployment_id=deployment_id)
    if not deployment or str(deployment.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    return deployment

@router.put("/{deployment_id}", response_model=schemas.deployment.Deployment)
def update_deployment(
    *,
    db: Session = Depends(deps.get_db),
    deployment_id: uuid.UUID,
    item_in: schemas.deployment.DeploymentCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Update an existing deployment for the current tenant.
    """
    deployment = deployment_service.get_deployment(db, deployment_id=deployment_id)
    if not deployment or str(deployment.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    item = deployment_service.update_deployment(db=db, db_obj=deployment, obj_in=item_in)
    return item

@router.delete("/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deployment(
    *,
    db: Session = Depends(deps.get_db),
    deployment_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Delete a deployment for the current tenant.
    """
    deployment = deployment_service.get_deployment(db, deployment_id=deployment_id)
    if not deployment or str(deployment.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    deployment_service.delete_deployment(db=db, deployment_id=deployment_id)
    return {"message": "Deployment deleted successfully"}
