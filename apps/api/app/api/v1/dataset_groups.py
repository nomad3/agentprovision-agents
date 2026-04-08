from typing import List
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.api import deps
from app.services import dataset_groups as service
from app.models.user import User

router = APIRouter()
@router.get("", response_model=List[schemas.dataset_group.DatasetGroup])
def read_dataset_groups(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve dataset groups for the current tenant.
    """
    dataset_groups = dataset_group_service.get_dataset_groups_by_tenant(
        db, tenant_id=current_user.tenant_id, skip=skip, limit=limit
    )
    return dataset_groups


@router.post("", response_model=schemas.dataset_group.DatasetGroup, status_code=status.HTTP_201_CREATED)
def create_dataset_group(
    *,
    db: Session = Depends(deps.get_db),
    item_in: schemas.dataset_group.DatasetGroupCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Create new dataset group.
    """
    return service.create_dataset_group(
        db=db, item_in=item_in, tenant_id=current_user.tenant_id
    )

@router.get("/{group_id}", response_model=schemas.dataset_group.DatasetGroup)
def read_dataset_group(
    group_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Get dataset group by ID.
    """
    group = service.get_dataset_group(db, group_id=group_id)
    if not group or group.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset group not found"
        )
    return group

@router.put("/{group_id}", response_model=schemas.dataset_group.DatasetGroup)
def update_dataset_group(
    *,
    db: Session = Depends(deps.get_db),
    group_id: uuid.UUID,
    item_in: schemas.dataset_group.DatasetGroupUpdate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Update dataset group.
    """
    group = service.get_dataset_group(db, group_id=group_id)
    if not group or group.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset group not found"
        )
    return service.update_dataset_group(db=db, db_obj=group, obj_in=item_in)

@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset_group(
    *,
    db: Session = Depends(deps.get_db),
    group_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Delete dataset group.
    """
    group = service.get_dataset_group(db, group_id=group_id)
    if not group or group.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset group not found"
        )
    service.delete_dataset_group(db=db, group_id=group_id)
