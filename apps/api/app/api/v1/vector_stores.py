from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.api import deps
from app.services import vector_stores as vector_store_service
from app.models.user import User
import uuid

router = APIRouter()

@router.get("", response_model=List[schemas.vector_store.VectorStore])
def read_vector_stores(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve vector stores for the current tenant.
    """
    vector_stores = vector_store_service.get_vector_stores_by_tenant(
        db, tenant_id=current_user.tenant_id, skip=skip, limit=limit
    )
    return vector_stores


@router.post("", response_model=schemas.vector_store.VectorStore, status_code=status.HTTP_201_CREATED)
def create_vector_store(
    *,
    db: Session = Depends(deps.get_db),
    item_in: schemas.vector_store.VectorStoreCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Create new vector store for the current tenant.
    """
    item = vector_store_service.create_tenant_vector_store(db=db, item_in=item_in, tenant_id=current_user.tenant_id)
    return item

@router.get("/{vector_store_id}", response_model=schemas.vector_store.VectorStore)
def read_vector_store_by_id(
    vector_store_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve a specific vector store by ID for the current tenant.
    """
    vector_store = vector_store_service.get_vector_store(db, vector_store_id=vector_store_id)
    if not vector_store or str(vector_store.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vector store not found")
    return vector_store

@router.put("/{vector_store_id}", response_model=schemas.vector_store.VectorStore)
def update_vector_store(
    *,
    db: Session = Depends(deps.get_db),
    vector_store_id: uuid.UUID,
    item_in: schemas.vector_store.VectorStoreCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Update an existing vector store for the current tenant.
    """
    vector_store = vector_store_service.get_vector_store(db, vector_store_id=vector_store_id)
    if not vector_store or str(vector_store.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vector store not found")
    item = vector_store_service.update_vector_store(db=db, db_obj=vector_store, obj_in=item_in)
    return item

@router.delete("/{vector_store_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vector_store(
    *,
    db: Session = Depends(deps.get_db),
    vector_store_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Delete a vector store for the current tenant.
    """
    vector_store = vector_store_service.get_vector_store(db, vector_store_id=vector_store_id)
    if not vector_store or str(vector_store.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vector store not found")
    vector_store_service.delete_vector_store(db=db, vector_store_id=vector_store_id)
    return {"message": "Vector store deleted successfully"}
