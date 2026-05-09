"""SMS MCP tools — Twilio.

Three tools:
  - send_sms(to, body)
  - list_sms_threads()
  - read_sms(thread_id)

All three call the API's internal endpoints (not Twilio directly) so:
  1. Credential decryption stays inside the API where the Fernet key lives.
  2. The audit trail (channel_events, chat_messages) is written
     consistently regardless of which agent dispatched the call.
  3. The MCP server never sees the Twilio auth_token in plaintext.

Apple iMessage / "Messages for Business" is intentionally NOT exposed here.
That path requires an Apple Business Register approval (4-12 weeks) and a
separate per-tenant Business ID. The send_sms tool will gain an
`imessage_first` parameter when that lands; until then SMS is the channel.
"""
from __future__ import annotations

import logging

import httpx
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id

logger = logging.getLogger(__name__)


def _api_base_url() -> str:
    from src.config import settings
    return settings.API_BASE_URL.rstrip("/")


def _internal_key() -> str:
    from src.config import settings
    return settings.API_INTERNAL_KEY


@mcp.tool()
async def send_sms(
    to: str = "",
    body: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Send an SMS message via the tenant's configured Twilio number.

    Use when the user asks to text a client (e.g. "text Mrs. Garcia about
    Bella's vaccine reminder") AND the tenant has connected the SMS (Twilio)
    integration. If the integration isn't connected, this returns an error;
    in that case ask the user to connect it under Integrations.

    Args:
        to: Destination phone number in E.164 format (e.g. +17145551234).
        body: Message text. Truncated to 1600 chars (Twilio hard cap).
        tenant_id: Tenant UUID (resolved from session if omitted).
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with status, message_sid, to, from. On error: {"error": "..."}.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id required (no session context found)"}
    if not to or not body:
        return {"error": "Both `to` and `body` are required"}

    payload = {"tenant_id": tid, "to": to, "body": body}
    headers = {"X-Internal-Key": _internal_key()}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_api_base_url()}/api/v1/integrations/twilio/internal/send",
                json=payload,
                headers=headers,
            )
            if resp.status_code == 200:
                return resp.json()
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            logger.warning("send_sms failed: %s %s", resp.status_code, detail)
            return {"error": f"send failed ({resp.status_code}): {detail}"}
    except Exception as e:
        logger.exception("send_sms request error")
        return {"error": str(e)}


@mcp.tool()
async def list_sms_threads(
    limit: int = 20,
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """List recent SMS conversations (chat sessions) for this tenant.

    Returns the most recent SMS threads; each row has the remote phone
    number, session id, and the agent that's been replying. Use this before
    `read_sms` when the user asks "show me my texts" or "what did Mrs.
    Garcia send last week".

    Args:
        limit: Maximum threads to return (1-100, default 20).
        tenant_id: Tenant UUID (resolved from session if omitted).
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with `threads` array and `count`.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id required (no session context found)"}

    headers = {"X-Internal-Key": _internal_key()}
    params = {"tenant_id": tid, "limit": limit}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_api_base_url()}/api/v1/integrations/twilio/internal/threads",
                headers=headers,
                params=params,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"threads": data.get("threads", []), "count": len(data.get("threads", []))}
            return {"error": f"list_sms_threads failed ({resp.status_code}): {resp.text}"}
    except Exception as e:
        logger.exception("list_sms_threads request error")
        return {"error": str(e)}


@mcp.tool()
async def read_sms(
    thread_id: str = "",
    limit: int = 50,
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Read messages in a single SMS thread.

    Pass `thread_id` from `list_sms_threads`. Returns the conversation in
    chronological order, role tagged (user / assistant) so the agent can
    reason over the recent back-and-forth.

    Args:
        thread_id: Chat session UUID returned by list_sms_threads.
        limit: Max messages to return (1-500, default 50).
        tenant_id: Tenant UUID (resolved from session if omitted).
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with `thread` metadata and `messages` array.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id required (no session context found)"}
    if not thread_id:
        return {"error": "thread_id required"}

    headers = {"X-Internal-Key": _internal_key()}
    params = {"tenant_id": tid, "limit": limit}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_api_base_url()}/api/v1/integrations/twilio/internal/thread/{thread_id}",
                headers=headers,
                params=params,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"read_sms failed ({resp.status_code}): {resp.text}"}
    except Exception as e:
        logger.exception("read_sms request error")
        return {"error": str(e)}
