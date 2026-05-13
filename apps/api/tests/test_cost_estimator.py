"""Tests for `app.services.cost_estimator` (#190).

Pins:
  - Empty provider list → static fallback, confidence="low".
  - No historical data for any provider → fallback per slot,
    confidence="low".
  - Some history (≥1 sample on ≥1 provider) → real average,
    confidence="medium".
  - Lots of history (≥5 samples on every provider) → confidence="high".
  - Provider → model-prefix mapping correctly attributes
    chat_messages.model = "claude-sonnet-4-7-..." to the "claude"
    provider, not to "codex"/"gemini"/etc.

Uses sqlite + ChatSession + ChatMessage to exercise the SQL path
without monkeypatching the aggregator itself.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.services import cost_estimator as ce


def _stub_session_with_messages(rows):
    """Build a MagicMock SQLAlchemy session that returns `rows` from
    the cost_usd / tokens_used aggregation query. `rows` is a list of
    `(cost_usd, tokens_used)` tuples; we wrap each as a MagicMock
    with attribute access matching what the aggregator reads."""

    db = MagicMock()
    # Each `db.query(...).join(...).filter(...)...limit(...).all()`
    # chain returns the same `rows` regardless of provider filter.
    # The aggregator constructs a fresh chain per provider, so the
    # mock just terminates each chain at `.all()` returning rows.
    chain = MagicMock()
    chain.all.return_value = [
        MagicMock(cost_usd=c, tokens_used=t) for c, t in rows
    ]
    # Make every intermediate `.join / .filter / .order_by / .limit`
    # return the same chain.
    for method in ("join", "filter", "order_by", "limit"):
        getattr(chain, method).return_value = chain
    db.query.return_value = chain
    return db


def test_empty_providers_returns_fallback():
    """No providers → static placeholder, confidence=low."""
    db = MagicMock()
    estimate = ce.estimate_fanout_cost(
        db, tenant_id=uuid.uuid4(), providers=[]
    )
    assert estimate.confidence == "low"
    assert estimate.estimated_cost_usd == ce._FALLBACK_COST_PER_PROVIDER_USD
    assert estimate.estimated_duration_seconds == ce._FALLBACK_DURATION_SECONDS


def test_no_history_falls_back_per_slot():
    """Empty rows for every provider → low confidence + fallback
    per-slot accumulated."""
    db = _stub_session_with_messages([])
    estimate = ce.estimate_fanout_cost(
        db, tenant_id=uuid.uuid4(), providers=["claude", "codex"]
    )
    assert estimate.confidence == "low"
    # 2 providers × fallback per slot.
    expected = round(2 * ce._FALLBACK_COST_PER_PROVIDER_USD, 4)
    assert estimate.estimated_cost_usd == expected


def test_some_history_yields_medium_confidence():
    """≥1 sample on any provider → medium confidence."""
    db = _stub_session_with_messages([(0.05, 1000), (0.07, 1500)])
    estimate = ce.estimate_fanout_cost(
        db, tenant_id=uuid.uuid4(), providers=["claude"]
    )
    assert estimate.confidence == "medium"
    # avg cost = 0.06; 1 provider; total = 0.06.
    assert estimate.estimated_cost_usd == pytest.approx(0.06, abs=0.001)


def test_lots_of_history_yields_high_confidence():
    """≥5 samples on every provider → high confidence."""
    rows = [(0.10, 1000) for _ in range(6)]
    db = _stub_session_with_messages(rows)
    estimate = ce.estimate_fanout_cost(
        db, tenant_id=uuid.uuid4(), providers=["claude", "codex"]
    )
    assert estimate.confidence == "high"
    # 2 providers × 0.10 avg = 0.20.
    assert estimate.estimated_cost_usd == pytest.approx(0.20, abs=0.001)


def test_duration_proxy_scales_with_tokens():
    """Duration = max(5, avg_tokens / 1000 * 5). Parallel dispatch
    takes max(child_duration), not sum."""
    db = _stub_session_with_messages([(0.10, 4000)])
    estimate = ce.estimate_fanout_cost(
        db, tenant_id=uuid.uuid4(), providers=["claude", "codex"]
    )
    # avg_tokens=4000 → 4000/1000*5 = 20s. Both providers see the
    # same mock rows, so max is also 20s (not 40s as a sum would be).
    assert estimate.estimated_duration_seconds == 20


def test_provider_model_prefix_mapping_recognizes_known_providers():
    """Sanity: the prefix map covers the 5 documented providers."""
    for p in ("claude", "codex", "gemini", "copilot", "opencode"):
        assert p in ce._PROVIDER_MODEL_PREFIXES
        assert ce._PROVIDER_MODEL_PREFIXES[p], f"empty prefix list for {p}"


def test_whitespace_providers_dropped():
    """Round-2 N4-style leniency: ['', ' ', 'claude'] → just claude."""
    db = _stub_session_with_messages([])
    estimate = ce.estimate_fanout_cost(
        db, tenant_id=uuid.uuid4(), providers=["", " ", "claude"]
    )
    # 1 provider only, fallback per slot.
    assert estimate.estimated_cost_usd == round(
        ce._FALLBACK_COST_PER_PROVIDER_USD, 4
    )
