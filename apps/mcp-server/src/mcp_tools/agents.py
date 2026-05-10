"""dispatch_agent + request_human_approval MCP tools — Phase 4 commit 8.

These two tools are the primary leaf-side delegation surfaces.

  - ``dispatch_agent`` lets a leaf forward a task to a different agent
    (delegate task_type) or kick off a code task (code task_type). It
    walks parent_chain += [self.agent_id] so the §3.1 recursion gate at
    /tasks/dispatch refuses the call when depth would exceed
    MAX_FALLBACK_DEPTH.

  - ``request_human_approval`` lets a leaf gate a workflow step on
    tenant-admin signoff. Posts to the existing
    /api/v1/tasks/{id}/workflow-approve with decision='requested'.

Both tools require tier='agent_token' on the calling auth_context —
attempting them with tenant_header or internal_key returns an error.
The scope-enforcement gate (Phase 4 commit 7) handles per-tool
allowlist checks.
"""
from __future__ import annotations

import logging
import os

import httpx
from mcp.server.fastmcp import Context

from src.config import settings
from src.mcp_app import mcp
from src.mcp_auth import resolve_auth_context

logger = logging.getLogger(__name__)


def _api_url() -> str:
    return os.environ.get("API_BASE_URL", settings.API_BASE_URL)


def _internal_key() -> str:
    return os.environ.get("API_INTERNAL_KEY") or os.environ.get(
        "MCP_API_KEY", settings.API_INTERNAL_KEY
    )


@mcp.tool()
async def dispatch_agent(
    target_agent_id: str,
    objective: str,
    task_type: str = "delegate",
    ctx: Context | None = None,
) -> dict:
    """Dispatch a task to another agent (or kick off a code task).

    The caller's agent_id is appended to parent_chain so the §3.1
    recursion gate refuses calls at depth >= MAX_FALLBACK_DEPTH (3).
    Returns the API's response: {"task_id", "workflow_id"} on success
    or surfaces the dispatch endpoint's 503/422 as a structured error
    dict so the caller can render the actionable_hint.

    Args:
        target_agent_id: UUID of the receiving agent. Required for
            task_type='delegate'.
        objective: Free-text task description / goal.
        task_type: 'delegate' (default) → TaskExecutionWorkflow on the
            orchestration queue. 'code' → CodeTaskWorkflow on the
            agentprovision-code queue.
    """
    auth = resolve_auth_context(ctx) if ctx is not None else None
    if auth is None or auth.tier != "agent_token":
        return {
            "error": "PERMISSION_DENIED",
            "message": "dispatch_agent requires agent-token auth tier",
        }
    if not auth.tenant_id or not auth.agent_id:
        return {
            "error": "PERMISSION_DENIED",
            "message": "agent_token claim missing tenant_id or agent_id",
        }

    new_parent_chain = list(auth.parent_chain) + [auth.agent_id]
    body = {
        "task_type": task_type,
        "objective": objective,
        "target_agent_id": target_agent_id if task_type == "delegate" else None,
        "parent_chain": new_parent_chain,
    }

    headers = {
        "X-Internal-Key": _internal_key(),
        "X-Tenant-Id": auth.tenant_id,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                f"{_api_url()}/api/v1/tasks/dispatch",
                json=body,
                headers=headers,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "error": "DISPATCH_TRANSPORT_FAILED",
                "message": str(exc),
            }
    if resp.status_code in (200, 201):
        return resp.json()
    # 503 / 422 / 401 → surface as structured error so caller can see
    # the actionable_hint (recursion gate, target_agent_id missing, etc.).
    try:
        detail = resp.json().get("detail")
    except Exception:
        detail = resp.text[:500]
    return {
        "error": f"DISPATCH_FAILED_{resp.status_code}",
        "detail": detail,
    }


@mcp.tool()
async def request_human_approval(
    task_id: str,
    reason: str,
    ctx: Context | None = None,
) -> dict:
    """Request human-admin approval for a workflow step.

    Round-trips through /api/v1/tasks/{id}/workflow-approve with
    decision='requested' + comment=<reason>. The endpoint signals the
    Temporal workflow waiting on the human_approval step; the
    tenant-admin UI surfaces the request in the approval queue.
    Returns the endpoint's response payload.
    """
    auth = resolve_auth_context(ctx) if ctx is not None else None
    if auth is None or auth.tier != "agent_token":
        return {
            "error": "PERMISSION_DENIED",
            "message": "request_human_approval requires agent-token auth tier",
        }

    body = {
        "decision": "requested",
        "comment": reason,
    }
    headers = {
        "X-Internal-Key": _internal_key(),
        "X-Tenant-Id": auth.tenant_id,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                f"{_api_url()}/api/v1/tasks/{task_id}/workflow-approve",
                json=body,
                headers=headers,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "error": "APPROVAL_TRANSPORT_FAILED",
                "message": str(exc),
            }
    if resp.status_code in (200, 201, 204):
        try:
            return resp.json()
        except Exception:
            return {"status": "requested"}
    try:
        detail = resp.json()
    except Exception:
        detail = resp.text[:500]
    return {
        "error": f"APPROVAL_FAILED_{resp.status_code}",
        "detail": detail,
    }
