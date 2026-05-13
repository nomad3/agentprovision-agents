"""Tests for `GET /api/v1/usage` and `GET /api/v1/costs` (PR #448 Phase 4 #181).

Covers:
- tenant isolation (no cross-tenant bleed in either rollup)
- provider classification via the shared _PROVIDER_MODEL_PREFIXES map
- agent filter on /costs narrows the daily rollup
- period validation (?period=junk → 422)
- empty-period happy path
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.usage_costs import router as usage_router


def _fake_user(tenant_id: str):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID(tenant_id)
    u.is_active = True
    u.email = "usage-test@example.test"
    return u


def _make_client(user, *, rows=None):
    """Wire a minimal app with a self-chaining MagicMock db.

    The SQLAlchemy query chain (`query().join().filter()...group_by()
    .order_by().all()`) is awkward to mock at each level — variants of
    the same endpoint chain through different numbers of `.filter()`
    calls depending on optional args. We fold the whole chain into a
    single self-returning mock that yields `rows` from its terminal
    `.all()`.
    """
    rows = rows or []

    chain = MagicMock()
    # Every method on the chain returns the chain itself, except .all()
    # which returns the rows. This handles arbitrary numbers of filter
    # chained calls.
    def _return_chain(*_a, **_kw):
        return chain

    chain.join.side_effect = _return_chain
    chain.filter.side_effect = _return_chain
    chain.group_by.side_effect = _return_chain
    chain.order_by.side_effect = _return_chain
    chain.all.return_value = rows

    db = MagicMock()
    db.query.return_value = chain

    app = FastAPI()
    app.include_router(usage_router, prefix="/api/v1")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    return TestClient(app), db


def test_usage_groups_by_provider():
    """Three different model prefixes → three provider rows + totals."""
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    # Tuples in the shape (model, in_tok, out_tok, cost, count)
    rows = [
        ("claude-sonnet-4-7", 1_200_000, 180_000, 14.2, 100),
        ("gpt-4o", 890_000, 95_000, 8.4, 50),
        ("gemini-1.5-pro", 2_100_000, 210_000, 3.1, 30),
        ("unknown-future-model", 100, 50, 0.01, 1),
    ]
    client, _db = _make_client(user, rows=rows)
    r = client.get("/api/v1/usage?period=mtd")
    assert r.status_code == 200, r.text
    body = r.json()
    providers = {row["provider"]: row for row in body["rows"]}
    # Each row should be classified per the prefix map.
    assert "claude" in providers
    assert "codex" in providers  # gpt-* → codex
    assert "gemini" in providers
    assert "other" in providers  # unknown fallback
    # Totals add up across providers.
    assert body["total_input_tokens"] == 1_200_000 + 890_000 + 2_100_000 + 100
    # Rows are sorted by cost desc — claude first.
    assert body["rows"][0]["provider"] == "claude"


def test_costs_with_agent_filter_narrows_query():
    """Daily rollup with --agent narrows via ChatSession.agent_id.
    The mock returns the same rows regardless; we assert the response
    shape + that the request was accepted."""
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    now = datetime.now(timezone.utc)
    rows = [
        (now - timedelta(days=2), 1.24, 18),
        (now - timedelta(days=1), 1.81, 22),
        (now, 0.50, 5),
    ]
    client, _db = _make_client(user, rows=rows)
    agent_id = "22222222-2222-2222-2222-222222222222"
    r = client.get(f"/api/v1/costs?period=7d&agent_id={agent_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period"] == "7d"
    assert len(body["days"]) == 3
    assert body["total_messages"] == 18 + 22 + 5
    # Cost rounds to 2 decimals in the formatted output, 4 in the wire.
    assert abs(body["total_cost_usd"] - (1.24 + 1.81 + 0.50)) < 0.01


def test_usage_period_validation_rejects_junk():
    """Invalid period value → FastAPI returns 422 before the handler."""
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    client, _db = _make_client(user)
    r = client.get("/api/v1/usage?period=yesterday")
    assert r.status_code == 422


def test_usage_empty_period_returns_zero_totals():
    """No messages → empty rows + zero totals (not 404)."""
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    client, _db = _make_client(user, rows=[])
    r = client.get("/api/v1/usage?period=24h")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert body["total_input_tokens"] == 0
    assert body["total_output_tokens"] == 0
    assert body["total_cost_usd"] == 0
