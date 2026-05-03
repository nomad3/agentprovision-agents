"""Tests for the cost-insights endpoint helpers (Tier 2).

Schema-level pinning + bucket-aggregator correctness. The full
endpoint test would need a populated DB, which spins up via conftest;
this file targets the pure-logic surfaces that run on the host
without docker-compose.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.api.v1.insights_cost import (
    CostInsightsResponse,
    QuotaBurn,
    SeriesEntry,
    TimeBucket,
    TopAgent,
    _aggregate_by_bucket,
    _bucket_date,
)


# ── Schema invariants — curate-don't-dump ─────────────────────────

def test_top_agent_does_not_leak_full_agent():
    """TopAgent rows must NOT carry persona_prompt, config, owner
    relationships — only what the dashboard needs to render the row."""
    fields = (
        TopAgent.model_fields if hasattr(TopAgent, "model_fields") else TopAgent.__fields__
    )
    forbidden = {"persona_prompt", "config", "owner", "team", "tenant_id", "metadata"}
    assert forbidden.isdisjoint(fields.keys())


def test_series_entry_schema_is_lean():
    """Per-bucket data has aggregates + label — no raw audit rows or
    nested ORM relationships. Per the curate-don't-dump pattern."""
    fields = (
        SeriesEntry.model_fields
        if hasattr(SeriesEntry, "model_fields")
        else SeriesEntry.__fields__
    )
    forbidden = {"raw_calls", "tenant_id", "audit_logs", "agents"}
    assert forbidden.isdisjoint(fields.keys())


def test_response_does_not_expose_tenant_id():
    """Response root has no tenant_id — caller knows their own tenant."""
    fields = (
        CostInsightsResponse.model_fields
        if hasattr(CostInsightsResponse, "model_fields")
        else CostInsightsResponse.__fields__
    )
    assert "tenant_id" not in fields


# ── Bucket date snapping ──────────────────────────────────────────

def test_bucket_date_day_granularity_returns_iso_date():
    dt = datetime(2026, 5, 3, 14, 30)
    assert _bucket_date(dt, "day") == "2026-05-03"


def test_bucket_date_week_granularity_snaps_to_monday():
    """ISO weeks start Monday. A Wednesday timestamp must snap to the
    Monday of that week. Edge: a Sunday snaps backwards to Monday."""
    # 2026-05-03 is a Sunday → Monday is 2026-04-27
    sunday = datetime(2026, 5, 3, 14, 30)
    assert _bucket_date(sunday, "week") == "2026-04-27"
    # 2026-05-06 is a Wednesday → Monday is 2026-05-04
    wednesday = datetime(2026, 5, 6, 9, 0)
    assert _bucket_date(wednesday, "week") == "2026-05-04"
    # Monday itself stays
    monday = datetime(2026, 5, 4, 0, 0)
    assert _bucket_date(monday, "week") == "2026-05-04"


# ── Aggregator correctness ────────────────────────────────────────

class _FakeSnap:
    def __init__(self, agent_id, window_start, tokens, cost, invs):
        self.agent_id = agent_id
        self.window_start = window_start
        self.total_tokens = tokens
        self.total_cost_usd = cost
        self.invocation_count = invs


def test_aggregate_groups_by_key_and_buckets_by_date():
    """Two snapshots for the same agent on the same day: tokens + cost
    sum into a single bucket. Two days: two buckets."""
    aid = uuid.uuid4()
    snaps = [
        (_FakeSnap(aid, datetime(2026, 5, 3, 8), 100, 0.10, 5), None, None),
        (_FakeSnap(aid, datetime(2026, 5, 3, 14), 50, 0.05, 2), None, None),
        (_FakeSnap(aid, datetime(2026, 5, 4, 9), 200, 0.20, 10), None, None),
    ]
    out = _aggregate_by_bucket(
        snaps, granularity="day",
        key_fn=lambda r: str(r[0].agent_id),
        label_fn=lambda r: "Test Agent",
    )
    assert len(out) == 1  # one agent
    e = out[0]
    assert e.tokens == 350
    assert abs(e.cost_usd - 0.35) < 1e-6
    assert e.invocations == 17
    # Two buckets: 2026-05-03 (sum of two snaps) + 2026-05-04
    assert len(e.buckets) == 2
    bucket_03 = next(b for b in e.buckets if b.date == "2026-05-03")
    assert bucket_03.tokens == 150
    assert bucket_03.invocations == 7


def test_aggregate_handles_null_keys_as_unassigned():
    """Snapshots whose key_fn returns None (agent has no team / no
    owner) bucket under "unassigned" so leadership sees the unassigned
    cost as a separate row to triage, not silently dropped."""
    snaps = [
        (_FakeSnap(uuid.uuid4(), datetime(2026, 5, 3), 100, 0.10, 5), None, None),
    ]
    out = _aggregate_by_bucket(
        snaps, granularity="day",
        key_fn=lambda r: None,
        label_fn=lambda r: None,
    )
    assert len(out) == 1
    assert out[0].key == "unassigned"


def test_aggregate_sorts_series_by_cost_desc():
    """Most expensive group comes first — the chart legend is most
    actionable when sorted by cost."""
    a, b = uuid.uuid4(), uuid.uuid4()
    snaps = [
        (_FakeSnap(a, datetime(2026, 5, 3), 100, 0.05, 5), None, None),
        (_FakeSnap(b, datetime(2026, 5, 3), 100, 0.50, 5), None, None),
    ]
    out = _aggregate_by_bucket(
        snaps, granularity="day",
        key_fn=lambda r: str(r[0].agent_id),
        label_fn=lambda r: "agent",
    )
    assert len(out) == 2
    assert out[0].cost_usd > out[1].cost_usd  # b first


def test_aggregate_buckets_are_sorted_chronologically():
    aid = uuid.uuid4()
    snaps = [
        (_FakeSnap(aid, datetime(2026, 5, 5), 100, 0.10, 5), None, None),
        (_FakeSnap(aid, datetime(2026, 5, 3), 100, 0.10, 5), None, None),
        (_FakeSnap(aid, datetime(2026, 5, 4), 100, 0.10, 5), None, None),
    ]
    out = _aggregate_by_bucket(
        snaps, granularity="day",
        key_fn=lambda r: str(r[0].agent_id),
        label_fn=lambda r: "agent",
    )
    bucket_dates = [b.date for b in out[0].buckets]
    assert bucket_dates == sorted(bucket_dates)


# ── Quota burn schema ────────────────────────────────────────────

def test_quota_burn_optional_fields_can_be_null():
    """``projected_exhaustion_date`` and ``days_until_exhaustion``
    are Optional — when usage is on track to stay under the limit
    we omit them."""
    qb = QuotaBurn(
        monthly_limit_tokens=1_000_000,
        tokens_used_mtd=10_000,
        projected_exhaustion_date=None,
        days_until_exhaustion=None,
    )
    assert qb.projected_exhaustion_date is None
    assert qb.days_until_exhaustion is None
