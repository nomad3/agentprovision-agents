"""Internal orchestrator-events ingestion — Phase 3 commit 8.

``POST /api/v1/internal/orchestrator/events`` accepts an
``{event_type, payload}`` body, gated by ``X-Internal-Key`` (matches
the RL internal endpoint pattern at ``apps/api/app/api/v1/rl.py:23-27``).

Body validation:
  - ``event_type`` MUST start with ``execution.`` — otherwise 400.

The handler resolves ``tenant_id`` from the payload (REQUIRED) and
dispatches via ``webhook_connectors.fire_outbound_event`` so any
matching outbound webhook gets the delivery.

Used by the worker-side heartbeat-poll loop in
``cli_session_manager.run_agent_session`` to emit
``execution.heartbeat_missed`` when staleness exceeds
``2 * heartbeat_interval`` (per design §9.1).
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_internal_key(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    if x_internal_key not in (settings.API_INTERNAL_KEY, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")


class OrchestratorEventBody(BaseModel):
    event_type: str = Field(..., description="execution.* event name")
    payload: dict[str, Any] = Field(..., description="webhook payload dict")
    tenant_id: str = Field(..., description="tenant uuid (string)")


@router.post("/orchestrator/events")
def ingest_orchestrator_event(
    body: OrchestratorEventBody,
    db: Session = Depends(deps.get_db),
    _auth: None = Depends(_verify_internal_key),
) -> dict:
    """Ingest a single orchestrator event from the worker side.

    Validates event_type prefix, then delegates to fire_outbound_event
    so any tenant outbound webhook subscribed to ``execution.*`` (or
    the specific event) gets the delivery. Returns the per-webhook
    delivery summary list (same shape as the existing
    /webhook-connectors/test-trigger endpoint).
    """
    if not body.event_type.startswith("execution."):
        raise HTTPException(
            status_code=400,
            detail="event_type must start with 'execution.'",
        )

    try:
        tenant_uuid = UUID(body.tenant_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="tenant_id must be a uuid")

    try:
        from app.services import webhook_connectors as wh_svc
        results = wh_svc.fire_outbound_event(
            db, tenant_uuid, body.event_type, body.payload,
        )
    except BaseException as exc:  # noqa: BLE001
        # Defensive — but we want to actually surface delivery errors
        # so the caller can decide whether to retry. log + 502.
        logger.warning(
            "fire_outbound_event raised event=%s tenant=%s: %s",
            body.event_type, body.tenant_id, exc,
        )
        raise HTTPException(
            status_code=502,
            detail=f"webhook fire failed: {exc.__class__.__name__}",
        )

    return {"event_type": body.event_type, "deliveries": results}


__all__ = ["router"]
