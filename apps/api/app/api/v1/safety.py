"""Tenant safety governance APIs."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.safety_policy import (
    ActionType,
    SafetyActionCatalogEntry,
    SafetyActionEvaluation,
    SafetyActionEvaluationRequest,
    SafetyEnforcementRequest,
    SafetyEnforcementResult,
    SafetyEvidencePack,
    TenantActionPolicy,
    TenantActionPolicyUpsert,
)
from app.services import safety_enforcement as enforcement_service
from app.services import safety_policies as service

router = APIRouter()


@router.get("/actions", response_model=List[SafetyActionCatalogEntry])
def list_actions(
    channel: str = Query(default="web"),
    action_type: Optional[ActionType] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List governed actions with tenant-specific effective policy for a channel."""
    return service.list_action_catalog(
        db,
        tenant_id=current_user.tenant_id,
        channel=channel,
        action_type=action_type,
    )


@router.get("/policies", response_model=List[TenantActionPolicy])
def list_policies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List explicit tenant policy overrides."""
    return service.list_tenant_policies(db, current_user.tenant_id)


@router.put("/policies", response_model=TenantActionPolicy)
def upsert_policy(
    policy_in: TenantActionPolicyUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create or update a tenant/channel override for a governed action."""
    return service.upsert_tenant_policy(
        db,
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        policy_in=policy_in,
    )


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a tenant policy override."""
    deleted = service.delete_tenant_policy(db, current_user.tenant_id, policy_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy override not found")
    return None


@router.post("/evaluate", response_model=SafetyActionEvaluation)
def evaluate_action(
    request: SafetyActionEvaluationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Evaluate the effective policy for a governed action on a channel."""
    return service.evaluate_action(
        db,
        tenant_id=current_user.tenant_id,
        action_type=request.action_type,
        action_name=request.action_name,
        channel=request.channel,
    )


@router.post("/enforce", response_model=SafetyEnforcementResult)
def enforce_action(
    request: SafetyEnforcementRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Evaluate and persist an evidence-backed safety enforcement decision."""
    return enforcement_service.enforce_action(
        db,
        tenant_id=current_user.tenant_id,
        request=request,
        created_by=current_user.id,
    )


@router.get("/evidence-packs", response_model=List[SafetyEvidencePack])
def list_evidence_packs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List recent safety evidence packs for the current tenant."""
    return enforcement_service.list_evidence_packs(db, current_user.tenant_id, limit=limit)


@router.get("/evidence-packs/{evidence_pack_id}", response_model=SafetyEvidencePack)
def get_evidence_pack(
    evidence_pack_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a single evidence pack by id."""
    evidence_pack = enforcement_service.get_evidence_pack(db, current_user.tenant_id, evidence_pack_id)
    if not evidence_pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence pack not found")
    return evidence_pack
