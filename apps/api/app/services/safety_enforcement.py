"""Central safety enforcement and evidence-pack persistence."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.models.safety_policy import SafetyEvidencePack
from app.schemas.safety_policy import (
    ActionType,
    PolicyDecision,
    SafetyEnforcementRequest,
    SafetyEnforcementResult,
)
from app.services import safety_policies


def _normalize_items(values: Optional[List[Any]]) -> List[Any]:
    return [value for value in (values or []) if value not in (None, "", [], {})]


def _evidence_required(result: SafetyEnforcementResult) -> bool:
    if result.decision in (
        PolicyDecision.REQUIRE_CONFIRMATION,
        PolicyDecision.REQUIRE_REVIEW,
        PolicyDecision.BLOCK,
    ):
        return True
    return result.risk_level.value in {"high", "critical"}


def _evidence_sufficient(request: SafetyEnforcementRequest) -> bool:
    has_context = any(
        (
            _normalize_items(request.world_state_facts),
            _normalize_items(request.recent_observations),
            _normalize_items(request.assumptions),
            _normalize_items(request.uncertainty_notes),
        )
    )
    has_proposed_action = bool(request.proposed_action)
    has_downside = bool((request.expected_downside or "").strip())
    return has_context and has_proposed_action and has_downside


def list_evidence_packs(
    db: Session,
    tenant_id: uuid.UUID,
    limit: int = 100,
) -> List[SafetyEvidencePack]:
    return (
        db.query(SafetyEvidencePack)
        .filter(SafetyEvidencePack.tenant_id == tenant_id)
        .order_by(SafetyEvidencePack.created_at.desc())
        .limit(limit)
        .all()
    )


def get_evidence_pack(
    db: Session,
    tenant_id: uuid.UUID,
    evidence_pack_id: uuid.UUID,
) -> Optional[SafetyEvidencePack]:
    return (
        db.query(SafetyEvidencePack)
        .filter(
            SafetyEvidencePack.id == evidence_pack_id,
            SafetyEvidencePack.tenant_id == tenant_id,
        )
        .first()
    )


def enforce_action(
    db: Session,
    tenant_id: uuid.UUID,
    request: SafetyEnforcementRequest,
    created_by: Optional[uuid.UUID] = None,
) -> SafetyEnforcementResult:
    evaluation = safety_policies.evaluate_action(
        db,
        tenant_id=tenant_id,
        action_type=request.action_type,
        action_name=request.action_name,
        channel=request.channel,
    )
    evaluation_data = (
        evaluation.model_dump()
        if hasattr(evaluation, "model_dump")
        else evaluation.dict()
    )

    result = SafetyEnforcementResult(
        **evaluation_data,
        evidence_required=False,
        evidence_sufficient=False,
        evidence_pack_id=None,
    )
    result.evidence_required = _evidence_required(result)
    result.evidence_sufficient = (
        _evidence_sufficient(request) if result.evidence_required else True
    )

    if result.evidence_required and not result.evidence_sufficient:
        if result.decision in (
            PolicyDecision.ALLOW,
            PolicyDecision.ALLOW_WITH_LOGGING,
            PolicyDecision.REQUIRE_CONFIRMATION,
        ):
            result.decision = PolicyDecision.REQUIRE_REVIEW
            result.rationale = (
                f"{result.rationale} Evidence pack is incomplete for this sensitive action."
            )

    if result.evidence_required:
        evidence_pack = SafetyEvidencePack(
            tenant_id=tenant_id,
            action_type=request.action_type.value,
            action_name=request.action_name,
            channel=request.channel,
            decision=result.decision.value,
            decision_source=result.decision_source,
            risk_class=result.risk_class.value,
            risk_level=result.risk_level.value,
            evidence_required=result.evidence_required,
            evidence_sufficient=result.evidence_sufficient,
            world_state_facts=_normalize_items(request.world_state_facts),
            recent_observations=_normalize_items(request.recent_observations),
            assumptions=_normalize_items(request.assumptions),
            uncertainty_notes=_normalize_items(request.uncertainty_notes),
            proposed_action=request.proposed_action,
            expected_downside=request.expected_downside,
            context_summary=request.context_summary,
            context_ref=request.context_ref,
            agent_slug=request.agent_slug,
            created_by=created_by,
        )
        db.add(evidence_pack)
        db.commit()
        db.refresh(evidence_pack)
        result.evidence_pack_id = evidence_pack.id

    return result
