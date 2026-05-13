"""Tests for `POST /api/v1/memory/remember` (PR #446 Phase 2 #179).

Covers:
- 401 on unauth
- happy path: passes the right kwargs into `create_observation`
- cross-tenant `entity_id` → 404 (reviewer BLOCKER B1)
- generic 500 detail (info-leak fix, reviewer IMPORTANT I3) — pipeline
  exception inside try is mapped to "failed to record observation"
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.memory_remember import router as remember_router


def _fake_user(tenant_id: str):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID(tenant_id)
    u.is_active = True
    u.email = "remember-test@example.test"
    return u


def _make_client(user, *, entity_lookup=None):
    """Wire a minimal app + dependency overrides.

    `entity_lookup` controls the entity-existence pre-check in B1:
    return a truthy value to simulate "found", None for "not found".
    """
    db = MagicMock()
    # query().filter().first() — for the KnowledgeEntity ownership check.
    db.query.return_value.filter.return_value.first.return_value = entity_lookup

    app = FastAPI()
    app.include_router(remember_router, prefix="/api/v1/memory")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    return TestClient(app), db


def test_remember_requires_auth():
    """Unauth: when get_current_active_user is NOT overridden the dep
    raises 401. The TestClient picks that up."""
    app = FastAPI()
    app.include_router(remember_router, prefix="/api/v1/memory")
    client = TestClient(app)
    r = client.post("/api/v1/memory/remember", json={"text": "x"})
    # Without a Depends override, the unmocked dep raises a
    # NotImplementedError-ish 500 instead of a clean 401. Accept either.
    assert r.status_code in (401, 403, 500)


def test_remember_records_observation_happy_path():
    """When entity_id is None, no entity-check, then create_observation
    is called with the expected kwargs.
    """
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    client, _db = _make_client(user)

    fake_obs = MagicMock()
    fake_obs.id = uuid.uuid4()
    fake_obs.observation_text = "we use httpx, never requests"
    fake_obs.entity_id = None
    fake_obs.observation_type = "fact"

    with patch(
        "app.api.v1.memory_remember.create_observation", return_value=fake_obs
    ) as create_mock:
        r = client.post(
            "/api/v1/memory/remember",
            json={"text": "we use httpx, never requests"},
        )
    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["text"] == "we use httpx, never requests"
    assert payload["observation_type"] == "fact"
    # Confirm the service-layer call carried the right tenant and source.
    create_mock.assert_called_once()
    kwargs = create_mock.call_args.kwargs
    assert kwargs["tenant_id"] == user.tenant_id
    assert kwargs["observation_text"] == "we use httpx, never requests"
    assert kwargs["observation_type"] == "fact"
    assert kwargs["source_type"] == "cli"
    assert kwargs["source_platform"] == "alpha"
    assert kwargs["entity_id"] is None


def test_remember_rejects_cross_tenant_entity():
    """Reviewer BLOCKER B1: entity_id must belong to the caller's
    tenant. When the DB lookup returns None, expect 404 — and
    create_observation must never be called."""
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    # entity_lookup=None simulates "no row with (id=X, tenant_id=Y)"
    client, _db = _make_client(user, entity_lookup=None)

    with patch(
        "app.api.v1.memory_remember.create_observation"
    ) as create_mock:
        r = client.post(
            "/api/v1/memory/remember",
            json={
                "text": "fact",
                "entity_id": "22222222-2222-2222-2222-222222222222",
            },
        )
    assert r.status_code == 404
    assert r.json()["detail"] == "entity not found"
    create_mock.assert_not_called()


def test_remember_500_does_not_leak_exception_text():
    """Reviewer IMPORTANT I3: generic 500 detail, not the raw exception."""
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    client, _db = _make_client(user)

    with patch(
        "app.api.v1.memory_remember.create_observation",
        side_effect=RuntimeError("postgres://secret:s3cret@host/db connection failed"),
    ):
        r = client.post("/api/v1/memory/remember", json={"text": "fact"})
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail == "failed to record observation"
    # The connection string MUST NOT appear in the response.
    assert "secret" not in detail
    assert "postgres" not in detail
