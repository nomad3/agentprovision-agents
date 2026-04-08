from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.api import deps
from app.services import notebook as notebook_service
from app.models.user import User
import uuid

router = APIRouter()

@router.get("", response_model=List[schemas.notebook.Notebook])
def read_notebooks(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve notebooks for the current tenant.
    """
    notebooks = notebook_service.get_notebooks_by_tenant(
        db, tenant_id=current_user.tenant_id, skip=skip, limit=limit
    )
    return notebooks


@router.post("", response_model=schemas.notebook.Notebook, status_code=status.HTTP_201_CREATED)
def create_notebook(
    *,
    db: Session = Depends(deps.get_db),
    item_in: schemas.notebook.NotebookCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Create new notebook for the current tenant.
    """
    item = notebook_service.create_tenant_notebook(db=db, item_in=item_in, tenant_id=current_user.tenant_id)
    return item

@router.get("/{notebook_id}", response_model=schemas.notebook.Notebook)
def read_notebook_by_id(
    notebook_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve a specific notebook by ID for the current tenant.
    """
    notebook = notebook_service.get_notebook(db, notebook_id=notebook_id)
    if not notebook or str(notebook.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")
    return notebook

@router.put("/{notebook_id}", response_model=schemas.notebook.Notebook)
def update_notebook(
    *,
    db: Session = Depends(deps.get_db),
    notebook_id: uuid.UUID,
    item_in: schemas.notebook.NotebookCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Update an existing notebook for the current tenant.
    """
    notebook = notebook_service.get_notebook(db, notebook_id=notebook_id)
    if not notebook or str(notebook.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")
    item = notebook_service.update_notebook(db=db, db_obj=notebook, obj_in=item_in)
    return item

@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notebook(
    *,
    db: Session = Depends(deps.get_db),
    notebook_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Delete a notebook for the current tenant.
    """
    notebook = notebook_service.get_notebook(db, notebook_id=notebook_id)
    if not notebook or str(notebook.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")
    notebook_service.delete_notebook(db=db, notebook_id=notebook_id)
    return {"message": "Notebook deleted successfully"}