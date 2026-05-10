"""Agent-token verifier for the MCP server (Phase 4 commit 6).

Standalone counterpart of ``apps/api/app/services/agent_token``. Lives
in apps/mcp-server because:
  - the MCP server has its own settings (no shared core import path)
  - importing from apps/api into apps/mcp-server would create a
    cross-service dependency the deployment manifests don't model

The two files MUST stay in sync re: claim shape and the
``kind == "agent_token"`` + ``sub.startswith("agent:")`` (SR-11)
double-check. We mirror the verify side here; minting only happens in
the API pod.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from jose import ExpiredSignatureError, JWTError, jwt

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """Resolved auth context for a single MCP tool call.

    ``tier`` is one of:
      - "agent_token"    — third tier (Phase 4)
      - "tenant_jwt"     — second tier (web SPA / human CLI)
      - "tenant_header"  — X-Tenant-Id only (legacy chat dispatch path)
      - "internal_key"   — X-Internal-Key only (service-to-service)
      - "anonymous"      — no auth context resolved
    """

    tier: str = "anonymous"
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    parent_workflow_id: Optional[str] = None
    parent_chain: tuple = field(default_factory=tuple)
    scope: Optional[list] = None  # None = no scope check; [] = empty allowlist


def decode_agent_token_if_present(
    authorization_header: Optional[str],
) -> Optional[AuthContext]:
    """Decode an Authorization header into an AuthContext if it carries
    a valid agent_token. Returns None on:
      - missing header
      - bad/non-Bearer scheme
      - token doesn't decode / wrong kind / wrong sub shape
      - expired

    A ``None`` return tells the caller "fall through to next tier";
    the caller should NOT treat this as an error path.
    """
    if not authorization_header:
        return None
    parts = authorization_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except ExpiredSignatureError:
        logger.info("agent_token expired — falling through to next tier")
        return None
    except JWTError as e:
        logger.debug("agent_token decode failed: %s", e)
        return None

    # SR-11: double-check kind + sub shape.
    if payload.get("kind") != "agent_token":
        return None
    sub = payload.get("sub", "")
    if not (isinstance(sub, str) and sub.startswith("agent:")):
        return None

    parent_chain = tuple(payload.get("parent_chain") or ())
    return AuthContext(
        tier="agent_token",
        tenant_id=payload.get("tenant_id"),
        agent_id=payload.get("agent_id"),
        task_id=payload.get("task_id"),
        parent_workflow_id=payload.get("parent_workflow_id"),
        parent_chain=parent_chain,
        scope=payload.get("scope"),  # may be None or list
    )
