from typing import List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.api import deps
from app.services import connectors as connector_service
from app.services.connector_testing import test_connector
from app.models.user import User
import uuid

router = APIRouter()

@router.get("/", response_model=List[schemas.connector.Connector])
def read_connectors(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve connectors for the current tenant.
    """
    connectors = connector_service.get_connectors_by_tenant(
        db, tenant_id=current_user.tenant_id, skip=skip, limit=limit
    )
    return connectors


@router.post("/", response_model=schemas.connector.Connector, status_code=status.HTTP_201_CREATED)
def create_connector(
    *,
    db: Session = Depends(deps.get_db),
    item_in: schemas.connector.ConnectorCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Create new connector for the current tenant.
    """
    item = connector_service.create_tenant_connector(db=db, item_in=item_in, tenant_id=current_user.tenant_id)
    return item


@router.post("/test", response_model=schemas.connector.ConnectorTestResponse)
async def test_connector_endpoint(
    *,
    request: schemas.connector.ConnectorTestRequest,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Test a connector configuration without saving.
    Useful for validating credentials before creating a connector.
    """
    result = await test_connector(request.type, request.config)
    return schemas.connector.ConnectorTestResponse(**result)


@router.post("/{connector_id}/test", response_model=schemas.connector.ConnectorTestResponse)
async def test_existing_connector(
    connector_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Test an existing connector and update its status.
    """
    connector = connector_service.get_connector(db, connector_id=connector_id)
    if not connector or str(connector.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    result = await test_connector(connector.type, connector.config)

    # Update connector status
    connector.last_test_at = datetime.utcnow()
    if result["success"]:
        connector.status = "active"
        connector.last_test_error = None
    else:
        connector.status = "error"
        connector.last_test_error = result["message"]

    db.commit()
    db.refresh(connector)

    return schemas.connector.ConnectorTestResponse(**result)


@router.get("/{connector_id}", response_model=schemas.connector.Connector)
def read_connector_by_id(
    connector_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve a specific connector by ID for the current tenant.
    """
    connector = connector_service.get_connector(db, connector_id=connector_id)
    if not connector or str(connector.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    return connector

@router.put("/{connector_id}", response_model=schemas.connector.Connector)
def update_connector(
    *,
    db: Session = Depends(deps.get_db),
    connector_id: uuid.UUID,
    item_in: schemas.connector.ConnectorUpdate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Update an existing connector for the current tenant.
    """
    connector = connector_service.get_connector(db, connector_id=connector_id)
    if not connector or str(connector.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    item = connector_service.update_connector(db=db, db_obj=connector, obj_in=item_in)
    return item

@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connector(
    *,
    db: Session = Depends(deps.get_db),
    connector_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Delete a connector for the current tenant.
    """
    connector = connector_service.get_connector(db, connector_id=connector_id)
    if not connector or str(connector.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    connector_service.delete_connector(db=db, connector_id=connector_id)
    return {"message": "Connector deleted successfully"}
