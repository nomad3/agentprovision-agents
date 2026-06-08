"""Commitment MCP tools — Accountable Learning & Commitment System (plan PR-B).

Lets Luna (and other leaf agents) create, complete, and review commitments
through the kernel: each tool delegates to the internal API
(`/api/v1/internal/commitments*`) with X-Internal-Key + X-Tenant-Id, the same
pattern as the other MCP tool modules. The proof gate, red-flag engine, and
tenant isolation all live server-side — these tools never bypass them.

Every call must include `tenant_id` (CLAUDE.md MCP contract).
"""
import logging
import os
from typing import List, Optional

import httpx
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id

logger = logging.getLogger(__name__)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")
API_INTERNAL_KEY = os.environ.get("MCP_API_KEY", "dev_mcp_key")


async def _internal(method: str, path: str, tenant_id: str, json_data: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        kwargs = {
            "headers": {
                "X-Internal-Key": API_INTERNAL_KEY,
                "X-Tenant-Id": tenant_id,
            }
        }
        if json_data is not None and method.lower() != "get":
            kwargs["json"] = json_data
        resp = await getattr(client, method.lower())(f"{API_BASE_URL}{path}", **kwargs)
    if resp.status_code in (200, 201):
        return resp.json()
    if resp.status_code == 204:
        return {"status": "success"}
    return {"error": f"API {resp.status_code}: {resp.text[:300]}"}


@mcp.tool()
async def commitment_create(
    title: str,
    proof_required: Optional[List[str]] = None,
    due_at: Optional[str] = None,
    session_id: Optional[str] = None,
    risk_threshold: Optional[str] = None,
    action_kind: str = "delegated_work",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Record an explicit commitment (an outcome Luna promised).

    Use this when you promise to do something with a definition of done — NOT
    for casual statements. Completion later requires proof (`proof_required`
    names what proof closes it), so capture the proof path up front.

    Args:
        title: Short description of the promised outcome.
        proof_required: What proof closes it (e.g. ["merged_pr_url","ci_run_id"]).
        due_at: ISO-8601 due time, or omit.
        session_id: Chat session id, for session-scoped queries.
        risk_threshold: low | medium | high | irreversible.
        tenant_id: Tenant UUID.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    body = {
        "title": title,
        "action_kind": action_kind,
        "proof_required": proof_required,
        "due_at": due_at,
        "session_id": session_id,
        "risk_threshold": risk_threshold,
        "source_ref": {},
    }
    return await _internal("post", "/api/v1/internal/commitments", tid, body)


@mcp.tool()
async def commitment_complete(
    commitment_id: str,
    proof_refs: Optional[List[str]] = None,
    user_confirmed: bool = False,
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Mark a commitment done — ONLY with proof or explicit user confirmation.

    The server rejects (409) a completion that has neither `proof_refs` nor
    `user_confirmed=True`. Never invent proof; if you don't have it, leave the
    commitment open and say so.

    Args:
        commitment_id: The commitment UUID.
        proof_refs: Concrete evidence (merged PR url, CI run id, message id…).
        user_confirmed: True only if the user explicitly confirmed completion now.
        tenant_id: Tenant UUID.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    body = {"proof_refs": proof_refs or [], "user_confirmed": user_confirmed}
    return await _internal(
        "post", f"/api/v1/internal/commitments/{commitment_id}/complete", tid, body
    )


@mcp.tool()
async def commitment_list_open(
    session_id: Optional[str] = None,
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """List open/live commitments (optionally for one chat session).

    Use this to answer "what are we missing / what did we promise?" without
    guessing. Returns commitments still open, in_progress, blocked, or at_risk.

    Args:
        session_id: Restrict to a chat session, or omit for all.
        tenant_id: Tenant UUID.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    path = "/api/v1/internal/commitments/open"
    if session_id:
        path += f"?session_id={session_id}"
    rows = await _internal("get", path, tid)
    return {"commitments": rows} if isinstance(rows, list) else rows


@mcp.tool()
async def commitment_scan_red_flags(
    session_id: Optional[str] = None,
    min_level: str = "warn",
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Scan open commitments for drift (overdue, missing proof, blocked, stale).

    Returns red flags at or above `min_level` (watch|warn|escalate|block). Empty
    if the red-flag engine is disabled for the tenant (operator opt-in). Raise
    flags BEFORE a commitment fails — a late red flag is a failed red flag.

    Args:
        session_id: Restrict to a chat session, or omit for all.
        min_level: Minimum severity to return (default warn).
        tenant_id: Tenant UUID.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    path = f"/api/v1/internal/commitments/red-flags?min_level={min_level}"
    if session_id:
        path += f"&session_id={session_id}"
    flags = await _internal("get", path, tid)
    return {"red_flags": flags} if isinstance(flags, list) else flags
