"""Tests for src.mcp_tools.sms — Twilio SMS tools.

We assert that:
  - send_sms / list_sms_threads / read_sms validate their inputs and refuse
    to call the API without tenant_id / required fields
  - On a happy POST, send_sms forwards the API response unchanged
  - The MCP layer never tries to talk to Twilio directly — every outbound
    request is to the API at /api/v1/integrations/twilio/internal/...
"""
from __future__ import annotations

import pytest

from src.mcp_tools import sms


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None):
        client = make_client(default_status=default_status, default_json=default_json or {})
        monkeypatch.setattr(sms.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# send_sms
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_sms_requires_tenant_id(mock_ctx):
    out = await sms.send_sms(to="+15551234567", body="hi", tenant_id="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_send_sms_requires_to_and_body(mock_ctx):
    assert "error" in await sms.send_sms(to="", body="hi", tenant_id="t", ctx=mock_ctx)
    assert "error" in await sms.send_sms(to="+1", body="", tenant_id="t", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_send_sms_happy_calls_internal_endpoint(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(
        default_status=200,
        default_json={
            "status": "sent",
            "message_sid": "SM123",
            "to": "+15551234567",
            "from": "+17145551234",
        },
    )
    out = await sms.send_sms(
        to="+15551234567", body="hello",
        tenant_id="00000000-0000-0000-0000-000000000001",
        ctx=mock_ctx,
    )
    assert out["status"] == "sent"
    assert out["message_sid"] == "SM123"

    # Verify it called the API's /internal/send, NOT Twilio directly
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/integrations/twilio/internal/send")
    assert "twilio.com" not in call["url"]  # never bypass the API
    # The internal key header is set
    assert call["headers"]["X-Internal-Key"] == "test-mcp-key"
    # The body forwards tenant_id, to, body
    assert call["json"]["tenant_id"] == "00000000-0000-0000-0000-000000000001"
    assert call["json"]["to"] == "+15551234567"
    assert call["json"]["body"] == "hello"


@pytest.mark.asyncio
async def test_send_sms_propagates_api_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=400, default_json={"detail": "twilio_sms not configured for tenant"})
    out = await sms.send_sms(
        to="+15551234567", body="x", tenant_id="t-1", ctx=mock_ctx,
    )
    assert "error" in out
    assert "not configured" in out["error"]


# ---------------------------------------------------------------------------
# list_sms_threads
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_sms_threads_requires_tenant(mock_ctx):
    out = await sms.list_sms_threads(tenant_id="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_list_sms_threads_happy(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(
        default_status=200,
        default_json={
            "threads": [
                {"id": "s-1", "title": "SMS: +15551234567", "remote_number": "+15551234567"},
            ],
        },
    )
    out = await sms.list_sms_threads(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 1
    assert out["threads"][0]["id"] == "s-1"
    call = client.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith("/api/v1/integrations/twilio/internal/threads")


# ---------------------------------------------------------------------------
# read_sms
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_sms_requires_thread_id(mock_ctx):
    out = await sms.read_sms(thread_id="", tenant_id="t", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_read_sms_happy(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(
        default_status=200,
        default_json={
            "thread": {"id": "s-1", "remote_number": "+15551234567"},
            "messages": [
                {"role": "user", "content": "hi", "created_at": "2026-05-09T10:00:00"},
                {"role": "assistant", "content": "hello!", "created_at": "2026-05-09T10:00:01"},
            ],
        },
    )
    out = await sms.read_sms(thread_id="s-1", tenant_id="t", ctx=mock_ctx)
    assert len(out["messages"]) == 2
    assert out["thread"]["remote_number"] == "+15551234567"
    call = client.calls[0]
    assert call["url"].endswith("/api/v1/integrations/twilio/internal/thread/s-1")
