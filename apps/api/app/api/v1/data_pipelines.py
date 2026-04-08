from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.api import deps
from app.services import data_pipeline as data_pipeline_service
from app.models.user import User
import uuid

router = APIRouter()

@router.get("", response_model=List[schemas.data_pipeline.DataPipeline])
def read_data_pipelines(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve data pipelines for the current tenant.
    """
    data_pipelines = data_pipeline_service.get_data_pipelines_by_tenant(
        db, tenant_id=current_user.tenant_id, skip=skip, limit=limit
    )
    return data_pipelines


@router.post("", response_model=schemas.data_pipeline.DataPipeline, status_code=status.HTTP_201_CREATED)
def create_data_pipeline(
    *,
    db: Session = Depends(deps.get_db),
    item_in: schemas.data_pipeline.DataPipelineCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Create new data pipeline for the current tenant.
    """
    item = data_pipeline_service.create_tenant_data_pipeline(db=db, item_in=item_in, tenant_id=current_user.tenant_id)
    return item

@router.get("/{data_pipeline_id}", response_model=schemas.data_pipeline.DataPipeline)
def read_data_pipeline_by_id(
    data_pipeline_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Retrieve a specific data pipeline by ID for the current tenant.
    """
    data_pipeline = data_pipeline_service.get_data_pipeline(db, data_pipeline_id=data_pipeline_id)
    if not data_pipeline or str(data_pipeline.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data pipeline not found")
    return data_pipeline

@router.put("/{data_pipeline_id}", response_model=schemas.data_pipeline.DataPipeline)
def update_data_pipeline(
    *,
    db: Session = Depends(deps.get_db),
    data_pipeline_id: uuid.UUID,
    item_in: schemas.data_pipeline.DataPipelineCreate,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Update an existing data pipeline for the current tenant.
    """
    data_pipeline = data_pipeline_service.get_data_pipeline(db, data_pipeline_id=data_pipeline_id)
    if not data_pipeline or str(data_pipeline.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data pipeline not found")
    item = data_pipeline_service.update_data_pipeline(db=db, db_obj=data_pipeline, obj_in=item_in)
    return item

@router.delete("/{data_pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_data_pipeline(
    *,
    db: Session = Depends(deps.get_db),
    data_pipeline_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Delete a data pipeline for the current tenant.
    """
    data_pipeline = data_pipeline_service.get_data_pipeline(db, data_pipeline_id=data_pipeline_id)
    if not data_pipeline or str(data_pipeline.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data pipeline not found")
    data_pipeline_service.delete_data_pipeline(db=db, data_pipeline_id=data_pipeline_id)
    return {"message": "Data pipeline deleted successfully"}

@router.post("/{data_pipeline_id}/execute", status_code=status.HTTP_202_ACCEPTED)
async def execute_data_pipeline(
    *,
    db: Session = Depends(deps.get_db),
    data_pipeline_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Execute a data pipeline manually.
    Returns execution details including workflow ID for tracking.
    """
    data_pipeline = data_pipeline_service.get_data_pipeline(db, data_pipeline_id=data_pipeline_id)
    if not data_pipeline or str(data_pipeline.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Data pipeline not found or not accessible"
        )

    # Check if pipeline is already running
    if data_pipeline.last_run_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pipeline is already running. Please wait for it to complete."
        )

    try:
        result = await data_pipeline_service.execute_pipeline(db, data_pipeline_id=data_pipeline_id)
        return {
            "message": "Pipeline execution started successfully",
            "pipeline_id": str(data_pipeline_id),
            "pipeline_name": data_pipeline.name,
            "workflow_id": result.get("workflow_id"),
            "status": "started",
            "started_at": result.get("started_at")
        }
    except ValueError as e:
        # Handle configuration errors
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pipeline configuration error: {str(e)}"
        )
    except ConnectionError as e:
        # Handle connection/network errors
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service temporarily unavailable: {str(e)}"
        )
    except Exception as e:
        # Handle all other errors
        import traceback
        error_details = str(e)
        if len(error_details) > 200:
            error_details = error_details[:200] + "..."
        
        # Log the full error for debugging
        print(f"Pipeline execution error: {traceback.format_exc()}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution failed: {error_details}"
        )
