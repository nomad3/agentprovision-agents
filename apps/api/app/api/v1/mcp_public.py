"""Public MCP gateway — Phase 1 of #175.

Exposes the in-cluster FastMCP server (`mcp-tools:8086/sse`) on a
publicly-reachable URL gated by per-user JWT auth so external MCP
clients (Claude.ai, custom integrations) can connect to a tenant's
AgentProvision tool surface without holding the shared
`X-Internal-Key` secret.

Auth model (Phase 1):
    - Client sends `Authorization: Bearer <jwt>` — the same JWT the
      web SPA / `alpha` CLI already use.
    - Gateway validates via `get_current_user`, extracts `tenant_id`,
      and forwards the request to internal mcp-tools with
      `X-Internal-Key` + `X-Tenant-Id` populated server-side.

Out of scope for Phase 1 (filed for Phase 2):
    - OAuth 2.1 PKCE flow for Claude.ai's standard MCP connector.
    - Per-tool scoping (today the bearer can call every tool the
      tenant's MCP surface exposes; Phase 2 adds per-token scope
      narrowing).
    - Public manifest endpoint advertising tool list to anonymous
      browsers (Claude.ai discovery currently relies on the user
      pasting a config snippet manually).

Cloudflared ingress: `agentprovision.com/api/v1/mcp/*` is NOT in the
`/api/v1/*/internal($|/)` block-list — public traffic reaches it
through the standard `/api/*` route in cloudflared/config.yml.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api import deps
from app.core.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# Internal mcp-tools endpoint. FastMCP serves SSE on /sse and accepts
# JSON-RPC POSTs at /messages/. Both are forwarded one-for-one; the
# only thing the gateway changes is the auth header.
_INTERNAL_MCP_BASE = "http://mcp-tools:8086"


@router.get("/sse")
async def mcp_sse_gateway(
    request: Request,
    current_user: User = Depends(deps.get_current_active_user),
) -> StreamingResponse:
    """Public SSE endpoint that streams the internal mcp-tools SSE
    feed back to the client.

    httpx's async streaming response is forwarded chunk-by-chunk so
    that Server-Sent Events arrive at the client with the same
    framing the in-cluster server emits. No buffering at this layer
    — FastMCP relies on the client receiving each event promptly,
    and our SSE clients (Claude.ai, `alpha chat` REPL) timeout if the
    initial `event: endpoint` doesn't arrive within ~5 seconds.
    """
    tenant_id = str(current_user.tenant_id)
    headers = {
        "X-Internal-Key": settings.MCP_API_KEY,
        "X-Tenant-Id": tenant_id,
        # Forward through any query params the client passed.
        # FastMCP doesn't use any today, but be defensive.
        "Accept": "text/event-stream",
    }

    async def _stream():
        # New AsyncClient per request — FastAPI doesn't pool these for
        # us, and the SSE stream may live for hours. Sharing a client
        # across requests would couple stream lifetimes.
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream(
                    "GET",
                    f"{_INTERNAL_MCP_BASE}/sse",
                    headers=headers,
                    params=dict(request.query_params),
                ) as upstream:
                    if upstream.status_code != 200:
                        # Yield a single error event so the client sees
                        # something rather than hanging on an empty stream.
                        logger.warning(
                            "mcp gateway: upstream returned %s for tenant=%s",
                            upstream.status_code,
                            tenant_id[:8],
                        )
                        yield (
                            f"event: error\ndata: upstream {upstream.status_code}\n\n"
                        ).encode()
                        return
                    async for chunk in upstream.aiter_raw():
                        yield chunk
            except httpx.RequestError as exc:
                logger.warning(
                    "mcp gateway: upstream connection failed for tenant=%s: %s",
                    tenant_id[:8],
                    exc,
                )
                yield (
                    "event: error\ndata: upstream connection failed\n\n"
                ).encode()

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            # The same headers FastMCP sets directly — propagate so
            # well-behaved SSE clients don't reconnect aggressively.
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx-style buffering
        },
    )


@router.post("/messages/")
async def mcp_messages_gateway(
    request: Request,
    session_id: Optional[str] = Query(None),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Public JSON-RPC POST endpoint that forwards to FastMCP's
    `/messages/?session_id=<id>` handler.

    Phase 1 maintains a 1:1 forwarding contract — FastMCP returns
    202 Accepted with no body, so the response shape is opaque to
    us. The session_id query param is the one FastMCP assigns from
    its initial SSE `event: endpoint` push.
    """
    tenant_id = str(current_user.tenant_id)
    # Hard-cap body size — Claude.ai MCP messages should be ~kB, not
    # MB. Cuts a class of DoS where a malicious bearer could pipe
    # gigabytes through the gateway.
    body = await request.body()
    if len(body) > 1 * 1024 * 1024:  # 1 MB
        raise HTTPException(
            status_code=413,
            detail="request body exceeds 1 MB",
        )

    headers = {
        "X-Internal-Key": settings.MCP_API_KEY,
        "X-Tenant-Id": tenant_id,
        "Content-Type": request.headers.get("content-type", "application/json"),
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                f"{_INTERNAL_MCP_BASE}/messages/",
                content=body,
                headers=headers,
                params={"session_id": session_id} if session_id else {},
            )
        except httpx.RequestError as exc:
            logger.warning(
                "mcp gateway: messages POST upstream failed for tenant=%s: %s",
                tenant_id[:8],
                exc,
            )
            raise HTTPException(status_code=502, detail="upstream unavailable")

    return StreamingResponse(
        iter([resp.content]),
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


@router.get("/info")
def mcp_info(
    current_user: User = Depends(deps.get_current_active_user),
) -> dict:
    """Cheap discovery endpoint — surfaces the connection details a
    user should paste into Claude.ai (or any other MCP client) to
    reach their tenant's tool surface.

    Returns:
        {
            "server_name": "AgentProvision",
            "tenant_id": "<uuid>",
            "tenant_name": "<readable>",
            "endpoint_url": "https://agentprovision.com/api/v1/mcp/sse",
            "transport": "sse",
            "auth": "Bearer <alpha login token>",
            "phase": 1
        }

    Phase 2 will replace the bearer-paste flow with a Claude.ai
    OAuth 2.1 PKCE handshake.
    """
    tenant_name: Optional[str] = None
    try:
        if current_user.tenant is not None:
            tenant_name = current_user.tenant.name
    except Exception:
        # The relationship may lazily fail in some test setups; the
        # name isn't load-bearing.
        tenant_name = None

    return {
        "server_name": "AgentProvision",
        "tenant_id": str(current_user.tenant_id),
        "tenant_name": tenant_name,
        "endpoint_url": "https://agentprovision.com/api/v1/mcp/sse",
        "transport": "sse",
        "auth_scheme": "bearer",
        "auth_hint": (
            "Run `alpha login` then paste the access token from "
            "~/Library/Application Support/agentprovision/tokens/agentprovision.com.token "
            "(macOS path) into your MCP client's Authorization header."
        ),
        "phase": 1,
    }
