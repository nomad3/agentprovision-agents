"""Phase 3 commit 8 — POST /api/v1/internal/orchestrator/events tests.

Verifies:
  - 401 without X-Internal-Key
  - 400 when event_type doesn't start with 'execution.'
  - 200 + delivery summary when event matches a tenant webhook
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.internal_orchestrator_events import router as internal_router
from app.core.config import settings


@pytest.fixture
def client():
    app = FastAPI()
    # Mock app.api.deps.get_db so the route doesn't need a real DB.
    from app.api import deps

    def _fake_get_db():
        yield object()

    app.dependency_overrides[deps.get_db] = _fake_get_db
    app.include_router(internal_router, prefix="/api/v1/internal", tags=["internal"])
    return TestClient(app)


def test_orchestrator_events_requires_internal_key(client):
    resp = client.post(
        "/api/v1/internal/orchestrator/events",
        json={
            "event_type": "execution.heartbeat_missed",
            "payload": {"run_id": "r-1"},
            "tenant_id": str(uuid4()),
        },
    )
    assert resp.status_code == 401


def test_orchestrator_events_rejects_non_execution_prefix(client):
    resp = client.post(
        "/api/v1/internal/orchestrator/events",
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
        json={
            "event_type": "memory.observation_recorded",
            "payload": {"run_id": "r-1"},
            "tenant_id": str(uuid4()),
        },
    )
    assert resp.status_code == 400
    assert "execution." in resp.json()["detail"]


def test_orchestrator_events_happy_path_delivers(client):
    tenant_id = str(uuid4())
    fake_results = [
        {"webhook_id": "wh-1", "delivered": True, "status_code": 200},
    ]
    with patch(
        "app.services.webhook_connectors.fire_outbound_event",
        return_value=fake_results,
    ):
        resp = client.post(
            "/api/v1/internal/orchestrator/events",
            headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
            json={
                "event_type": "execution.heartbeat_missed",
                "payload": {"run_id": "r-1", "last_seen_ts": 1234567890},
                "tenant_id": tenant_id,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["event_type"] == "execution.heartbeat_missed"
    assert body["deliveries"] == fake_results


def test_orchestrator_events_rejects_bad_tenant_uuid(client):
    resp = client.post(
        "/api/v1/internal/orchestrator/events",
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
        json={
            "event_type": "execution.heartbeat_missed",
            "payload": {"run_id": "r-1"},
            "tenant_id": "not-a-uuid",
        },
    )
    assert resp.status_code == 400


def test_orchestrator_events_accepts_mcp_api_key(client):
    tenant_id = str(uuid4())
    with patch(
        "app.services.webhook_connectors.fire_outbound_event", return_value=[],
    ):
        resp = client.post(
            "/api/v1/internal/orchestrator/events",
            headers={"X-Internal-Key": settings.MCP_API_KEY},
            json={
                "event_type": "execution.started",
                "payload": {"run_id": "r-1"},
                "tenant_id": tenant_id,
            },
        )
    assert resp.status_code == 200
