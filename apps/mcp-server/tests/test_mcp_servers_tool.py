"""Tests for src.mcp_tools.mcp_servers (MCP server connector registry)."""
from __future__ import annotations

import json
import pytest

from src.mcp_tools import mcp_servers as ms


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None, side_effect=None):
        client = make_client(
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        monkeypatch.setattr(ms.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# Required-tenant guards
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool,kwargs",
    [
        (ms.connect_mcp_server, {"name": "x", "server_url": "http://x"}),
        (ms.list_mcp_servers, {}),
        (ms.discover_mcp_tools, {"connector_id": "c-1"}),
        (ms.call_mcp_tool, {"connector_id": "c-1", "tool_name": "t"}),
        (ms.disconnect_mcp_server, {"connector_id": "c-1"}),
        (ms.health_check_mcp_server, {"connector_id": "c-1"}),
        (ms.get_mcp_server_logs, {}),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_requires_tenant(tool, kwargs, mock_ctx):
    out = await tool(tenant_id="", ctx=mock_ctx, **kwargs)
    assert "error" in out


# ---------------------------------------------------------------------------
# connect_mcp_server
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_mcp_server_validates_transport(mock_ctx):
    out = await ms.connect_mcp_server(
        name="x", server_url="http://x", transport="bogus", tenant_id="t", ctx=mock_ctx
    )
    assert "transport must be" in out["error"]


@pytest.mark.asyncio
async def test_connect_mcp_server_requires_url(mock_ctx):
    out = await ms.connect_mcp_server(
        name="x", server_url="", tenant_id="t", ctx=mock_ctx
    )
    assert "server_url" in out["error"]


@pytest.mark.asyncio
async def test_connect_mcp_server_invalid_custom_headers(patch_httpx, mock_ctx, patch_settings):
    out = await ms.connect_mcp_server(
        name="x", server_url="http://x", custom_headers="not-json",
        tenant_id="t", ctx=mock_ctx,
    )
    assert "custom_headers" in out["error"]


@pytest.mark.asyncio
async def test_connect_mcp_server_happy(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=201, default_json={
        "id": "c-1", "name": "Stripe", "server_url": "http://x", "transport": "sse",
    })
    out = await ms.connect_mcp_server(
        name="Stripe", server_url="http://x", auth_token="tok",
        custom_headers='{"X-Api-Key": "k"}',
        description="payments",
        tenant_id="t", ctx=mock_ctx,
    )
    assert out["status"] == "created"
    body = client.calls[0]["json"]
    assert body["custom_headers"] == {"X-Api-Key": "k"}
    assert body["auth_token"] == "tok"


@pytest.mark.asyncio
async def test_connect_mcp_server_api_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await ms.connect_mcp_server(
        name="x", server_url="http://x", tenant_id="t", ctx=mock_ctx
    )
    assert "Failed to connect" in out["error"]


# ---------------------------------------------------------------------------
# list_mcp_servers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_mcp_servers_returns_normalized(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json=[
        {
            "id": "c-1", "name": "Stripe", "server_url": "http://x",
            "transport": "sse", "status": "connected",
            "tool_count": 3, "call_count": 10, "enabled": True,
        }
    ])
    out = await ms.list_mcp_servers(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 1
    assert out["servers"][0]["tool_count"] == 3


@pytest.mark.asyncio
async def test_list_mcp_servers_filter(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json=[])
    await ms.list_mcp_servers(status="error", tenant_id="t", ctx=mock_ctx)
    assert client.calls[0]["params"]["status"] == "error"


# ---------------------------------------------------------------------------
# discover_mcp_tools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_mcp_tools_404(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=404, default_json={})
    out = await ms.discover_mcp_tools(connector_id="c-x", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"]


@pytest.mark.asyncio
async def test_discover_mcp_tools_happy(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"tools": [{"name": "x"}]})
    out = await ms.discover_mcp_tools(connector_id="c-1", tenant_id="t", ctx=mock_ctx)
    assert out["tools"][0]["name"] == "x"


# ---------------------------------------------------------------------------
# call_mcp_tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_mcp_tool_invalid_args(mock_ctx):
    out = await ms.call_mcp_tool(
        connector_id="c-1", tool_name="t", arguments="not-json",
        tenant_id="t", ctx=mock_ctx,
    )
    assert "valid JSON" in out["error"]


@pytest.mark.asyncio
async def test_call_mcp_tool_happy(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json={"output": "ok"})
    out = await ms.call_mcp_tool(
        connector_id="c-1", tool_name="t",
        arguments=json.dumps({"q": 1}),
        tenant_id="t", ctx=mock_ctx,
    )
    assert out == {"output": "ok"}
    assert client.calls[0]["json"] == {"tool_name": "t", "arguments": {"q": 1}}


@pytest.mark.asyncio
async def test_call_mcp_tool_400_uses_detail(patch_httpx, mock_ctx, patch_settings):
    from tests.conftest import _DummyResponse  # type: ignore

    def _side_effect(method, url, kwargs):
        return _DummyResponse(400, {"detail": "bad input"})

    patch_httpx(side_effect=_side_effect)
    out = await ms.call_mcp_tool(
        connector_id="c-1", tool_name="t", tenant_id="t", ctx=mock_ctx
    )
    assert out["error"] == "bad input"


# ---------------------------------------------------------------------------
# disconnect_mcp_server
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disconnect_mcp_server_happy(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={})
    out = await ms.disconnect_mcp_server(
        connector_id="c-1", tenant_id="t", ctx=mock_ctx
    )
    assert out["status"] == "disconnected"


@pytest.mark.asyncio
async def test_disconnect_mcp_server_404(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=404, default_json={})
    out = await ms.disconnect_mcp_server(
        connector_id="ghost", tenant_id="t", ctx=mock_ctx
    )
    assert "not found" in out["error"]


# ---------------------------------------------------------------------------
# health_check_mcp_server
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check_returns_payload(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"status": "healthy"})
    out = await ms.health_check_mcp_server(
        connector_id="c-1", tenant_id="t", ctx=mock_ctx
    )
    assert out["status"] == "healthy"


# ---------------------------------------------------------------------------
# get_mcp_server_logs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_mcp_server_logs_global(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json=[
        {
            "id": "l-1", "tool_name": "x", "success": True,
            "duration_ms": 50, "created_at": "now",
        }
    ])
    out = await ms.get_mcp_server_logs(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 1
    # Without connector_id, should hit /logs
    assert client.calls[0]["url"].endswith("/internal/logs")


@pytest.mark.asyncio
async def test_get_mcp_server_logs_per_connector(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json=[])
    await ms.get_mcp_server_logs(
        connector_id="c-1", tenant_id="t", ctx=mock_ctx
    )
    assert "/c-1/logs" in client.calls[0]["url"]
