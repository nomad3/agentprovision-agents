"""Tests for src.mcp_tools.webhooks (universal webhook connector tools)."""
from __future__ import annotations

import json
import pytest

from src.mcp_tools import webhooks as wh


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None):
        client = make_client(default_status=default_status, default_json=default_json)
        monkeypatch.setattr(wh.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# Required-tenant guards
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool,kwargs",
    [
        (wh.register_webhook, {"name": "n", "direction": "inbound", "events": "entity.created"}),
        (wh.list_webhooks, {}),
        (wh.delete_webhook, {"webhook_id": "w-1"}),
        (wh.test_webhook, {"webhook_id": "w-1"}),
        (wh.send_webhook_event, {"event_type": "x", "payload": "{}"}),
        (wh.get_webhook_logs, {}),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_requires_tenant(tool, kwargs, mock_ctx):
    out = await tool(tenant_id="", ctx=mock_ctx, **kwargs)
    assert "error" in out


# ---------------------------------------------------------------------------
# register_webhook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_webhook_validates_direction(mock_ctx):
    out = await wh.register_webhook(
        name="n", direction="weird", events="x", tenant_id="t", ctx=mock_ctx
    )
    assert "direction must" in out["error"]


@pytest.mark.asyncio
async def test_register_webhook_outbound_requires_target_url(mock_ctx):
    out = await wh.register_webhook(
        name="n", direction="outbound", events="x", tenant_id="t", ctx=mock_ctx
    )
    assert "target_url is required" in out["error"]


@pytest.mark.asyncio
async def test_register_webhook_requires_events(mock_ctx):
    out = await wh.register_webhook(
        name="n", direction="inbound", events="", tenant_id="t", ctx=mock_ctx
    )
    assert "event type" in out["error"]


@pytest.mark.asyncio
async def test_register_webhook_invalid_headers(mock_ctx):
    out = await wh.register_webhook(
        name="n", direction="inbound", events="x", headers="not-json",
        tenant_id="t", ctx=mock_ctx,
    )
    assert "headers must" in out["error"]


@pytest.mark.asyncio
async def test_register_webhook_invalid_payload_transform(mock_ctx):
    out = await wh.register_webhook(
        name="n", direction="inbound", events="x", payload_transform="not-json",
        tenant_id="t", ctx=mock_ctx,
    )
    assert "payload_transform must" in out["error"]


@pytest.mark.asyncio
async def test_register_webhook_inbound_returns_slug(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=201, default_json={
        "id": "w-1", "name": "S", "direction": "inbound",
        "events": ["entity.created"], "slug": "abc123",
    })
    out = await wh.register_webhook(
        name="S", direction="inbound", events="entity.created",
        headers='{"X-Y": "z"}',
        payload_transform='{"a": "$.b"}',
        secret="s",
        description="d",
        tenant_id="t", ctx=mock_ctx,
    )
    assert out["status"] == "created"
    assert out["slug"] == "abc123"
    assert "/in/abc123" in out["inbound_url"]


@pytest.mark.asyncio
async def test_register_webhook_outbound_returns_target_url(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=201, default_json={
        "id": "w-1", "name": "S", "direction": "outbound",
        "events": ["x"], "target_url": "http://x",
    })
    out = await wh.register_webhook(
        name="S", direction="outbound", events="x",
        target_url="http://x",
        tenant_id="t", ctx=mock_ctx,
    )
    assert out["target_url"] == "http://x"


@pytest.mark.asyncio
async def test_register_webhook_api_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await wh.register_webhook(
        name="n", direction="inbound", events="x", tenant_id="t", ctx=mock_ctx
    )
    assert "Failed to create" in out["error"]


# ---------------------------------------------------------------------------
# list_webhooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_webhooks_normalizes(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json=[
        {
            "id": "w-1", "name": "x", "direction": "inbound",
            "events": ["e"], "enabled": True, "status": "active",
            "trigger_count": 7,
        }
    ])
    out = await wh.list_webhooks(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 1
    assert out["webhooks"][0]["trigger_count"] == 7


@pytest.mark.asyncio
async def test_list_webhooks_filter(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json=[])
    await wh.list_webhooks(direction="outbound", tenant_id="t", ctx=mock_ctx)
    assert client.calls[0]["params"]["direction"] == "outbound"


@pytest.mark.asyncio
async def test_list_webhooks_api_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await wh.list_webhooks(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# delete_webhook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_webhook_happy(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={})
    out = await wh.delete_webhook(webhook_id="w-1", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "deleted"


@pytest.mark.asyncio
async def test_delete_webhook_404(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=404, default_json={})
    out = await wh.delete_webhook(webhook_id="w-x", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"]


# ---------------------------------------------------------------------------
# test_webhook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_webhook_invalid_payload(mock_ctx):
    out = await wh.test_webhook(
        webhook_id="w-1", test_payload="not-json", tenant_id="t", ctx=mock_ctx
    )
    assert "valid JSON" in out["error"]


@pytest.mark.asyncio
async def test_test_webhook_success(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"delivered": True})
    out = await wh.test_webhook(
        webhook_id="w-1", test_payload='{"a": 1}', tenant_id="t", ctx=mock_ctx
    )
    assert out["delivered"] is True


@pytest.mark.asyncio
async def test_test_webhook_404(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=404, default_json={})
    out = await wh.test_webhook(webhook_id="w-x", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"]


# ---------------------------------------------------------------------------
# send_webhook_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_webhook_event_invalid_payload(mock_ctx):
    out = await wh.send_webhook_event(
        event_type="x", payload="not-json", tenant_id="t", ctx=mock_ctx
    )
    assert "valid JSON" in out["error"]


@pytest.mark.asyncio
async def test_send_webhook_event_happy(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json={"delivered_count": 3})
    out = await wh.send_webhook_event(
        event_type="entity.created", payload='{"id": 1}',
        tenant_id="t", ctx=mock_ctx,
    )
    assert out == {"delivered_count": 3}
    assert client.calls[0]["json"] == {"event_type": "entity.created", "payload": {"id": 1}}


@pytest.mark.asyncio
async def test_send_webhook_event_api_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await wh.send_webhook_event(
        event_type="x", payload="{}", tenant_id="t", ctx=mock_ctx
    )
    assert "Failed to fire" in out["error"]


# ---------------------------------------------------------------------------
# get_webhook_logs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_webhook_logs_returns_normalized(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json=[{
        "id": "l-1", "direction": "outbound", "event_type": "x",
        "success": True, "response_status": 200,
        "duration_ms": 50, "created_at": "now",
    }])
    out = await wh.get_webhook_logs(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 1


@pytest.mark.asyncio
async def test_get_webhook_logs_per_webhook(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json=[])
    await wh.get_webhook_logs(webhook_id="w-1", tenant_id="t", ctx=mock_ctx)
    assert "/w-1/logs" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_get_webhook_logs_api_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await wh.get_webhook_logs(tenant_id="t", ctx=mock_ctx)
    assert "error" in out
