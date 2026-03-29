"""User activity tracking for workflow pattern detection."""
import logging
from datetime import datetime, timedelta
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.api import deps
from app.models.user import User
from app.models.user_activity import UserActivity

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/activities", tags=["activities"])


@router.post("/track")
def track_activity(
    body: dict,
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Log a user activity event from the native client."""
    activity = UserActivity(
        tenant_id=current_user.tenant_id,
        event_type=body.get("type", "unknown"),
        source_shell=body.get("source_shell"),
        app_name=body.get("to_app") or body.get("app_name"),
        window_title=body.get("window_title"),
        detail=body,
        duration_secs=body.get("duration_secs"),
    )
    db.add(activity)
    db.commit()
    return {"status": "ok"}


@router.get("/patterns")
def detect_patterns(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    days: int = Query(7, ge=1, le=30),
):
    """Detect repeating app usage patterns from recent activity.

    Returns sequences of apps that appear together frequently,
    with suggested workflow automations.
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Get recent app switches
    activities = db.query(UserActivity).filter(
        UserActivity.tenant_id == current_user.tenant_id,
        UserActivity.event_type == "app_switch",
        UserActivity.created_at > since,
    ).order_by(UserActivity.created_at).all()

    if len(activities) < 10:
        return {"patterns": [], "message": "Not enough activity data yet"}

    # Build app transition sequences (bigrams)
    transitions = []
    for i in range(len(activities) - 1):
        if activities[i].app_name and activities[i + 1].app_name:
            transitions.append(f"{activities[i].app_name} -> {activities[i + 1].app_name}")

    # Count frequent transitions
    counter = Counter(transitions)
    frequent = [(seq, count) for seq, count in counter.most_common(20) if count >= 3]

    # Build trigram sequences (3-app patterns)
    trigrams = []
    for i in range(len(activities) - 2):
        apps = [activities[i].app_name, activities[i + 1].app_name, activities[i + 2].app_name]
        if all(apps):
            trigrams.append(" -> ".join(apps))

    trigram_counter = Counter(trigrams)
    frequent_trigrams = [(seq, count) for seq, count in trigram_counter.most_common(10) if count >= 2]

    # Time-of-day patterns
    hour_apps = {}
    for a in activities:
        if a.app_name and a.created_at:
            hour = a.created_at.hour
            bucket = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
            hour_apps.setdefault(bucket, []).append(a.app_name)

    time_patterns = {}
    for period, apps in hour_apps.items():
        top = Counter(apps).most_common(3)
        time_patterns[period] = [{"app": app, "count": count} for app, count in top]

    # Generate workflow suggestions
    suggestions = []
    for seq, count in frequent_trigrams[:5]:
        apps = seq.split(" -> ")
        suggestions.append({
            "pattern": seq,
            "frequency": count,
            "apps": apps,
            "suggestion": f"Automate your {apps[0]} -> {apps[1]} -> {apps[2]} workflow",
            "workflow_template": {
                "name": f"Auto: {' + '.join(apps)}",
                "description": f"Detected pattern: you frequently switch {seq} ({count} times in {days} days)",
                "trigger_config": {"type": "manual"},
                "definition": {
                    "steps": [
                        {"id": f"step_{i+1}", "type": "agent", "prompt": f"Check {app} for pending items", "output": f"step_{i+1}_result"}
                        for i, app in enumerate(apps)
                    ]
                },
            },
        })

    return {
        "patterns": {
            "transitions": [{"sequence": s, "count": c} for s, c in frequent],
            "sequences": [{"sequence": s, "count": c} for s, c in frequent_trigrams],
            "time_of_day": time_patterns,
        },
        "suggestions": suggestions,
        "activity_count": len(activities),
        "period_days": days,
    }


@router.get("/summary")
def activity_summary(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    days: int = Query(7, ge=1, le=30),
):
    """Summary of user activity for the given period."""
    since = datetime.utcnow() - timedelta(days=days)

    total = db.query(func.count(UserActivity.id)).filter(
        UserActivity.tenant_id == current_user.tenant_id,
        UserActivity.created_at > since,
    ).scalar()

    top_apps = db.query(
        UserActivity.app_name,
        func.count(UserActivity.id).label("count"),
        func.sum(UserActivity.duration_secs).label("total_seconds"),
    ).filter(
        UserActivity.tenant_id == current_user.tenant_id,
        UserActivity.created_at > since,
        UserActivity.app_name.isnot(None),
    ).group_by(UserActivity.app_name).order_by(text("count DESC")).limit(10).all()

    return {
        "total_events": total,
        "period_days": days,
        "top_apps": [
            {"app": app, "switches": count, "total_seconds": secs or 0}
            for app, count, secs in top_apps
        ],
    }
