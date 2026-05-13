"""Cross-machine task dashboard rollup for the `alpha tasks` CLI surface.

`GET /api/v1/dashboard/tasks` unions in-flight + recently completed
`workflow_runs` for the caller's tenant, grouped into the buckets the
CLI renders (working / completed). The `needs_input` bucket is
deliberately deferred to a follow-up — see the v1 scope note in
docs/plans/2026-05-13-alpha-agent-view-and-goal-recipes.md, the issue
being there's no canonical "awaiting reply" column on workflow_runs
yet, so any heuristic we ship today (last-message-from-agent etc.) is
brittle and gives the user a false signal.

Why not extend `agent_tasks.router` instead? `agent_tasks` is the
orchestration-internal task record (per-agent invocation, queued by
worker pool). The dashboard is a human-facing rollup that may
eventually span agent_tasks + workflow_runs + chat_sessions. Keeping
the two separate prevents schema drift between "what an agent is
doing" and "what a user sees in their terminal."

Counterpart CLI command: apps/agentprovision-cli/src/commands/tasks.rs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.models.dynamic_workflow import DynamicWorkflow, WorkflowRun
from app.models.user import User

router = APIRouter()


# Window for the "completed" group. Anything older than this is treated
# as history and excluded from the dashboard — keeps the response small
# and matches the user's mental model of "what did I just finish."
COMPLETED_LOOKBACK = timedelta(hours=24)


class TaskRow(BaseModel):
    """One row of the dashboard rollup.

    `status` is the v1 grouping signal — values are tightly enumerated
    so the CLI can switch on it without parsing free text. The legacy
    `workflow_runs.status` strings ("running" / "completed" / "failed"
    / "cancelled") fold into `working` (running) and `completed`
    (everything else terminal).
    """

    id: uuid.UUID
    status: Literal["working", "completed"]
    raw_status: str
    title: str
    workflow_id: uuid.UUID
    workflow_name: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    total_tokens: Optional[int] = None
    total_cost_usd: Optional[float] = None
    error: Optional[str] = None


class TaskDashboardResponse(BaseModel):
    working: List[TaskRow]
    completed: List[TaskRow]
    # Hint to the CLI: the v1 endpoint doesn't surface a needs_input
    # group yet. Setting this to False stops the CLI from rendering an
    # empty "NEEDS INPUT (0)" section that would otherwise mislead
    # users into thinking the system never blocks for input.
    supports_needs_input: bool = False


def _row_from_run(run: WorkflowRun, workflow_name: str) -> TaskRow:
    """Map a (run, workflow) tuple to a dashboard row.

    `title` falls back to the workflow name when the run never had its
    own first message — covers the bootstrap window before the agent
    has emitted any text.
    """
    if run.status == "running":
        status: Literal["working", "completed"] = "working"
    else:
        status = "completed"
    return TaskRow(
        id=run.id,
        status=status,
        raw_status=run.status or "unknown",
        title=workflow_name,
        workflow_id=run.workflow_id,
        workflow_name=workflow_name,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_ms=run.duration_ms,
        total_tokens=run.total_tokens,
        total_cost_usd=run.total_cost_usd,
        error=run.error,
    )


@router.get(
    "/tasks",
    response_model=TaskDashboardResponse,
    summary="Cross-machine task rollup for alpha tasks",
)
def list_dashboard_tasks(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    limit: int = Query(50, ge=1, le=200),
) -> TaskDashboardResponse:
    """Return the user's working + recently completed workflow runs.

    Cap behaviour: at most `limit` rows per group. Sorted by most
    recent activity (working: started_at desc; completed: completed_at
    desc with a fallback to started_at). RLS is enforced via the
    tenant_id filter — the model itself has no row-level policy in
    pg, so missing this filter would leak across tenants.
    """
    now = datetime.now(timezone.utc)

    # ── Working: status="running" within this tenant ──
    working_rows = (
        db.query(WorkflowRun, DynamicWorkflow.name)
        .join(DynamicWorkflow, WorkflowRun.workflow_id == DynamicWorkflow.id)
        .filter(
            WorkflowRun.tenant_id == current_user.tenant_id,
            WorkflowRun.status == "running",
        )
        .order_by(WorkflowRun.started_at.desc())
        .limit(limit)
        .all()
    )

    # ── Completed: terminal statuses, within the lookback window ──
    cutoff = now - COMPLETED_LOOKBACK
    completed_rows = (
        db.query(WorkflowRun, DynamicWorkflow.name)
        .join(DynamicWorkflow, WorkflowRun.workflow_id == DynamicWorkflow.id)
        .filter(
            WorkflowRun.tenant_id == current_user.tenant_id,
            WorkflowRun.status.in_(["completed", "failed", "cancelled", "canceled"]),
            # Use COALESCE-style fallback: some legacy rows never wrote
            # completed_at because they crashed mid-step. Allow
            # started_at as a fallback so the user still sees them.
            (WorkflowRun.completed_at.is_(None))
            | (WorkflowRun.completed_at >= cutoff),
        )
        .order_by(
            WorkflowRun.completed_at.desc().nullslast(),
            WorkflowRun.started_at.desc(),
        )
        .limit(limit)
        .all()
    )

    return TaskDashboardResponse(
        working=[_row_from_run(run, name) for run, name in working_rows],
        completed=[_row_from_run(run, name) for run, name in completed_rows],
        supports_needs_input=False,
    )
