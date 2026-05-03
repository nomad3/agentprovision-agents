"""Tests for src.mcp_tools.connectors.

Single tool ``query_data_source`` with auto-discovery + per-connector
forwarding. Helpers ``_parse_json`` and the connector preference logic
exercised across happy/error paths.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import connectors as conn


# ---------------------------------------------------------------------------
# _parse_json helper
# ---------------------------------------------------------------------------

def test_parse_json_passthrough_dict():
    assert conn._parse_json({"a": 1}) == {"a": 1}


def test_parse_json_decodes_str():
    assert conn._parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_default_for_invalid():
    assert conn._parse_json("garbage", default={}) == {}


def test_parse_json_default_for_none():
    assert conn._parse_json(None, default={"x": 1}) == {"x": 1}


# ---------------------------------------------------------------------------
# query_data_source
# ---------------------------------------------------------------------------

@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(side_effect=None, default_status=200, default_json=None):
        client = make_client(
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        monkeypatch.setattr(conn.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


@pytest.mark.asyncio
async def test_query_data_source_requires_tenant(mock_ctx):
    out = await conn.query_data_source(query="SELECT 1", tenant_id="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_query_data_source_no_sources_returns_error(patch_httpx, mock_ctx, patch_settings):
    from tests.conftest import _DummyResponse  # type: ignore

    def _side_effect(method, url, kwargs):
        if "/internal/list" in url:
            return _DummyResponse(200, [])
        return _DummyResponse(200, [])

    patch_httpx(side_effect=_side_effect)
    out = await conn.query_data_source(query="SELECT 1", tenant_id="t", ctx=mock_ctx)
    assert "No data sources found" in out["error"]


@pytest.mark.asyncio
async def test_query_data_source_filters_by_type(patch_httpx, mock_ctx, patch_settings):
    from tests.conftest import _DummyResponse  # type: ignore

    rows_returned = [{"id": 1, "name": "Acme"}, {"id": 2, "name": "Beta"}]

    def _side_effect(method, url, kwargs):
        if "/internal/list" in url:
            return _DummyResponse(
                200,
                [
                    {"id": "ds-pg-1", "type": "postgres"},
                    {"id": "ds-api-1", "type": "api"},
                ],
            )
        # POST /internal-query
        return _DummyResponse(200, rows_returned)

    client = patch_httpx(side_effect=_side_effect)

    out = await conn.query_data_source(
        query="SELECT * FROM customers",
        tenant_id="t",
        connector_type="postgres",
        ctx=mock_ctx,
    )

    assert out["success"] is True
    assert out["row_count"] == 2
    assert out["connector_id"] == "ds-pg-1"
    # Second call (POST /internal-query) hit the postgres connector
    posts = [c for c in client.calls if c["method"] == "POST"]
    assert "ds-pg-1" in posts[0]["url"]


@pytest.mark.asyncio
async def test_query_data_source_uses_explicit_connector_id(patch_httpx, mock_ctx, patch_settings):
    """When ``connector_id`` is set we skip the discovery call and post
    directly to that connector."""
    from tests.conftest import _DummyResponse  # type: ignore

    def _side_effect(method, url, kwargs):
        return _DummyResponse(200, [{"x": 1}])

    client = patch_httpx(side_effect=_side_effect)

    out = await conn.query_data_source(
        query="SELECT 1",
        tenant_id="t",
        connector_id="ds-explicit",
        ctx=mock_ctx,
    )

    assert out["success"] is True
    # Only one POST should be issued (no discovery list GET)
    gets = [c for c in client.calls if c["method"] == "GET"]
    posts = [c for c in client.calls if c["method"] == "POST"]
    assert gets == []
    assert "ds-explicit" in posts[0]["url"]


@pytest.mark.asyncio
async def test_query_data_source_passes_endpoint_and_params(patch_httpx, mock_ctx, patch_settings):
    from tests.conftest import _DummyResponse  # type: ignore

    def _side_effect(method, url, kwargs):
        return _DummyResponse(200, [{"sku": "x", "price": 10}])

    client = patch_httpx(side_effect=_side_effect)

    out = await conn.query_data_source(
        query="",
        tenant_id="t",
        connector_id="ds-1",
        endpoint="/medications/search",
        params='{"q": "paracetamol"}',
        method="POST",
        ctx=mock_ctx,
    )
    assert out["success"] is True
    body = client.calls[0]["json"]
    assert body["endpoint"] == "/medications/search"
    assert body["params"] == {"q": "paracetamol"}
    assert body["method"] == "POST"


@pytest.mark.asyncio
async def test_query_data_source_prefers_queryable_when_no_filter(patch_httpx, mock_ctx, patch_settings):
    """When multiple sources and no type filter, prefer queryable ones."""
    from tests.conftest import _DummyResponse  # type: ignore

    def _side_effect(method, url, kwargs):
        if "/internal/list" in url:
            return _DummyResponse(
                200,
                [
                    {"id": "ds-other", "type": "salesforce"},
                    {"id": "ds-pg", "type": "postgres"},
                ],
            )
        return _DummyResponse(200, [])

    client = patch_httpx(side_effect=_side_effect)
    out = await conn.query_data_source(query="x", tenant_id="t", ctx=mock_ctx)
    assert out["success"] is True
    assert out["connector_id"] == "ds-pg"


@pytest.mark.asyncio
async def test_query_data_source_propagates_http_status_error(patch_httpx, mock_ctx, patch_settings):
    from tests.conftest import _DummyResponse  # type: ignore
    import httpx as real_httpx

    class _Resp:
        def __init__(self, status, text):
            self.status_code = status
            self.text = text

        def json(self):
            return {}

        def raise_for_status(self):
            req = real_httpx.Request("POST", "http://x")
            resp = real_httpx.Response(self.status_code, request=req, text=self.text)
            raise real_httpx.HTTPStatusError("err", request=req, response=resp)

    def _side_effect(method, url, kwargs):
        if "/internal/list" in url:
            return _DummyResponse(200, [{"id": "ds-1", "type": "postgres"}])
        return _Resp(500, "boom")

    patch_httpx(side_effect=_side_effect)
    out = await conn.query_data_source(query="x", tenant_id="t", ctx=mock_ctx)
    assert "error" in out
    assert "500" in out["error"]


@pytest.mark.asyncio
async def test_query_data_source_handles_unexpected_exception(monkeypatch, mock_ctx, patch_settings):
    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("network")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(conn.httpx, "AsyncClient", lambda *a, **kw: _Boom())
    out = await conn.query_data_source(query="x", tenant_id="t", ctx=mock_ctx)
    assert "error" in out
