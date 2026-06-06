"""Luna desktop-control MCP tools.

Phase 1 registers read-only observation tools but does not execute desktop
capture from the server side. The tools call the API control plane, which
records a tenant/user/session/shell-scoped, display-safe audit event and fails
closed until the Tauri command down-channel ships.
"""
from __future__ import annotations

import logging
import os

import httpx
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id, resolve_user_id

logger = logging.getLogger(__name__)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")
API_INTERNAL_KEY = os.environ.get("MCP_API_KEY", "dev_mcp_key")

_TOOL_ACTIONS = {
    "desktop_observe_screen": "capture_screenshot",
    "desktop_get_active_app": "get_active_app",
    "desktop_read_clipboard": "read_clipboard",
}


async def _request_observation(
    *,
    tool_name: str,
    session_id: str,
    shell_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    tid = resolve_tenant_id(ctx, tenant_id)
    if not tid:
        return {"status": "error", "error": "tenant_id required"}

    user_id = resolve_user_id(ctx)
    if not user_id:
        return {"status": "error", "error": "X-User-Id required for desktop observation"}

    body = {
        "session_id": session_id,
        "action": _TOOL_ACTIONS[tool_name],
        "tool_name": tool_name,
    }
    if shell_id:
        body["shell_id"] = shell_id

    headers = {
        "X-Internal-Key": API_INTERNAL_KEY,
        "X-Tenant-Id": tid,
        "X-User-Id": user_id,
    }
    url = f"{API_BASE_URL}/api/v1/desktop-control/internal/observations/request"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        logger.warning(
            "%s: HTTP transport error session=%s err=%s",
            tool_name,
            session_id,
            exc,
        )
        return {"status": "error", "error": f"transport: {exc}"}

    if resp.status_code == 201:
        payload = resp.json()
        return {
            **payload,
            "message": (
                "Observation was recorded by the desktop-control control plane. "
                "Live content capture is disabled until the Luna Tauri command "
                "down-channel ships."
            ),
        }
    if resp.status_code == 401:
        return {"status": "error", "error": "invalid internal key"}
    if resp.status_code == 404:
        return {"status": "error", "error": "session not found"}
    if resp.status_code == 409:
        return {"status": "error", "error": f"desktop shell unavailable: {resp.text[:200]}"}
    if resp.status_code in (400, 422):
        return {"status": "error", "error": f"bad request: {resp.text[:200]}"}
    return {"status": "error", "error": f"upstream {resp.status_code}: {resp.text[:200]}"}


@mcp.tool()
async def desktop_observe_screen(
    session_id: str,
    shell_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Request a governed screen observation for a Luna chat session.

    Returns an audit/result envelope, not screenshot pixels. Live content
    delivery remains blocked until the Tauri command down-channel is in place.
    """
    return await _request_observation(
        tool_name="desktop_observe_screen",
        session_id=session_id,
        shell_id=shell_id,
        tenant_id=tenant_id,
        ctx=ctx,
    )


@mcp.tool()
async def desktop_get_active_app(
    session_id: str,
    shell_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Request a governed active-app/window observation for a Luna session.

    Returns an audit/result envelope, not app names or window titles, until the
    Tauri command down-channel can return sanitized observation results.
    """
    return await _request_observation(
        tool_name="desktop_get_active_app",
        session_id=session_id,
        shell_id=shell_id,
        tenant_id=tenant_id,
        ctx=ctx,
    )


@mcp.tool()
async def desktop_read_clipboard(
    session_id: str,
    shell_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Request a governed clipboard-read observation for a Luna session.

    Returns an audit/result envelope only. Raw clipboard text is never returned
    by this Phase 1 MCP tool.
    """
    return await _request_observation(
        tool_name="desktop_read_clipboard",
        session_id=session_id,
        shell_id=shell_id,
        tenant_id=tenant_id,
        ctx=ctx,
    )


__all__ = [
    "desktop_observe_screen",
    "desktop_get_active_app",
    "desktop_read_clipboard",
]
