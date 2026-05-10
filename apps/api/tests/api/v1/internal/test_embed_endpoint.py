"""Tests for ``POST /api/v1/internal/embed``.

Covers:
  - 401 without/with bad ``X-Internal-Key``
  - 200 happy path returns the embedding from ``embed_text``
  - 200 graceful failure (``embed_text`` returns None → ``{"embedding": null}``)
  - 200 hard failure (``embed_text`` raises) is swallowed → null
  - task_type is mapped onto the API's internal naming
  - Both ``API_INTERNAL_KEY`` and ``MCP_API_KEY`` are accepted
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.internal_embed import router as embed_router
from app.core.config import settings


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(embed_router, prefix="/api/v1/internal", tags=["internal"])
    return TestClient(app)


def test_missing_key_returns_401(client):
    resp = client.post(
        "/api/v1/internal/embed",
        json={"text": "hello world", "task_type": "document"},
    )
    assert resp.status_code == 401


def test_wrong_key_returns_401(client):
    resp = client.post(
        "/api/v1/internal/embed",
        json={"text": "hello world", "task_type": "document"},
        headers={"X-Internal-Key": "definitely-not-the-real-key"},
    )
    assert resp.status_code == 401


def test_happy_path_returns_embedding(client):
    fake_vec = [0.1] * 768
    with patch(
        "app.api.v1.internal_embed.embed_text", return_value=fake_vec
    ) as mock_embed:
        resp = client.post(
            "/api/v1/internal/embed",
            json={"text": "hello world", "task_type": "document"},
            headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["embedding"] == fake_vec
    # Document task_type is mapped to the API-internal naming.
    mock_embed.assert_called_once_with("hello world", task_type="RETRIEVAL_DOCUMENT")


def test_query_task_type_maps_to_retrieval_query(client):
    fake_vec = [0.2] * 768
    with patch(
        "app.api.v1.internal_embed.embed_text", return_value=fake_vec
    ) as mock_embed:
        resp = client.post(
            "/api/v1/internal/embed",
            json={"text": "find me leads", "task_type": "query"},
            headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
        )
    assert resp.status_code == 200
    mock_embed.assert_called_once_with("find me leads", task_type="RETRIEVAL_QUERY")


def test_mcp_api_key_also_accepted(client):
    fake_vec = [0.3] * 768
    with patch(
        "app.api.v1.internal_embed.embed_text", return_value=fake_vec
    ):
        resp = client.post(
            "/api/v1/internal/embed",
            json={"text": "hello", "task_type": "document"},
            headers={"X-Internal-Key": settings.MCP_API_KEY},
        )
    assert resp.status_code == 200
    assert resp.json()["embedding"] == fake_vec


def test_graceful_none_returns_null_embedding(client):
    """When embed_text returns None (both gRPC + Python paths failed)
    the endpoint must surface that as ``{"embedding": null}`` rather
    than 500 — the caller decides whether to skip indexing."""
    with patch("app.api.v1.internal_embed.embed_text", return_value=None):
        resp = client.post(
            "/api/v1/internal/embed",
            json={"text": "anything", "task_type": "document"},
            headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
        )
    assert resp.status_code == 200
    assert resp.json() == {"embedding": None}


def test_unexpected_exception_swallowed_to_null(client):
    """If ``embed_text`` raises (it shouldn't — but defence in depth),
    we log and return null instead of 500."""
    with patch(
        "app.api.v1.internal_embed.embed_text",
        side_effect=RuntimeError("boom"),
    ):
        resp = client.post(
            "/api/v1/internal/embed",
            json={"text": "anything", "task_type": "document"},
            headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
        )
    assert resp.status_code == 200
    assert resp.json() == {"embedding": None}


def test_invalid_task_type_returns_422(client):
    """``task_type`` is constrained to document|query."""
    resp = client.post(
        "/api/v1/internal/embed",
        json={"text": "hello", "task_type": "garbage"},
        headers={"X-Internal-Key": settings.API_INTERNAL_KEY},
    )
    assert resp.status_code == 422
