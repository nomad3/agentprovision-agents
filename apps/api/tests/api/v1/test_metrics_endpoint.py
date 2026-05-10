"""Phase 3 commit 4 — /api/v1/metrics endpoint tests.

Verifies:
  - 401 without X-Internal-Key header
  - 401 with wrong key
  - 200 + text/plain OpenMetrics body when key matches API_INTERNAL_KEY
  - response body contains the cli_orchestrator_status_total metric name

We mount JUST the metrics router on a fresh FastAPI app so the test
doesn't drag the full app's DB / pgvector / temporal init path. That
way it stays out of the @pytest.mark.integration set.
"""
from __future__ import annotations

import pytest

# Skip the entire module if FastAPI's test client / prometheus_client
# aren't installed — keeps the suite green in environments without
# the dev extras.
pytest.importorskip("fastapi")
pytest.importorskip("prometheus_client")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.metrics import router as metrics_router
from app.core.config import settings


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(metrics_router, prefix="/api/v1", tags=["metrics"])
    return TestClient(app)


def test_metrics_endpoint_requires_internal_key(client):
    resp = client.get("/api/v1/metrics")
    assert resp.status_code == 401


def test_metrics_endpoint_rejects_wrong_key(client):
    resp = client.get(
        "/api/v1/metrics", headers={"X-Internal-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_metrics_endpoint_serves_text_plain_with_internal_key(client):
    resp = client.get(
        "/api/v1/metrics",
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
    )
    assert resp.status_code == 200
    # Prometheus exposition is text/plain (CONTENT_TYPE_LATEST).
    assert resp.headers["content-type"].startswith("text/plain")


def test_metrics_endpoint_contains_cli_orchestrator_status_total(client):
    """The cli_orchestrator_status_total counter is registered when the
    package is imported — assert it shows up in /metrics."""
    # Force import to register the metric on the default registry.
    import cli_orchestrator.executor  # noqa: F401

    resp = client.get(
        "/api/v1/metrics",
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "cli_orchestrator_status_total" in body
    # The Phase 3 preflight histogram should be registered too.
    assert "cli_orchestrator_preflight_duration_ms" in body


def test_metrics_endpoint_accepts_mcp_api_key(client):
    """MCP_API_KEY also works (matches RL internal endpoint pattern)."""
    resp = client.get(
        "/api/v1/metrics",
        headers={"X-Internal-Key": settings.MCP_API_KEY},
    )
    assert resp.status_code == 200
