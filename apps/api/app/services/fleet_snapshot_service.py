"""Fleet snapshot — single-shot aggregator for the Luna OS Podium boot.

Returns everything the spatial scene needs in one round-trip so the user's
podium paints in <1.5s on first launch:
  - agents (production + staging) with their team_id
  - agent_groups (sections in the orchestra)
  - latest performance snapshot per agent (for halo intensity)
  - active collaborations (for comms beams)
  - recent unread notifications (inbox melody, top of scene)
  - open commitments (inbox melody)

No new tables. Pure read-only aggregation over existing models.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_group import AgentGroup
from app.models.agent_performance_snapshot import AgentPerformanceSnapshot
from app.models.notification import Notification
from app.models.dynamic_workflow import DynamicWorkflow, WorkflowRun, WorkflowStepLog


def _agent_to_dict(a: Agent, latest_snapshot: Optional[AgentPerformanceSnapshot]) -> Dict[str, Any]:
    return {
        "id": str(a.id),
        "name": a.name,
        "role": a.role,
        "team_id": str(a.team_id) if a.team_id else None,
        "status": a.status,
        "version": a.version,
        "owner_user_id": str(a.owner_user_id) if a.owner_user_id else None,
        "personality": a.personality,
        # Halo signal — derived from the last performance window. The scene
        # multiplies these into pulse intensity / color.
        "activity": {
            "invocations": latest_snapshot.invocation_count if latest_snapshot else 0,
            "success_rate": (
                latest_snapshot.success_count / latest_snapshot.invocation_count
                if latest_snapshot and latest_snapshot.invocation_count
                else None
            ),
            "avg_quality_score": latest_snapshot.avg_quality_score if latest_snapshot else None,
            "p95_latency_ms": latest_snapshot.latency_p95_ms if latest_snapshot else None,
            "window_start": latest_snapshot.window_start.isoformat() if latest_snapshot else None,
        },
    }


def _group_to_dict(g: AgentGroup) -> Dict[str, Any]:
    return {
        "id": str(g.id),
        "name": g.name,
        "description": g.description,
        "goal": g.goal,
    }


def _notification_to_dict(n: Notification) -> Dict[str, Any]:
    return {
        "id": str(n.id),
        "title": n.title,
        "body": (n.body or "")[:200] if n.body else None,
        "source": n.source,
        "priority": n.priority,
        "created_at": n.created_at.isoformat(),
        "read": bool(n.read),
        "reference_type": n.reference_type,
    }


def build_snapshot(db: Session, tenant_id: uuid.UUID) -> Dict[str, Any]:
    """Assemble the full podium snapshot in one transaction."""
    now = datetime.utcnow()
    one_hour_ago = now - timedelta(hours=1)

    # ── Agents (production + staging only — drafts and deprecated stay off
    # the podium) ──────────────────────────────────────────────────────────
    agents = (
        db.query(Agent)
        .filter(
            Agent.tenant_id == tenant_id,
            Agent.status.in_(("production", "staging")),
        )
        .order_by(Agent.team_id.asc().nullslast(), Agent.name.asc())
        .all()
    )

    # ── Latest performance snapshot per agent (one query, in-memory bucket) ─
    snapshots = (
        db.query(AgentPerformanceSnapshot)
        .filter(
            AgentPerformanceSnapshot.tenant_id == tenant_id,
            AgentPerformanceSnapshot.window_start >= now - timedelta(hours=24),
        )
        .order_by(AgentPerformanceSnapshot.window_start.desc())
        .all()
    )
    snapshot_by_agent: Dict[uuid.UUID, AgentPerformanceSnapshot] = {}
    for s in snapshots:
        if s.agent_id and s.agent_id not in snapshot_by_agent:
            snapshot_by_agent[s.agent_id] = s

    agents_payload = [_agent_to_dict(a, snapshot_by_agent.get(a.id)) for a in agents]

    # ── Groups (sections) ──────────────────────────────────────────────────
    groups = (
        db.query(AgentGroup)
        .filter(AgentGroup.tenant_id == tenant_id)
        .order_by(AgentGroup.name.asc())
        .all()
    )
    groups_payload = [_group_to_dict(g) for g in groups]

    # ── Active collaborations (for comms beams) ────────────────────────────
    # Active = blackboards with status='active' that have entries within the
    # last hour. Participants are derived from the *distinct authors* of
    # those entries (BlackboardEntry.author_agent_slug). We resolve each
    # slug to an agent.id by name match against the tenant's agent roster
    # so the spatial scene can locate them; slugs that don't match any
    # known agent are returned as-is so the UI can still log them.
    active_collaborations: List[Dict[str, Any]] = []
    try:
        from app.models.blackboard import Blackboard, BlackboardEntry  # type: ignore

        # Build a slug → agent_id map once. Agents may not have a "slug" field
        # so we match on lowercased name; this is best-effort.
        slug_to_agent_id: Dict[str, str] = {}
        for a in agents:
            if a.name:
                slug_to_agent_id[a.name.lower()] = str(a.id)
                # Common slug convention: lowercased name with spaces → underscores
                slug_to_agent_id[a.name.lower().replace(" ", "_")] = str(a.id)

        live = (
            db.query(Blackboard)
            .filter(
                Blackboard.tenant_id == tenant_id,
                Blackboard.status == "active",
                Blackboard.updated_at >= one_hour_ago,
            )
            .order_by(desc(Blackboard.updated_at))
            .limit(20)
            .all()
        )
        for bb in live:
            slugs = (
                db.query(BlackboardEntry.author_agent_slug)
                .filter(BlackboardEntry.blackboard_id == bb.id)
                .distinct()
                .all()
            )
            slug_set = [s[0] for s in slugs if s[0]]
            participants = [
                slug_to_agent_id.get(s.lower(), s) for s in slug_set
            ]
            active_collaborations.append(
                {
                    "id": str(bb.id),
                    "title": bb.title,
                    "status": bb.status,
                    "participants": participants,
                    "participant_slugs": slug_set,  # for UI fallback
                    "started_at": bb.created_at.isoformat() if bb.created_at else None,
                    "updated_at": bb.updated_at.isoformat() if bb.updated_at else None,
                }
            )
    except Exception as e:  # pragma: no cover — defensive for schema variants
        active_collaborations = []

    # ── Inbox melody — recent notifications (unread, last 24h) ─────────────
    # Priority is a string column ("high"/"medium"/"low"); alphabetic sort
    # would order "high" < "low" < "medium" which puts low-priority items
    # ahead of medium ones. Map to integer rank so high comes first.
    priority_rank = case(
        (Notification.priority == "high", 0),
        (Notification.priority == "medium", 1),
        (Notification.priority == "low", 2),
        else_=3,
    )
    notifications = (
        db.query(Notification)
        .filter(
            Notification.tenant_id == tenant_id,
            Notification.dismissed.is_(False),
            Notification.created_at >= now - timedelta(hours=24),
        )
        .order_by(priority_rank, Notification.created_at.desc())
        .limit(15)
        .all()
    )
    notifications_payload = [_notification_to_dict(n) for n in notifications]

    # ── Inbox melody — open commitments (best-effort import; tolerate absence) ─
    commitments_payload: List[Dict[str, Any]] = []
    try:
        from app.models.commitment_record import CommitmentRecord  # type: ignore
        commitments = (
            db.query(CommitmentRecord)
            .filter(
                CommitmentRecord.tenant_id == tenant_id,
                CommitmentRecord.state == "open",
            )
            .order_by(CommitmentRecord.due_at.asc().nullslast())
            .limit(10)
            .all()
        )
        for c in commitments:
            commitments_payload.append(
                {
                    "id": str(c.id),
                    "title": c.title,
                    "owner_agent_slug": c.owner_agent_slug,
                    "state": c.state,
                    "priority": c.priority,
                    "due_at": c.due_at.isoformat() if c.due_at else None,
                }
            )
    except Exception:
        commitments_payload = []

    # ── The Score (Phase B) — running workflows + their last few steps ──────
    # Surface workflow_runs that are running OR completed within the last
    # 10 minutes (so finishing flourishes are visible). Each run carries a
    # compact step list so the spatial Score zone can draw the flowing
    # graph without an extra round-trip.
    running_workflows: List[Dict[str, Any]] = []
    try:
        ten_min_ago = now - timedelta(minutes=10)
        runs = (
            db.query(WorkflowRun)
            .filter(
                WorkflowRun.tenant_id == tenant_id,
                (
                    (WorkflowRun.status == "running")
                    | (WorkflowRun.completed_at >= ten_min_ago)
                ),
            )
            .order_by(desc(WorkflowRun.started_at))
            .limit(15)
            .all()
        )
        run_ids = [r.id for r in runs]
        steps_by_run: Dict[uuid.UUID, List[WorkflowStepLog]] = {}
        if run_ids:
            step_rows = (
                db.query(WorkflowStepLog)
                .filter(WorkflowStepLog.run_id.in_(run_ids))
                .order_by(WorkflowStepLog.started_at.asc().nullslast())
                .all()
            )
            for s in step_rows:
                steps_by_run.setdefault(s.run_id, []).append(s)

        # Best-effort lookup of workflow names for display labels.
        workflow_ids = list({r.workflow_id for r in runs if r.workflow_id})
        wf_names: Dict[uuid.UUID, str] = {}
        if workflow_ids:
            for wf in db.query(DynamicWorkflow).filter(DynamicWorkflow.id.in_(workflow_ids)).all():
                wf_names[wf.id] = wf.name

        for r in runs:
            steps = steps_by_run.get(r.id, [])[:12]  # cap per run
            running_workflows.append({
                "id": str(r.id),
                "workflow_id": str(r.workflow_id) if r.workflow_id else None,
                "workflow_name": wf_names.get(r.workflow_id) if r.workflow_id else None,
                "status": r.status,
                "current_step": r.current_step,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_ms": r.duration_ms,
                "platform": r.platform,
                "steps": [
                    {
                        "id": str(s.id),
                        "step_id": s.step_id,
                        "step_type": s.step_type,
                        "step_name": s.step_name,
                        "status": s.status,
                        "duration_ms": s.duration_ms,
                    }
                    for s in steps
                ],
            })
    except Exception:  # pragma: no cover — defensive for schema variants
        running_workflows = []

    return {
        "captured_at": now.isoformat(),
        "agents": agents_payload,
        "groups": groups_payload,
        "active_collaborations": active_collaborations,
        "notifications": notifications_payload,
        "commitments": commitments_payload,
        "running_workflows": running_workflows,
    }
