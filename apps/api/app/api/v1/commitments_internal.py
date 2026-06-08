"""Internal commitment endpoints for MCP / service-to-service use.

This is the "Luna drives it" surface: MCP tools call these with
``X-Internal-Key`` + ``X-Tenant-Id`` (the canonical internal pattern — see
``internal_embed.py``). User-facing JWT endpoints stay in ``commitments.py``;
these mirror the same service layer but derive the tenant from the header so a
leaf agent can create / complete / query commitments and scan red flags.

Plan: docs/plans/2026-06-08-accountable-learning-and-commitment-system.md (PR-B).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.schemas.accountable_learning import ESCALATION_POLICIES, RISK_THRESHOLDS
from app.services import commitment_service, red_flag_engine

router = APIRouter()


def _verify_internal_key(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
) -> None:
    if x_internal_key not in (settings.API_INTERNAL_KEY, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")


def _tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header required")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-Id must be a UUID")


def _to_dict(c) -> dict:
    return {
        "id": str(c.id),
        "title": c.title,
        "state": c.state,
        "owner_agent_slug": c.owner_agent_slug,
        "proof_required": list(c.proof_required or []),
        "proof_refs": list(c.proof_refs or []),
        "risk_threshold": c.risk_threshold,
        "due_at": c.due_at.isoformat() if c.due_at else None,
        "checkpoint_at": c.checkpoint_at.isoformat() if c.checkpoint_at else None,
        "session_id": (c.source_ref or {}).get("session_id"),
    }


class CommitmentCreateIn(BaseModel):
    title: str
    owner_agent_slug: str = "luna"
    action_kind: str = "delegated_work"
    source_ref: dict = Field(default_factory=dict)
    session_id: Optional[str] = None
    proof_required: Optional[List[str]] = None
    due_at: Optional[datetime] = None
    checkpoint_at: Optional[datetime] = None
    risk_threshold: Optional[str] = None
    escalation_policy: Optional[str] = None
    description: Optional[str] = None


class CommitmentCompleteInternalIn(BaseModel):
    proof_refs: List[str] = Field(default_factory=list)
    user_confirmed: bool = False


@router.post("/commitments", dependencies=[Depends(_verify_internal_key)])
def internal_create_commitment(
    body: CommitmentCreateIn,
    tenant_id: uuid.UUID = Depends(_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if body.risk_threshold is not None and body.risk_threshold not in RISK_THRESHOLDS:
        raise HTTPException(status_code=422, detail="invalid risk_threshold")
    if body.escalation_policy is not None and body.escalation_policy not in ESCALATION_POLICIES:
        raise HTTPException(status_code=422, detail="invalid escalation_policy")
    c = commitment_service.record_action_commitment(
        db,
        tenant_id,
        owner_agent_slug=body.owner_agent_slug,
        title=body.title,
        action_kind=body.action_kind,
        source_ref=body.source_ref,
        session_id=body.session_id,
        proof_required=body.proof_required,
        due_at=body.due_at,
        checkpoint_at=body.checkpoint_at,
        risk_threshold=body.risk_threshold,
        escalation_policy=body.escalation_policy,
        description=body.description,
    )
    return _to_dict(c)


@router.post(
    "/commitments/{commitment_id}/complete",
    dependencies=[Depends(_verify_internal_key)],
)
def internal_complete_commitment(
    commitment_id: uuid.UUID,
    body: CommitmentCompleteInternalIn,
    tenant_id: uuid.UUID = Depends(_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        c = commitment_service.complete_commitment_with_proof(
            db, tenant_id, commitment_id,
            proof_refs=body.proof_refs, user_confirmed=body.user_confirmed,
        )
    except commitment_service.CommitmentProofRequired as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not c:
        raise HTTPException(status_code=404, detail="Commitment not found")
    return _to_dict(c)


@router.get("/commitments/open", dependencies=[Depends(_verify_internal_key)])
def internal_list_open(
    session_id: Optional[str] = None,
    tenant_id: uuid.UUID = Depends(_tenant_id),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        _to_dict(c)
        for c in commitment_service.list_open_commitments(
            db, tenant_id, session_id=session_id
        )
    ]


@router.get("/commitments/red-flags", dependencies=[Depends(_verify_internal_key)])
def internal_red_flags(
    session_id: Optional[str] = None,
    min_level: str = "warn",
    tenant_id: uuid.UUID = Depends(_tenant_id),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    flags = red_flag_engine.scan_open_commitments(
        db, tenant_id, session_id=session_id, min_level=min_level
    )
    return [f.__dict__ for f in flags]
