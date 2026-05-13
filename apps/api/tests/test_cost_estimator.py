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


def test_unknown_provider_skipped_not_ilike_matched():
    """Round-1 review H1: unknown providers must NOT fall through to
    `ilike(provider + '-%')` because a caller passing '%' would
    estimate-poison the tenant by ilike-matching every assistant
    message. Unknown providers are silently treated as zero-history."""
    # Mock returns non-empty rows for ANY ilike — if unknown providers
    # were ilike-matched, the estimate would reflect those rows. With
    # the H1 fix, the unknown provider returns 0 samples and hits
    # the per-slot fallback regardless of what the mock returns.
    db = _stub_session_with_messages([(0.50, 1000)])
    estimate = ce.estimate_fanout_cost(
        db, tenant_id=uuid.uuid4(), providers=["%"]
    )
    # Per-slot fallback (NOT 0.50 from the mock rows).
    assert estimate.estimated_cost_usd == round(
        ce._FALLBACK_COST_PER_PROVIDER_USD, 4
    )
    assert estimate.confidence == "low"


# ── Round-1 review H3: real-SQL test against in-memory SQLite ─────────
#
# The mock-only tests above don't exercise the actual join + filter +
# ilike chain. This fixture seeds three real (ChatSession, ChatMessage)
# pairs across two tenants and asserts the estimator returns the right
# per-provider cost AND does not leak cross-tenant data.


def _make_real_db():
    """In-memory SQLite session with chat_sessions + chat_messages
    tables and a tenants table. Returns the session — caller is
    responsible for cleanup (just drop reference; the engine is GC'd)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.models import tenant, user, chat  # noqa: F401  side-effect

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        tenant.Tenant.__table__,
        user.User.__table__,
        chat.ChatSession.__table__,
        chat.ChatMessage.__table__,
    ])
    Session = sessionmaker(bind=engine)
    return Session()


def _seed_chat(db, *, tenant_id, model, cost, tokens=1000):
    """Seed one assistant chat_message under a fresh session for
    the given tenant + model. Returns the ChatMessage row."""
    from app.models.chat import ChatSession, ChatMessage

    session = ChatSession(id=uuid.uuid4(), tenant_id=tenant_id, title="t")
    db.add(session)
    db.flush()
    msg = ChatMessage(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content="reply",
        cost_usd=cost,
        tokens_used=tokens,
        model=model,
    )
    db.add(msg)
    db.commit()
    return msg


def test_real_sql_tenant_isolation_and_prefix_attribution():
    """Round-1 review H3: integration test against in-memory SQLite.
    Seed 3 messages across 2 tenants and assert:
      - tenant A's claude estimate uses ONLY tenant A's claude row,
        not tenant B's claude row (tenant isolation).
      - tenant A's claude estimate uses the claude- model row, not
        the gpt- row (prefix attribution).
      - tenant A's gpt estimate (codex provider) picks up the gpt-
        row correctly.
    """
    db = _make_real_db()
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    # Tenant A: claude-sonnet $0.10, gpt-4o $0.30.
    _seed_chat(db, tenant_id=tenant_a, model="claude-sonnet-4-7-20250101", cost=0.10)
    _seed_chat(db, tenant_id=tenant_a, model="gpt-4o-2024-08-06", cost=0.30)
    # Tenant B: claude-sonnet $9.99 — must NOT bleed into A's estimate.
    _seed_chat(db, tenant_id=tenant_b, model="claude-sonnet-4-7-20250101", cost=9.99)

    # Tenant A claude estimate ↦ $0.10 (NOT 0.10+9.99=10.09).
    est_a_claude = ce.estimate_fanout_cost(
        db, tenant_id=tenant_a, providers=["claude"]
    )
    assert est_a_claude.confidence == "medium"
    assert est_a_claude.estimated_cost_usd == pytest.approx(0.10, abs=0.001)

    # Tenant A codex (gpt prefix) estimate ↦ $0.30 (NOT 0.10).
    est_a_codex = ce.estimate_fanout_cost(
        db, tenant_id=tenant_a, providers=["codex"]
    )
    assert est_a_codex.confidence == "medium"
    assert est_a_codex.estimated_cost_usd == pytest.approx(0.30, abs=0.001)

    # Tenant B claude ↦ $9.99 (its own data).
    est_b_claude = ce.estimate_fanout_cost(
        db, tenant_id=tenant_b, providers=["claude"]
    )
    assert est_b_claude.confidence == "medium"
    assert est_b_claude.estimated_cost_usd == pytest.approx(9.99, abs=0.001)

    # Tenant A fanout = claude + codex ↦ $0.40 ($0.10 + $0.30).
    est_a_fanout = ce.estimate_fanout_cost(
        db, tenant_id=tenant_a, providers=["claude", "codex"]
    )
    assert est_a_fanout.estimated_cost_usd == pytest.approx(0.40, abs=0.001)
    assert est_a_fanout.confidence == "medium"  # 1 sample each, not 5
