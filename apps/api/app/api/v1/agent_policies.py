"""GET /api/v1/agents/{agent_id}/policies — read-only policy inspection.

Backs the `alpha policy show <agent>` CLI subcommand from Phase 2 of
the CLI differentiation roadmap (#179). Returns AgentPolicy rows that
apply to a specific agent: both the agent-scoped rows AND the
tenant-wide rows (where `agent_id IS NULL`).

Read-only by design: policy mutation goes through the web UI for
audit trail. The roadmap explicitly excludes `alpha policy set`.
"""
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_active_user
from app.models.agent import Agent
from app.models.agent_policy import AgentPolicy
from app.models.user import User

router = APIRouter()


class PolicyRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    agent_id: uuid.UUID | None
    policy_type: str
    config: dict[str, Any]
    enabled: bool
    scope: str
    created_at: datetime
    updated_at: datetime


class PolicyListResponse(BaseModel):
    agent_id: uuid.UUID
    agent_name: str | None = None
    policies: list[PolicyRow]


@router.get("/{agent_id}/policies", response_model=PolicyListResponse)
def get_agent_policies(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List policies that apply to `agent_id` for the caller's tenant.

    Includes both agent-scoped (agent_policies.agent_id == agent_id)
    and tenant-wide (agent_policies.agent_id IS NULL) rows.
    Tenant isolation: 404 if the agent doesn't belong to the caller's
    tenant. Resolves the agent first so we can surface its name in
    the response header without a second round-trip.
    """
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.tenant_id == current_user.tenant_id)
        .first()
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    rows = (
        db.query(AgentPolicy)
        .filter(
            AgentPolicy.tenant_id == current_user.tenant_id,
            (AgentPolicy.agent_id == agent_id) | (AgentPolicy.agent_id.is_(None)),
        )
        .order_by(AgentPolicy.policy_type.asc(), AgentPolicy.created_at.desc())
        .all()
    )
    return PolicyListResponse(
        agent_id=agent.id,
        agent_name=agent.name,
        policies=[
            PolicyRow(
                id=r.id,
                agent_id=r.agent_id,
                policy_type=r.policy_type,
                config=r.config or {},
                enabled=r.enabled,
                scope="tenant" if r.agent_id is None else "agent",
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ],
    )
