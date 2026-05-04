"""Briefing service — morning overture + evening finale.

Aggregates "what happened since you last looked" into a compact narrative
the spatial scene's Movements component can animate. Same shape for both
overture (morning) and finale (evening); the consumer chooses framing.

No new tables. Pure read over agent_performance_snapshots, workflow_runs,
notifications, commitment_records, memory_activities.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.dynamic_workflow import WorkflowRun
from app.models.notification import Notification


def _short(s: Optional[str], n: int = 100) -> Optional[str]:
    if not s:
        return s
    return s[:n] + ("…" if len(s) > n else "")


def build_briefing(
    db: Session, tenant_id: uuid.UUID, since: Optional[datetime] = None
) -> Dict[str, Any]:
    now = datetime.utcnow()
    if since is None:
        since = now - timedelta(hours=12)
    if since > now:
        since = now - timedelta(hours=12)

    # ── Workflow runs that completed in the window ────────────────────────
    completed = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.completed_at >= since,
            WorkflowRun.status.in_(("completed", "failed")),
        )
        .order_by(desc(WorkflowRun.completed_at))
        .limit(20)
        .all()
    )
    completed_payload = [
        {
            "id": str(r.id),
            "status": r.status,
            "duration_ms": r.duration_ms,
            "platform": r.platform,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "workflow_id": str(r.workflow_id) if r.workflow_id else None,
        }
        for r in completed
    ]

    # ── Notifications received in the window (high-priority first) ────────
    from sqlalchemy import case
    priority_rank = case(
        (Notification.priority == "high", 0),
        (Notification.priority == "medium", 1),
        (Notification.priority == "low", 2),
        else_=3,
    )
    new_notifs = (
        db.query(Notification)
        .filter(
            Notification.tenant_id == tenant_id,
            Notification.created_at >= since,
        )
        .order_by(priority_rank, Notification.created_at.desc())
        .limit(10)
        .all()
    )
    notifs_payload = [
        {
            "id": str(n.id),
            "title": _short(n.title, 80),
            "source": n.source,
            "priority": n.priority,
            "created_at": n.created_at.isoformat(),
        }
        for n in new_notifs
    ]

    # ── Recently logged memory activities ─────────────────────────────────
    activities_payload: List[Dict[str, Any]] = []
    try:
        from app.models.memory_activity import MemoryActivity  # type: ignore
        activities = (
            db.query(MemoryActivity)
            .filter(
                MemoryActivity.tenant_id == tenant_id,
                MemoryActivity.created_at >= since,
            )
            .order_by(MemoryActivity.created_at.desc())
            .limit(10)
            .all()
        )
        for a in activities:
            activities_payload.append(
                {
                    "id": str(a.id),
                    "event_type": a.event_type,
                    "description": _short(a.description, 100),
                    "source": a.source,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
            )
    except Exception:
        activities_payload = []

    # ── Open commitments (best-effort) ─────────────────────────────────────
    open_commitments_payload: List[Dict[str, Any]] = []
    try:
        from app.models.commitment_record import CommitmentRecord  # type: ignore
        rows = (
            db.query(CommitmentRecord)
            .filter(
                CommitmentRecord.tenant_id == tenant_id,
                CommitmentRecord.state == "open",
            )
            .order_by(CommitmentRecord.due_at.asc().nullslast())
            .limit(10)
            .all()
        )
        for c in rows:
            open_commitments_payload.append(
                {
                    "id": str(c.id),
                    "title": _short(c.title, 100),
                    "owner_agent_slug": c.owner_agent_slug,
                    "due_at": c.due_at.isoformat() if c.due_at else None,
                    "priority": c.priority,
                }
            )
    except Exception:
        open_commitments_payload = []

    # ── Headline numbers — for the spatial scene's totals ──────────────────
    completed_count = sum(1 for r in completed if r.status == "completed")
    failed_count = sum(1 for r in completed if r.status == "failed")
    return {
        "captured_at": now.isoformat(),
        "since": since.isoformat(),
        "totals": {
            "workflows_completed": completed_count,
            "workflows_failed": failed_count,
            "notifications_received": len(new_notifs),
            "memory_activities": len(activities_payload),
            "open_commitments": len(open_commitments_payload),
        },
        "completed_workflows": completed_payload,
        "notifications": notifs_payload,
        "activities": activities_payload,
        "open_commitments": open_commitments_payload,
    }
