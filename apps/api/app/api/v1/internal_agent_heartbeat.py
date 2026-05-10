"""Internal agent-heartbeat endpoint — Phase 4 commit 8.

POST /api/v1/agents/internal/heartbeat

Called by the Claude Code PostToolUse hook on every leaf tool call.
Auth-tier-only: rejects tenant JWT and X-Internal-Key with 403 +
audit-log entry (defence-in-depth — Cloudflare /internal/* block is
network-layer; the route enforces auth-tier in code too). Per design
§10.3(c).

Body: {task_id, tool_name, ts}
Returns: 204 No Content on success, 403 if not agent-token.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.agent_task import AgentTask as AgentTaskModel
from app.services.agent_token import AgentTokenClaims, verify_agent_token

router = APIRouter()
logger = logging.getLogger(__name__)


class HeartbeatBody(BaseModel):
    task_id: str = Field(..., description="Task UUID (string)")
    tool_name: Optional[str] = Field(None, description="Tool that fired the hook")
    ts: Optional[int] = Field(None, description="Unix epoch seconds when hook fired")


def _require_agent_token(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> AgentTokenClaims:
    """Authenticate via agent-token only.

    Rejects tenant-JWT (kind=access) and X-Internal-Key with 403. The
    rejection itself is audit-logged so the security pipeline can
    surface a leaf misconfigured to dispatch via the wrong auth tier.
    """
    if not authorization:
        logger.info(
            "heartbeat: rejected (no Authorization header)",
            extra={"event": "agent_heartbeat_auth_rejected", "reason": "missing"},
        )
        raise HTTPException(status_code=403, detail="agent-token required")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.info(
            "heartbeat: rejected (non-Bearer scheme)",
            extra={"event": "agent_heartbeat_auth_rejected", "reason": "scheme"},
        )
        raise HTTPException(status_code=403, detail="agent-token required")
    try:
        claims = verify_agent_token(parts[1].strip())
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "heartbeat: rejected (verify failed: %s)", exc,
            extra={"event": "agent_heartbeat_auth_rejected", "reason": "verify"},
        )
        raise HTTPException(status_code=403, detail="agent-token required")
    return claims


@router.post("/agents/internal/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def heartbeat(
    body: HeartbeatBody,
    claims: AgentTokenClaims = Depends(_require_agent_token),
    db: Session = Depends(deps.get_db),
):
    """Update ``agent_tasks.last_seen_at`` for the in-flight task.

    Tenant scope is read from the agent-token claim; the path body
    cannot override it. The endpoint always returns 204 — even when
    the row is missing, in the wrong tenant, or simply silent no-op.
    This is intentional: leaf PostToolUse hooks are fire-and-forget
    (curl -m 2 || true), so any non-2xx would just spam the leaf's
    error log without changing behavior. Tenant mismatch causes a
    silent no-op (no UPDATE), which prevents cross-tenant timestamp
    leakage without leaking task existence either.
    """
    tenant_id = claims.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="claim missing tenant_id")

    # Update last_seen_at if a row exists; silent no-op otherwise so the
    # synthetic-task-id chat path doesn't 404-spam.
    row = (
        db.query(AgentTaskModel)
        .filter(AgentTaskModel.id == body.task_id)
        .first()
    )
    if row is not None:
        # Verify the task lives in the claim's tenant — agent_tasks has
        # no direct tenant_id column, so we walk via assigned_agent.
        from app.models.agent import Agent as _Agent

        agent = (
            db.query(_Agent)
            .filter(_Agent.id == row.assigned_agent_id)
            .first()
        )
        if agent is not None and str(agent.tenant_id) == str(tenant_id):
            row.last_seen_at = datetime.now(timezone.utc)
            db.commit()

    return None
