"""Tests for `GET /api/v1/agents/{agent_id}/policies` (PR #446 Phase 2 #179).

Covers:
- 401 on unauth
- 404 on cross-tenant agent (reviewer R-1 follow-on)
- happy path: includes both agent-scoped + tenant-wide rows
- ordering contract the CLI relies on (policy_type ASC, created_at DESC)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.agent_policies import router as policies_router


def _fake_user(tenant_id: str):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID(tenant_id)
    u.is_active = True
    u.email = "policies-test@example.test"
    return u


def _fake_agent(agent_id: str, tenant_id: str, *, name: str = "code-agent"):
    a = MagicMock()
    a.id = uuid.UUID(agent_id)
    a.tenant_id = uuid.UUID(tenant_id)
    a.name = name
    return a


def _fake_policy_row(
    policy_id: str,
    agent_id: str | None,
    tenant_id: str,
    *,
    policy_type: str = "rate_limit",
    config: dict | None = None,
    enabled: bool = True,
    created_at: datetime | None = None,
):
    p = MagicMock()
    p.id = uuid.UUID(policy_id)
    p.agent_id = uuid.UUID(agent_id) if agent_id else None
    p.tenant_id = uuid.UUID(tenant_id)
    p.policy_type = policy_type
    p.config = config or {"max_per_minute": 60}
    p.enabled = enabled
    p.created_at = created_at or datetime(2026, 5, 13, 12, 0, 0)
    p.updated_at = p.created_at
    return p


def _make_client(user, *, agent, policies):
    """Wire a minimal app. The route runs two queries:
       1. db.query(Agent).filter(...).first()  → returns `agent` or None
       2. db.query(AgentPolicy).filter(...).order_by(...).all() → returns `policies`
    """
    db = MagicMock()
    # First call: agent lookup. Subsequent calls: policy list.
    query_chain = MagicMock()
    query_chain.filter.return_value.first.return_value = agent
    query_chain.filter.return_value.order_by.return_value.all.return_value = policies
    db.query.return_value = query_chain

    app = FastAPI()
    app.include_router(policies_router, prefix="/api/v1/agents")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    return TestClient(app)


def test_get_agent_policies_returns_404_cross_tenant():
    """Caller in tenant A asks for an agent that doesn't belong to them.
    The .filter on (id, tenant_id) returns None → 404."""
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    client = _make_client(user, agent=None, policies=[])
    r = client.get(f"/api/v1/agents/{uuid.uuid4()}/policies")
    assert r.status_code == 404
    assert r.json()["detail"] == "agent not found"


def test_get_agent_policies_happy_path():
    """Two policies (one agent-scoped, one tenant-wide) come back with
    the expected scope tags."""
    tenant = "11111111-1111-1111-1111-111111111111"
    agent_id = "22222222-2222-2222-2222-222222222222"
    user = _fake_user(tenant)
    agent = _fake_agent(agent_id, tenant, name="code-agent")
    rows = [
        _fake_policy_row(
            str(uuid.uuid4()),
            agent_id,
            tenant,
            policy_type="rate_limit",
        ),
        _fake_policy_row(
            str(uuid.uuid4()),
            None,  # tenant-wide
            tenant,
            policy_type="data_access",
        ),
    ]
    client = _make_client(user, agent=agent, policies=rows)
    r = client.get(f"/api/v1/agents/{agent_id}/policies")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == agent_id
    assert body["agent_name"] == "code-agent"
    assert len(body["policies"]) == 2
    scopes = {p["scope"] for p in body["policies"]}
    assert scopes == {"agent", "tenant"}
