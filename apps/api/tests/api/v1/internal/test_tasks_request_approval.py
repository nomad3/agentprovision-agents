"""Tests for ``POST /api/v1/tasks/internal/{task_id}/request-approval``.

Phase 4 review C1: backs the ``request_human_approval`` MCP tool.
The user-facing ``/workflow-approve`` endpoint requires JWT bearer
auth and validates ``decision in ("approved","rejected")`` — neither
fits a leaf-MCP caller.

Verifies:
  - 401 without X-Internal-Key
  - 400 without X-Tenant-Id
  - 404 when task not in tenant (no info leak)
  - 200 + status='requested' on the happy path, with task.status flipped,
    context.approval_request stashed, and a high-priority Notification row.
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
from app.api.v1.internal_agent_tasks import router as internal_router
from app.core.config import settings


@pytest.fixture
def state():
    """Shared mutable state so tests can inspect what the endpoint did
    to the task / Notification."""
    return {
        "task": None,
        "agent": None,
        "notif_added": [],
    }


@pytest.fixture
def client(state):
    """Build a TestClient whose get_db override walks task → agent and
    captures any Notification add() call."""
    def _make_db():
        db = MagicMock()

        def _query(model):
            class _Q:
                def filter(self, *_a, **_kw):
                    return self

                def first(self_inner):  # noqa: N805
                    name = getattr(model, "__name__", "")
                    if name == "AgentTask":
                        return state["task"]
                    if name == "Agent":
                        return state["agent"]
                    return None

            return _Q()

        db.query.side_effect = _query
        db.add.side_effect = lambda obj: state["notif_added"].append(obj)
        db.commit = MagicMock()
        db.refresh = lambda obj: setattr(obj, "id", obj.id or uuid.uuid4())
        return db

    app = FastAPI()
    app.include_router(internal_router, prefix="/api/v1", tags=["internal"])
    app.dependency_overrides[deps.get_db] = _make_db
    return TestClient(app)


def _body(reason: str = "needs admin review"):
    return {"reason": reason}


def test_no_key_returns_401(client):
    task_id = uuid.uuid4()
    resp = client.post(
        f"/api/v1/tasks/internal/{task_id}/request-approval",
        json=_body(),
        headers={"X-Tenant-Id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


def test_no_tenant_returns_400(client):
    task_id = uuid.uuid4()
    resp = client.post(
        f"/api/v1/tasks/internal/{task_id}/request-approval",
        json=_body(),
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
    )
    assert resp.status_code == 400
    assert "X-Tenant-Id" in resp.text


def test_task_not_found_returns_404(client, state):
    """No task row → 404."""
    state["task"] = None
    state["agent"] = None
    resp = client.post(
        f"/api/v1/tasks/internal/{uuid.uuid4()}/request-approval",
        json=_body(),
        headers={
            "X-Internal-Key": settings.API_INTERNAL_KEY,
            "X-Tenant-Id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404


def test_task_in_other_tenant_returns_404(client, state):
    """Task exists but belongs to a different tenant → same 404 (no
    info leak across tenants)."""
    task_id = uuid.uuid4()
    other_tenant = uuid.uuid4()
    requesting_tenant = uuid.uuid4()
    state["task"] = SimpleNamespace(
        id=task_id,
        assigned_agent_id=uuid.uuid4(),
        status="running",
        context=None,
    )
    state["agent"] = SimpleNamespace(
        id=state["task"].assigned_agent_id,
        tenant_id=other_tenant,
    )

    resp = client.post(
        f"/api/v1/tasks/internal/{task_id}/request-approval",
        json=_body(),
        headers={
            "X-Internal-Key": settings.API_INTERNAL_KEY,
            "X-Tenant-Id": str(requesting_tenant),
        },
    )
    assert resp.status_code == 404


def test_happy_path_flips_status_and_adds_notification(client, state):
    """Task in tenant → status flipped, context updated, notification queued."""
    task_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    state["task"] = SimpleNamespace(
        id=task_id,
        assigned_agent_id=uuid.uuid4(),
        status="running",
        context={"existing": "value"},
    )
    state["agent"] = SimpleNamespace(
        id=state["task"].assigned_agent_id,
        tenant_id=tenant_id,
    )

    resp = client.post(
        f"/api/v1/tasks/internal/{task_id}/request-approval",
        json={"reason": "needs admin review"},
        headers={
            "X-Internal-Key": settings.API_INTERNAL_KEY,
            "X-Tenant-Id": str(tenant_id),
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "requested"
    assert payload["task_id"] == str(task_id)
    assert "notification_id" in payload

    # task.status flipped, existing context preserved, approval_request stashed
    assert state["task"].status == "waiting_for_approval"
    assert state["task"].context["existing"] == "value"
    assert state["task"].context["approval_request"]["reason"] == "needs admin review"

    # Notification row was added (priority=high, source=system)
    assert len(state["notif_added"]) == 1
    notif = state["notif_added"][0]
    assert notif.priority == "high"
    assert notif.source == "system"
    assert notif.tenant_id == tenant_id
    assert notif.reference_id == str(task_id)
    assert notif.reference_type == "agent_task"
