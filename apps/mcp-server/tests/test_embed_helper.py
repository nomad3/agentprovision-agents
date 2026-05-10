"""Tests for ``src._embed.get_embedding`` — the shared MCP-side helper
that replaces the in-process sentence-transformers call.

We mock ``httpx.AsyncClient`` (via the ``DummyHttpxClient`` from
``conftest.py``) so the tests don't require a live API. The helper's
public contract is:

  - URL: ``${API_BASE_URL}/api/v1/internal/embed``
  - method: POST
  - headers: ``X-Internal-Key: ${API_INTERNAL_KEY}``
  - body: ``{"text": <str>, "task_type": "document"|"query"}``
  - returns the ``embedding`` field on a 200, else ``None``
  - never raises — all error paths log + return None

These contract assertions are what the email + knowledge tools
depend on, so verify each branch.
"""
from __future__ import annotations

from typing import Optional

import httpx
import pytest

from src import _embed


def test_returns_embedding_on_happy_path(
    monkeypatch, patch_settings, make_client, DummyResponse
):
    fake_vec = [0.1] * 768
    client = make_client(
        responses={
            (
                "POST",
                "http://api:8000/api/v1/internal/embed",
            ): DummyResponse(200, {"embedding": fake_vec}),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)

    import asyncio

    result = asyncio.run(_embed.get_embedding("hello", task_type="document"))
    assert result == fake_vec

    # Inspect the captured outbound request.
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://api:8000/api/v1/internal/embed"
    assert call["headers"] == {"X-Internal-Key": "test-mcp-key"}
    assert call["json"] == {"text": "hello", "task_type": "document"}


def test_query_task_type_is_passed_through(
    monkeypatch, patch_settings, make_client, DummyResponse
):
    client = make_client(
        responses={
            (
                "POST",
                "http://api:8000/api/v1/internal/embed",
            ): DummyResponse(200, {"embedding": [0.0] * 768}),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)

    import asyncio

    asyncio.run(_embed.get_embedding("find leads", task_type="query"))
    assert client.calls[0]["json"]["task_type"] == "query"


def test_truncates_at_8000_chars(
    monkeypatch, patch_settings, make_client, DummyResponse
):
    """We pass the raw text up to 8000 chars; the API does its own
    truncation but we shouldn't blow the wire payload."""
    client = make_client(
        responses={
            (
                "POST",
                "http://api:8000/api/v1/internal/embed",
            ): DummyResponse(200, {"embedding": [0.0] * 768}),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)

    import asyncio

    long_text = "x" * 20000
    asyncio.run(_embed.get_embedding(long_text, task_type="document"))
    assert len(client.calls[0]["json"]["text"]) == 8000


def test_empty_text_returns_none_without_call(
    monkeypatch, patch_settings, make_client, DummyResponse
):
    client = make_client()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)

    import asyncio

    result = asyncio.run(_embed.get_embedding("", task_type="document"))
    assert result is None
    assert client.calls == []


def test_http_500_returns_none(
    monkeypatch, patch_settings, make_client, DummyResponse
):
    client = make_client(
        default_status=500,
        default_json={"detail": "kaboom"},
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)

    import asyncio

    result = asyncio.run(_embed.get_embedding("hello", task_type="document"))
    assert result is None


def test_http_401_returns_none(
    monkeypatch, patch_settings, make_client, DummyResponse
):
    """Wrong/missing internal key — caller must not crash."""
    client = make_client(
        default_status=401,
        default_json={"detail": "Invalid internal key"},
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)

    import asyncio

    result = asyncio.run(_embed.get_embedding("hello", task_type="document"))
    assert result is None


def test_api_returns_null_embedding_passes_through_as_none(
    monkeypatch, patch_settings, make_client, DummyResponse
):
    """When the API itself surfaces ``{"embedding": null}`` (graceful
    failure of both gRPC + Python upstream paths) we propagate None."""
    client = make_client(
        responses={
            (
                "POST",
                "http://api:8000/api/v1/internal/embed",
            ): DummyResponse(200, {"embedding": None}),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)

    import asyncio

    result = asyncio.run(_embed.get_embedding("hello", task_type="document"))
    assert result is None


def test_network_error_returns_none(monkeypatch, patch_settings):
    """ConnectError / TimeoutException must not propagate."""

    class _BoomClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _BoomClient())

    import asyncio

    result = asyncio.run(_embed.get_embedding("hello", task_type="document"))
    assert result is None


def test_timeout_returns_none(monkeypatch, patch_settings):
    class _SlowClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise httpx.TimeoutException("too slow")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _SlowClient())

    import asyncio

    result = asyncio.run(_embed.get_embedding("hello", task_type="document"))
    assert result is None


def test_email_legacy_helper_delegates_to_shared(
    monkeypatch, patch_settings, make_client, DummyResponse
):
    """``email._get_embedding`` is now a thin wrapper around
    ``_embed.get_embedding`` — verify the wire shape stays correct
    when called through the legacy entry point so existing call-sites
    don't regress."""
    fake_vec = [0.42] * 768
    client = make_client(
        responses={
            (
                "POST",
                "http://api:8000/api/v1/internal/embed",
            ): DummyResponse(200, {"embedding": fake_vec}),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)

    import asyncio

    from src.mcp_tools import email as em

    result = asyncio.run(em._get_embedding("body text", task_type="document"))
    assert result == fake_vec
    assert client.calls[0]["json"] == {"text": "body text", "task_type": "document"}


def test_knowledge_legacy_helper_delegates_to_shared(
    monkeypatch, patch_settings, make_client, DummyResponse
):
    fake_vec = [0.7] * 768
    client = make_client(
        responses={
            (
                "POST",
                "http://api:8000/api/v1/internal/embed",
            ): DummyResponse(200, {"embedding": fake_vec}),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)

    import asyncio

    from src.mcp_tools import knowledge as kn

    result = asyncio.run(kn._get_embedding("query text", task_type="query"))
    assert result == fake_vec
    assert client.calls[0]["json"] == {"text": "query text", "task_type": "query"}
