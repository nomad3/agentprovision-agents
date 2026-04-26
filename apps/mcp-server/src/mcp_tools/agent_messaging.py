"""Chat-side primitives for agent-to-agent communication.

Three tools:
  * ``delegate_to_agent`` — handoff a task to another agent. Backed by a
    1-step Dynamic Workflow (`Delegate To Agent` template), so the
    audit trail is the WorkflowRun + WorkflowStepLog the platform
    already renders in RunsTab. The user sees an inline ``[handoff]``
    chat message linking to the run id; no new audit table.
  * ``read_handoff_status`` — poll a handoff for its reply.
  * ``find_agent`` — wraps GET /agents/discover (extended in PR-B) so
    chat agents resolve native + external in one call.
"""
import logging

import httpx
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id, resolve_user_id

logger = logging.getLogger(__name__)


def _get_api_base_url() -> str:
    from src.config import settings
    return settings.API_BASE_URL.rstrip("/")


def _get_internal_key() -> str:
    from src.config import settings
    return settings.API_INTERNAL_KEY


@mcp.tool()
async def delegate_to_agent(
    recipient_agent_id: str,
    task: str,
    reason: str = "",
    chat_session_id: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Hand off a task to another agent via a single-step Dynamic Workflow.

    Use this when you want a peer agent to handle something while the
    user keeps watching the chat — sales-agent grading a lead, a
    cardiology agent reading an ECG, etc. Coalition (multi-round) is
    overkill for one-shot dispatch; use that only for investigations
    spanning multiple phases.

    Args:
        recipient_agent_id: Native agent UUID or external agent UUID.
        task: The instruction / prompt for the recipient.
        reason: Short rationale — appears in the [handoff] chat message.
        chat_session_id: If set, drops a [handoff] system message into
            that session so the user sees "→ Handoff to {Agent} (run #X)".
        tenant_id: Tenant UUID (resolved from session if omitted).

    Returns:
        Dict with run_id, recipient_agent_id, recipient_name. Poll
        read_handoff_status(run_id) until the run completes.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    uid = resolve_user_id(ctx)
    if not recipient_agent_id:
        return {"error": "recipient_agent_id is required."}
    if not task or not task.strip():
        return {"error": "task is required and must be non-empty."}
    if not tid:
        return {"error": "tenant_id is required (or X-Tenant-Id header)."}

    api_base_url = _get_api_base_url()
    internal_key = _get_internal_key()

    body = {
        "tenant_id": tid,
        "recipient_agent_id": recipient_agent_id,
        "task": task,
        "reason": reason or None,
        "actor_user_id": uid,
        "chat_session_id": chat_session_id or None,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{api_base_url}/api/v1/agents/internal/delegate",
                headers={"X-Internal-Key": internal_key},
                json=body,
            )
            if resp.status_code in (200, 201):
                return {"status": "success", **resp.json()}
            return {
                "error": f"delegate failed: HTTP {resp.status_code}",
                "detail": resp.text[:500],
            }
    except Exception as e:
        logger.exception("delegate_to_agent failed")
        return {"error": f"Failed to delegate: {str(e)}"}


@mcp.tool()
async def read_handoff_status(
    run_id: str,
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Read the current status + reply for a handoff run.

    Args:
        run_id: The Temporal workflow id returned by delegate_to_agent.
        tenant_id: Tenant UUID (resolved from session if omitted).

    Returns:
        Dict with status (running|completed|failed), reply (when done),
        error (when failed), started_at, completed_at.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not run_id:
        return {"error": "run_id is required."}
    if not tid:
        return {"error": "tenant_id is required (or X-Tenant-Id header)."}

    api_base_url = _get_api_base_url()
    internal_key = _get_internal_key()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{api_base_url}/api/v1/agents/internal/handoff/{run_id}/status",
                headers={"X-Internal-Key": internal_key},
                params={"tenant_id": tid},
            )
            if resp.status_code == 200:
                return {"status": "success", **resp.json()}
            if resp.status_code == 404:
                return {"error": f"Run '{run_id}' not found."}
            return {"error": f"status check failed: HTTP {resp.status_code}", "detail": resp.text[:500]}
    except Exception as e:
        logger.exception("read_handoff_status failed")
        return {"error": f"Failed to read handoff status: {str(e)}"}


@mcp.tool()
async def find_agent(
    capability: str,
    kind: str = "",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Resolve agents (native + external) that declared a capability.

    Args:
        capability: e.g. "lead-scoring", "code-review", "data-analysis".
        kind: Filter to "native" or "external"; empty = both.
        tenant_id: Tenant UUID (resolved from session if omitted).

    Returns:
        Dict with results: list of {kind, id, name, description, status, capabilities}.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not capability:
        return {"error": "capability is required."}
    if not tid:
        return {"error": "tenant_id is required (or X-Tenant-Id header)."}

    api_base_url = _get_api_base_url()
    internal_key = _get_internal_key()

    params: dict = {"capability": capability, "tenant_id": tid}
    if kind in ("native", "external"):
        params["kind"] = kind

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{api_base_url}/api/v1/agents/internal/discover",
                headers={"X-Internal-Key": internal_key},
                params=params,
            )
            if resp.status_code == 200:
                return {"status": "success", "results": resp.json()}
            return {
                "error": f"discover failed: HTTP {resp.status_code}",
                "detail": resp.text[:500],
            }
    except Exception as e:
        logger.exception("find_agent failed")
        return {"error": f"Failed to discover: {str(e)}"}
