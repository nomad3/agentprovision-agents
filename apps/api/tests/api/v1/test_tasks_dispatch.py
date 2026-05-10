"""Tests for ``POST /api/v1/tasks/dispatch`` — Phase 4 commit 2.

Verifies:
  - code task type → CodeTaskWorkflow on agentprovision-code
  - delegate task type → TaskExecutionWorkflow on agentprovision-orchestration
  - parent_task_id forwarded
  - parent_chain forwarded
  - 422 when delegate without target_agent_id
  - 401 without tenant JWT
  - 503 when parent_chain length 3 (recursion gate)
  - 503 when parent_chain has cycle
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


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def fake_user():
    """A fake authenticated user with a tenant_id."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.tenant_id = uuid.uuid4()
    user.is_active = True
    return user


@pytest.fixture
def client(fake_user):
    """FastAPI TestClient with fake DB + fake auth dependency."""
    app = FastAPI()
    app.include_router(tasks_router, prefix="/api/v1/tasks", tags=["tasks"])

    fake_db = MagicMock()
    # The delegate path queries Agent — return a stub agent matching tenant.
    fake_agent = MagicMock()
    fake_agent.tenant_id = fake_user.tenant_id
    fake_db.query.return_value.filter.return_value.first.return_value = fake_agent

    # Make commit/refresh populate id on the AgentTask row.
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
def mock_temporal():
    """Mock TemporalClient.connect → start_workflow."""
    handle = MagicMock()
    handle.id = "wf-mock-id"

    fake_client = MagicMock()
    fake_client.start_workflow = AsyncMock(return_value=handle)

    with patch(
        "temporalio.client.Client.connect",
        new=AsyncMock(return_value=fake_client),
    ):
        yield fake_client


# ── Tests ───────────────────────────────────────────────────────────────


def test_code_task_dispatches_codetaskworkflow(client, mock_temporal, fake_user):
    body = {
        "task_type": "code",
        "objective": "Add a comment to main.py",
    }
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "task_id" in data
    assert "workflow_id" in data
    # Inspect the start_workflow call.
    call = mock_temporal.start_workflow.await_args
    assert call.args[0] == "CodeTaskWorkflow"
    assert call.kwargs["task_queue"] == "agentprovision-code"
    payload = call.args[1]
    assert payload["task_description"] == body["objective"]
    assert payload["tenant_id"] == str(fake_user.tenant_id)


def test_delegate_dispatches_task_execution_workflow(client, mock_temporal, fake_user):
    target_agent_id = str(uuid.uuid4())
    body = {
        "task_type": "delegate",
        "objective": "Investigate cardiac case",
        "target_agent_id": target_agent_id,
    }
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 201, resp.text
    call = mock_temporal.start_workflow.await_args
    assert call.args[0] == "TaskExecutionWorkflow"
    assert call.kwargs["task_queue"] == "agentprovision-orchestration"
    payload = call.args[1]
    assert payload["target_agent_id"] == target_agent_id
    assert payload["tenant_id"] == str(fake_user.tenant_id)


def test_parent_task_id_forwarded(client, mock_temporal):
    parent = str(uuid.uuid4())
    body = {
        "task_type": "code",
        "objective": "Refactor X",
        "parent_task_id": parent,
    }
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 201
    payload = mock_temporal.start_workflow.await_args.args[1]
    assert payload["parent_task_id"] == parent


def test_parent_chain_forwarded(client, mock_temporal):
    chain = [str(uuid.uuid4()) for _ in range(2)]
    body = {
        "task_type": "code",
        "objective": "Some objective",
        "parent_chain": chain,
    }
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 201
    payload = mock_temporal.start_workflow.await_args.args[1]
    assert payload["parent_chain"] == chain


def test_delegate_without_target_agent_id_returns_422(client):
    body = {"task_type": "delegate", "objective": "x"}
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 422
    assert "target_agent_id" in resp.text


def test_no_jwt_returns_401():
    """Without dependency override on get_current_user, the real
    OAuth2PasswordBearer dep returns 401 when no Authorization header."""
    app = FastAPI()
    app.include_router(tasks_router, prefix="/api/v1/tasks", tags=["tasks"])
    # Override get_db only; leave get_current_user untouched.
    app.dependency_overrides[deps.get_db] = lambda: iter([MagicMock()])
    test_client = TestClient(app)
    resp = test_client.post(
        "/api/v1/tasks/dispatch",
        json={"task_type": "code", "objective": "x"},
    )
    assert resp.status_code == 401


def test_parent_chain_length_3_triggers_recursion_gate_503(client, mock_temporal):
    """SR-3: depth >= MAX_FALLBACK_DEPTH refused with 503 + actionable_hint."""
    chain = [str(uuid.uuid4()) for _ in range(3)]
    body = {
        "task_type": "code",
        "objective": "deep call",
        "parent_chain": chain,
    }
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["status"].lower() == "provider_unavailable"
    assert "recursion_depth" in (detail.get("actionable_hint") or "")
    # Ensure no Temporal dispatch happened.
    mock_temporal.start_workflow.assert_not_called()


def test_parent_chain_cycle_triggers_recursion_gate_503(client, mock_temporal):
    """Cycle in parent_chain refused with 503."""
    same = str(uuid.uuid4())
    body = {
        "task_type": "code",
        "objective": "loopy",
        "parent_chain": [same, same],
    }
    resp = client.post("/api/v1/tasks/dispatch", json=body)
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "cycle" in (detail.get("actionable_hint") or "").lower() or \
           "cycle" in (detail.get("error_message") or "").lower()
    mock_temporal.start_workflow.assert_not_called()
