"""User activity tracking for workflow pattern detection."""
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Literal
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.api import deps
from app.models.user import User
from app.models.user_activity import UserActivity

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/activities", tags=["activities"])

MACOS_APP_MONITOR_EVENT_SCHEMA = "agentprovision.macos_app_monitor_event.v1"
MACOS_APP_MONITOR_SOURCE = "tauri_activity_tracker"
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_CONTEXT_ID_RE = re.compile(r"^[^:\n\r]{1,80}:[0-9a-f]+$", re.IGNORECASE)

# ── Schemas ──

class ActivityTrackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_schema: Optional[str] = Field(None, alias="schema", max_length=96)
    event_id: Optional[str] = Field(None, max_length=96)
    type: Literal["app_switch", "clipboard_copy", "file_open", "url_visit", "screenshot"] = Field(...)
    source_shell: Optional[str] = Field(None, max_length=100)
    from_app: Optional[str] = Field(None, max_length=255)
    to_app: Optional[str] = Field(None, max_length=255)
    app_name: Optional[str] = Field(None, max_length=255)
    window_title: Optional[str] = Field(None, max_length=500)
    subprocess: Optional[dict] = None  # {active_processes, terminal_cwd} from native client
    duration_secs: Optional[float] = None
    timestamp: Optional[int] = None
    observed_at_ms: Optional[int] = Field(None, ge=0)
    active_context_id: Optional[str] = Field(None, max_length=120)
    detail_level: Optional[str] = Field(None, max_length=80)
    monitor_source: Optional[str] = Field(None, max_length=80)
    window_title_present: Optional[bool] = None
    window_title_chars: Optional[int] = Field(None, ge=0)


def _is_uuid(value: str | None) -> bool:
    return bool(value and _UUID_RE.match(value))


def _is_context_id(value: str | None, app_name: str | None) -> bool:
    if not value or not app_name or not _CONTEXT_ID_RE.match(value):
        return False
    prefix, _hash = value.rsplit(":", 1)
    return prefix == app_name


def _activity_detail(body: ActivityTrackRequest) -> dict:
    """Return display-safe activity detail; raw local content is never stored."""
    base = body.model_dump(
        exclude_none=True,
        exclude={"window_title", "subprocess", "app_name"},
        by_alias=True,
    )

    if body.type != "app_switch":
        return base

    app_name = body.to_app or body.app_name
    detail = {
        "type": body.type,
        "detail_level": "metadata_only",
    }
    for key in ("source_shell", "from_app", "to_app", "duration_secs", "timestamp"):
        value = getattr(body, key)
        if value is not None:
            detail[key] = value

    if body.event_schema == MACOS_APP_MONITOR_EVENT_SCHEMA:
        detail["schema"] = MACOS_APP_MONITOR_EVENT_SCHEMA
        detail["monitor_source"] = MACOS_APP_MONITOR_SOURCE
        if _is_uuid(body.event_id):
            detail["event_id"] = body.event_id.lower()
        if body.observed_at_ms is not None:
            detail["observed_at_ms"] = body.observed_at_ms
        if _is_context_id(body.active_context_id, app_name):
            prefix, context_hash = body.active_context_id.rsplit(":", 1)
            detail["active_context_id"] = f"{prefix}:{context_hash.lower()}"
        if body.window_title_present is not None:
            detail["window_title_present"] = body.window_title_present
        if body.window_title_chars is not None:
            detail["window_title_chars"] = body.window_title_chars

    return detail


# ── App-to-MCP tool mapping for workflow generation ──

APP_TOOL_MAP = {
    "Slack": {"type": "agent", "agent": "luna", "prompt": "Check Slack for unread messages, mentions, and threads needing a reply"},
    "Mail": {"type": "mcp_tool", "tool": "search_emails", "prompt": "Check email inbox for new messages"},
    "Gmail": {"type": "mcp_tool", "tool": "search_emails", "prompt": "Check Gmail for unread emails"},
    "Calendar": {"type": "mcp_tool", "tool": "list_calendar_events", "prompt": "Check upcoming calendar events"},
    "Jira": {"type": "mcp_tool", "tool": "search_jira_issues", "prompt": "Check Jira for assigned issues and sprint items"},
    "GitHub Desktop": {"type": "mcp_tool", "tool": "list_github_pull_requests", "prompt": "Check GitHub for open pull requests"},
    "Chrome": {"type": "agent", "agent": "luna", "prompt": "Summarize what the user was researching in Chrome"},
    "Safari": {"type": "agent", "agent": "luna", "prompt": "Summarize what the user was researching in Safari"},
    "Terminal": {"type": "agent", "agent": "luna", "prompt": "Review recent terminal activity"},
    "Claude Code (Terminal)": {"type": "mcp_tool", "tool": "get_git_history", "prompt": "Check recent Claude Code activity — PRs created, commits, files changed"},
    "Claude Code (iTerm2)": {"type": "mcp_tool", "tool": "get_git_history", "prompt": "Check recent Claude Code activity — PRs created, commits, files changed"},
    "Docker CLI (Terminal)": {"type": "agent", "agent": "luna", "prompt": "Check Docker container status and recent deployments"},
    "Antigravity": {"type": "agent", "agent": "luna", "prompt": "Review Antigravity project status and recent activity"},
    "Xcode": {"type": "agent", "agent": "luna", "prompt": "Check the current Xcode project for build status and recent changes"},
    "Figma": {"type": "agent", "agent": "luna", "prompt": "Review recent Figma design activity"},
    "Notion": {"type": "agent", "agent": "luna", "prompt": "Check Notion for recent updates and assigned tasks"},
}


def _build_step(app: str, step_num: int) -> dict:
    """Build a workflow step for an app, using MCP tools when possible."""
    mapping = APP_TOOL_MAP.get(app)
    if mapping:
        step = {
            "id": f"step_{step_num}",
            "type": mapping["type"],
            "prompt": mapping["prompt"],
            "output": f"step_{step_num}_result",
        }
        if mapping["type"] == "mcp_tool":
            step["tool"] = mapping["tool"]
            step["params"] = {}
        if mapping.get("agent"):
            step["agent"] = mapping["agent"]
        return step
    # Fallback: generic agent step
    return {
        "id": f"step_{step_num}",
        "type": "agent",
        "agent": "luna",
        "prompt": f"Check {app} for any pending items or updates relevant to the user",
        "output": f"step_{step_num}_result",
    }


# ── Endpoints ──

@router.post("/track")
def track_activity(
    body: ActivityTrackRequest,
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Log a user activity event from the native client."""
    if body.event_schema == MACOS_APP_MONITOR_EVENT_SCHEMA and not _is_uuid(body.event_id):
        raise HTTPException(status_code=422, detail="Valid monitor event_id is required")

    activity = UserActivity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        event_type=body.type,
        source_shell=body.source_shell,
        app_name=body.to_app or body.app_name,
        window_title=None,
        detail=_activity_detail(body),
        duration_secs=body.duration_secs,
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
    with suggested workflow automations using real MCP tools.
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Get recent app switches (limit to 10k for performance)
    activities = db.query(UserActivity).filter(
        UserActivity.tenant_id == current_user.tenant_id,
        UserActivity.user_id == current_user.id,
        UserActivity.event_type == "app_switch",
        UserActivity.created_at > since,
    ).order_by(UserActivity.created_at.asc()).limit(10000).all()

    if len(activities) < 10:
        return {"patterns": [], "suggestions": [], "message": "Not enough activity data yet"}

    # Build app transition sequences (bigrams)
    transitions = []
    for i in range(len(activities) - 1):
        if activities[i].app_name and activities[i + 1].app_name:
            transitions.append(f"{activities[i].app_name} -> {activities[i + 1].app_name}")

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

    # Generate workflow suggestions with real MCP tool steps
    suggestions = []
    for seq, count in frequent_trigrams[:5]:
        apps = seq.split(" -> ")
        steps = [_build_step(app, i + 1) for i, app in enumerate(apps)]
        suggestions.append({
            "pattern": seq,
            "frequency": count,
            "apps": apps,
            "suggestion": f"Automate your {apps[0]} + {apps[1]} + {apps[2]} routine",
            "workflow_template": {
                "name": f"Auto: {' + '.join(apps)}",
                "description": f"Detected pattern: you frequently use {seq} ({count} times in {days} days). Created as draft — edit steps before activating.",
                "status": "draft",
                "trigger_config": {"type": "manual"},
                "definition": {
                    "steps": steps,
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
        UserActivity.user_id == current_user.id,
        UserActivity.created_at > since,
    ).scalar()

    top_apps = db.query(
        UserActivity.app_name,
        func.count(UserActivity.id).label("count"),
        func.sum(UserActivity.duration_secs).label("total_seconds"),
    ).filter(
        UserActivity.tenant_id == current_user.tenant_id,
        UserActivity.user_id == current_user.id,
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
