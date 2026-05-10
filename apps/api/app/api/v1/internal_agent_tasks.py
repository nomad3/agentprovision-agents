"""Internal task-side endpoints called by leaf MCP tools — Phase 4 review fixes.

Two endpoints, both auth'd via X-Internal-Key + X-Tenant-Id (matches the
existing internal-endpoint pattern at internal_orchestrator_events.py
and internal_agent_tokens.py):

  POST /api/v1/tasks/internal/{task_id}/request-approval
  POST /api/v1/tasks/internal/dispatch

The user-facing ``/api/v1/tasks/{id}/workflow-approve`` and
``/api/v1/tasks/dispatch`` endpoints stay JWT-gated for the human CLI
and web UI. Leaf MCP tools route through these internal-tier endpoints
which share the same business logic (approval flip / recursion gate +
Temporal dispatch) but accept the leaf's auth headers.

## Why not just one endpoint?

The user-facing endpoints take ``Depends(get_current_user)`` which
decodes a tenant JWT and looks up the User row. Leaves have no tenant
JWT — they authenticate as their owning agent via the agent_token's
claim. The mcp-server's resolver verifies the agent_token, then the
MCP tool sends the resolved tenant in X-Tenant-Id.

## /tasks/internal/{task_id}/request-approval

Backs the ``request_human_approval`` MCP tool (Phase 4 review C1).
Flips ``task.status='waiting_for_approval'``, stashes rationale in
``context.approval_request``, writes a high-priority Notification.
Resuming a Temporal human_approval workflow step stays JWT-gated on
the existing /workflow-approve so only a human admin can approve.

## /tasks/internal/dispatch (Phase 4 review C-FINAL-1)

Backs the ``dispatch_agent`` MCP tool. Shares the §3.1 recursion gate
and Temporal dispatch logic with the JWT-gated /tasks/dispatch via
``app.api.v1.agent_tasks.dispatch_core``.
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
from app.api.v1.agent_tasks import DispatchRequest, dispatch_core
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


# ---------------------------------------------------------------------------
# /tasks/internal/dispatch — Phase 4 review C-FINAL-1
# ---------------------------------------------------------------------------


@router.post("/tasks/internal/dispatch", status_code=201)
async def dispatch_internal(
    body: DispatchRequest,
    tenant_id: _uuid.UUID = Depends(_resolve_tenant_id),
    _auth: None = Depends(_verify_internal_key),
    db: Session = Depends(deps.get_db),
) -> dict:
    """Internal-tier sibling of ``/api/v1/tasks/dispatch``.

    Backs the ``dispatch_agent`` MCP tool. Auth: X-Internal-Key +
    X-Tenant-Id. Tenant scope is the X-Tenant-Id header — the mcp-server
    resolver authenticates the agent_token and forwards the canonical
    tenant from the claim. Body shape and response shape are identical
    to the JWT-gated endpoint; the §3.1 recursion gate fires the same
    way via the shared ``dispatch_core`` helper.

    Phase 4 review C-FINAL-1: the prior Phase 4 implementation pointed
    ``dispatch_agent`` at the JWT-gated ``/tasks/dispatch`` endpoint,
    which would 401 every leaf invocation in production because the MCP
    tool sends X-Internal-Key, not Bearer JWT. The integration test
    only passed via ``app.dependency_overrides[get_current_user]`` —
    that's covered now by ``test_dispatch_internal_*`` which exercises
    the real wire contract without overrides.
    """
    return await dispatch_core(db, tenant_id=tenant_id, body=body)
