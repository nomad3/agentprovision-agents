"""Tenant authentication for MCP tool calls.

FastMCP's Context.request_context is a RequestContext object, not a dict.
We extract tenant_id and internal_key from HTTP headers passed via the
Streamable HTTP transport.

Phase 4 adds a third auth tier (agent-scoped JWT) and a unified
resolver ``resolve_auth_context`` that returns an ``AuthContext``
covering all four tiers in precedence order:

    agent_token > tenant_jwt > X-Tenant-Id header > X-Internal-Key

Tenant-JWT decoding is not implemented in this server today (the chat
hot path passes X-Tenant-Id explicitly), so the resolver falls through
to the header tier when no agent-token is present. Adding tenant-JWT
decode is a future commit — out of scope for Phase 4 ship gates.

The legacy ``resolve_tenant_id(ctx)`` is kept as a thin wrapper that
delegates to ``resolve_auth_context(ctx).tenant_id`` so existing
callers don't need to migrate eagerly.
"""
import os
import logging
import threading
import time
from typing import Optional

from src.agent_token_verify import (
    AuthContext,
    decode_agent_token_if_present,
)

logger = logging.getLogger(__name__)

INTERNAL_KEY = os.environ.get("MCP_API_KEY", "dev_mcp_key")

# ── Tenancy-mismatch audit-log rate-limiter (SR-6) ───────────────────────
# When ``kind=agent_token``, the JWT's tenant_id claim is authoritative
# but the leaf may also pass an X-Tenant-Id header (default reqwest
# header set, etc.). A mismatch is audit-logged (NOT rejected — the leaf
# may not even know it sent the header). Per SR-6 we rate-limit to one
# log per (tenant, agent, header_value) per 60s — otherwise a misbehaving
# leaf can flood audit_logs.
_MISMATCH_LRU: dict[tuple, float] = {}
_MISMATCH_LRU_LOCK = threading.Lock()
_MISMATCH_TTL_SECONDS = 60.0
_MISMATCH_LRU_MAX = 1024  # soft cap; we don't need a real LRU eviction


def _should_log_mismatch(tenant_id: str, agent_id: str, header_value: str) -> bool:
    """Return True if this (tenant, agent, header) tuple should be
    audit-logged, False if we've already logged it within TTL.

    Side effect: records the timestamp on True.
    """
    key = (tenant_id, agent_id, header_value)
    now = time.monotonic()
    with _MISMATCH_LRU_LOCK:
        last = _MISMATCH_LRU.get(key)
        if last is not None and (now - last) < _MISMATCH_TTL_SECONDS:
            return False
        # Prune oldest if cache grows too large.
        if len(_MISMATCH_LRU) >= _MISMATCH_LRU_MAX:
            oldest_key = min(_MISMATCH_LRU, key=_MISMATCH_LRU.get)
            _MISMATCH_LRU.pop(oldest_key, None)
        _MISMATCH_LRU[key] = now
    return True


def _get_header(ctx, header_name: str) -> Optional[str]:
    """Safely extract an HTTP header from MCP request context.

    Handles both dict-like and object-like request_context,
    and checks common header variations (X-Tenant-Id, x-tenant-id).
    """
    if ctx is None:
        return None

    rc = getattr(ctx, 'request_context', None)
    if rc is None:
        return None

    # Try dict-like access first
    if isinstance(rc, dict):
        return rc.get(header_name) or rc.get(header_name.lower())

    # Try attribute access on RequestContext object
    # FastMCP exposes headers via the request_context.headers or similar
    headers = getattr(rc, 'headers', None)
    if headers:
        if isinstance(headers, dict):
            return headers.get(header_name) or headers.get(header_name.lower())
        # httpx/starlette Headers object
        if hasattr(headers, 'get'):
            return headers.get(header_name) or headers.get(header_name.lower())

    # Try direct attribute access
    for attr in [header_name, header_name.lower(), header_name.replace("-", "_").lower()]:
        val = getattr(rc, attr, None)
        if val is not None:
            return str(val)

    return None


def resolve_auth_context(ctx) -> AuthContext:
    """Resolve the auth context for one MCP tool call.

    Precedence (per design §8 step 3):
      1. agent_token    — Authorization: Bearer <jwt> with kind=agent_token
      2. tenant_jwt     — Authorization: Bearer <jwt> with kind=access (NOT
         IMPLEMENTED in this server today; falls through to next tier)
      3. tenant_header  — X-Tenant-Id header
      4. internal_key   — X-Internal-Key header (anonymous tenant)

    On agent_token tenancy mismatch (X-Tenant-Id header set AND its
    value differs from the claim), the claim wins. The mismatch is
    audit-logged at most once per minute per (tenant, agent, header).
    """
    auth_header = _get_header(ctx, "Authorization") or _get_header(ctx, "authorization")

    # ── Tier 1: agent_token ────────────────────────────────────────────
    auth_ctx = decode_agent_token_if_present(auth_header)
    if auth_ctx is not None:
        # Tenancy precedence rule: claim wins, header is ignored. Log on
        # mismatch (rate-limited).
        header_tenant = (
            _get_header(ctx, "X-Tenant-Id") or _get_header(ctx, "tenant_id")
        )
        if (
            header_tenant
            and auth_ctx.tenant_id
            and header_tenant != auth_ctx.tenant_id
        ):
            if _should_log_mismatch(
                auth_ctx.tenant_id, auth_ctx.agent_id or "", header_tenant
            ):
                _audit_tenancy_mismatch(
                    claim_tenant_id=auth_ctx.tenant_id,
                    header_tenant_id=header_tenant,
                    agent_id=auth_ctx.agent_id,
                    task_id=auth_ctx.task_id,
                )
        # User-id passes through (set by chat hot path).
        auth_ctx.user_id = (
            _get_header(ctx, "X-User-Id") or _get_header(ctx, "user_id")
        )
        return auth_ctx

    # ── Tier 2: tenant_jwt (deferred — see module docstring) ───────────

    # ── Tier 3: X-Tenant-Id header ─────────────────────────────────────
    header_tenant = (
        _get_header(ctx, "X-Tenant-Id") or _get_header(ctx, "tenant_id")
    )
    if header_tenant:
        return AuthContext(
            tier="tenant_header",
            tenant_id=header_tenant,
            user_id=(
                _get_header(ctx, "X-User-Id") or _get_header(ctx, "user_id")
            ),
        )

    # ── Tier 4: X-Internal-Key (anonymous tenant) ──────────────────────
    if verify_internal_key(ctx):
        return AuthContext(tier="internal_key")

    return AuthContext(tier="anonymous")


def _audit_tenancy_mismatch(
    *,
    claim_tenant_id: str,
    header_tenant_id: str,
    agent_id: Optional[str],
    task_id: Optional[str],
) -> None:
    """Write a tenancy-mismatch audit log row.

    Best-effort — the audit pipe may be down; never block on this.
    The actual write is delegated to ``tool_audit._log_call`` via a
    structured logger.info so the existing audit pipeline picks it up.
    """
    logger.info(
        "agent_token_tenancy_mismatch",
        extra={
            "event": "agent_token_tenancy_mismatch",
            "claim_tenant_id": claim_tenant_id,
            "header_tenant_id": header_tenant_id,
            "agent_id": agent_id,
            "task_id": task_id,
        },
    )


def resolve_tenant_id(ctx) -> Optional[str]:
    """Extract tenant_id from MCP request context headers.

    Thin wrapper around ``resolve_auth_context`` for legacy callers.
    Returns the tenant_id from whichever tier won.
    """
    return resolve_auth_context(ctx).tenant_id


def resolve_user_id(ctx) -> Optional[str]:
    """Extract the calling user's UUID from MCP request context headers.

    Set by ``cli_session_manager.generate_mcp_config`` so chat-side mutating
    tools (update_skill_definition / update_agent_definition) can attribute
    a revision to the user actually driving the chat session.
    """
    return _get_header(ctx, "X-User-Id") or _get_header(ctx, "user_id")


def verify_internal_key(ctx) -> bool:
    """Verify the X-Internal-Key header matches the configured key."""
    key = _get_header(ctx, "X-Internal-Key") or _get_header(ctx, "internal_key")
    if not key:
        return False
    return key == INTERNAL_KEY
