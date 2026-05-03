"""Tests for src.mcp_tools.calendar.

Two tools backed by httpx + Google Calendar v3.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import calendar as cal


@pytest.fixture
def patch_oauth(monkeypatch):
    def _install(token="oauth-tok"):
        async def _get(*a, **kw):
            return token

        monkeypatch.setattr(cal, "_get_oauth_token", _get)
        return token

    return _install


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None, side_effect=None):
        client = make_client(
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        monkeypatch.setattr(cal.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


@pytest.mark.asyncio
async def test_list_calendar_events_no_token(monkeypatch, mock_ctx):
    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(cal, "_get_oauth_token", _none)
    out = await cal.list_calendar_events(tenant_id="t", ctx=mock_ctx)
    assert "not connected" in out["error"]


@pytest.mark.asyncio
async def test_list_calendar_events_happy(patch_oauth, patch_httpx, mock_ctx):
    patch_oauth()
    patch_httpx(default_status=200, default_json={
        "items": [
            {
                "id": "ev-1",
                "summary": "Standup",
                "start": {"dateTime": "2026-05-04T09:00:00Z"},
                "end": {"dateTime": "2026-05-04T09:30:00Z"},
                "attendees": [{"email": "a@x"}],
            },
            {
                "id": "ev-2",
                "summary": "All-day",
                "start": {"date": "2026-05-05"},
                "end": {"date": "2026-05-06"},
            },
        ]
    })
    out = await cal.list_calendar_events(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 2
    assert out["events"][0]["summary"] == "Standup"
    assert out["events"][1]["start"] == "2026-05-05"


@pytest.mark.asyncio
async def test_list_calendar_events_token_expired(patch_oauth, monkeypatch, mock_ctx):
    patch_oauth()
    import httpx as real

    class _Resp:
        def __init__(self, status):
            self.status_code = status
            self.text = "expired"

        def json(self):
            return {}

        def raise_for_status(self):
            req = real.Request("GET", "http://x")
            raise real.HTTPStatusError("401", request=req, response=real.Response(401, request=req))

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return _Resp(401)

    monkeypatch.setattr(cal.httpx, "AsyncClient", lambda *a, **kw: _Client())
    out = await cal.list_calendar_events(tenant_id="t", ctx=mock_ctx)
    assert "expired" in out["error"]


@pytest.mark.asyncio
async def test_list_calendar_events_handles_unexpected(monkeypatch, patch_oauth, mock_ctx):
    patch_oauth()

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("net")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(cal.httpx, "AsyncClient", lambda *a, **kw: _Boom())
    out = await cal.list_calendar_events(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# create_calendar_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_calendar_event_validates_required(mock_ctx):
    out = await cal.create_calendar_event(
        summary="", start_time="x", end_time="y", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_create_calendar_event_no_token(monkeypatch, mock_ctx):
    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(cal, "_get_oauth_token", _none)
    out = await cal.create_calendar_event(
        summary="Lunch", start_time="2026-05-04T12:00:00Z",
        end_time="2026-05-04T13:00:00Z", tenant_id="t", ctx=mock_ctx,
    )
    assert "not connected" in out["error"]


@pytest.mark.asyncio
async def test_create_calendar_event_happy(patch_oauth, patch_httpx, mock_ctx):
    patch_oauth()
    client = patch_httpx(default_status=200, default_json={
        "id": "ev-100",
        "summary": "Lunch",
        "start": {"dateTime": "2026-05-04T12:00:00Z"},
        "end": {"dateTime": "2026-05-04T13:00:00Z"},
        "htmlLink": "http://x",
    })

    out = await cal.create_calendar_event(
        summary="Lunch",
        start_time="2026-05-04T12:00:00Z",
        end_time="2026-05-04T13:00:00Z",
        attendees="a@x.com, b@x.com",
        description="lunchtime",
        tenant_id="t",
        ctx=mock_ctx,
    )
    assert out["status"] == "success"
    assert out["event_id"] == "ev-100"
    sent = client.calls[0]["json"]
    assert sent["summary"] == "Lunch"
    assert len(sent["attendees"]) == 2


@pytest.mark.asyncio
async def test_create_calendar_event_token_expired(patch_oauth, monkeypatch, mock_ctx):
    patch_oauth()
    import httpx as real

    class _Resp:
        def __init__(self, s):
            self.status_code = s
            self.text = ""

        def json(self):
            return {}

        def raise_for_status(self):
            req = real.Request("POST", "http://x")
            raise real.HTTPStatusError("401", request=req, response=real.Response(401, request=req))

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _Resp(401)

    monkeypatch.setattr(cal.httpx, "AsyncClient", lambda *a, **kw: _Client())
    out = await cal.create_calendar_event(
        summary="x", start_time="t", end_time="t2", tenant_id="t", ctx=mock_ctx,
    )
    assert "expired" in out["error"]
