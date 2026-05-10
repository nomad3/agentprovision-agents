"""Internal task-side endpoints called by leaf MCP tools — Phase 4 review fix.

POST /api/v1/tasks/internal/{task_id}/request-approval

Backs the ``request_human_approval`` MCP tool. The user-facing
``/api/v1/tasks/{id}/workflow-approve`` endpoint requires JWT bearer
auth and validates ``decision in ("approved","rejected")`` — neither
fits a leaf-MCP caller, which authenticates via X-Internal-Key +
X-Tenant-Id and is *requesting* an admin signoff (not approving one).

This endpoint:
  • authenticates via X-Internal-Key (matches the existing
    internal-endpoint pattern at internal_orchestrator_events.py and
    internal_agent_tokens.py),
  • takes ``X-Tenant-Id`` as the canonical tenant scope,
  • verifies the task exists in that tenant (404 otherwise),
  • flips ``status`` to ``waiting_for_approval`` and stores the reason
    in ``context.approval_request``,
  • writes a Notification row (priority=high, source=system) so the
    tenant-admin UI's notification bell surfaces the request,
  • returns ``{"status":"requested","task_id":..., "notification_id":...}``.

The Temporal-signal half (resuming a paused human_approval workflow
step) is the existing ``/workflow-approve`` endpoint's job and stays
JWT-gated — only the human admin can approve, and they do it from the
UI. Phase 4.5 may unify these once the visual-builder approval queue
ships.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.models.agent_task import AgentTask as AgentTaskModel
from app.models.notification import Notification

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_internal_key(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    if x_internal_key not in (settings.API_INTERNAL_KEY, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")


def _resolve_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> _uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id required")
    try:
        return _uuid.UUID(x_tenant_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="X-Tenant-Id not a valid UUID")


class RequestApprovalBody(BaseModel):
    reason: str = Field(..., max_length=2000, description="Human-readable rationale")


@router.post("/tasks/internal/{task_id}/request-approval")
def request_approval(
    task_id: _uuid.UUID,
    body: RequestApprovalBody,
    tenant_id: _uuid.UUID = Depends(_resolve_tenant_id),
    _auth: None = Depends(_verify_internal_key),
    db: Session = Depends(deps.get_db),
) -> dict:
    """Mark a task as awaiting human approval and notify the tenant admin."""
    # AgentTask has no direct tenant_id column — walk via assigned_agent
    # to enforce tenant scope. Defensive: fall back to 404 on any miss.
    from app.models.agent import Agent as _Agent

    task = (
        db.query(AgentTaskModel)
        .filter(AgentTaskModel.id == task_id)
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    agent = (
        db.query(_Agent)
        .filter(_Agent.id == task.assigned_agent_id)
        .first()
    )
    if agent is None or str(agent.tenant_id) != str(tenant_id):
        # Don't leak existence across tenants — same 404 either way.
        raise HTTPException(status_code=404, detail="Task not found")

    # Flip status and stash the reason. Idempotent — re-requesting just
    # overwrites context.approval_request.
    task.status = "waiting_for_approval"
    ctx = dict(task.context or {})
    ctx["approval_request"] = {
        "reason": body.reason,
        "requested_at": datetime.utcnow().isoformat() + "Z",
    }
    task.context = ctx

    notif = Notification(
        tenant_id=tenant_id,
        title="Agent task awaiting approval",
        body=body.reason[:1000],
        source="system",
        priority="high",
        reference_id=str(task_id),
        reference_type="agent_task",
        event_metadata={"event": "approval_requested", "task_id": str(task_id)},
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)

    logger.info(
        "approval requested for task=%s tenant=%s notif=%s",
        str(task_id)[:8], str(tenant_id)[:8], str(notif.id)[:8],
    )

    return {
        "status": "requested",
        "task_id": str(task_id),
        "notification_id": str(notif.id),
    }
