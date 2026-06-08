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
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.schemas.accountable_learning import (
    ESCALATION_POLICIES,
    RISK_THRESHOLDS,
    LearningArtifact,
)
from app.schemas.commitment_record import strip_blank_refs
from app.services import commitment_service, learning_artifact_io, red_flag_engine

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

    @field_validator("proof_refs")
    @classmethod
    def _v_proof_refs(cls, v):
        return strip_blank_refs(v) or []


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
    min_level: Literal["watch", "warn", "escalate", "block"] = "warn",
    tenant_id: uuid.UUID = Depends(_tenant_id),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    flags = red_flag_engine.scan_open_commitments(
        db, tenant_id, session_id=session_id, min_level=min_level
    )
    return [f.__dict__ for f in flags]


class LearningArtifactIn(BaseModel):
    task_summary: str
    intended_outcome: str
    observed_outcome: str
    outcome_quality: str  # succeeded | partially_succeeded | failed | inconclusive
    memory_write_recommendation: str  # fact|preference|commitment|pattern|...|none
    confidence: str = "medium"
    proof_refs: List[str] = Field(default_factory=list)
    failed_assumptions: List[str] = Field(default_factory=list)
    user_corrections: List[str] = Field(default_factory=list)
    source_refs: List[str] = Field(default_factory=list)
    reusable_pattern: Optional[str] = None
    anti_pattern: Optional[str] = None
    system_update_candidate: Optional[str] = None
    source_commitment_id: Optional[str] = None
    source_contract_id: Optional[str] = None


@router.post("/learning-artifacts", dependencies=[Depends(_verify_internal_key)])
def internal_write_learning_artifact(
    body: LearningArtifactIn,
    tenant_id: uuid.UUID = Depends(_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # agent_memory.agent_id is a non-null FK; anchor on the tenant's agent.
    from app.models.agent import Agent
    agent = (
        db.query(Agent)
        .filter(Agent.tenant_id == tenant_id)
        .order_by(Agent.id)
        .first()
    )
    if agent is None:
        raise HTTPException(status_code=422, detail="no agent for tenant")
    try:
        artifact = LearningArtifact(
            tenant_id=str(tenant_id),
            artifact_id=str(uuid.uuid4()),
            created_at=datetime.utcnow().isoformat() + "Z",
            source_refs=body.source_refs,
            task_summary=body.task_summary,
            intended_outcome=body.intended_outcome,
            observed_outcome=body.observed_outcome,
            outcome_quality=body.outcome_quality,
            proof_refs=body.proof_refs,
            failed_assumptions=body.failed_assumptions,
            user_corrections=body.user_corrections,
            memory_write_recommendation=body.memory_write_recommendation,
            confidence=body.confidence,
            source_commitment_id=body.source_commitment_id,
            source_contract_id=body.source_contract_id,
            reusable_pattern=body.reusable_pattern,
            anti_pattern=body.anti_pattern,
            system_update_candidate=body.system_update_candidate,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    aid = learning_artifact_io.write_learning_artifact(
        db, artifact=artifact, agent_id=agent.id, current_tenant_id=tenant_id
    )
    if not aid:
        raise HTTPException(status_code=500, detail="learning artifact write failed")
    return {"artifact_id": str(aid), "outcome_quality": artifact.outcome_quality}
