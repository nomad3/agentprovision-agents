import logging
from datetime import datetime, timedelta
from typing import List, Literal, Optional

import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.agent import Agent
from app.models.agent_task import AgentTask as AgentTaskModel
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


class WorkflowApprovalDecision(BaseModel):
    """Body for approving/rejecting a human_approval workflow step linked to a task."""
    decision: str  # "approved" | "rejected"
    comment: Optional[str] = None
    # Optional: caller may pass these explicitly if the task context doesn't contain them.
    run_id: Optional[str] = None
    step_id: Optional[str] = None


@router.post("/{task_id}/workflow-approve")
async def workflow_approve_task(
    task_id: uuid.UUID,
    body: WorkflowApprovalDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send an approval_decision Temporal signal for a human_approval workflow step.

    The task's context may contain ``workflow_run_id`` and ``step_id`` that
    identify which workflow run and step to signal.  Callers can also pass
    ``run_id`` / ``step_id`` directly in the request body as a fallback.

    Returns ``{"status": "signal_sent", "decision": decision}`` on success or
    ``{"status": "not_implemented", ...}`` when the Temporal client is
    unreachable.
    """
    task = service.get_task(db, task_id, current_user.tenant_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")

    # Resolve run_id and step_id from task context or explicit body fields.
    task_context = task.context or {}
    run_id = body.run_id or task_context.get("workflow_run_id")
    step_id = body.step_id or task_context.get("approval_step_id", "approval")

    if not run_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Cannot resolve workflow run: provide run_id in the request body "
                "or store workflow_run_id in the task context."
            ),
        )

    # Look up the WorkflowRun to get the Temporal workflow ID.
    try:
        from app.models.dynamic_workflow import WorkflowRun
        run = db.query(WorkflowRun).filter(
            WorkflowRun.id == run_id,
            WorkflowRun.tenant_id == current_user.tenant_id,
        ).first()
    except Exception as exc:
        logger.warning("DB lookup for WorkflowRun %s failed: %s", run_id, exc)
        run = None

    if not run or not run.temporal_workflow_id:
        raise HTTPException(
            status_code=404,
            detail="Workflow run not found or has no associated Temporal workflow ID.",
        )

    # Send the Temporal signal.
    try:
        from app.core.config import settings
        from temporalio.client import Client

        client = await Client.connect(settings.TEMPORAL_ADDRESS)
        handle = client.get_workflow_handle(run.temporal_workflow_id)
        await handle.signal("approval_decision", step_id, body.decision)

        logger.info(
            "approval_decision signal sent: run=%s step=%s decision=%s by user=%s",
            run_id, step_id, body.decision, current_user.id,
        )
        return {"status": "signal_sent", "decision": body.decision, "step_id": step_id, "run_id": run_id}

    except Exception as exc:
        logger.warning("Temporal signal failed for run=%s: %s", run_id, exc)
        return {
            "status": "not_implemented",
            "reason": f"Temporal signal client error: {exc}",
            "decision": body.decision,
        }


# --------------------------------------------------------------------------
# Phase 4 commit 2 — POST /tasks/dispatch
# --------------------------------------------------------------------------
#
# Surfaces the missing dispatch verb. Existing POST /tasks just queues a row
# (create_task above); the chat hot path (cli_session_manager) is the only
# pre-Phase-4 dispatch site. The dispatch endpoint is the explicit API for
# both the human CLI (`agentprovision agent dispatch`) and the leaf-side
# `dispatch_agent` MCP tool.
#
# The §3.1 recursion gate fires HERE: we construct an ExecutionRequest with
# the caller's parent_chain and let ResilientExecutor.execute() refuse if
# depth >= 3 or the chain has a cycle. On refusal we surface 503 with the
# actionable_hint so the leaf can stop walking.

class DispatchRequest(BaseModel):
    """Request to dispatch a task — either a code task or a delegation."""

    task_type: Literal["code", "delegate"] = Field(
        ..., description="'code' = CodeTaskWorkflow, 'delegate' = TaskExecutionWorkflow",
    )
    objective: str = Field(..., description="Task description / goal")
    target_agent_id: Optional[uuid.UUID] = Field(
        None, description="Required when task_type='delegate'",
    )
    repo: Optional[str] = Field(None, description="Code task repo (org/name)")
    branch: Optional[str] = Field(None, description="Code task base branch")
    parent_chain: List[uuid.UUID] = Field(
        default_factory=list,
        description="Lineage of dispatching agent UUIDs — used by §3.1 recursion gate",
    )
    parent_task_id: Optional[uuid.UUID] = Field(
        None, description="Optional parent task UUID for audit linkage",
    )
    context: Optional[dict] = Field(None, description="Free-form context payload")


@router.post("/dispatch", status_code=201)
async def dispatch_task(
    body: DispatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Dispatch a task to either CodeTaskWorkflow or TaskExecutionWorkflow.

    The recursion gate (§3.1) is enforced here: we build an ExecutionRequest
    with parent_chain and ask the executor to refuse depth >= 3 or cycles.
    On refusal: 503 + actionable_hint. On success: returns
    {task_id, workflow_id}.
    """
    # ── §3.1 recursion gate ─────────────────────────────────────────────
    # We don't actually run the executor (no chain/platform here — that's
    # for the LLM hot path). We just call _enforce_recursion_gate directly
    # so the policy stays single-sourced.
    try:
        from cli_orchestrator.adapters.base import ExecutionRequest
        from cli_orchestrator.executor import ResilientExecutor
    except ImportError:
        # cli_orchestrator package always available in production; if it's
        # absent at import (e.g. unit-test bootstrap), skip the gate. The
        # gate is also enforced executor-side at chat time.
        ExecutionRequest = None  # type: ignore[assignment]
        ResilientExecutor = None  # type: ignore[assignment]

    if ExecutionRequest is not None and ResilientExecutor is not None:
        req = ExecutionRequest(
            chain=("dispatch",),  # synthetic — gate doesn't read this
            platform="dispatch",
            payload={"objective": body.objective},
            parent_chain=tuple(str(x) for x in body.parent_chain),
            tenant_id=str(current_user.tenant_id),
        )
        # Stand up the executor with no adapters — only the gate matters.
        gate_result = ResilientExecutor(adapters={})._enforce_recursion_gate(
            req, run_id=str(uuid.uuid4()),
        )
        if gate_result is not None:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": gate_result.status.value,
                    "actionable_hint": gate_result.actionable_hint,
                    "error_message": gate_result.error_message,
                },
            )

    # ── Validate target_agent_id for delegate ──────────────────────────
    if body.task_type == "delegate" and body.target_agent_id is None:
        raise HTTPException(
            status_code=422,
            detail="target_agent_id is required when task_type='delegate'",
        )

    # For delegate tasks, persist an AgentTask row so audit linkage works.
    task_row: Optional[AgentTaskModel] = None
    if body.task_type == "delegate" and body.target_agent_id is not None:
        # Verify agent belongs to tenant (parallels create_task above).
        agent = (
            db.query(Agent)
            .filter(
                Agent.id == body.target_agent_id,
                Agent.tenant_id == current_user.tenant_id,
            )
            .first()
        )
        if agent is None:
            raise HTTPException(
                status_code=422,
                detail="target_agent_id not found in this tenant",
            )
        task_row = AgentTaskModel(
            assigned_agent_id=body.target_agent_id,
            parent_task_id=body.parent_task_id,
            human_requested=True,
            status="queued",
            priority="normal",
            task_type="delegate",
            objective=body.objective,
            context=body.context,
            requires_approval=False,
        )
        db.add(task_row)
        db.commit()
        db.refresh(task_row)

    # ── Dispatch via Temporal ──────────────────────────────────────────
    from app.core.config import settings
    from temporalio.client import Client as TemporalClient

    workflow_name: str
    task_queue: str
    workflow_input: dict

    if body.task_type == "code":
        workflow_name = "CodeTaskWorkflow"
        task_queue = "agentprovision-code"
        workflow_input = {
            "task_description": body.objective,
            "tenant_id": str(current_user.tenant_id),
            "context": body.context or {},
            "repo": body.repo,
            "branch": body.branch,
            "parent_task_id": (
                str(body.parent_task_id) if body.parent_task_id else None
            ),
            "parent_chain": [str(x) for x in body.parent_chain],
        }
    else:  # delegate
        workflow_name = "TaskExecutionWorkflow"
        task_queue = "agentprovision-orchestration"
        workflow_input = {
            "task_id": str(task_row.id) if task_row else None,
            "tenant_id": str(current_user.tenant_id),
            "target_agent_id": str(body.target_agent_id),
            "objective": body.objective,
            "context": body.context or {},
            "parent_chain": [str(x) for x in body.parent_chain],
        }

    workflow_id = (
        f"{body.task_type}-task-{uuid.uuid4().hex[:12]}"
    )

    try:
        client = await TemporalClient.connect(settings.TEMPORAL_ADDRESS)
        handle = await client.start_workflow(
            workflow_name,
            workflow_input,
            id=workflow_id,
            task_queue=task_queue,
            execution_timeout=timedelta(minutes=180),
        )
        logger.info(
            "Dispatched %s for tenant %s objective=%r workflow=%s",
            workflow_name, str(current_user.tenant_id)[:8],
            body.objective[:80], handle.id,
        )
    except Exception as exc:
        logger.warning(
            "Temporal dispatch failed for %s: %s", workflow_name, exc,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "status": "PROVIDER_UNAVAILABLE",
                "actionable_hint": "cli.errors.temporal_dispatch_failed",
                "error_message": str(exc),
            },
        )

    return {
        "task_id": str(task_row.id) if task_row else workflow_id,
        "workflow_id": workflow_id,
    }
