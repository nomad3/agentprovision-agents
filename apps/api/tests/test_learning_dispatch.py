"""T4.4c — internal `POST /api/v1/learning/dispatch` endpoint.

Thin HTTP wrapper around ``LearningService.dispatch()`` (T4.1a). Pins:

  * internal-key gating (401 without header)
  * request body validates against ``LearningIntent`` schema (422)
  * happy path returns ``{workflow_id}`` from the service helper
  * service-layer exception → 500 with detail
"""
from __future__ import annotations

import os
os.environ["TESTING"] = "True"

from unittest.mock import AsyncMock, patch

import pytest


def test_dispatch_router_imports_clean():
    """Locked per feedback_test_router_startup."""
    from app.api.v1 import routes  # noqa: F401
    from app.api.v1 import learning

    paths = {r.path for r in learning.router.routes}
    assert "/dispatch" in paths


def _build_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.api.v1.learning import router

    monkeypatch.setattr(settings, "API_INTERNAL_KEY", "test-key", raising=False)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/learning")
    return TestClient(app)


def test_dispatch_requires_internal_key(monkeypatch):
    client = _build_client(monkeypatch)
    r = client.post(
        "/api/v1/learning/dispatch",
        json={"source_url": "https://youtu.be/abcdefghijk", "tenant_id": "t1", "actor_user_id": "u1"},
    )
    assert r.status_code == 401


def test_dispatch_rejects_intent_without_source(monkeypatch):
    """LearningIntent's model_validator requires source_url OR attachment_path
    OR resume_job_id — body missing all three should yield 422."""
    client = _build_client(monkeypatch)
    r = client.post(
        "/api/v1/learning/dispatch",
        json={"tenant_id": "t1", "actor_user_id": "u1"},
        headers={"X-Internal-Key": "test-key"},
    )
    assert r.status_code == 422


def test_dispatch_returns_workflow_id_from_service(monkeypatch):
    client = _build_client(monkeypatch)
    fake = AsyncMock(return_value="luna-learn-t1-deadbeefcafe")
    with patch("app.services.learning_service.LearningService.dispatch", new=fake):
        r = client.post(
            "/api/v1/learning/dispatch",
            json={"source_url": "https://youtu.be/abcdefghijk", "tenant_id": "t1", "actor_user_id": "u1"},
            headers={"X-Internal-Key": "test-key"},
        )
    assert r.status_code == 200, r.text
    assert r.json() == {"workflow_id": "luna-learn-t1-deadbeefcafe"}
    fake.assert_awaited_once()
    intent = fake.await_args.args[0]
    assert intent.source_url == "https://youtu.be/abcdefghijk"
    assert intent.tenant_id == "t1"


def test_dispatch_passes_attachment_path_through(monkeypatch):
    client = _build_client(monkeypatch)
    fake = AsyncMock(return_value="wf-x")
    with patch("app.services.learning_service.LearningService.dispatch", new=fake):
        r = client.post(
            "/api/v1/learning/dispatch",
            json={"attachment_path": "/tmp/x.ogg", "tenant_id": "t1", "actor_user_id": "u1"},
            headers={"X-Internal-Key": "test-key"},
        )
    assert r.status_code == 200, r.text
    intent = fake.await_args.args[0]
    assert intent.attachment_path == "/tmp/x.ogg"
    assert intent.source_url is None


def test_dispatch_service_failure_returns_500(monkeypatch):
    client = _build_client(monkeypatch)
    fake = AsyncMock(side_effect=RuntimeError("temporal down"))
    with patch("app.services.learning_service.LearningService.dispatch", new=fake):
        r = client.post(
            "/api/v1/learning/dispatch",
            json={"source_url": "https://youtu.be/abcdefghijk", "tenant_id": "t1", "actor_user_id": "u1"},
            headers={"X-Internal-Key": "test-key"},
        )
    assert r.status_code == 500
    assert "temporal" in r.json()["detail"].lower() or "dispatch" in r.json()["detail"].lower()
