"""Tenant health admin page — Op-2 of the visibility roadmap.

Superuser-only cross-tenant rollup. Each row summarizes how a single
tenant is using the platform over a recent window: chat volume,
fallback rate, chain-exhausted count, last activity, agent count.

Curate-don't-dump rule (PR #248 / #256 / #263 / #265 / #267 / #268 /
#269): no per-tenant message IDs, no agent IDs in the rollup, no
PII. The dashboard is for "is tenant X healthy?" triage, not deep
inspection — operators drill into the tenant's normal pages from
there.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api import deps
from app.models.agent import Agent
from app.models.chat import ChatMessage, ChatSession
from app.models.tenant import Tenant
from app.models.user import User


router = APIRouter()


class TenantHealthRow(BaseModel):
    """Single row in the cross-tenant rollup. Exposed fields are
    curated for triage; per-message detail stays inside the tenant's
    own pages."""

    tenant_id: str = Field(..., description="UUID — superuser scope, drillable")
    tenant_name: str
    user_count: int
    active_agent_count: int = Field(..., description="Agents with status=production")
    turn_count_24h: int
    fallback_rate_24h: float = Field(..., description="0..1, share of turns where served != requested")
    chain_exhausted_24h: int = Field(..., description="Turns where every CLI in the chain errored")
    last_activity_at: Optional[datetime] = Field(None, description="Most recent assistant turn timestamp")
    primary_cli: Optional[str] = Field(None, description="snake_case identifier of the dominant served-by CLI")


class TenantHealthResponse(BaseModel):
    window_hours: int
    rows: List[TenantHealthRow]


@router.get("/tenant-health", response_model=TenantHealthResponse)
def list_tenant_health(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.require_superuser),
    lookback_hours: int = Query(24, ge=1, le=168),
):
    """Cross-tenant health rollup. Superuser only."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    # Base tenant list — every tenant gets a row, even if they had
    # zero activity (a stalled tenant is exactly the kind of thing
    # this dashboard exists to surface).
    tenants = db.query(Tenant).order_by(Tenant.name).all()

    # User counts
    user_counts = dict(
        db.query(User.tenant_id, func.count(User.id))
        .group_by(User.tenant_id)
        .all()
    )

    # Active agent counts (status='production')
    agent_counts = dict(
        db.query(Agent.tenant_id, func.count(Agent.id))
        .filter(Agent.status == "production")
        .group_by(Agent.tenant_id)
        .all()
    )

    # Per-tenant chat aggregates over the window
    msg_rows = (
        db.query(ChatSession.tenant_id, ChatMessage.context, ChatMessage.created_at)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .filter(
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= cutoff,
        )
        .all()
    )

    by_tenant_turns: Counter = Counter()
    by_tenant_fallback: Counter = Counter()
    by_tenant_exhausted: Counter = Counter()
    by_tenant_last_activity: dict = {}
    by_tenant_served: defaultdict = defaultdict(Counter)

    for tenant_id, ctx, created_at in msg_rows:
        if tenant_id is None:
            continue
        # Track last_activity even when context is missing — the
        # absence of routing_summary doesn't make the turn invisible,
        # only un-aggregatable for fallback/served stats.
        prev = by_tenant_last_activity.get(tenant_id)
        if prev is None or created_at > prev:
            by_tenant_last_activity[tenant_id] = created_at

        if not isinstance(ctx, dict):
            continue
        rs = ctx.get("routing_summary")
        if not isinstance(rs, dict):
            continue

        by_tenant_turns[tenant_id] += 1

        platform = rs.get("served_by_platform")
        if platform:
            by_tenant_served[tenant_id][platform] += 1

        if rs.get("error_state") == "exhausted":
            by_tenant_exhausted[tenant_id] += 1

        served_p = (rs.get("served_by_platform") or "").lower()
        requested_p = (rs.get("requested_platform") or "").lower()
        if rs.get("fallback_reason") or (
            requested_p and served_p and served_p != requested_p
        ):
            by_tenant_fallback[tenant_id] += 1

    rows: List[TenantHealthRow] = []
    for t in tenants:
        turns = by_tenant_turns.get(t.id, 0)
        served_dist = by_tenant_served.get(t.id, Counter())
        primary = served_dist.most_common(1)[0][0] if served_dist else None
        last_at = by_tenant_last_activity.get(t.id)
        rows.append(
            TenantHealthRow(
                tenant_id=str(t.id),
                tenant_name=t.name or "(unnamed)",
                user_count=user_counts.get(t.id, 0),
                active_agent_count=agent_counts.get(t.id, 0),
                turn_count_24h=turns,
                fallback_rate_24h=(
                    round(by_tenant_fallback.get(t.id, 0) / turns, 4) if turns else 0.0
                ),
                chain_exhausted_24h=by_tenant_exhausted.get(t.id, 0),
                last_activity_at=last_at,
                primary_cli=primary,
            )
        )

    return TenantHealthResponse(window_hours=lookback_hours, rows=rows)
