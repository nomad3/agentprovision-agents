from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.api import deps
from app.services import tools as tool_service
from app.models.user import User
import uuid

router = APIRouter()

@router.get("", response_model=List[schemas.tool.Tool])
def read_tools(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve tools for the current tenant.
    """
    tools = tool_service.get_tools_by_tenant(
        db, tenant_id=current_user.tenant_id, skip=skip, limit=limit
    )
    return tools


@router.post("", response_model=schemas.tool.Tool, status_code=status.HTTP_201_CREATED)
def create_tool(
    *,
    db: Session = Depends(deps.get_db),
    item_in: schemas.tool.ToolCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Create new tool for the current tenant.
    """
    item = tool_service.create_tenant_tool(db=db, item_in=item_in, tenant_id=current_user.tenant_id)
    return item

@router.get("/{tool_id}", response_model=schemas.tool.Tool)
def read_tool_by_id(
    tool_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve a specific tool by ID for the current tenant.
    """
    tool = tool_service.get_tool(db, tool_id=tool_id)
    if not tool or str(tool.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    return tool

@router.put("/{tool_id}", response_model=schemas.tool.Tool)
def update_tool(
    *,
    db: Session = Depends(deps.get_db),
    tool_id: uuid.UUID,
    item_in: schemas.tool.ToolCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Update an existing tool for the current tenant.
    """
    tool = tool_service.get_tool(db, tool_id=tool_id)
    if not tool or str(tool.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    item = tool_service.update_tool(db=db, db_obj=tool, obj_in=item_in)
    return item

@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool(
    *,
    db: Session = Depends(deps.get_db),
    tool_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Delete a tool for the current tenant.
    """
    tool = tool_service.get_tool(db, tool_id=tool_id)
    if not tool or str(tool.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    tool_service.delete_tool(db=db, tool_id=tool_id)
    return {"message": "Tool deleted successfully"}
