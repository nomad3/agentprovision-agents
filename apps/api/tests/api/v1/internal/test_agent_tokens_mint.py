"""Tests for ``POST /api/v1/internal/agent-tokens/mint`` — Phase 4 commit 5.

Verifies:
  - 401 without X-Internal-Key
  - 200 + {token: <jwt>} when X-Internal-Key valid
  - 422 when parent_chain length > MAX_FALLBACK_DEPTH
"""
from __future__ import annotations

import uuid

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.internal_agent_tokens import router as internal_router
from app.core.config import settings
from app.services.agent_token import verify_agent_token


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(internal_router, prefix="/api/v1/internal", tags=["internal"])
    return TestClient(app)


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
