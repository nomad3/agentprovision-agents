"""Internal agent-token mint endpoint — Phase 4 commit 5.

POST /api/v1/internal/agent-tokens/mint

Used by the code-worker (and any other in-cluster service) to mint an
agent-scoped JWT for a leaf subprocess. Gated by ``X-Internal-Key``
(matches the existing internal-endpoint pattern at
``apps/api/app/api/v1/internal_orchestrator_events.py``).

Why an endpoint instead of a worker-side import: the code-worker pod
doesn't share the API's SECRET_KEY by design (separation of concerns
+ smaller secret blast radius). All token minting happens in the API
pod; the worker fetches a freshly-minted token over the in-cluster
network using its X-Internal-Key.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.services.agent_token import mint_agent_token

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_internal_key(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    if x_internal_key not in (settings.API_INTERNAL_KEY, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")


class MintAgentTokenBody(BaseModel):
    tenant_id: str = Field(..., description="Tenant UUID (string)")
    agent_id: str = Field(..., description="Agent UUID (string)")
    task_id: str = Field(..., description="Task UUID (string)")
    parent_workflow_id: Optional[str] = Field(
        None, description="Temporal workflow id of the dispatching activity"
    )
    scope: Optional[List[str]] = Field(
        None,
        description=(
            "Scope claim — list of allowed bare MCP tool names; None "
            "means 'no per-call scope check' (full agent allowlist)."
        ),
    )
    parent_chain: List[str] = Field(
        default_factory=list,
        description="Lineage of dispatching agent UUIDs (max 3)",
    )
    heartbeat_timeout_seconds: int = Field(
        240, description="Heartbeat timeout — exp = 2x this value"
    )


@router.post("/agent-tokens/mint")
def mint_token(
    body: MintAgentTokenBody,
    _auth: None = Depends(_verify_internal_key),
    db: Session = Depends(deps.get_db),
) -> dict:
    """Mint an agent-scoped JWT for a leaf subprocess.

    Returns ``{"token": "<jwt>"}``. Raises 422 if parent_chain is
    longer than MAX_FALLBACK_DEPTH (the mint helper raises
    ValueError; we surface as 422 to make the error actionable on the
    worker side).

    Defence-in-depth: verify ``agent_id`` actually belongs to
    ``tenant_id`` before minting. ``X-Internal-Key`` already grants
    cross-tenant access by design, so a misconfigured worker passing
    ``tenant=A, agent=B`` (where agent B belongs to tenant C) is not an
    exploit — but the soft check catches the bug at mint time instead
    of letting a token with mismatched tenant/agent reach the resolver.
    Phase 4 review I-4.
    """
    # Local import to avoid cycle with app.models.agent at module load.
    from app.models.agent import Agent as _Agent

    agent_row = (
        db.query(_Agent)
        .filter(
            _Agent.id == body.agent_id,
            _Agent.tenant_id == body.tenant_id,
        )
        .first()
    )
    if agent_row is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "agent_id does not belong to tenant_id (or agent does "
                "not exist)"
            ),
        )

    try:
        tok = mint_agent_token(
            tenant_id=body.tenant_id,
            agent_id=body.agent_id,
            task_id=body.task_id,
            parent_workflow_id=body.parent_workflow_id,
            scope=body.scope,
            parent_chain=body.parent_chain,
            heartbeat_timeout_seconds=body.heartbeat_timeout_seconds,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    logger.info(
        "agent-token minted for tenant=%s agent=%s task=%s",
        body.tenant_id[:8], body.agent_id[:8], body.task_id[:8],
    )
    return {"token": tok}
