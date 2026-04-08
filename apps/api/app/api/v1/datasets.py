from __future__ import annotations

from typing import List
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.schemas import dataset as dataset_schema
from app.services import datasets as dataset_service

router = APIRouter()


class RecordIngestionRequest(BaseModel):
    name: str
    records: List[dict]
    description: str | None = None
    source_type: str | None = None


class QueryRequest(BaseModel):
    sql: str
    limit: int = 100


@router.get("", response_model=List[dataset_schema.Dataset])
def list_datasets(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    return dataset_service.list_datasets(db, tenant_id=current_user.tenant_id)


@router.post("/upload", response_model=dataset_schema.Dataset, status_code=status.HTTP_201_CREATED)
def upload_dataset(
    *,
    db: Session = Depends(deps.get_db),
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str | None = Form(None),
    current_user: User = Depends(deps.get_current_active_user),
):
    try:
        dataset = dataset_service.ingest_tabular(
            db,
            tenant_id=current_user.tenant_id,
            file=file,
            name=name,
            description=description,
        )
        return dataset
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/ingest", response_model=dataset_schema.Dataset, status_code=status.HTTP_201_CREATED)
def create_dataset_from_records(
    *,
    db: Session = Depends(deps.get_db),
    payload: RecordIngestionRequest,
    current_user: User = Depends(deps.get_current_active_user),
):
    try:
        dataset = dataset_service.ingest_records(
            db,
            tenant_id=current_user.tenant_id,
            records=payload.records,
            name=payload.name,
            description=payload.description,
            source_type=payload.source_type or "data_agent",
        )
        return dataset
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{dataset_id}", response_model=dataset_schema.Dataset)
def read_dataset(
    dataset_id: uuid.UUID,
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    dataset = dataset_service.get_dataset(db, dataset_id=dataset_id, tenant_id=current_user.tenant_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


@router.get("/{dataset_id}/preview", response_model=dataset_schema.DatasetPreview)
def preview_dataset(
    dataset_id: uuid.UUID,
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    dataset = dataset_service.get_dataset(db, dataset_id=dataset_id, tenant_id=current_user.tenant_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset_service.dataset_preview(dataset)


@router.get("/{dataset_id}/summary")
def dataset_summary(
    dataset_id: uuid.UUID,
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    dataset = dataset_service.get_dataset(db, dataset_id=dataset_id, tenant_id=current_user.tenant_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    try:
        return dataset_service.run_summary_query(dataset)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{dataset_id}/schema")
def get_dataset_schema(
    dataset_id: uuid.UUID,
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Get detailed schema information for a dataset including column types and sample values."""
    dataset = dataset_service.get_dataset(db, dataset_id=dataset_id, tenant_id=current_user.tenant_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    try:
        return dataset_service.get_schema_info(dataset)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{dataset_id}/query")
def query_dataset(
    dataset_id: uuid.UUID,
    *,
    db: Session = Depends(deps.get_db),
    payload: QueryRequest,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Execute a SQL query on a dataset using DuckDB.

    The table is accessible as 'dataset' in the SQL query.
    Only SELECT queries are allowed (no DROP, DELETE, INSERT, UPDATE, etc.).
    Maximum 1000 rows can be returned per query.
    """
    dataset = dataset_service.get_dataset(db, dataset_id=dataset_id, tenant_id=current_user.tenant_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    try:
        return dataset_service.execute_query(dataset, payload.sql, payload.limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{dataset_id}/databricks/status")
def get_dataset_databricks_status(
    dataset_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db)
):
    """
    Get Databricks sync status for a dataset

    Returns:
    - sync_status: synced|syncing|failed|pending|not_synced
    - databricks_enabled: boolean
    - bronze_table: table name if synced
    - silver_table: table name if synced
    - last_sync_at: timestamp
    - last_sync_error: error message if failed
    """
    from app.models.dataset import Dataset

    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id,
        Dataset.tenant_id == current_user.tenant_id
    ).first()

    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    metadata = dataset.metadata_ or {}

    return {
        "dataset_id": str(dataset.id),
        "dataset_name": dataset.name,
        "databricks_enabled": metadata.get("databricks_enabled", False),
        "sync_status": metadata.get("sync_status", "not_synced"),
        "bronze_table": metadata.get("bronze_table"),
        "silver_table": metadata.get("silver_table"),
        "last_sync_at": metadata.get("last_sync_at"),
        "last_sync_error": metadata.get("last_sync_error"),
        "row_count_local": dataset.row_count,
        "row_count_databricks": metadata.get("row_count_databricks")
    }


@router.post("/{dataset_id}/sync", status_code=status.HTTP_202_ACCEPTED)
def sync_dataset_to_databricks(
    dataset_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Manually trigger synchronization of a dataset to Databricks.
    """
    dataset = dataset_service.get_dataset(db, dataset_id=dataset_id, tenant_id=current_user.tenant_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    # Access the internal trigger function (or we could expose a public one)
    # We'll use the protected one for now as it's available in the module
    dataset_service._trigger_databricks_sync(db, dataset, current_user.tenant_id)

    return {"message": "Sync triggered successfully", "status": "pending"}
