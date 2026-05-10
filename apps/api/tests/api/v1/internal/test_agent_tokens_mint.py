"""Tests for ``POST /api/v1/internal/agent-tokens/mint`` — Phase 4 commit 5.

Verifies:
  - 401 without X-Internal-Key
  - 200 + {token: <jwt>} when X-Internal-Key valid AND agent belongs to tenant
  - 422 when parent_chain length > MAX_FALLBACK_DEPTH
  - 422 when agent_id does NOT belong to tenant_id (Phase 4 review I-4)
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.internal_agent_tokens import router as internal_router
from app.core.config import settings
from app.services.agent_token import verify_agent_token


def _make_db(*, tenant_match: bool = True):
    """Return a MagicMock SA Session whose Agent lookup returns either a
    matching row (tenant_match=True) or None (tenant_match=False).
    """
    db = MagicMock()
    if tenant_match:
        # Any first() call returns a SimpleNamespace stand-in for an Agent.
        db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            name="Luna",
        )
    else:
        db.query.return_value.filter.return_value.first.return_value = None
    return db


@pytest.fixture
def client_factory():
    """Return a function that builds a TestClient with a per-test get_db
    override (so the tenant-membership lookup returns a matching or
    missing agent on demand)."""
    def _build(*, tenant_match: bool = True):
        app = FastAPI()
        app.include_router(internal_router, prefix="/api/v1/internal", tags=["internal"])
        app.dependency_overrides[deps.get_db] = lambda: _make_db(tenant_match=tenant_match)
        return TestClient(app)
    return _build


@pytest.fixture
def client(client_factory):
    return client_factory(tenant_match=True)


def _body(**overrides):
    base = {
        "tenant_id": str(uuid.uuid4()),
        "agent_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "parent_workflow_id": "wf-1",
        "scope": ["recall_memory"],
        "parent_chain": [],
        "heartbeat_timeout_seconds": 240,
    }
    base.update(overrides)
    return base


def test_no_key_returns_401(client):
    resp = client.post(
        "/api/v1/internal/agent-tokens/mint",
        json=_body(),
    )
    assert resp.status_code == 401


def test_valid_key_returns_token(client):
    body = _body()
    resp = client.post(
        "/api/v1/internal/agent-tokens/mint",
        json=body,
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    # Verify the minted JWT is well-formed.
    claims = verify_agent_token(data["token"])
    assert claims["tenant_id"] == body["tenant_id"]
    assert claims["agent_id"] == body["agent_id"]
    assert claims["task_id"] == body["task_id"]
    assert claims["scope"] == ["recall_memory"]


def test_parent_chain_too_long_returns_422(client):
    chain = [str(uuid.uuid4()) for _ in range(4)]
    resp = client.post(
        "/api/v1/internal/agent-tokens/mint",
        json=_body(parent_chain=chain),
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
    )
    assert resp.status_code == 422
    assert "parent_chain" in resp.text


def test_mcp_api_key_also_works(client):
    """Both API_INTERNAL_KEY and MCP_API_KEY are accepted (matches the
    pattern in internal_orchestrator_events)."""
    resp = client.post(
        "/api/v1/internal/agent-tokens/mint",
        json=_body(),
        headers={"X-Internal-Key": settings.MCP_API_KEY},
    )
    assert resp.status_code == 200


def test_agent_not_in_tenant_returns_422(client_factory):
    """Phase 4 review I-4: agent_id missing from tenant_id → 422.

    Defence-in-depth: X-Internal-Key already grants cross-tenant access
    by design, so this isn't an exploit — but a misconfigured worker
    passing the wrong agent_id should fail at mint time, not silently
    mint a token whose claim mixes tenants A and B.
    """
    client = client_factory(tenant_match=False)
    resp = client.post(
        "/api/v1/internal/agent-tokens/mint",
        json=_body(),
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
    )
    assert resp.status_code == 422
    assert "tenant" in resp.text.lower()
