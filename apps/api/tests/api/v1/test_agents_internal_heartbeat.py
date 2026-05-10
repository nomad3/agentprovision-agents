"""Tests for ``POST /api/v1/agents/internal/heartbeat`` — Phase 4 commit 8.

Verifies (per design §10.3(c) auth-tier rejection):
  - 403 with no Authorization header
  - 403 with X-Internal-Key only (NOT an agent-token)
  - 403 with a tenant-JWT (kind != agent_token)
  - 204 with a valid agent-token + matching task row
  - 204 silent no-op when task_id doesn't exist (synthetic chat path)
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from app.api import deps
from app.api.v1.internal_agent_heartbeat import router as heartbeat_router
from app.core.config import settings


def _agent_token(tenant_id: str = None, agent_id: str = None, task_id: str = None) -> str:
    now = int(time.time())
    payload = {
        "sub": f"agent:{agent_id or uuid.uuid4()}",
        "kind": "agent_token",
        "tenant_id": tenant_id or str(uuid.uuid4()),
        "agent_id": agent_id or str(uuid.uuid4()),
        "task_id": task_id or str(uuid.uuid4()),
        "parent_workflow_id": None,
        "scope": None,
        "parent_chain": [],
        "iat": now,
        "exp": now + 600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _tenant_jwt(email: str = "u@x.com") -> str:
    """A regular login token (kind=access)."""
    now = int(time.time())
    payload = {
        "sub": email,
        "kind": "access",
        "iat": now,
        "exp": now + 600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


@pytest.fixture
def fake_db_with_no_task():
    """Returns a db whose .filter(...).first() returns None for the
    AgentTask query — exercising the silent-no-op path."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


@pytest.fixture
def client_no_task(fake_db_with_no_task):
    app = FastAPI()
    # Mount under /api/v1 so the route's full path matches.
    app.include_router(heartbeat_router, prefix="/api/v1", tags=["internal"])

    def _fake_db():
        yield fake_db_with_no_task

    app.dependency_overrides[deps.get_db] = _fake_db
    return TestClient(app)


def test_no_authorization_returns_403(client_no_task):
    resp = client_no_task.post(
        "/api/v1/agents/internal/heartbeat",
        json={"task_id": str(uuid.uuid4()), "tool_name": "Bash", "ts": 1},
    )
    assert resp.status_code == 403


def test_x_internal_key_only_returns_403(client_no_task):
    resp = client_no_task.post(
        "/api/v1/agents/internal/heartbeat",
        json={"task_id": str(uuid.uuid4()), "tool_name": "Bash", "ts": 1},
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
    )
    assert resp.status_code == 403


def test_tenant_jwt_returns_403(client_no_task):
    """SR-11: a regular login token (kind=access) is NOT an agent-token."""
    tok = _tenant_jwt()
    resp = client_no_task.post(
        "/api/v1/agents/internal/heartbeat",
        json={"task_id": str(uuid.uuid4()), "tool_name": "Bash", "ts": 1},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 403


def test_agent_token_with_no_matching_task_returns_204(client_no_task):
    """Synthetic chat-path task_id (no AgentTask row) → silent no-op
    so the leaf hook stays fire-and-forget."""
    tok = _agent_token()
    resp = client_no_task.post(
        "/api/v1/agents/internal/heartbeat",
        json={"task_id": str(uuid.uuid4()), "tool_name": "Bash", "ts": 1},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 204


def test_agent_token_with_matching_task_updates_last_seen_at():
    """Agent-token + AgentTask row in the claim's tenant → update
    last_seen_at and return 204."""
    tenant_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    # Build a fake DB whose first .first() returns a fake AgentTask, and
    # the second .first() (after the Agent query) returns a fake Agent
    # with matching tenant_id.
    fake_task = MagicMock()
    fake_task.id = uuid.UUID(task_id)
    fake_task.assigned_agent_id = uuid.UUID(agent_id)
    fake_task.last_seen_at = None

    fake_agent = MagicMock()
    fake_agent.id = uuid.UUID(agent_id)
    fake_agent.tenant_id = uuid.UUID(tenant_id)

    db = MagicMock()
    # First query is AgentTask, second is Agent.
    db.query.return_value.filter.return_value.first.side_effect = [fake_task, fake_agent]

    app = FastAPI()
    app.include_router(heartbeat_router, prefix="/api/v1", tags=["internal"])
    def _fake_db():
        yield db
    app.dependency_overrides[deps.get_db] = _fake_db
    test_client = TestClient(app)

    tok = _agent_token(tenant_id=tenant_id, agent_id=agent_id, task_id=task_id)
    resp = test_client.post(
        "/api/v1/agents/internal/heartbeat",
        json={"task_id": task_id, "tool_name": "Bash", "ts": int(time.time())},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 204
    # last_seen_at should have been mutated to a non-None value.
    assert fake_task.last_seen_at is not None
    db.commit.assert_called_once()


def test_agent_token_with_cross_tenant_task_does_not_update():
    """Defence-in-depth: claim tenant != task agent's tenant → no update,
    no 403 leak (silently 204)."""
    claim_tenant = str(uuid.uuid4())
    other_tenant = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    fake_task = MagicMock()
    fake_task.id = uuid.UUID(task_id)
    fake_task.assigned_agent_id = uuid.UUID(agent_id)
    fake_task.last_seen_at = None

    fake_agent = MagicMock()
    fake_agent.tenant_id = uuid.UUID(other_tenant)  # cross-tenant

    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [fake_task, fake_agent]

    app = FastAPI()
    app.include_router(heartbeat_router, prefix="/api/v1", tags=["internal"])
    def _fake_db():
        yield db
    app.dependency_overrides[deps.get_db] = _fake_db
    test_client = TestClient(app)

    tok = _agent_token(tenant_id=claim_tenant, agent_id=agent_id, task_id=task_id)
    resp = test_client.post(
        "/api/v1/agents/internal/heartbeat",
        json={"task_id": task_id, "tool_name": "Bash", "ts": int(time.time())},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 204
    # Did NOT update last_seen_at since the task is in another tenant.
    assert fake_task.last_seen_at is None
    db.commit.assert_not_called()
