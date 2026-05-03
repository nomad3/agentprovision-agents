"""Tests for src.mcp_tools.agent_messaging — A2A handoff tools."""
from __future__ import annotations

import pytest

from src.mcp_tools import agent_messaging as am


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None):
        client = make_client(default_status=default_status, default_json=default_json)
        monkeypatch.setattr(am.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# delegate_to_agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delegate_validates_recipient(mock_ctx):
    out = await am.delegate_to_agent(
        recipient_agent_id="", task="x", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_delegate_validates_task(mock_ctx):
    out = await am.delegate_to_agent(
        recipient_agent_id="a", task="   ", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_delegate_requires_tenant(mock_ctx):
    out = await am.delegate_to_agent(
        recipient_agent_id="a", task="x", tenant_id="", ctx=mock_ctx
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_delegate_happy(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json={
        "run_id": "r-1",
        "recipient_agent_id": "a",
        "recipient_name": "Sales",
    })
    out = await am.delegate_to_agent(
        recipient_agent_id="a",
        task="grade lead",
        reason="qualifying",
        chat_session_id="cs-1",
        tenant_id="t",
        ctx=mock_ctx,
    )
    assert out["status"] == "success"
    assert out["run_id"] == "r-1"
    body = client.calls[0]["json"]
    assert body["recipient_agent_id"] == "a"
    assert body["chat_session_id"] == "cs-1"


@pytest.mark.asyncio
async def test_delegate_propagates_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await am.delegate_to_agent(
        recipient_agent_id="a", task="x", tenant_id="t", ctx=mock_ctx
    )
    assert "delegate failed" in out["error"]


# ---------------------------------------------------------------------------
# read_handoff_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_handoff_status_validates(mock_ctx):
    assert "error" in await am.read_handoff_status(run_id="", tenant_id="t", ctx=mock_ctx)
    assert "error" in await am.read_handoff_status(run_id="r-1", tenant_id="", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_read_handoff_status_404(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=404, default_json={})
    out = await am.read_handoff_status(run_id="r-x", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"]


@pytest.mark.asyncio
async def test_read_handoff_status_happy(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={
        "status": "completed", "reply": "ok", "completed_at": "now",
    })
    out = await am.read_handoff_status(run_id="r-1", tenant_id="t", ctx=mock_ctx)
    # The tool spreads resp.json() over the dict — payload "status" key
    # overwrites the wrapper's "success" sentinel.
    assert out["status"] == "completed"
    assert out["reply"] == "ok"


@pytest.mark.asyncio
async def test_read_handoff_status_other_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await am.read_handoff_status(run_id="r-1", tenant_id="t", ctx=mock_ctx)
    assert "status check failed" in out["error"]


# ---------------------------------------------------------------------------
# find_agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_agent_validates(mock_ctx):
    assert "error" in await am.find_agent(capability="", tenant_id="t", ctx=mock_ctx)
    assert "error" in await am.find_agent(capability="x", tenant_id="", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_find_agent_passes_kind_filter(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json=[])
    await am.find_agent(capability="lead-scoring", kind="native", tenant_id="t", ctx=mock_ctx)
    assert client.calls[0]["params"]["kind"] == "native"


@pytest.mark.asyncio
async def test_find_agent_ignores_invalid_kind(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json=[])
    await am.find_agent(capability="x", kind="weird", tenant_id="t", ctx=mock_ctx)
    assert "kind" not in client.calls[0]["params"]


@pytest.mark.asyncio
async def test_find_agent_happy(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json=[{"id": "a-1", "name": "Sales"}])
    out = await am.find_agent(capability="lead-scoring", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["results"][0]["id"] == "a-1"


@pytest.mark.asyncio
async def test_find_agent_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await am.find_agent(capability="x", tenant_id="t", ctx=mock_ctx)
    assert "discover failed" in out["error"]
