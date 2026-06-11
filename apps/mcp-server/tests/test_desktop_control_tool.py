"""Tests for Luna desktop-control MCP tools."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.mcp_tools import desktop_control as dc


def _ctx_with_user(user_id: str = "22222222-2222-2222-2222-222222222222"):
    return SimpleNamespace(request_context={"X-User-Id": user_id})


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(side_effect=None, default_status=201, default_json=None):
        client = make_client(
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        monkeypatch.setattr(dc.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


@pytest.mark.asyncio
async def test_desktop_observe_screen_posts_display_safe_request(patch_httpx):
    client = patch_httpx(
        default_json={
            "status": "denied",
            "desktop_event_id": "66666666-6666-6666-6666-666666666666",
            "session_event_id": "session-event-2",
            "session_seq_no": 8,
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "action": "capture_screenshot",
            "capability": "screenshot",
            "reason": "desktop observation down-channel unavailable; capture_screenshot request denied",
            "down_channel_available": False,
        },
    )

    out = await dc.desktop_observe_screen(
        session_id="33333333-3333-3333-3333-333333333333",
        shell_id="desktop-44444444-4444-4444-4444-444444444444",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "denied"
    assert out["action"] == "capture_screenshot"
    assert out["capability"] == "screenshot"
    assert out["down_channel_available"] is False
    assert "screenshot" not in out
    assert "clipboard_text" not in out
    assert "down-channel" in out["message"]
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/desktop-control/internal/observations/request")
    assert call["json"] == {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "action": "capture_screenshot",
        "tool_name": "desktop_observe_screen",
    }
    assert call["headers"]["X-Tenant-Id"] == "11111111-1111-1111-1111-111111111111"
    assert call["headers"]["X-User-Id"] == "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_desktop_read_clipboard_omits_empty_shell_id(patch_httpx):
    client = patch_httpx(
        default_json={
            "status": "denied",
            "desktop_event_id": "66666666-6666-6666-6666-666666666666",
            "session_event_id": None,
            "session_seq_no": None,
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "action": "read_clipboard",
            "capability": "clipboard_read",
            "reason": "desktop observation down-channel unavailable; read_clipboard request denied",
            "down_channel_available": False,
        },
    )

    out = await dc.desktop_read_clipboard(
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "denied"
    assert out["action"] == "read_clipboard"
    assert "shell_id" not in client.calls[0]["json"]


@pytest.mark.asyncio
async def test_desktop_background_app_control_dry_run_posts_command(patch_httpx):
    client = patch_httpx(
        default_json={
            "desktop_command_id": "99999999-9999-9999-9999-999999999999",
            "desktop_event_id": "66666666-6666-6666-6666-666666666666",
            "session_event_id": "session-event-background",
            "session_seq_no": 13,
            "status": "pending",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "device_id": "88888888-8888-8888-8888-888888888888",
            "approval_id": None,
            "capability": "background_control",
            "lease_expires_at": None,
            "payload": {
                "action": "background_app_control_dry_run",
                "mode": "background_control_dry_run",
                "dry_run": {"native_envelope": False},
            },
            "idempotent": False,
        },
    )

    out = await dc.desktop_background_app_control_dry_run(
        session_id="33333333-3333-3333-3333-333333333333",
        bundle_id="com.example.LunaCanaryTarget",
        shell_id="desktop-44444444-4444-4444-4444-444444444444",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "pending"
    assert out["capability"] == "background_control"
    assert "native macOS actuation" in out["message"]
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/desktop-control/internal/commands")
    assert call["json"] == {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "action": "background_app_control_dry_run",
        "tool_name": "desktop_background_app_control_dry_run",
        "payload": {
            "target": {
                "bundle_id": "com.example.LunaCanaryTarget",
                "action": "background_app_control_dry_run",
            },
            "dry_run": True,
        },
    }


@pytest.mark.asyncio
async def test_desktop_tools_require_tenant():
    out = await dc.desktop_get_active_app(
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="",
        ctx=_ctx_with_user(),
    )

    assert out == {"status": "error", "error": "tenant_id required"}


@pytest.mark.asyncio
async def test_desktop_tools_require_user_header(patch_httpx):
    client = patch_httpx()

    out = await dc.desktop_get_active_app(
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=None,
    )

    assert out["status"] == "error"
    assert "X-User-Id required" in out["error"]
    assert client.calls == []


@pytest.mark.asyncio
async def test_desktop_tools_surface_shell_unavailable(patch_httpx):
    patch_httpx(default_status=409, default_json={}, side_effect=None)

    out = await dc.desktop_observe_screen(
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "error"
    assert "desktop shell unavailable" in out["error"]


@pytest.mark.asyncio
async def test_desktop_tools_transport_error_returns_error(monkeypatch):
    import httpx

    class _RaisingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("api unreachable")

    monkeypatch.setattr(dc.httpx, "AsyncClient", lambda *a, **kw: _RaisingClient())

    out = await dc.desktop_observe_screen(
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "error"
    assert "transport" in out["error"]
