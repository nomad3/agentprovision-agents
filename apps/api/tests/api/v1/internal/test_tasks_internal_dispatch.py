"""Tests for ``POST /api/v1/tasks/internal/dispatch`` — Phase 4 review C-FINAL-1.

The leaf-side ``dispatch_agent`` MCP tool authenticates via
X-Internal-Key + X-Tenant-Id, NOT Bearer JWT. Phase 4 originally
pointed the tool at the JWT-gated /tasks/dispatch endpoint, which
would have 401'd every leaf invocation in production. Tests
green-stamped via app.dependency_overrides[get_current_user] — masking
the bug.

This test exercises the real wire contract WITHOUT any
get_current_user override:

  - 401 with no X-Internal-Key
  - 400 with no X-Tenant-Id
  - 201 with valid headers + parent_chain of length 0
  - 503 with valid headers + parent_chain of length 3 (recursion gate
    fires) AND no Temporal dispatch
  - Confirms behavioural parity with /tasks/dispatch via shared
    dispatch_core helper
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.internal_agent_tasks import router as internal_router
from app.core.config import settings


@pytest.fixture
def fake_db():
    db = MagicMock()
    fake_agent = MagicMock()
    fake_agent.tenant_id = None  # set per-test where the body uses delegate
    db.query.return_value.filter.return_value.first.return_value = fake_agent

    def _refresh(obj):
        if not getattr(obj, "id", None):
            obj.id = uuid.uuid4()

    db.refresh.side_effect = _refresh
    return db


@pytest.fixture
def client(fake_db):
    """TestClient with NO get_current_user override. The internal router
    must work via X-Internal-Key + X-Tenant-Id only."""
    app = FastAPI()
    app.include_router(internal_router, prefix="/api/v1", tags=["internal"])
    app.dependency_overrides[deps.get_db] = lambda: fake_db
    return TestClient(app)


@pytest.fixture
def mock_temporal_dispatch():
    handle = MagicMock()
    handle.id = "wf-mock"
    fake_client = MagicMock()
    fake_client.start_workflow = AsyncMock(return_value=handle)
    with patch(
        "temporalio.client.Client.connect",
        new=AsyncMock(return_value=fake_client),
    ):
        yield fake_client


def _body(**overrides):
    base = {
        "task_type": "code",
        "objective": "do the thing",
        "parent_chain": [],
    }
    base.update(overrides)
    return base


def test_no_internal_key_returns_401(client, mock_temporal_dispatch):
    """Real wire contract — no Authorization header, no X-Internal-Key.
    The endpoint must return 401, NOT 422 from body validation. This
    is the test the prior Phase 4 implementation was missing."""
    resp = client.post(
        "/api/v1/tasks/internal/dispatch",
        json=_body(),
        headers={"X-Tenant-Id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401
    mock_temporal_dispatch.start_workflow.assert_not_called()


def test_missing_tenant_returns_400(client, mock_temporal_dispatch):
    resp = client.post(
        "/api/v1/tasks/internal/dispatch",
        json=_body(),
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
    )
    assert resp.status_code == 400
    mock_temporal_dispatch.start_workflow.assert_not_called()


def test_valid_headers_parent_chain_zero_dispatches(client, mock_temporal_dispatch):
    """Happy path. NO get_current_user dep is registered — only the
    new internal-tier auth must pass."""
    resp = client.post(
        "/api/v1/tasks/internal/dispatch",
        json=_body(),
        headers={
            "X-Internal-Key": settings.API_INTERNAL_KEY,
            "X-Tenant-Id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 201
    payload = resp.json()
    assert "task_id" in payload
    assert "workflow_id" in payload
    mock_temporal_dispatch.start_workflow.assert_awaited_once()


def test_parent_chain_length_3_refused_no_dispatch(client, mock_temporal_dispatch):
    """§3.1 recursion gate fires from this endpoint exactly the same
    way it fires from /tasks/dispatch — both routes share dispatch_core.
    Critical: NO Temporal dispatch happens on refusal."""
    chain = [str(uuid.uuid4()) for _ in range(3)]
    resp = client.post(
        "/api/v1/tasks/internal/dispatch",
        json=_body(parent_chain=chain),
        headers={
            "X-Internal-Key": settings.API_INTERNAL_KEY,
            "X-Tenant-Id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["status"] == "provider_unavailable"
    assert "recursion" in detail.get("actionable_hint", "").lower() or \
           "depth" in detail.get("error_message", "").lower()
    mock_temporal_dispatch.start_workflow.assert_not_called()


def test_mcp_api_key_also_works(client, mock_temporal_dispatch):
    """Both API_INTERNAL_KEY and MCP_API_KEY accepted (matches the
    pattern from internal_orchestrator_events / internal_agent_tokens)."""
    resp = client.post(
        "/api/v1/tasks/internal/dispatch",
        json=_body(),
        headers={
            "X-Internal-Key": settings.MCP_API_KEY,
            "X-Tenant-Id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 201


def test_jwt_endpoint_still_requires_jwt():
    """Belt-and-braces parity check: the original /tasks/dispatch
    endpoint stays JWT-gated. A leaf accidentally pointing at it would
    still 401. This regression-tests that the C-FINAL-1 split didn't
    silently widen the JWT-gated endpoint."""
    from app.api.v1.agent_tasks import router as user_router

    app = FastAPI()
    app.include_router(user_router, prefix="/api/v1/tasks", tags=["tasks"])
    # NO get_current_user override.

    client = TestClient(app)
    resp = client.post(
        "/api/v1/tasks/dispatch",
        json=_body(),
        headers={
            "X-Internal-Key": settings.API_INTERNAL_KEY,
            "X-Tenant-Id": str(uuid.uuid4()),
        },
    )
    # 401 — the JWT dependency rejects the request before body validation.
    assert resp.status_code == 401
