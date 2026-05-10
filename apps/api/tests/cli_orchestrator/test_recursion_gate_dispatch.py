"""Phase 4 commit 9 — §3.1 recursion gate via /tasks/dispatch.

Commit 2 already wired the gate into the dispatch endpoint; this file
proves the gate fires from a real dispatch_agent → /tasks/dispatch
flow end-to-end. Specifically:

  - parent_chain length 0 → endpoint accepts (201)
  - parent_chain length 3 → endpoint refuses with 503 +
    PROVIDER_UNAVAILABLE
  - parent_chain cycle (same agent twice) → 503 + cycle reason
  - Critical: when the gate refuses, NO Temporal dispatch happens —
    the executor's gate is enforced BEFORE any adapter.run() is ever
    invoked.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.agent_tasks import router as tasks_router


@pytest.fixture
def fake_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.tenant_id = uuid.uuid4()
    user.is_active = True
    return user


@pytest.fixture
def client(fake_user):
    app = FastAPI()
    app.include_router(tasks_router, prefix="/api/v1/tasks", tags=["tasks"])

    fake_db = MagicMock()
    fake_agent = MagicMock()
    fake_agent.tenant_id = fake_user.tenant_id
    fake_db.query.return_value.filter.return_value.first.return_value = fake_agent

    def _refresh(obj):
        if not getattr(obj, "id", None):
            obj.id = uuid.uuid4()

    fake_db.refresh.side_effect = _refresh

    def _fake_db():
        yield fake_db

    def _fake_user():
        return fake_user

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_user] = _fake_user

    yield TestClient(app)


@pytest.fixture
def mock_temporal_dispatch():
    """Track every Temporal start_workflow call. We can assert
    .called == False on refusal paths."""
    handle = MagicMock()
    handle.id = "wf-mock"
    fake_client = MagicMock()
    fake_client.start_workflow = AsyncMock(return_value=handle)
    with patch(
        "temporalio.client.Client.connect",
        new=AsyncMock(return_value=fake_client),
    ):
        yield fake_client


def test_parent_chain_length_0_accepts(client, mock_temporal_dispatch):
    body = {
        "task_type": "code",
        "objective": "Normal task",
        "parent_chain": [],
    }
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 201
    mock_temporal_dispatch.start_workflow.assert_awaited_once()


def test_parent_chain_length_3_refused_no_dispatch(client, mock_temporal_dispatch):
    """The §3.1 gate fires server-side at /tasks/dispatch BEFORE any
    Temporal dispatch happens. Critical for the resilience loop —
    a runaway delegation chain stops at the API, never spins up a
    new workflow."""
    chain = [str(uuid.uuid4()) for _ in range(3)]
    body = {
        "task_type": "code",
        "objective": "deeply-recursing call",
        "parent_chain": chain,
    }
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["status"].lower() == "provider_unavailable"
    assert "recursion_depth" in (detail.get("actionable_hint") or "")
    # No adapter.run, no Temporal dispatch — the gate is BEFORE everything.
    mock_temporal_dispatch.start_workflow.assert_not_called()


def test_parent_chain_cycle_refused_no_dispatch(client, mock_temporal_dispatch):
    same = str(uuid.uuid4())
    body = {
        "task_type": "code",
        "objective": "loop",
        "parent_chain": [same, same],
    }
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    error_text = (detail.get("error_message") or "") + (detail.get("actionable_hint") or "")
    assert "cycle" in error_text.lower()
    mock_temporal_dispatch.start_workflow.assert_not_called()


def test_dispatch_agent_from_depth_3_no_adapter_invoked(client, mock_temporal_dispatch):
    """Integration scenario from the plan: dispatch_agent called from a
    depth-3 agent, ExecutionRequest built with parent_chain length 3,
    assert NO adapter.run() invoked.

    We simulate the dispatch_agent → /tasks/dispatch HTTP call by
    POSTing with parent_chain=[a, b, c] and asserting the gate fires.
    The MCP tool itself appends the caller's agent_id; here we
    pre-construct the post-append chain length 3.
    """
    chain = [str(uuid.uuid4()) for _ in range(3)]
    body = {
        "task_type": "delegate",
        "target_agent_id": str(uuid.uuid4()),
        "objective": "Call from depth 3",
        "parent_chain": chain,
    }
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 503
    # No Temporal dispatch happened → no adapter.run() either, since the
    # adapter chain only spins up inside the workflow execution path.
    mock_temporal_dispatch.start_workflow.assert_not_called()
