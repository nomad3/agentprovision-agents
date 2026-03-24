"""Activities for the GoalReviewWorkflow."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List

from temporalio import activity

logger = logging.getLogger(__name__)

# Goals not reviewed in this many days are considered stalled
STALE_GOAL_DAYS = 7
# Goals active for this long without progress update are flagged
NO_PROGRESS_DAYS = 14


@activity.defn(name="review_goals")
async def review_goals(tenant_id: str) -> dict:
    """Review all active goals for a tenant. Detect stalled, blocked, contradictory."""
    from app.db.session import SessionLocal
    from app.models.goal_record import GoalRecord

    db = SessionLocal()
    try:
        active_goals = (
            db.query(GoalRecord)
            .filter(
                GoalRecord.tenant_id == tenant_id,
                GoalRecord.state.in_(["proposed", "active", "blocked"]),
            )
            .all()
        )

        now = datetime.utcnow()
        stalled: List[Dict] = []
        no_progress: List[Dict] = []
        long_blocked: List[Dict] = []
        total = len(active_goals)

        for goal in active_goals:
            goal_info = {
                "id": str(goal.id),
                "title": goal.title,
                "state": goal.state,
                "agent": goal.owner_agent_slug,
                "priority": goal.priority,
            }

            # Stalled: not reviewed in STALE_GOAL_DAYS
            last_touch = goal.last_reviewed_at or goal.updated_at or goal.created_at
            if last_touch < now - timedelta(days=STALE_GOAL_DAYS):
                stalled.append(goal_info)

            # No progress: active for NO_PROGRESS_DAYS with 0% progress
            if (
                goal.state == "active"
                and goal.progress_pct == 0
                and goal.created_at < now - timedelta(days=NO_PROGRESS_DAYS)
            ):
                no_progress.append(goal_info)

            # Long blocked: blocked for more than 3 days
            if (
                goal.state == "blocked"
                and goal.updated_at
                and goal.updated_at < now - timedelta(days=3)
            ):
                long_blocked.append(goal_info)

            # Only mark non-flagged goals as reviewed.
            # Stalled/blocked goals keep their old timestamp so they stay
            # flagged until a human or agent actually touches them.
            is_flagged = (
                goal_info in stalled
                or goal_info in no_progress
                or goal_info in long_blocked
            )
            if not is_flagged:
                goal.last_reviewed_at = now

        # Overdue deadlines
        overdue_goals = [
            {
                "id": str(g.id),
                "title": g.title,
                "agent": g.owner_agent_slug,
                "deadline": g.deadline.isoformat() if g.deadline else None,
            }
            for g in active_goals
            if g.deadline and g.deadline < now and g.state != "completed"
        ]

        db.commit()

        return {
            "total_reviewed": total,
            "stalled_count": len(stalled),
            "stalled": stalled[:20],
            "no_progress": no_progress[:20],
            "long_blocked": long_blocked[:20],
            "overdue_goals": overdue_goals[:20],
        }
    except Exception as e:
        logger.error("review_goals failed for tenant %s: %s", tenant_id[:8], e)
        db.rollback()
        raise
    finally:
        db.close()


@activity.defn(name="review_commitments")
async def review_commitments(tenant_id: str) -> dict:
    """Check for overdue and stale commitments."""
    from app.db.session import SessionLocal
    from app.models.commitment_record import CommitmentRecord

    db = SessionLocal()
    try:
        open_commitments = (
            db.query(CommitmentRecord)
            .filter(
                CommitmentRecord.tenant_id == tenant_id,
                CommitmentRecord.state.in_(["open", "in_progress"]),
            )
            .all()
        )

        now = datetime.utcnow()
        overdue: List[Dict] = []
        stale: List[Dict] = []

        for c in open_commitments:
            info = {
                "id": str(c.id),
                "title": c.title,
                "agent": c.owner_agent_slug,
                "due_at": c.due_at.isoformat() if c.due_at else None,
            }

            if c.due_at and c.due_at < now:
                overdue.append(info)

            last_touch = c.updated_at or c.created_at
            if last_touch < now - timedelta(days=STALE_GOAL_DAYS):
                stale.append(info)

        return {
            "total_open": len(open_commitments),
            "overdue_count": len(overdue),
            "overdue": overdue[:20],
            "stale": stale[:20],
        }
    except Exception as e:
        logger.error("review_commitments failed for tenant %s: %s", tenant_id[:8], e)
        raise
    finally:
        db.close()


@activity.defn(name="create_review_notifications")
async def create_review_notifications(
    tenant_id: str,
    goal_review: dict,
    commitment_review: dict,
) -> int:
    """Create notifications for flagged goals and commitments."""
    from app.db.session import SessionLocal
    from app.models.notification import Notification

    items_to_notify = []

    for g in goal_review.get("stalled", []):
        items_to_notify.append({
            "title": f"Stalled goal: {g['title']}",
            "message": f"Goal '{g['title']}' (agent: {g['agent']}) has not been reviewed recently.",
            "priority": "medium",
            "reference_id": f"goal:{g['id']}:stalled",
            "reference_type": "goal_review",
        })

    for g in goal_review.get("no_progress", []):
        items_to_notify.append({
            "title": f"No progress: {g['title']}",
            "message": f"Goal '{g['title']}' (agent: {g['agent']}) has been active for 14+ days with 0% progress.",
            "priority": "medium",
            "reference_id": f"goal:{g['id']}:no_progress",
            "reference_type": "goal_review",
        })

    for g in goal_review.get("overdue_goals", []):
        items_to_notify.append({
            "title": f"Overdue goal: {g['title']}",
            "message": f"Goal '{g['title']}' (agent: {g['agent']}) is past its deadline ({g.get('deadline', 'unknown')}).",
            "priority": "high",
            "reference_id": f"goal:{g['id']}:overdue",
            "reference_type": "goal_review",
        })

    for g in goal_review.get("long_blocked", []):
        items_to_notify.append({
            "title": f"Blocked goal: {g['title']}",
            "message": f"Goal '{g['title']}' (agent: {g['agent']}) has been blocked for more than 3 days.",
            "priority": "medium",
            "reference_id": f"goal:{g['id']}:blocked",
            "reference_type": "goal_review",
        })

    for c in commitment_review.get("overdue", []):
        items_to_notify.append({
            "title": f"Overdue commitment: {c['title']}",
            "message": f"Commitment '{c['title']}' (agent: {c['agent']}) is past due ({c.get('due_at', 'unknown')}).",
            "priority": "high",
            "reference_id": f"commitment:{c['id']}:overdue",
            "reference_type": "goal_review",
        })

    if not items_to_notify:
        return 0

    db = SessionLocal()
    try:
        created = 0
        for item in items_to_notify[:50]:  # cap at 50 per cycle
            # Dedup: skip if an active (not dismissed) notification exists for same ref
            existing = (
                db.query(Notification)
                .filter(
                    Notification.tenant_id == tenant_id,
                    Notification.source == "goal_review",
                    Notification.reference_id == item["reference_id"],
                    Notification.dismissed == False,  # noqa: E712
                )
                .first()
            )
            if existing:
                continue
            notification = Notification(
                tenant_id=tenant_id,
                source="goal_review",
                title=item["title"],
                body=item["message"],
                priority=item["priority"],
                reference_id=item["reference_id"],
                reference_type=item["reference_type"],
            )
            db.add(notification)
            created += 1
        db.commit()
        logger.info("Created %d goal review notifications for tenant %s", created, tenant_id[:8])
        return created
    except Exception as e:
        logger.error("create_review_notifications failed: %s", e)
        db.rollback()
        return 0
    finally:
        db.close()
