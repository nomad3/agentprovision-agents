"""Tests for src.mcp_tools.devices.

Four tools that read from ``device_registry`` via a shared asyncpg
pool helper. We stub ``_get_pool`` (imported lazily inside each tool)
to inject a recording connection.
"""
from __future__ import annotations

import json

import pytest

from src.mcp_tools import devices as dev
from src.mcp_tools import knowledge as kn


class _FakeConn:
    def __init__(self, fetch_rows=None, fetchrow_row=None):
        self.fetch_rows = fetch_rows or []
        self.fetchrow_row = fetchrow_row
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self.fetch_rows

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self.fetchrow_row


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


def _patch_pool(monkeypatch, conn):
    fake_pool = _FakePool(conn)

    async def _get_pool():
        return fake_pool

    monkeypatch.setattr(kn, "_get_pool", _get_pool)


# ---------------------------------------------------------------------------
# Required-tenant guards
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool,kwargs",
    [
        (dev.list_connected_devices, {}),
        (dev.get_device_status, {"device_id": "d-1"}),
        (dev.get_device_config, {"device_id": "d-1"}),
        (dev.capture_camera_snapshot, {"device_id": "d-1"}),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_requires_tenant(tool, kwargs, mock_ctx):
    out = await tool(tenant_id="", ctx=mock_ctx, **kwargs)
    assert "error" in out


# ---------------------------------------------------------------------------
# list_connected_devices
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_connected_devices_returns_rows(monkeypatch, mock_ctx):
    rows = [
        {
            "device_id": "d-1",
            "device_name": "Camera 1",
            "device_type": "camera",
            "status": "online",
            "last_heartbeat": "2026-05-03",
        }
    ]
    _patch_pool(monkeypatch, _FakeConn(fetch_rows=rows))

    out = await dev.list_connected_devices(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 1
    assert out["devices"][0]["device_id"] == "d-1"


# ---------------------------------------------------------------------------
# get_device_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_device_status_not_found(monkeypatch, mock_ctx):
    _patch_pool(monkeypatch, _FakeConn(fetchrow_row=None))
    out = await dev.get_device_status(device_id="d-x", tenant_id="t", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_get_device_status_returns_dict(monkeypatch, mock_ctx):
    _patch_pool(
        monkeypatch,
        _FakeConn(fetchrow_row={
            "device_id": "d-1",
            "device_name": "Cam",
            "device_type": "camera",
            "status": "online",
        }),
    )
    out = await dev.get_device_status(device_id="d-1", tenant_id="t", ctx=mock_ctx)
    assert out["device_id"] == "d-1"


# ---------------------------------------------------------------------------
# get_device_config
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_device_config_handles_string_config(monkeypatch, mock_ctx):
    _patch_pool(
        monkeypatch,
        _FakeConn(fetchrow_row={"device_id": "d-1", "config": json.dumps({"a": 1})}),
    )
    out = await dev.get_device_config(device_id="d-1", tenant_id="t", ctx=mock_ctx)
    assert out["config"] == {"a": 1}


@pytest.mark.asyncio
async def test_get_device_config_handles_dict_config(monkeypatch, mock_ctx):
    _patch_pool(
        monkeypatch,
        _FakeConn(fetchrow_row={"device_id": "d-1", "config": {"a": 1}}),
    )
    out = await dev.get_device_config(device_id="d-1", tenant_id="t", ctx=mock_ctx)
    assert out["config"] == {"a": 1}


@pytest.mark.asyncio
async def test_get_device_config_not_found(monkeypatch, mock_ctx):
    _patch_pool(monkeypatch, _FakeConn(fetchrow_row=None))
    out = await dev.get_device_config(device_id="d-x", tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# capture_camera_snapshot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capture_camera_snapshot_requires_internal_key(monkeypatch, mock_ctx):
    monkeypatch.delenv("API_INTERNAL_KEY", raising=False)
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    out = await dev.capture_camera_snapshot(device_id="d-1", tenant_id="t", ctx=mock_ctx)
    assert "API_INTERNAL_KEY" in out["error"]


@pytest.mark.asyncio
async def test_capture_camera_snapshot_camera_not_found(monkeypatch, mock_ctx):
    monkeypatch.setenv("API_INTERNAL_KEY", "key")
    _patch_pool(monkeypatch, _FakeConn(fetchrow_row=None))
    out = await dev.capture_camera_snapshot(device_id="d-x", tenant_id="t", ctx=mock_ctx)
    assert "Camera not found" in out["error"]


@pytest.mark.asyncio
async def test_capture_camera_snapshot_missing_bridge_token(monkeypatch, mock_ctx):
    monkeypatch.setenv("API_INTERNAL_KEY", "key")
    _patch_pool(
        monkeypatch,
        _FakeConn(fetchrow_row={
            "device_id": "d-1",
            "config": {"bridge_url": "http://b"},
        }),
    )
    monkeypatch.delenv("DEVICE_BRIDGE_TOKEN", raising=False)
    out = await dev.capture_camera_snapshot(device_id="d-1", tenant_id="t", ctx=mock_ctx)
    assert "bridge token" in out["error"]


@pytest.mark.asyncio
async def test_capture_camera_snapshot_happy(monkeypatch, mock_ctx):
    monkeypatch.setenv("API_INTERNAL_KEY", "key")
    _patch_pool(
        monkeypatch,
        _FakeConn(fetchrow_row={
            "device_id": "d-1",
            "config": {"bridge_url": "http://b", "bridge_token": "tok"},
        }),
    )

    from tests.conftest import _DummyResponse, DummyHttpxClient  # type: ignore

    responses = {
        ("POST", "http://b/cameras/d-1/snapshot"): _DummyResponse(
            200, {"image_b64": "abc", "timestamp": "now"}
        ),
    }
    # second POST goes to vision API — handled by default
    client = DummyHttpxClient(responses=responses, default=_DummyResponse(200, {}))

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client, raising=False)
    # devices imports httpx lazily inside the tool; the module-level
    # ``import httpx`` inside the function uses the real httpx, so we
    # also need to monkeypatch httpx in src.mcp_tools.devices once it's
    # imported. Easiest: patch httpx at the module level globally.
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: client)

    out = await dev.capture_camera_snapshot(device_id="d-1", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"


@pytest.mark.asyncio
async def test_capture_camera_snapshot_bridge_error(monkeypatch, mock_ctx):
    monkeypatch.setenv("API_INTERNAL_KEY", "key")
    _patch_pool(
        monkeypatch,
        _FakeConn(fetchrow_row={
            "device_id": "d-1",
            "config": {"bridge_url": "http://b", "bridge_token": "tok"},
        }),
    )
    from tests.conftest import _DummyResponse, DummyHttpxClient  # type: ignore
    client = DummyHttpxClient(default=_DummyResponse(500, text="boom"))
    import httpx
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: client)

    out = await dev.capture_camera_snapshot(device_id="d-1", tenant_id="t", ctx=mock_ctx)
    assert "error" in out
