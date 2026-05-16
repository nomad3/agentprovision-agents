"""read_session_events MCP tool — lets agents query their own session's
audit log of channel-agnostic events.

Calls the internal-key endpoint at /api/v2/internal/session-events/{id}
which mirrors the SPA's v2 JSON replay envelope. Read-only; poll model
(no streaming). Use this when an agent needs to:
  - Look at the most recent tool calls / plan steps / coalition handoffs
  - Catch up after a long-running task with `since=<last_seq_no>`
  - Reconstruct what happened in a session for audit / debugging

Phase 2 of the Alpha Control Center rollout.
"""
import logging
from typing import Optional

import httpx
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id

logger = logging.getLogger(__name__)


def _get_api_base_url() -> str:
    from src.config import settings
    return settings.API_BASE_URL.rstrip("/")


def _get_internal_key() -> str:
    from src.config import settings
    return settings.API_INTERNAL_KEY


@mcp.tool()
async def read_session_events(
    session_id: str,
    since: int = 0,
    limit: int = 100,
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Read paginated session events for the given session.

    Each event envelope contains: event_id, session_id, tenant_id,
    seq_no, type, payload, ts. The `type` field is one of the channel-
    agnostic event types (chat_message, tool_call_started,
    tool_call_complete, plan_step_changed, subagent_dispatched,
    subagent_response, cli_subprocess_stream, resource_referenced,
    auto_quality_score) or a legacy v1 type prefixed with `legacy.`.

    Args:
        session_id: The chat_sessions UUID whose events to read.
        since: Return only events with seq_no > since (default 0 = from
               the start). Use the previous response's next_cursor or
               latest_seq_no to page forward.
        limit: Max events to return (default 100, max 500).
        tenant_id: Tenant UUID (resolved from session context if omitted).

    Returns:
        {
          "events": [{event_id, session_id, tenant_id, seq_no, type, payload, ts}, ...],
          "next_cursor": int | None,   # last seq_no when there might be more
          "latest_seq_no": int,         # highest seq_no currently in the session
        }
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id required (could not resolve from context)"}
    if not session_id:
        return {"error": "session_id required"}

    api_base_url = _get_api_base_url()
    internal_key = _get_internal_key()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{api_base_url}/api/v2/internal/session-events/{session_id}",
                headers={"X-Internal-Key": internal_key},
                params={
                    "tenant_id": tid,
                    "since": since,
                    "limit": min(max(limit, 1), 500),
                },
            )
            if resp.status_code == 404:
                return {"error": "Session not found (or belongs to a different tenant)"}
            if resp.status_code != 200:
                return {"error": f"Read failed: {resp.status_code}"}
            return resp.json()
    except Exception as e:
        logger.exception("read_session_events failed")
        return {"error": f"Read failed: {str(e)}"}
