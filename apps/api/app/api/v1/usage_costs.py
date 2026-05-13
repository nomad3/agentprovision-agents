"""Tenant-scoped usage + cost rollups for the `alpha usage` and
`alpha costs` CLI subcommands (Phase 4 of the CLI roadmap, #181).

Two surfaces:

* `GET /api/v1/usage?period=mtd|7d|30d|24h` — per-provider
  aggregation over `chat_messages` for the caller's tenant. One row
  per provider (claude / codex / gemini / opencode / copilot) with
  total input_tokens, output_tokens, cost_usd, message count. Sorted
  by cost desc.

* `GET /api/v1/costs?period=mtd|7d|30d|24h[&agent_id=...]` — daily
  rollup of cost + task count + p95 latency over `chat_messages`
  for the caller's tenant. One row per day. Optional agent filter.

Provider classification uses the same `_PROVIDER_MODEL_PREFIXES`
map as `cost_estimator.py` so a future ledger schema swap keeps the
two surfaces in sync.

Distinct from `/insights/cost`:
* `/insights/cost` aggregates `agent_performance_snapshots`
  (hourly per-agent rollups) and groups by agent / team / owner.
* `/usage` + `/costs` aggregate `chat_messages` directly (per-
  message granularity) and group by provider / day. The CLI needs
  the per-message shape because the roadmap example surfaces
  per-provider token splits, which the snapshots don't track.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_active_user
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.services.cost_estimator import _PROVIDER_MODEL_PREFIXES

router = APIRouter()

# Tenant-scoped periods. `mtd` = month-to-date. The rest are rolling
# windows ending now. Aligns with the roadmap example values.
Period = Literal["24h", "7d", "30d", "mtd"]


def _period_start(period: str) -> datetime:
    """Translate a period code to a start datetime (UTC, naive — the
    column is `TIMESTAMP WITHOUT TIME ZONE`)."""
    now = datetime.utcnow()
    if period == "24h":
        return now - timedelta(hours=24)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    if period == "mtd":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Defensive — pydantic gates the Literal so we shouldn't get here.
    return now - timedelta(days=30)


# ──────────────────────────────────────────────────────────────────────
# /usage — per-provider rollup
# ──────────────────────────────────────────────────────────────────────


class ProviderUsage(BaseModel):
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    message_count: int = 0


class UsageResponse(BaseModel):
    period: str
    start: datetime
    end: datetime
    rows: list[ProviderUsage]
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0


@router.get("/usage", response_model=UsageResponse)
def get_usage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    period: Period = Query("mtd"),
):
    """Per-provider usage rollup for the caller's tenant."""
    start = _period_start(period)
    end = datetime.utcnow()

    # One SQL pass: join chat_messages → chat_sessions for tenant
    # isolation, aggregate per chat_message.model. Then classify in
    # Python — the prefix-map is small (5 providers, ~10 prefixes
    # total) and the post-aggregation row count is bounded by the
    # number of distinct models actually used.
    rows = (
        db.query(
            ChatMessage.model.label("model"),
            func.coalesce(func.sum(ChatMessage.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(ChatMessage.output_tokens), 0).label("out_tok"),
            func.coalesce(func.sum(ChatMessage.cost_usd), 0.0).label("cost"),
            func.count(ChatMessage.id).label("n"),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(ChatSession.tenant_id == current_user.tenant_id)
        .filter(ChatMessage.created_at >= start)
        .filter(ChatMessage.model.isnot(None))
        .group_by(ChatMessage.model)
        .all()
    )

    # Classify model → provider via prefix match.
    by_provider: dict[str, ProviderUsage] = {}
    for model, in_tok, out_tok, cost, n in rows:
        provider = _classify_provider(model)
        slot = by_provider.setdefault(provider, ProviderUsage(provider=provider))
        slot.input_tokens += int(in_tok or 0)
        slot.output_tokens += int(out_tok or 0)
        slot.cost_usd += float(cost or 0.0)
        slot.message_count += int(n or 0)

    # Round costs to 4 decimals; sort by cost desc.
    out_rows = sorted(by_provider.values(), key=lambda r: r.cost_usd, reverse=True)
    for r in out_rows:
        r.cost_usd = round(r.cost_usd, 4)

    return UsageResponse(
        period=period,
        start=start,
        end=end,
        rows=out_rows,
        total_input_tokens=sum(r.input_tokens for r in out_rows),
        total_output_tokens=sum(r.output_tokens for r in out_rows),
        total_cost_usd=round(sum(r.cost_usd for r in out_rows), 4),
    )


def _classify_provider(model: Optional[str]) -> str:
    """Match a `chat_messages.model` value against the provider
    prefix map. Unmatched names fall into `other` so the row count
    stays accurate even on novel model ids.
    """
    if not model:
        return "other"
    m = model.lower()
    for provider, prefixes in _PROVIDER_MODEL_PREFIXES.items():
        for prefix in prefixes:
            if m.startswith(prefix):
                return provider
    return "other"


# ──────────────────────────────────────────────────────────────────────
# /costs — per-day rollup
# ──────────────────────────────────────────────────────────────────────


class DailyCost(BaseModel):
    day: str  # YYYY-MM-DD
    message_count: int = 0
    cost_usd: float = 0.0


class CostsResponse(BaseModel):
    period: str
    start: datetime
    end: datetime
    days: list[DailyCost]
    total_cost_usd: float = 0.0
    total_messages: int = 0


@router.get("/costs", response_model=CostsResponse)
def get_costs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    period: Period = Query("7d"),
    agent_id: Optional[uuid.UUID] = Query(None, description="Optional agent filter"),
):
    """Per-day cost rollup for the caller's tenant."""
    start = _period_start(period)
    end = datetime.utcnow()

    q = (
        db.query(
            func.date_trunc("day", ChatMessage.created_at).label("day"),
            func.coalesce(func.sum(ChatMessage.cost_usd), 0.0).label("cost"),
            func.count(ChatMessage.id).label("n"),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(ChatSession.tenant_id == current_user.tenant_id)
        .filter(ChatMessage.created_at >= start)
    )
    if agent_id is not None:
        q = q.filter(ChatSession.agent_id == agent_id)
    rows = q.group_by("day").order_by("day").all()

    days = [
        DailyCost(
            day=d.strftime("%Y-%m-%d") if d else "",
            message_count=int(n or 0),
            cost_usd=round(float(c or 0.0), 4),
        )
        for d, c, n in rows
        if d is not None
    ]

    return CostsResponse(
        period=period,
        start=start,
        end=end,
        days=days,
        total_cost_usd=round(sum(d.cost_usd for d in days), 4),
        total_messages=sum(d.message_count for d in days),
    )
