"""Luna desktop-control MCP tools.

The observe tools enqueue display-safe commands through the API-to-Luna
down-channel. The Tauri app claims and completes those commands locally; MCP
responses expose command/audit envelopes only, never raw pixels, app titles, or
clipboard text.
"""
from __future__ import annotations

import logging
import os
import uuid

import httpx
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id, resolve_user_id

logger = logging.getLogger(__name__)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")
API_INTERNAL_KEY = os.environ.get("MCP_API_KEY", "dev_mcp_key")


def _validate_uuid(value: str, field: str) -> str | None:
    """Return the canonical UUID string for ``value`` or None if it is not a
    UUID. Agent-supplied ids are interpolated into internal-key-bearing API
    URLs; a raw value containing path separators / ``..`` could otherwise
    retarget the request at another ``/internal/*`` endpoint (httpx normalizes
    dot segments). Pinning to a canonical UUID removes every traversal char."""
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        logger.warning("desktop-control: rejected non-UUID %s", field)
        return None

_TOOL_ACTIONS = {
    "desktop_observe_screen": "capture_screenshot",
    "desktop_get_active_app": "get_active_app",
    "desktop_read_clipboard": "read_clipboard",
    "desktop_background_app_control_dry_run": "background_app_control_dry_run",
}


async def _enqueue_observation_command(
    *,
    tool_name: str,
    session_id: str,
    grant_id: str = "",
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

    safe_grant_id = _validate_uuid(grant_id, "grant_id") if grant_id else None
    if grant_id and not safe_grant_id:
        return {"status": "error", "error": "grant_id must be a UUID"}
    if not safe_grant_id:
        return {
            "status": "approval_required",
            "command_id": None,
            "message": (
                "Observation requires an approved observe grant. Call "
                "`desktop_request_grant` for `capture_screenshot`, "
                "`get_active_app`, or `read_clipboard`, wait for a human-approved "
                "`grant_id`, then retry this observation tool with that grant."
            ),
        }

    body = {
        "session_id": session_id,
        "action": _TOOL_ACTIONS[tool_name],
        "tool_name": tool_name,
        "approval_id": safe_grant_id,
    }
    if shell_id:
        body["shell_id"] = shell_id

    headers = {
        "X-Internal-Key": API_INTERNAL_KEY,
        "X-Tenant-Id": tid,
        "X-User-Id": user_id,
    }
    url = f"{API_BASE_URL}/api/v1/desktop-control/internal/commands"

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
                "Observation command was queued for the Luna Tauri down-channel "
                "using an approved observe grant. "
                "Results remain display-safe: raw screen bytes, clipboard text, "
                "app names, and window titles are not returned by this MCP tool."
            ),
        }
    if resp.status_code == 401:
        return {"status": "error", "error": "invalid internal key"}
    if resp.status_code == 403:
        return {"status": "error", "error": f"desktop observation denied: {resp.text[:200]}"}
    if resp.status_code == 404:
        return {"status": "error", "error": "session not found"}
    if resp.status_code == 409:
        return {"status": "error", "error": f"desktop shell unavailable: {resp.text[:200]}"}
    if resp.status_code in (400, 422):
        return {"status": "error", "error": f"bad request: {resp.text[:200]}"}
    return {"status": "error", "error": f"upstream {resp.status_code}: {resp.text[:200]}"}


async def _enqueue_background_dry_run(
    *,
    session_id: str,
    bundle_id: str,
    shell_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    tid = resolve_tenant_id(ctx, tenant_id)
    if not tid:
        return {"status": "error", "error": "tenant_id required"}

    user_id = resolve_user_id(ctx)
    if not user_id:
        return {"status": "error", "error": "X-User-Id required for desktop control"}

    action = _TOOL_ACTIONS["desktop_background_app_control_dry_run"]
    body = {
        "session_id": session_id,
        "action": action,
        "tool_name": "desktop_background_app_control_dry_run",
        "payload": {
            "target": {
                "bundle_id": bundle_id,
                "action": action,
            },
            "dry_run": True,
        },
    }
    if shell_id:
        body["shell_id"] = shell_id

    headers = {
        "X-Internal-Key": API_INTERNAL_KEY,
        "X-Tenant-Id": tid,
        "X-User-Id": user_id,
    }
    url = f"{API_BASE_URL}/api/v1/desktop-control/internal/commands"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        logger.warning(
            "desktop_background_app_control_dry_run: HTTP transport error session=%s err=%s",
            session_id,
            exc,
        )
        return {"status": "error", "error": f"transport: {exc}"}

    if resp.status_code == 201:
        payload = resp.json()
        return {
            **payload,
            "message": (
                "Background app-control dry-run was queued. No native macOS "
                "actuation or signed native envelope is issued by this tool."
            ),
        }
    if resp.status_code == 401:
        return {"status": "error", "error": "invalid internal key"}
    if resp.status_code == 403:
        return {"status": "error", "error": f"desktop control denied: {resp.text[:200]}"}
    if resp.status_code == 404:
        return {"status": "error", "error": "session not found"}
    if resp.status_code == 409:
        return {"status": "error", "error": f"desktop shell unavailable: {resp.text[:200]}"}
    if resp.status_code in (400, 422):
        return {"status": "error", "error": f"bad request: {resp.text[:200]}"}
    return {"status": "error", "error": f"upstream {resp.status_code}: {resp.text[:200]}"}


async def _get_command_status(
    *,
    command_id: str,
    session_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    tid = resolve_tenant_id(ctx, tenant_id)
    if not tid:
        return {"status": "error", "error": "tenant_id required"}

    user_id = resolve_user_id(ctx)
    if not user_id:
        return {"status": "error", "error": "X-User-Id required for desktop control"}

    safe_command_id = _validate_uuid(command_id, "command_id")
    if not safe_command_id:
        return {"status": "error", "error": "command_id must be a UUID"}

    headers = {
        "X-Internal-Key": API_INTERNAL_KEY,
        "X-Tenant-Id": tid,
        "X-User-Id": user_id,
    }
    params = {"session_id": session_id} if session_id else None
    url = f"{API_BASE_URL}/api/v1/desktop-control/internal/commands/{safe_command_id}/status"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=headers)
    except httpx.RequestError as exc:
        logger.warning(
            "desktop_command_status: HTTP transport error command=%s err=%s",
            command_id,
            exc,
        )
        return {"status": "error", "error": f"transport: {exc}"}

    if resp.status_code == 200:
        payload = resp.json()
        return {
            **payload,
            "message": (
                "Desktop command status is display-safe. Raw command payloads, "
                "screen bytes, clipboard text, signed envelopes, and actuation "
                "args are not returned."
            ),
        }
    if resp.status_code == 401:
        return {"status": "error", "error": "invalid internal key"}
    if resp.status_code == 404:
        return {"status": "error", "error": "desktop command not found"}
    if resp.status_code in (400, 422):
        return {"status": "error", "error": f"bad request: {resp.text[:200]}"}
    return {"status": "error", "error": f"upstream {resp.status_code}: {resp.text[:200]}"}


async def _stop_commands(
    *,
    session_id: str,
    shell_id: str,
    reason: str = "desktop control stopped",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    tid = resolve_tenant_id(ctx, tenant_id)
    if not tid:
        return {"status": "error", "error": "tenant_id required"}

    user_id = resolve_user_id(ctx)
    if not user_id:
        return {"status": "error", "error": "X-User-Id required for desktop control"}

    body = {
        "session_id": session_id,
        "shell_id": shell_id,
        "reason": reason,
    }
    headers = {
        "X-Internal-Key": API_INTERNAL_KEY,
        "X-Tenant-Id": tid,
        "X-User-Id": user_id,
    }
    url = f"{API_BASE_URL}/api/v1/desktop-control/internal/commands/stop"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        logger.warning(
            "desktop_stop_commands: HTTP transport error session=%s err=%s",
            session_id,
            exc,
        )
        return {"status": "error", "error": f"transport: {exc}"}

    if resp.status_code == 200:
        payload = resp.json()
        return {
            **payload,
            "message": (
                "Desktop work was stopped for this session/shell. This safety "
                "tool revokes active grants and preempts queued/running commands; "
                "it never returns command payloads, screen bytes, signed envelopes, "
                "or native actuation args."
            ),
        }
    if resp.status_code == 401:
        return {"status": "error", "error": "invalid internal key"}
    if resp.status_code == 403:
        return {"status": "error", "error": f"desktop stop denied: {resp.text[:200]}"}
    if resp.status_code == 404:
        return {"status": "error", "error": "session or user not found"}
    if resp.status_code == 409:
        return {"status": "error", "error": f"desktop shell unavailable: {resp.text[:200]}"}
    if resp.status_code in (400, 422):
        return {"status": "error", "error": f"bad request: {resp.text[:200]}"}
    return {"status": "error", "error": f"upstream {resp.status_code}: {resp.text[:200]}"}


@mcp.tool()
async def desktop_observe_screen(
    session_id: str,
    grant_id: str = "",
    shell_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Request a governed screen observation for a Luna chat session.

    Queues a Tauri-claimed command and returns an audit/result envelope, not
    screenshot pixels.
    """
    return await _enqueue_observation_command(
        tool_name="desktop_observe_screen",
        session_id=session_id,
        grant_id=grant_id,
        shell_id=shell_id,
        tenant_id=tenant_id,
        ctx=ctx,
    )


@mcp.tool()
async def desktop_get_active_app(
    session_id: str,
    grant_id: str = "",
    shell_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Request a governed active-app/window observation for a Luna session.

    Queues a Tauri-claimed command and returns an audit/result envelope, not app
    names or window titles.
    """
    return await _enqueue_observation_command(
        tool_name="desktop_get_active_app",
        session_id=session_id,
        grant_id=grant_id,
        shell_id=shell_id,
        tenant_id=tenant_id,
        ctx=ctx,
    )


@mcp.tool()
async def desktop_read_clipboard(
    session_id: str,
    grant_id: str = "",
    shell_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Request a governed clipboard-read observation for a Luna session.

    Queues a Tauri-claimed command and returns an audit/result envelope only.
    Raw clipboard text is never returned by this MCP tool.
    """
    return await _enqueue_observation_command(
        tool_name="desktop_read_clipboard",
        session_id=session_id,
        grant_id=grant_id,
        shell_id=shell_id,
        tenant_id=tenant_id,
        ctx=ctx,
    )


@mcp.tool()
async def desktop_background_app_control_dry_run(
    session_id: str,
    bundle_id: str,
    shell_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Queue a governed background app-control dry-run command.

    The command enters the same API-to-Luna down-channel as native desktop
    control, but claim completes as `no_op`: no native macOS actuation, no raw
    screen/app bytes, and no signed native envelope.
    """
    return await _enqueue_background_dry_run(
        session_id=session_id,
        bundle_id=bundle_id,
        shell_id=shell_id,
        tenant_id=tenant_id,
        ctx=ctx,
    )


async def _fetch_observation(
    *,
    artifact_id: str,
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

    safe_artifact_id = _validate_uuid(artifact_id, "artifact_id")
    if not safe_artifact_id:
        return {"status": "error", "error": "artifact_id must be a UUID"}

    headers = {
        "X-Internal-Key": API_INTERNAL_KEY,
        "X-Tenant-Id": tid,
        "X-User-Id": user_id,
    }
    params = {"session_id": session_id}
    if shell_id:
        params["shell_id"] = shell_id
    url = (
        f"{API_BASE_URL}/api/v1/desktop-control/internal/observations/"
        f"{safe_artifact_id}/content"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params, headers=headers)
    except httpx.RequestError as exc:
        logger.warning(
            "desktop_fetch_observation: HTTP transport error artifact=%s err=%s",
            artifact_id,
            exc,
        )
        return {"status": "error", "error": f"transport: {exc}"}

    if resp.status_code == 200:
        payload = resp.json()
        return {
            **payload,
            "message": (
                "Planner-safe redacted observation delivered. `content_base64` "
                "is the reviewed redacted PNG; raw capture bytes were hard-"
                "deleted before this artifact became fetchable."
            ),
        }
    if resp.status_code == 401:
        return {"status": "error", "error": "invalid internal key"}
    if resp.status_code in (403, 404, 409, 410):
        # Display-safe structured denial from the delivery service
        # ({"detail": {"code": ..., "reason": ...}}) — surface it as-is.
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, dict) and "code" in detail:
            return {"status": "denied", **detail}
        return {"status": "error", "error": f"denied {resp.status_code}: {resp.text[:200]}"}
    if resp.status_code in (400, 422):
        return {"status": "error", "error": f"bad request: {resp.text[:200]}"}
    return {"status": "error", "error": f"upstream {resp.status_code}: {resp.text[:200]}"}


@mcp.tool()
async def desktop_fetch_observation(
    artifact_id: str,
    session_id: str,
    shell_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Fetch the planner-safe REDACTED content of a perception artifact.

    Delivery is fail-closed: the API serves only the redacted derivative of an
    artifact whose raw bytes were already hard-deleted (`redaction_status ==
    planner_safe` and `raw_deleted_at` set), scoped to this tenant/session and
    re-checked against the master desktop-control flag. Raw screenshots, paths,
    OCR text, window titles, and clipboard content are never returned.
    """
    return await _fetch_observation(
        artifact_id=artifact_id,
        session_id=session_id,
        shell_id=shell_id,
        tenant_id=tenant_id,
        ctx=ctx,
    )


@mcp.tool()
async def desktop_command_status(
    command_id: str,
    session_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Read a display-safe audit/status summary for a desktop command.

    This is a read-only reporting tool. It never returns raw command payloads,
    screen bytes, clipboard text, signed envelopes, or native actuation args.
    """
    return await _get_command_status(
        command_id=command_id,
        session_id=session_id,
        tenant_id=tenant_id,
        ctx=ctx,
    )


@mcp.tool()
async def desktop_stop_commands(
    session_id: str,
    shell_id: str,
    reason: str = "desktop control stopped",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Stop queued/running desktop work for one Luna session and shell.

    This is a safety/preemption tool, not an actuator. It revokes active
    approval grants and preempts pending/claimed/running commands without
    returning raw command payloads, screen bytes, signed envelopes, or native
    actuation args.
    """
    return await _stop_commands(
        session_id=session_id,
        shell_id=shell_id,
        reason=reason,
        tenant_id=tenant_id,
        ctx=ctx,
    )


_REQUESTABLE_ACTIONS = {
    "capture_screenshot",
    "get_active_app",
    "read_clipboard",
    "pointer_move",
    "pointer_click",
    "keyboard_type",
    "keyboard_key_chord",
}


async def _request_grant(
    *,
    session_id: str,
    action: str,
    target_bundle_id: str = "",
    shell_id: str = "",
    reason: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    tid = resolve_tenant_id(ctx, tenant_id)
    if not tid:
        return {"status": "error", "error": "tenant_id required"}

    user_id = resolve_user_id(ctx)
    if not user_id:
        return {"status": "error", "error": "X-User-Id required for desktop control"}

    if action not in _REQUESTABLE_ACTIONS:
        return {
            "status": "error",
            "error": "action must be one of: " + ", ".join(sorted(_REQUESTABLE_ACTIONS)),
        }

    body = {
        "session_id": session_id,
        "action": action,
    }
    if target_bundle_id:
        body["target_bundle_id"] = target_bundle_id
    if shell_id:
        body["shell_id"] = shell_id
    if reason:
        body["reason"] = reason

    headers = {
        "X-Internal-Key": API_INTERNAL_KEY,
        "X-Tenant-Id": tid,
        "X-User-Id": user_id,
    }
    url = f"{API_BASE_URL}/api/v1/desktop-control/internal/grants/request"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        logger.warning(
            "desktop_request_grant: HTTP transport error session=%s err=%s",
            session_id,
            exc,
        )
        return {"status": "error", "error": f"transport: {exc}"}

    if resp.status_code == 201:
        payload = resp.json()
        return {
            **payload,
            "message": (
                "Pending desktop approval request recorded. No native actuation "
                "happens and no approval grant is created — a human must approve "
                "this request before any action can run."
            ),
        }
    if resp.status_code == 401:
        return {"status": "error", "error": "invalid internal key"}
    if resp.status_code in (403, 404, 409, 422):
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, dict) and "code" in detail:
            return {"status": "denied", **detail}
        return {"status": "error", "error": f"denied {resp.status_code}: {resp.text[:200]}"}
    if resp.status_code == 400:
        return {"status": "error", "error": f"bad request: {resp.text[:200]}"}
    return {"status": "error", "error": f"upstream {resp.status_code}: {resp.text[:200]}"}


async def _request_status(
    *,
    request_id: str,
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    tid = resolve_tenant_id(ctx, tenant_id)
    if not tid:
        return {"status": "error", "error": "tenant_id required"}

    user_id = resolve_user_id(ctx)
    if not user_id:
        return {"status": "error", "error": "X-User-Id required for desktop control"}

    safe_request_id = _validate_uuid(request_id, "request_id")
    if not safe_request_id:
        return {"status": "error", "error": "request_id must be a UUID"}

    headers = {
        "X-Internal-Key": API_INTERNAL_KEY,
        "X-Tenant-Id": tid,
        "X-User-Id": user_id,
    }
    url = (
        f"{API_BASE_URL}/api/v1/desktop-control/internal/grants/requests/"
        f"{safe_request_id}"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
    except httpx.RequestError as exc:
        logger.warning(
            "desktop_request_status: HTTP transport error request=%s err=%s",
            request_id,
            exc,
        )
        return {"status": "error", "error": f"transport: {exc}"}

    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 401:
        return {"status": "error", "error": "invalid internal key"}
    if resp.status_code in (403, 404, 422):
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, dict) and "code" in detail:
            return {"status": "denied", **detail}
        return {"status": "error", "error": f"denied {resp.status_code}: {resp.text[:200]}"}
    return {"status": "error", "error": f"upstream {resp.status_code}: {resp.text[:200]}"}


@mcp.tool()
async def desktop_request_grant(
    session_id: str,
    action: str,
    target_bundle_id: str = "",
    shell_id: str = "",
    reason: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Record a PENDING request to observe or run a native desktop action.

    This asks a human for approval; it does NOT create an approval grant, does NOT
    sign an envelope, and does NOT actuate. The request sits `pending` until a
    human approves it (then a grant is minted out-of-band). Poll it with
    `desktop_request_status`. Observe actions do not require `target_bundle_id`;
    pointer/keyboard actions do.
    """
    return await _request_grant(
        session_id=session_id,
        action=action,
        target_bundle_id=target_bundle_id,
        shell_id=shell_id,
        reason=reason,
        tenant_id=tenant_id,
        ctx=ctx,
    )


@mcp.tool()
async def desktop_request_status(
    request_id: str,
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Read the display-safe status of a pending desktop approval request.

    Returns request id, status (pending/approved/denied/expired/cancelled),
    action, capability, and whether a human grant has been minted yet — never raw
    payloads, screen bytes, or actuation args.
    """
    return await _request_status(
        request_id=request_id,
        tenant_id=tenant_id,
        ctx=ctx,
    )


async def _actuate(
    *,
    session_id: str,
    grant_id: str,
    args: dict | None = None,
    nonce: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    tid = resolve_tenant_id(ctx, tenant_id)
    if not tid:
        return {"status": "error", "error": "tenant_id required"}

    user_id = resolve_user_id(ctx)
    if not user_id:
        return {"status": "error", "error": "X-User-Id required for desktop control"}

    safe_grant_id = _validate_uuid(grant_id, "grant_id")
    if not safe_grant_id:
        return {"status": "error", "error": "grant_id must be a UUID"}
    safe_session_id = _validate_uuid(session_id, "session_id")
    if not safe_session_id:
        return {"status": "error", "error": "session_id must be a UUID"}

    body: dict = {"session_id": safe_session_id, "grant_id": safe_grant_id}
    if args:
        body["args"] = args
    if nonce:
        body["nonce"] = nonce

    headers = {
        "X-Internal-Key": API_INTERNAL_KEY,
        "X-Tenant-Id": tid,
        "X-User-Id": user_id,
    }
    url = f"{API_BASE_URL}/api/v1/desktop-control/internal/commands/actuate"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        logger.warning(
            "desktop_actuate: HTTP transport error session=%s err=%s", session_id, exc
        )
        return {"status": "error", "error": f"transport: {exc}"}

    if resp.status_code == 200:
        payload = resp.json()
        return {
            **payload,
            "message": (
                "Actuate consumes an existing human-approved grant; it never mints "
                "one. `approval_required` means no active grant — request approval "
                "first. Raw actuation args/screen bytes are never returned."
            ),
        }
    if resp.status_code == 401:
        return {"status": "error", "error": "invalid internal key"}
    if resp.status_code in (403, 404, 409, 422):
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, dict) and "code" in detail:
            return {"status": "denied", **detail}
        return {"status": "error", "error": f"denied {resp.status_code}: {resp.text[:200]}"}
    return {"status": "error", "error": f"upstream {resp.status_code}: {resp.text[:200]}"}


@mcp.tool()
async def desktop_actuate(
    session_id: str,
    grant_id: str,
    args: dict | None = None,
    nonce: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Enqueue ONE bounded native desktop action against an EXISTING approval grant.

    `grant_id` must be a grant a human already approved (via the P5.5 approval
    surface) for this session. This tool NEVER mints a grant. If no active grant
    matches, it returns `status="approval_required"` and enqueues no command. The
    grant fixes the action + target app; `args` are the action-specific parameters
    (e.g. {"text": "..."} for keyboard_type, {"x":.., "y":..} for pointer). Raw
    actuation args, screen bytes, and signed envelopes are never returned.
    """
    return await _actuate(
        session_id=session_id,
        grant_id=grant_id,
        args=args,
        nonce=nonce,
        tenant_id=tenant_id,
        ctx=ctx,
    )


__all__ = [
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
]
