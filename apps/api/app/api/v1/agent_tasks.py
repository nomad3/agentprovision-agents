import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.agent_task import AgentTask, AgentTaskCreate, AgentTaskUpdate
from app.schemas.execution_trace import ExecutionTrace as ExecutionTraceSchema
from app.services import agent_tasks as service
from app.services import execution_traces as trace_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=AgentTask, status_code=201)
async def create_task(
    task_in: AgentTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new task for an agent.

    WhatsApp tasks (task_type='whatsapp', context.skill='whatsapp') are
    auto-executed immediately via the neonize WhatsApp service instead of
    going through the full TaskExecutionWorkflow.
    """
    try:
        task = service.create_task(db, task_in, current_user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Auto-execute WhatsApp send tasks
    if (
        task.task_type == "whatsapp"
        and task.context
        and task.context.get("skill") == "whatsapp"
    ):
        await _execute_whatsapp_task(task, db, str(current_user.tenant_id))

    return task


async def _execute_whatsapp_task(task, db: Session, tenant_id: str):
    """Send a WhatsApp message and update the task status."""
    from app.services.whatsapp_service import whatsapp_service

    payload = task.context.get("payload", {})
    action = payload.get("action")
    recipient = payload.get("recipient_phone", "")
    message_body = payload.get("message_body", "")
    account_id = payload.get("account_id", "default")

    if action not in ("send_message", "send_template"):
        return  # Unknown action, leave task queued for manual handling

    # For templates, format as plain text (neonize doesn't support WA templates)
    if action == "send_template":
        template_name = payload.get("template_name", "")
        template_params = payload.get("template_params", {})
        message_body = message_body or f"[{template_name}] {template_params}"

    if not recipient or not message_body:
        task.status = "failed"
        task.error = "Missing recipient_phone or message_body"
        task.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(task)
        return

    task.status = "executing"
    task.started_at = datetime.utcnow()
    db.commit()

    try:
        result = await whatsapp_service.send_message(
            tenant_id=tenant_id,
            account_id=account_id,
            to=recipient,
            message=message_body,
        )
        if result.get("status") == "error":
            task.status = "failed"
            task.error = result.get("error", "WhatsApp send failed")
        else:
            task.status = "completed"
            task.output = {
                "message_id": result.get("message_id"),
                "recipient": recipient,
                "status": "sent",
            }
    except Exception as e:
        logger.exception("WhatsApp task %s failed", task.id)
        task.status = "failed"
        task.error = str(e)

    task.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(task)


@router.get("", response_model=List[AgentTask])
def list_tasks(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all tasks."""
    return service.get_tasks(db, current_user.tenant_id, skip, limit, status)


@router.get("/{task_id}", response_model=AgentTask)
def get_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get task by ID."""
    task = service.get_task(db, task_id, current_user.tenant_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=AgentTask)
def update_task(
    task_id: uuid.UUID,
    task_in: AgentTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a task."""
    task = service.update_task(db, task_id, current_user.tenant_id, task_in)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/trace", response_model=List[ExecutionTraceSchema])
def get_task_trace(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get execution trace for a task."""
    task = service.get_task(db, task_id, current_user.tenant_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return trace_service.get_traces_by_task(db, task_id, current_user.tenant_id)


@router.post("/{task_id}/approve", response_model=AgentTask)
def approve_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Approve a task waiting for approval, setting status to executing."""
    task = service.get_task(db, task_id, current_user.tenant_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "waiting_for_approval":
        raise HTTPException(status_code=400, detail="Task is not waiting for approval")
    task.status = "executing"
    task.started_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/reject", response_model=AgentTask)
def reject_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Reject a task waiting for approval, setting status to failed."""
    task = service.get_task(db, task_id, current_user.tenant_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "waiting_for_approval":
        raise HTTPException(status_code=400, detail="Task is not waiting for approval")
    task.status = "failed"
    task.error = "Rejected by user"
    task.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task
