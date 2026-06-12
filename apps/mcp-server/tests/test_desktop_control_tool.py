"""Tests for Luna desktop-control MCP tools."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.mcp_tools import desktop_control as dc


def _ctx_with_user(user_id: str = "22222222-2222-2222-2222-222222222222"):
    return SimpleNamespace(request_context={"X-User-Id": user_id})


def test_desktop_control_module_exports_registered_tools():
    expected_tools = {
        "desktop_observe_screen",
        "desktop_get_active_app",
        "desktop_read_clipboard",
        "desktop_fetch_observation",
        "desktop_background_app_control_dry_run",
        "desktop_command_status",
        "desktop_stop_commands",
        "desktop_request_grant",
        "desktop_request_status",
        "desktop_actuate",
    }

    assert expected_tools.issubset(set(dc.__all__))
    for tool_name in expected_tools:
        assert hasattr(dc, tool_name)


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
            "desktop_command_id": "99999999-9999-9999-9999-999999999999",
            "desktop_event_id": "66666666-6666-6666-6666-666666666666",
            "session_event_id": "session-event-2",
            "session_seq_no": 8,
            "status": "pending",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "device_id": "88888888-8888-8888-8888-888888888888",
            "approval_id": None,
            "capability": "screenshot",
            "lease_expires_at": None,
            "payload": {
                "action": "capture_screenshot",
                "tool_name": "desktop_observe_screen",
                "mode": "observe",
                "request": {},
            },
            "idempotent": False,
        },
    )

    out = await dc.desktop_observe_screen(
        session_id="33333333-3333-3333-3333-333333333333",
        grant_id="55555555-5555-5555-5555-555555555555",
        shell_id="desktop-44444444-4444-4444-4444-444444444444",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "pending"
    assert out["payload"]["action"] == "capture_screenshot"
    assert out["capability"] == "screenshot"
    assert "screenshot" not in out
    assert "clipboard_text" not in out
    assert "down-channel" in out["message"]
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/desktop-control/internal/commands")
    assert call["json"] == {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "action": "capture_screenshot",
        "tool_name": "desktop_observe_screen",
        "approval_id": "55555555-5555-5555-5555-555555555555",
    }
    assert call["headers"]["X-Tenant-Id"] == "11111111-1111-1111-1111-111111111111"
    assert call["headers"]["X-User-Id"] == "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_desktop_observe_screen_requires_grant_before_queue(patch_httpx):
    client = patch_httpx(default_json={"unreached": True})

    out = await dc.desktop_observe_screen(
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "approval_required"
    assert out["command_id"] is None
    assert "desktop_request_grant" in out["message"]
    assert client.calls == []


@pytest.mark.asyncio
async def test_desktop_observe_screen_rejects_invalid_grant_id(patch_httpx):
    client = patch_httpx(default_json={"unreached": True})

    out = await dc.desktop_observe_screen(
        session_id="33333333-3333-3333-3333-333333333333",
        grant_id="../../oauth/internal/token/github",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out == {"status": "error", "error": "grant_id must be a UUID"}
    assert client.calls == []


@pytest.mark.asyncio
async def test_desktop_read_clipboard_omits_empty_shell_id(patch_httpx):
    client = patch_httpx(
        default_json={
            "desktop_command_id": "99999999-9999-9999-9999-999999999999",
            "desktop_event_id": "66666666-6666-6666-6666-666666666666",
            "session_event_id": None,
            "session_seq_no": None,
            "status": "pending",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "device_id": "88888888-8888-8888-8888-888888888888",
            "approval_id": None,
            "capability": "clipboard_read",
            "lease_expires_at": None,
            "payload": {
                "action": "read_clipboard",
                "tool_name": "desktop_read_clipboard",
                "mode": "observe",
                "request": {},
            },
            "idempotent": False,
        },
    )

    out = await dc.desktop_read_clipboard(
        session_id="33333333-3333-3333-3333-333333333333",
        grant_id="55555555-5555-5555-5555-555555555555",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "pending"
    assert out["payload"]["action"] == "read_clipboard"
    assert "shell_id" not in client.calls[0]["json"]
    assert client.calls[0]["json"]["approval_id"] == "55555555-5555-5555-5555-555555555555"


@pytest.mark.asyncio
async def test_desktop_get_active_app_queues_observe_command(patch_httpx):
    client = patch_httpx(
        default_json={
            "desktop_command_id": "99999999-9999-9999-9999-999999999999",
            "desktop_event_id": "66666666-6666-6666-6666-666666666666",
            "session_event_id": "session-event-active-app",
            "session_seq_no": 10,
            "status": "pending",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "device_id": "88888888-8888-8888-8888-888888888888",
            "approval_id": None,
            "capability": "active_app",
            "lease_expires_at": None,
            "payload": {
                "action": "get_active_app",
                "tool_name": "desktop_get_active_app",
                "mode": "observe",
                "request": {},
            },
            "idempotent": False,
        },
    )

    out = await dc.desktop_get_active_app(
        session_id="33333333-3333-3333-3333-333333333333",
        grant_id="55555555-5555-5555-5555-555555555555",
        shell_id="desktop-44444444-4444-4444-4444-444444444444",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "pending"
    assert out["capability"] == "active_app"
    assert out["payload"]["action"] == "get_active_app"
    assert "app" not in out
    assert "title" not in out
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/desktop-control/internal/commands")
    assert call["json"] == {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "action": "get_active_app",
        "tool_name": "desktop_get_active_app",
        "approval_id": "55555555-5555-5555-5555-555555555555",
    }


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
async def test_desktop_command_status_gets_display_safe_audit(patch_httpx):
    client = patch_httpx(
        default_status=200,
        default_json={
            "command": {
                "desktop_command_id": "99999999-9999-9999-9999-999999999999",
                "action": "background_app_control_dry_run",
                "tool_name": "desktop_background_app_control_dry_run",
                "status": "no_op",
                "capability": "background_control",
                "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            },
            "events": [
                {
                    "desktop_event_id": "66666666-6666-6666-6666-666666666666",
                    "event_type": "desktop_command_completed",
                    "outcome": "no_op",
                    "metadata": {"dry_run": True, "native_envelope": False},
                },
            ],
            "terminal": True,
        },
    )

    out = await dc.desktop_command_status(
        command_id="99999999-9999-9999-9999-999999999999",
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["terminal"] is True
    assert out["command"]["status"] == "no_op"
    assert "payload" not in out["command"]
    assert "Raw command payloads" in out["message"]
    call = client.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith(
        "/api/v1/desktop-control/internal/commands/99999999-9999-9999-9999-999999999999/status"
    )
    assert call["params"] == {"session_id": "33333333-3333-3333-3333-333333333333"}
    assert call["headers"]["X-Tenant-Id"] == "11111111-1111-1111-1111-111111111111"
    assert call["headers"]["X-User-Id"] == "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_desktop_command_status_requires_user_header(patch_httpx):
    client = patch_httpx()

    out = await dc.desktop_command_status(
        command_id="99999999-9999-9999-9999-999999999999",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=None,
    )

    assert out["status"] == "error"
    assert "X-User-Id required" in out["error"]
    assert client.calls == []


@pytest.mark.asyncio
async def test_desktop_command_status_surfaces_not_found(patch_httpx):
    patch_httpx(default_status=404, default_json={})

    out = await dc.desktop_command_status(
        command_id="99999999-9999-9999-9999-999999999999",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out == {"status": "error", "error": "desktop command not found"}


@pytest.mark.asyncio
async def test_desktop_stop_commands_posts_preempt_request(patch_httpx):
    client = patch_httpx(
        default_status=200,
        default_json={
            "status": "preempted",
            "preempted_count": 2,
            "desktop_event_ids": [
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            ],
        },
    )

    out = await dc.desktop_stop_commands(
        session_id="33333333-3333-3333-3333-333333333333",
        shell_id="desktop-44444444-4444-4444-4444-444444444444",
        reason="agent Stop",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "preempted"
    assert out["preempted_count"] == 2
    assert "screen bytes" in out["message"]
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/desktop-control/internal/commands/stop")
    assert call["json"] == {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "reason": "agent Stop",
    }
    assert call["headers"]["X-Tenant-Id"] == "11111111-1111-1111-1111-111111111111"
    assert call["headers"]["X-User-Id"] == "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_desktop_stop_commands_requires_user_header(patch_httpx):
    client = patch_httpx()

    out = await dc.desktop_stop_commands(
        session_id="33333333-3333-3333-3333-333333333333",
        shell_id="desktop-44444444-4444-4444-4444-444444444444",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=None,
    )

    assert out["status"] == "error"
    assert "X-User-Id required" in out["error"]
    assert client.calls == []


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
        grant_id="55555555-5555-5555-5555-555555555555",
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
        grant_id="55555555-5555-5555-5555-555555555555",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "error"
    assert "transport" in out["error"]


# ── P5.3b: desktop_fetch_observation (planner-safe redacted delivery) ─────────


@pytest.mark.asyncio
async def test_desktop_fetch_observation_delivers_planner_safe_payload(patch_httpx):
    client = patch_httpx(
        default_status=200,
        default_json={
            "artifact_id": "77777777-7777-7777-7777-777777777777",
            "session_id": "33333333-3333-3333-3333-333333333333",
            "redaction_status": "planner_safe",
            "size_bytes": 42,
            "sha256": "ab" * 32,
            "expires_at": "2026-06-11T13:00:00+00:00",
            "content_base64": "aGVsbG8=",
        },
    )

    out = await dc.desktop_fetch_observation(
        artifact_id="77777777-7777-7777-7777-777777777777",
        session_id="33333333-3333-3333-3333-333333333333",
        shell_id="desktop-44444444-4444-4444-4444-444444444444",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["redaction_status"] == "planner_safe"
    assert out["content_base64"] == "aGVsbG8="
    assert "planner-safe" in out["message"].lower()
    # no raw-content fields can appear in the envelope
    assert "screenshot" not in out
    assert "storage_path" not in out
    assert "ocr_text" not in out

    call = client.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith(
        "/api/v1/desktop-control/internal/observations/"
        "77777777-7777-7777-7777-777777777777/content"
    )
    assert call["params"] == {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
    }
    assert call["headers"]["X-Tenant-Id"] == "11111111-1111-1111-1111-111111111111"
    assert call["headers"]["X-User-Id"] == "22222222-2222-2222-2222-222222222222"
    assert call["headers"]["X-Internal-Key"]


@pytest.mark.asyncio
async def test_desktop_fetch_observation_requires_tenant():
    out = await dc.desktop_fetch_observation(
        artifact_id="77777777-7777-7777-7777-777777777777",
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="",
        ctx=_ctx_with_user(),
    )

    assert out == {"status": "error", "error": "tenant_id required"}


@pytest.mark.asyncio
async def test_desktop_fetch_observation_requires_user():
    out = await dc.desktop_fetch_observation(
        artifact_id="77777777-7777-7777-7777-777777777777",
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=SimpleNamespace(request_context={}),
    )

    assert out["status"] == "error"
    assert "X-User-Id required" in out["error"]


@pytest.mark.asyncio
async def test_desktop_fetch_observation_surfaces_display_safe_denial(patch_httpx):
    patch_httpx(
        default_status=409,
        default_json={
            "detail": {
                "code": "artifact_not_planner_safe",
                "reason": "perception artifact is not planner-safe",
            }
        },
    )

    out = await dc.desktop_fetch_observation(
        artifact_id="77777777-7777-7777-7777-777777777777",
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "denied"
    assert out["code"] == "artifact_not_planner_safe"
    assert "content_base64" not in out


@pytest.mark.asyncio
async def test_desktop_fetch_observation_omits_empty_shell_id(patch_httpx):
    client = patch_httpx(
        default_status=200,
        default_json={
            "artifact_id": "77777777-7777-7777-7777-777777777777",
            "session_id": "33333333-3333-3333-3333-333333333333",
            "redaction_status": "planner_safe",
            "size_bytes": 42,
            "sha256": "ab" * 32,
            "expires_at": "2026-06-11T13:00:00+00:00",
            "content_base64": "aGVsbG8=",
        },
    )

    await dc.desktop_fetch_observation(
        artifact_id="77777777-7777-7777-7777-777777777777",
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert client.calls[0]["params"] == {
        "session_id": "33333333-3333-3333-3333-333333333333",
    }


# ── SSRF / path-traversal hardening: agent-supplied ids must be UUIDs ─────────


@pytest.mark.asyncio
async def test_fetch_observation_rejects_traversal_artifact_id(patch_httpx):
    client = patch_httpx(default_status=200, default_json={"unreached": True})

    out = await dc.desktop_fetch_observation(
        artifact_id="../../../oauth/internal/token/github?x=",
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    # Rejected BEFORE any HTTP call — no internal-key request is ever issued, so
    # the traversal cannot retarget another /internal/* endpoint.
    assert out == {"status": "error", "error": "artifact_id must be a UUID"}
    assert client.calls == []


@pytest.mark.asyncio
async def test_command_status_rejects_traversal_command_id(patch_httpx):
    client = patch_httpx(default_status=200, default_json={"unreached": True})

    out = await dc.desktop_command_status(
        command_id="../../oauth/internal/token/github",
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out == {"status": "error", "error": "command_id must be a UUID"}
    assert client.calls == []


@pytest.mark.asyncio
async def test_fetch_observation_canonicalizes_uuid_into_url(patch_httpx):
    # A valid (upper/mixed-case) UUID is canonicalized; the URL only ever
    # contains the canonical lower-case UUID, never raw caller input.
    client = patch_httpx(
        default_status=200,
        default_json={
            "artifact_id": "77777777-7777-7777-7777-777777777777",
            "session_id": "33333333-3333-3333-3333-333333333333",
            "redaction_status": "planner_safe",
            "size_bytes": 42,
            "sha256": "ab" * 32,
            "expires_at": "2026-06-11T13:00:00+00:00",
            "content_base64": "aGVsbG8=",
        },
    )

    await dc.desktop_fetch_observation(
        artifact_id="77777777-7777-7777-7777-777777777777".upper(),
        session_id="33333333-3333-3333-3333-333333333333",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert client.calls[0]["url"].endswith(
        "/api/v1/desktop-control/internal/observations/"
        "77777777-7777-7777-7777-777777777777/content"
    )


# ── P5.4b: desktop_request_grant / desktop_request_status (pending approval) ──


@pytest.mark.asyncio
async def test_desktop_request_grant_posts_reduced_request(patch_httpx):
    client = patch_httpx(
        default_status=201,
        default_json={
            "request_id": "55555555-5555-5555-5555-555555555555",
            "session_id": "33333333-3333-3333-3333-333333333333",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "action": "keyboard_type",
            "capability": "keyboard_control",
            "status": "pending",
            "target_bundle_id": "net.whatsapp.WhatsApp",
            "grant_present": False,
        },
    )

    out = await dc.desktop_request_grant(
        session_id="33333333-3333-3333-3333-333333333333",
        action="keyboard_type",
        target_bundle_id="net.whatsapp.WhatsApp",
        shell_id="desktop-44444444-4444-4444-4444-444444444444",
        reason="send a message",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "pending"
    assert out["capability"] == "keyboard_control"
    assert out["grant_present"] is False
    assert "human must approve" in out["message"]
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/desktop-control/internal/grants/request")
    assert call["json"] == {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "action": "keyboard_type",
        "target_bundle_id": "net.whatsapp.WhatsApp",
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "reason": "send a message",
    }
    assert call["headers"]["X-Tenant-Id"] == "11111111-1111-1111-1111-111111111111"
    assert call["headers"]["X-User-Id"] == "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_desktop_request_grant_posts_observe_request_without_target(patch_httpx):
    client = patch_httpx(
        default_status=201,
        default_json={
            "request_id": "55555555-5555-5555-5555-555555555555",
            "session_id": "33333333-3333-3333-3333-333333333333",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "action": "capture_screenshot",
            "capability": "screenshot",
            "status": "pending",
            "target_bundle_id": None,
            "grant_present": False,
        },
    )

    out = await dc.desktop_request_grant(
        session_id="33333333-3333-3333-3333-333333333333",
        action="capture_screenshot",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "pending"
    assert out["capability"] == "screenshot"
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/desktop-control/internal/grants/request")
    assert call["json"] == {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "action": "capture_screenshot",
    }


@pytest.mark.asyncio
async def test_desktop_request_grant_rejects_unrequestable_action(patch_httpx):
    client = patch_httpx(default_status=201, default_json={"unreached": True})

    out = await dc.desktop_request_grant(
        session_id="33333333-3333-3333-3333-333333333333",
        action="background_app_control_dry_run",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    # Rejected client-side before any HTTP call — dry-run never needs a grant.
    assert out["status"] == "error"
    assert "pointer_move" in out["error"]
    assert client.calls == []


@pytest.mark.asyncio
async def test_desktop_request_grant_requires_tenant_and_user():
    out_no_tenant = await dc.desktop_request_grant(
        session_id="33333333-3333-3333-3333-333333333333",
        action="keyboard_type",
        target_bundle_id="net.whatsapp.WhatsApp",
        tenant_id="",
        ctx=_ctx_with_user(),
    )
    assert out_no_tenant == {"status": "error", "error": "tenant_id required"}

    out_no_user = await dc.desktop_request_grant(
        session_id="33333333-3333-3333-3333-333333333333",
        action="keyboard_type",
        target_bundle_id="net.whatsapp.WhatsApp",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=SimpleNamespace(request_context={}),
    )
    assert out_no_user["status"] == "error"
    assert "X-User-Id required" in out_no_user["error"]


@pytest.mark.asyncio
async def test_desktop_request_grant_surfaces_display_safe_denial(patch_httpx):
    patch_httpx(
        default_status=422,
        default_json={
            "detail": {
                "code": "action_not_requestable",
                "reason": "action is not a grant-requestable native-control action",
            }
        },
    )

    out = await dc.desktop_request_grant(
        session_id="33333333-3333-3333-3333-333333333333",
        action="keyboard_type",
        target_bundle_id="net.whatsapp.WhatsApp",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )
    assert out["status"] == "denied"
    assert out["code"] == "action_not_requestable"


@pytest.mark.asyncio
async def test_desktop_request_status_validates_uuid(patch_httpx):
    client = patch_httpx(default_status=200, default_json={"unreached": True})

    out = await dc.desktop_request_status(
        request_id="../../oauth/internal/token/github",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    # Rejected before any HTTP call — no internal-key request can be retargeted.
    assert out == {"status": "error", "error": "request_id must be a UUID"}
    assert client.calls == []


@pytest.mark.asyncio
async def test_desktop_request_status_polls_pending(patch_httpx):
    client = patch_httpx(
        default_status=200,
        default_json={
            "request_id": "55555555-5555-5555-5555-555555555555",
            "session_id": "33333333-3333-3333-3333-333333333333",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "action": "keyboard_type",
            "capability": "keyboard_control",
            "status": "pending",
            "grant_present": False,
        },
    )

    out = await dc.desktop_request_status(
        request_id="55555555-5555-5555-5555-555555555555",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "pending"
    call = client.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith(
        "/api/v1/desktop-control/internal/grants/requests/"
        "55555555-5555-5555-5555-555555555555"
    )


# ── P5.4b: desktop_actuate (grant-gated act; never mints) ────────────────────


@pytest.mark.asyncio
async def test_desktop_actuate_posts_to_internal_actuate(patch_httpx):
    client = patch_httpx(
        default_status=200,
        default_json={
            "status": "queued",
            "command_id": "99999999-9999-9999-9999-999999999999",
            "command_status": "pending",
            "action": "keyboard_type",
            "capability": "keyboard_control",
            "approval_id": "55555555-5555-5555-5555-555555555555",
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "target_bundle_id": "net.whatsapp.WhatsApp",
        },
    )

    out = await dc.desktop_actuate(
        session_id="33333333-3333-3333-3333-333333333333",
        grant_id="55555555-5555-5555-5555-555555555555",
        args={"text": "hello"},
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )

    assert out["status"] == "queued"
    assert out["approval_id"] == "55555555-5555-5555-5555-555555555555"
    assert "never mints" in out["message"]
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/desktop-control/internal/commands/actuate")
    assert call["json"] == {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "grant_id": "55555555-5555-5555-5555-555555555555",
        "args": {"text": "hello"},
    }
    assert call["headers"]["X-Tenant-Id"] == "11111111-1111-1111-1111-111111111111"
    assert call["headers"]["X-User-Id"] == "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_desktop_actuate_surfaces_approval_required(patch_httpx):
    patch_httpx(
        default_status=200,
        default_json={"status": "approval_required", "command_id": None},
    )

    out = await dc.desktop_actuate(
        session_id="33333333-3333-3333-3333-333333333333",
        grant_id="55555555-5555-5555-5555-555555555555",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )
    assert out["status"] == "approval_required"
    assert out["command_id"] is None


@pytest.mark.asyncio
async def test_desktop_actuate_validates_grant_uuid(patch_httpx):
    client = patch_httpx(default_status=200, default_json={"unreached": True})

    out = await dc.desktop_actuate(
        session_id="33333333-3333-3333-3333-333333333333",
        grant_id="../../oauth/internal/token/github",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )
    assert out == {"status": "error", "error": "grant_id must be a UUID"}
    assert client.calls == []


@pytest.mark.asyncio
async def test_desktop_actuate_surfaces_display_safe_denial(patch_httpx):
    patch_httpx(
        default_status=409,
        default_json={
            "detail": {"code": "approval_revoked", "reason": "approval grant revoked"}
        },
    )

    out = await dc.desktop_actuate(
        session_id="33333333-3333-3333-3333-333333333333",
        grant_id="55555555-5555-5555-5555-555555555555",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=_ctx_with_user(),
    )
    assert out["status"] == "denied"
    assert out["code"] == "approval_revoked"


@pytest.mark.asyncio
async def test_desktop_actuate_requires_tenant_and_user():
    out_no_tenant = await dc.desktop_actuate(
        session_id="33333333-3333-3333-3333-333333333333",
        grant_id="55555555-5555-5555-5555-555555555555",
        tenant_id="",
        ctx=_ctx_with_user(),
    )
    assert out_no_tenant == {"status": "error", "error": "tenant_id required"}

    out_no_user = await dc.desktop_actuate(
        session_id="33333333-3333-3333-3333-333333333333",
        grant_id="55555555-5555-5555-5555-555555555555",
        tenant_id="11111111-1111-1111-1111-111111111111",
        ctx=SimpleNamespace(request_context={}),
    )
    assert out_no_user["status"] == "error"
    assert "X-User-Id required" in out_no_user["error"]
