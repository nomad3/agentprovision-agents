"""Tests for src.mcp_tools.monitor.

Eight tools controlling the inbox monitor, competitor monitor, and
autonomous learning workflows. Each is a thin httpx wrapper around an
internal /api/v1/workflows/* endpoint.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import monitor as mon


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None, side_effect=None):
        client = make_client(
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        monkeypatch.setattr(mon.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# Required-tenant guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool",
    [
        mon.start_inbox_monitor,
        mon.stop_inbox_monitor,
        mon.check_inbox_monitor_status,
        mon.start_competitor_monitor,
        mon.stop_competitor_monitor,
        mon.start_autonomous_learning,
        mon.stop_autonomous_learning,
        mon.check_autonomous_learning_status,
        mon.check_competitor_monitor_status,
    ],
)
@pytest.mark.asyncio
async def test_each_tool_requires_tenant_id(tool, mock_ctx):
    out = await tool(tenant_id="", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# Inbox monitor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_inbox_monitor_started(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json={"status": "started"})
    out = await mon.start_inbox_monitor(tenant_id="t", interval_minutes=10, ctx=mock_ctx)
    assert out["status"] == "started"
    assert out["interval_minutes"] == 10
    assert client.calls[0]["params"]["check_interval_minutes"] == 10


@pytest.mark.asyncio
async def test_start_inbox_monitor_already_active(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"status": "already_running"})
    out = await mon.start_inbox_monitor(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "already_active"


@pytest.mark.asyncio
async def test_start_inbox_monitor_http_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500)
    out = await mon.start_inbox_monitor(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_stop_inbox_monitor_paths(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"status": "not_running"})
    assert (await mon.stop_inbox_monitor(tenant_id="t", ctx=mock_ctx))["status"] == "not_running"

    patch_httpx(default_status=200, default_json={"status": "stopped"})
    assert (await mon.stop_inbox_monitor(tenant_id="t", ctx=mock_ctx))["status"] == "stopped"

    patch_httpx(default_status=500)
    assert "error" in await mon.stop_inbox_monitor(tenant_id="t", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_check_inbox_monitor_status_paths(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"running": True, "start_time": "2026-05-03"})
    out = await mon.check_inbox_monitor_status(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "active"

    patch_httpx(default_status=200, default_json={"running": False})
    out2 = await mon.check_inbox_monitor_status(tenant_id="t", ctx=mock_ctx)
    assert out2["status"] == "inactive"

    patch_httpx(default_status=500)
    assert "error" in await mon.check_inbox_monitor_status(tenant_id="t", ctx=mock_ctx)


# ---------------------------------------------------------------------------
# Competitor monitor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_competitor_monitor_passthrough(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json={"workflow_id": "wf-1"})
    out = await mon.start_competitor_monitor(tenant_id="t", check_interval_hours=12, ctx=mock_ctx)
    assert out["workflow_id"] == "wf-1"
    body = client.calls[0]["json"]
    assert body["check_interval_seconds"] == 12 * 3600


@pytest.mark.asyncio
async def test_start_competitor_monitor_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await mon.start_competitor_monitor(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_stop_competitor_monitor_passthrough(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"status": "stopped"})
    out = await mon.stop_competitor_monitor(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "stopped"

    patch_httpx(default_status=500)
    assert "error" in await mon.stop_competitor_monitor(tenant_id="t", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_check_competitor_monitor_status_running(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"running": True})
    out = await mon.check_competitor_monitor_status(tenant_id="t", ctx=mock_ctx)
    assert out["running"] is True


@pytest.mark.asyncio
async def test_check_competitor_monitor_status_not_running(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=404)
    out = await mon.check_competitor_monitor_status(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "not_running"


# ---------------------------------------------------------------------------
# Autonomous learning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_autonomous_learning_started(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"workflow_id": "alw-1"})
    out = await mon.start_autonomous_learning(tenant_id="t", cycle_interval_hours=6, ctx=mock_ctx)
    assert out["status"] == "started"
    assert out["interval_hours"] == 6


@pytest.mark.asyncio
async def test_start_autonomous_learning_already_running(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"status": "already_running"})
    out = await mon.start_autonomous_learning(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "already_active"


@pytest.mark.asyncio
async def test_start_autonomous_learning_http_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await mon.start_autonomous_learning(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_stop_autonomous_learning_passthrough(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"status": "stopped"})
    out = await mon.stop_autonomous_learning(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "stopped"

    patch_httpx(default_status=500)
    assert "error" in await mon.stop_autonomous_learning(tenant_id="t", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_check_autonomous_learning_status_running(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"running": True, "workflow_id": "alw-2"})
    out = await mon.check_autonomous_learning_status(tenant_id="t", ctx=mock_ctx)
    assert out["running"] is True
    assert out["workflow_id"] == "alw-2"
    assert "active" in out["message"]


@pytest.mark.asyncio
async def test_check_autonomous_learning_status_not_running(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"running": False})
    out = await mon.check_autonomous_learning_status(tenant_id="t", ctx=mock_ctx)
    assert out["running"] is False
    assert "not running" in out["message"]


@pytest.mark.asyncio
async def test_check_autonomous_learning_status_404(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=404)
    out = await mon.check_autonomous_learning_status(tenant_id="t", ctx=mock_ctx)
    assert out["running"] is False
