"""Spatial orchestration view — what's the agent fleet doing right now.

Drives the Luna Spatial HUD's main canvas. Returns a curated snapshot
of the tenant's living orchestrator state: which agents exist, what
workflows are running, what just happened. The HUD polls this every
5 seconds and animates the deltas.

Curate-don't-dump (per the visibility-roadmap convention): we
deliberately do NOT return full audit log payloads, raw tool args, or
agent configs. Only enough to draw nodes + edges + color-coded status.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api import deps
from app.models.agent import Agent
from app.models.agent_audit_log import AgentAuditLog
from app.models.dynamic_workflow import DynamicWorkflow
from app.models.user import User


router = APIRouter()


class AgentNode(BaseModel):
    """One agent rendered as a node in the spatial scene."""
    id: str
    name: str
    role: str = ""
    status: str  # production / staging / draft / deprecated
    busy: bool = Field(False, description="Has invocation in last 60s")
    error: bool = Field(False, description="Has error in last 5min audit log")


class WorkflowNode(BaseModel):
    """One running dynamic-workflow as a node."""
    id: str
    name: str
    status: str  # active / draft / paused
    last_run_at: Optional[datetime]
    run_count: int = 0


class ActionEdge(BaseModel):
    """One recent agent action — flows as a pulse from agent to whatever
    it acted on (tool / workflow / message)."""
    agent_id: str
    action: str  # short verb: 'invoke', 'tool_call', 'workflow_run', 'error'
    target: str = ""  # short label of what was acted on
    at: datetime


class OrchestrationSnapshot(BaseModel):
    agents: List[AgentNode]
    workflows: List[WorkflowNode]
    recent_actions: List[ActionEdge]


@router.get("/orchestration", response_model=OrchestrationSnapshot)
def orchestration_snapshot(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Snapshot for the spatial HUD. Polled at ~0.2 Hz so prefer
    cheap aggregations over rich joins."""
    tenant_id = current_user.tenant_id
    now = datetime.now(timezone.utc)
    busy_window = now - timedelta(seconds=60)
    error_window = now - timedelta(minutes=5)

    # Agents — every production / staging agent in the tenant.
    db_agents = (
        db.query(Agent)
        .filter(
            Agent.tenant_id == tenant_id,
            Agent.status.in_(["production", "staging", "draft"]),
        )
        .order_by(Agent.name)
        .limit(50)
        .all()
    )
    agent_ids = [a.id for a in db_agents]

    # Per-agent invocation count in the last 60s (busy = >0).
    busy_rows = (
        db.query(AgentAuditLog.agent_id, func.count(AgentAuditLog.id))
        .filter(
            AgentAuditLog.tenant_id == tenant_id,
            AgentAuditLog.agent_id.in_(agent_ids) if agent_ids else False,
            AgentAuditLog.created_at >= busy_window,
        )
        .group_by(AgentAuditLog.agent_id)
        .all()
    )
    busy_set = {row[0] for row in busy_rows}

    # Per-agent error count in the last 5min.
    error_rows = (
        db.query(AgentAuditLog.agent_id, func.count(AgentAuditLog.id))
        .filter(
            AgentAuditLog.tenant_id == tenant_id,
            AgentAuditLog.agent_id.in_(agent_ids) if agent_ids else False,
            AgentAuditLog.action.in_(["error", "failure", "auth_failed"]),
            AgentAuditLog.created_at >= error_window,
        )
        .group_by(AgentAuditLog.agent_id)
        .all()
    )
    error_set = {row[0] for row in error_rows}

    agent_nodes = [
        AgentNode(
            id=str(a.id),
            name=a.name or "(unnamed)",
            role=a.role or "",
            status=a.status or "production",
            busy=a.id in busy_set,
            error=a.id in error_set,
        )
        for a in db_agents
    ]

    # Active dynamic workflows.
    db_workflows = (
        db.query(DynamicWorkflow)
        .filter(
            DynamicWorkflow.tenant_id == tenant_id,
            DynamicWorkflow.status.in_(["active", "draft", "paused"]),
        )
        .order_by(DynamicWorkflow.last_run_at.desc().nullslast())
        .limit(30)
        .all()
    )
    workflow_nodes = [
        WorkflowNode(
            id=str(w.id),
            name=w.name or "(unnamed)",
            status=w.status or "draft",
            last_run_at=w.last_run_at,
            run_count=w.run_count or 0,
        )
        for w in db_workflows
    ]

    # Recent actions — last 30 agent_audit_log rows in the last 5min.
    recent = (
        db.query(AgentAuditLog)
        .filter(
            AgentAuditLog.tenant_id == tenant_id,
            AgentAuditLog.created_at >= error_window,
        )
        .order_by(AgentAuditLog.created_at.desc())
        .limit(30)
        .all()
    )
    action_edges = [
        ActionEdge(
            agent_id=str(r.agent_id) if r.agent_id else "",
            action=(r.action or "")[:32],
            target=(getattr(r, "target", None) or "")[:48],
            at=r.created_at,
        )
        for r in recent
        if r.agent_id is not None
    ]

    return OrchestrationSnapshot(
        agents=agent_nodes,
        workflows=workflow_nodes,
        recent_actions=action_edges,
    )
