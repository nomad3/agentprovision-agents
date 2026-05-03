"""Tests for src.mcp_tools.copilot_studio.

Wraps the Microsoft Bot Framework Direct Line API. Mock the httpx.AsyncClient
context manager to avoid live HTTP calls.
"""
from __future__ import annotations

import asyncio
import pytest

from src.mcp_tools import copilot_studio as cs


class _DummyResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _DummyClient:
    """Records all calls and returns canned responses by URL substring."""

    def __init__(self, by_url):
        self.by_url = by_url
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        for key, resp in self.by_url.items():
            if key in url:
                return resp
        return _DummyResp(200, {})

    async def get(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        for key, resp in self.by_url.items():
            if key in url:
                return resp
        return _DummyResp(200, {})


@pytest.mark.asyncio
async def test_client_start_conversation_returns_id(monkeypatch):
    client = _DummyClient({"/conversations": _DummyResp(200, {"conversationId": "c-1"})})
    monkeypatch.setattr(cs.httpx, "AsyncClient", lambda *a, **kw: client)

    csc = cs.CopilotStudioClient(token="t", bot_id="b-1")
    cid = await csc.start_conversation()
    assert cid == "c-1"
    assert client.calls[0]["headers"]["Authorization"] == "Bearer t"


@pytest.mark.asyncio
async def test_client_send_message_returns_activity_id(monkeypatch):
    client = _DummyClient({
        "/activities": _DummyResp(200, {"id": "a-99"}),
    })
    monkeypatch.setattr(cs.httpx, "AsyncClient", lambda *a, **kw: client)

    csc = cs.CopilotStudioClient(token="t", bot_id="b-1")
    out = await csc.send_message("c-1", "hello")
    assert out == "a-99"
    activity = client.calls[0]["json"]
    assert activity["text"] == "hello"
    assert activity["type"] == "message"


@pytest.mark.asyncio
async def test_client_get_activities_appends_watermark(monkeypatch):
    client = _DummyClient({
        "/activities": _DummyResp(200, {"activities": []}),
    })
    monkeypatch.setattr(cs.httpx, "AsyncClient", lambda *a, **kw: client)

    csc = cs.CopilotStudioClient(token="t", bot_id="b-1")
    await csc.get_activities("c-1", watermark="42")
    assert "watermark=42" in client.calls[0]["url"]


# ---------------------------------------------------------------------------
# manage_copilot_studio_agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manage_start_returns_conversation_id(monkeypatch):
    client = _DummyClient({"/conversations": _DummyResp(200, {"conversationId": "c-1"})})
    monkeypatch.setattr(cs.httpx, "AsyncClient", lambda *a, **kw: client)

    out = await cs.manage_copilot_studio_agent(
        tenant_id="t", bot_id="b", token="tok", action="start"
    )
    assert out == {"status": "success", "conversation_id": "c-1"}


@pytest.mark.asyncio
async def test_manage_send_requires_conversation_and_message():
    out = await cs.manage_copilot_studio_agent(
        tenant_id="t", bot_id="b", token="tok", action="send",
        message=None, conversation_id=None,
    )
    assert out["status"] == "error"


@pytest.mark.asyncio
async def test_manage_unknown_action_returns_error():
    out = await cs.manage_copilot_studio_agent(
        tenant_id="t", bot_id="b", token="tok", action="weird"
    )
    assert out["status"] == "error"


@pytest.mark.asyncio
async def test_manage_send_collects_bot_responses(monkeypatch):
    """Send a message, then poll activities. Bot reply with from.id == bot_id
    is captured in responses; the polling loop short-circuits as soon as
    a response is found."""
    activities_payload = {
        "activities": [
            {"type": "message", "from": {"id": "user-x"}, "text": "echo"},
            {"type": "message", "from": {"id": "b-1"}, "text": "Hello human!"},
        ],
        "id": "send-1",
    }

    client = _DummyClient({
        "/activities": _DummyResp(200, activities_payload),
    })
    # The send_message call will hit /activities (POST) first, then GETs.
    # Stub asyncio.sleep to a no-op so the test is fast.
    async def _no_sleep(*a, **kw):
        return None

    monkeypatch.setattr(cs.httpx, "AsyncClient", lambda *a, **kw: client)
    # asyncio is imported lazily inside the function; patch the
    # real asyncio.sleep so the polling loop returns immediately.
    import asyncio as real_asyncio
    monkeypatch.setattr(real_asyncio, "sleep", _no_sleep)

    out = await cs.manage_copilot_studio_agent(
        tenant_id="t", bot_id="b-1", token="tok", action="send",
        message="hi", conversation_id="c-1",
    )

    assert out["status"] == "success"
    assert "Hello human!" in out["responses"]


@pytest.mark.asyncio
async def test_manage_send_handles_exception(monkeypatch):
    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("network down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(cs.httpx, "AsyncClient", lambda *a, **kw: _Boom())
    out = await cs.manage_copilot_studio_agent(
        tenant_id="t", bot_id="b", token="tok", action="start"
    )
    assert out["status"] == "error"
