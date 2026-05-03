"""Cost dashboard rollup endpoint — Tier 2 of the visibility roadmap.

`GET /api/v1/insights/cost` aggregates `agent_performance_snapshots`
(hourly per-agent rollups already in DB) into the time series the
chat dashboard needs:
  - Totals (tokens, cost, invocations) for the time range
  - Per-key time series buckets, group_by team / owner / agent
  - Top-10 most-expensive agents in the range
  - Quota burn projection vs `tenant_features.monthly_token_limit`

Curate-don't-dump (lineage from PR #248 UserBrief, PR #256
routing_summary, PR #263 fleet-health):
  - No raw audit_log rows — only aggregates
  - No `tenant_id` on rows (caller knows their own tenant)
  - Per-bucket data has no team/owner email — only top-10 rows do
  - Top-10 includes minimal agent identity (id + name) — no full
    persona, no config, no nested ORM relationships

`group_by=cli_platform` is intentionally NOT supported in this PR.
The agent_performance_snapshot doesn't carry a per-call platform
field; surfacing that needs a schema change. Deferred to a follow-up.
The plan acknowledges this scope cut.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.api import deps
from app.models.agent import Agent
from app.models.agent_performance_snapshot import AgentPerformanceSnapshot
from app.models.tenant_features import TenantFeatures
from app.models.user import User as UserModel

logger = logging.getLogger(__name__)
router = APIRouter()


# Range presets — closed Literal so the frontend filter can render
# matching chips and we get a free schema-level whitelist.
_Range = Literal["7d", "30d", "90d"]
_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}

_Granularity = Literal["day", "week"]
_GroupBy = Literal["team", "owner", "agent"]


class TimeBucket(BaseModel):
    date: str  # ISO date — caller can chart it directly
    tokens: int
    cost_usd: float
    invocations: int


class SeriesEntry(BaseModel):
    """One row in the stacked time series — keyed by team_id /
    owner_user_id / agent_id depending on group_by."""

    key: str  # The aggregation key (uuid string for team/owner/agent)
    label: str  # Human-readable label — team name, owner email, agent name
    tokens: int
    cost_usd: float
    invocations: int
    buckets: List[TimeBucket]


class TopAgent(BaseModel):
    """Per-agent row in the top-10 most-expensive list."""

    id: uuid.UUID
    name: str
    tokens: int
    cost_usd: float
    invocations: int


class QuotaBurn(BaseModel):
    """Linear projection vs tenant's monthly token limit. Absent
    when no limit is set on tenant_features."""

    monthly_limit_tokens: int
    tokens_used_mtd: int
    projected_exhaustion_date: Optional[str]  # ISO date, null if not on track to exceed
    days_until_exhaustion: Optional[int]


class CostInsightsResponse(BaseModel):
    range: Dict[str, str]  # {"start": iso, "end": iso}
    granularity: _Granularity
    group_by: _GroupBy
    totals: Dict[str, float]  # tokens, cost_usd, invocations
    series: List[SeriesEntry]
    top_agents: List[TopAgent]
    quota_burn: Optional[QuotaBurn]


def _bucket_date(dt: datetime, granularity: _Granularity) -> str:
    """Snap a datetime into a bucket key for the chart x-axis.

    Day: ISO date ('2026-05-03'). Week: ISO week-start Monday date.
    """
    if granularity == "week":
        # ISO weeks start Monday. Snap to the Monday of dt's week.
        monday = dt - timedelta(days=dt.weekday())
        return monday.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d")


def _aggregate_by_bucket(
    rows: List[Any],
    *,
    granularity: _Granularity,
    key_fn,
    label_fn,
) -> List[SeriesEntry]:
    """Group snapshot rows by ``key_fn(row)`` then sub-group by bucket.

    `rows` is a list of (snapshot, *labels) tuples; `key_fn` returns
    the grouping key (str) and `label_fn` the display label.
    """
    series_map: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        snap = row[0]
        key = key_fn(row)
        if key is None:
            key = "unassigned"
        bucket_key = _bucket_date(snap.window_start, granularity)
        entry = series_map.setdefault(key, {
            "key": key,
            "label": label_fn(row) or key,
            "tokens": 0,
            "cost_usd": 0.0,
            "invocations": 0,
            "_buckets": {},
        })
        entry["tokens"] += int(snap.total_tokens or 0)
        entry["cost_usd"] += float(snap.total_cost_usd or 0.0)
        entry["invocations"] += int(snap.invocation_count or 0)
        b = entry["_buckets"].setdefault(bucket_key, {
            "date": bucket_key, "tokens": 0, "cost_usd": 0.0, "invocations": 0,
        })
        b["tokens"] += int(snap.total_tokens or 0)
        b["cost_usd"] += float(snap.total_cost_usd or 0.0)
        b["invocations"] += int(snap.invocation_count or 0)

    out: List[SeriesEntry] = []
    for entry in series_map.values():
        buckets = sorted(entry["_buckets"].values(), key=lambda b: b["date"])
        out.append(SeriesEntry(
            key=entry["key"],
            label=entry["label"],
            tokens=entry["tokens"],
            cost_usd=round(entry["cost_usd"], 4),
            invocations=entry["invocations"],
            buckets=[TimeBucket(**b) for b in buckets],
        ))
    # Sort series by total cost desc — the most expensive group is
    # most actionable at the top of the legend.
    out.sort(key=lambda s: s.cost_usd, reverse=True)
    return out


def _quota_burn(
    db: Session, tenant_id: uuid.UUID, now: datetime,
) -> Optional[QuotaBurn]:
    """Linear projection vs tenant_features.monthly_token_limit.

    Skips entirely (returns None) when no limit is set — caller
    omits the field. Linear projection: tokens-used-this-month-to-date
    / days-elapsed-this-month × days-in-this-month >= limit →
    exhaustion before month-end.
    """
    features = (
        db.query(TenantFeatures)
        .filter(TenantFeatures.tenant_id == tenant_id)
        .first()
    )
    if not features or not features.monthly_token_limit:
        return None

    # Month-to-date token sum from snapshots (cheaper than audit_log).
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    mtd_tokens = (
        db.query(func.coalesce(func.sum(AgentPerformanceSnapshot.total_tokens), 0))
        .filter(AgentPerformanceSnapshot.tenant_id == tenant_id)
        .filter(AgentPerformanceSnapshot.window_start >= month_start)
        .scalar()
    ) or 0

    days_elapsed = max((now - month_start).days, 1)
    # Days in the calendar month
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    days_in_month = (next_month - month_start).days

    daily_rate = mtd_tokens / days_elapsed if days_elapsed > 0 else 0
    projected_total = daily_rate * days_in_month
    projected_date: Optional[str] = None
    days_until: Optional[int] = None

    limit = features.monthly_token_limit
    if daily_rate > 0 and projected_total > limit:
        # Days from month_start until usage hits limit at current rate.
        days_to_limit = limit / daily_rate
        exhaustion_dt = month_start + timedelta(days=days_to_limit)
        projected_date = exhaustion_dt.date().isoformat()
        days_until = max((exhaustion_dt - now).days, 0)

    return QuotaBurn(
        monthly_limit_tokens=int(limit),
        tokens_used_mtd=int(mtd_tokens),
        projected_exhaustion_date=projected_date,
        days_until_exhaustion=days_until,
    )


@router.get("/cost", response_model=CostInsightsResponse)
def get_cost_insights(
    *,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
    range: _Range = Query("30d"),
    granularity: _Granularity = Query("day"),
    group_by: _GroupBy = Query("agent"),
):
    """Aggregated cost / usage rollup for the tenant.

    `group_by=cli_platform` is intentionally NOT supported yet —
    snapshots don't carry per-call platform attribution. Use
    structured logs from the `routing_summary` (PR #256) until a
    schema column lands.
    """
    tenant_id = current_user.tenant_id
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    range_days = _RANGE_DAYS[range]
    start = now - timedelta(days=range_days)

    # Base query — outer-join to Agent so an agent that's been deleted
    # mid-range still surfaces as "(deleted agent)" rather than disappearing
    # the cost retroactively. Tenant-scoped at the snapshot level.
    base = (
        db.query(
            AgentPerformanceSnapshot,
            Agent,
            UserModel.email.label("owner_email"),
        )
        .outerjoin(Agent, Agent.id == AgentPerformanceSnapshot.agent_id)
        .outerjoin(UserModel, UserModel.id == Agent.owner_user_id)
        .filter(AgentPerformanceSnapshot.tenant_id == tenant_id)
        .filter(AgentPerformanceSnapshot.window_start >= start)
        .filter(AgentPerformanceSnapshot.agent_id.isnot(None))  # skip external_agent rows
    )
    rows = base.all()

    # Choose key + label functions per group_by.
    if group_by == "agent":
        def _key(row): return str(row[1].id) if row[1] else "deleted"
        def _label(row): return row[1].name if row[1] else "(deleted agent)"
    elif group_by == "team":
        def _key(row): return str(row[1].team_id) if row[1] and row[1].team_id else None
        def _label(row): return None  # team name lookup deferred — show team_id for now
    else:  # owner
        def _key(row): return str(row[1].owner_user_id) if row[1] and row[1].owner_user_id else None
        def _label(row): return row[2] or None  # owner email

    series = _aggregate_by_bucket(
        rows, granularity=granularity, key_fn=_key, label_fn=_label,
    )

    # Totals across all series — chart header card.
    totals = {
        "tokens": sum(s.tokens for s in series),
        "cost_usd": round(sum(s.cost_usd for s in series), 4),
        "invocations": sum(s.invocations for s in series),
    }

    # Top-10 most expensive agents in the range. Computed on the
    # SAME row set so totals + top_agents agree.
    by_agent: Dict[str, Dict[str, Any]] = {}
    for snap, agent, _email in rows:
        if not agent:
            continue
        e = by_agent.setdefault(str(agent.id), {
            "id": agent.id, "name": agent.name,
            "tokens": 0, "cost_usd": 0.0, "invocations": 0,
        })
        e["tokens"] += int(snap.total_tokens or 0)
        e["cost_usd"] += float(snap.total_cost_usd or 0.0)
        e["invocations"] += int(snap.invocation_count or 0)
    top_10 = sorted(by_agent.values(), key=lambda r: r["cost_usd"], reverse=True)[:10]
    top_agents = [TopAgent(
        id=r["id"], name=r["name"],
        tokens=r["tokens"], cost_usd=round(r["cost_usd"], 4),
        invocations=r["invocations"],
    ) for r in top_10]

    return CostInsightsResponse(
        range={"start": start.date().isoformat(), "end": now.date().isoformat()},
        granularity=granularity,
        group_by=group_by,
        totals=totals,
        series=series,
        top_agents=top_agents,
        quota_burn=_quota_burn(db, tenant_id, now),
    )
