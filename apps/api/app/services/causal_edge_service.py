"""Service layer for causal edges with tenant isolation."""

from datetime import datetime
from typing import List, Optional
import uuid

from sqlalchemy.orm import Session

from app.models.causal_edge import CausalEdge
from app.schemas.causal_edge import CausalEdgeCreate


def _validate_assertion_ref(
    db: Session,
    tenant_id: uuid.UUID,
    assertion_id: Optional[uuid.UUID],
) -> None:
    if not assertion_id:
        return
    from app.models.world_state import WorldStateAssertion
    exists = db.query(WorldStateAssertion).filter(
        WorldStateAssertion.id == assertion_id,
        WorldStateAssertion.tenant_id == tenant_id,
    ).first()
    if not exists:
        raise ValueError(f"Assertion {assertion_id} not found in this tenant")


def record_causal_edge(
    db: Session,
    tenant_id: uuid.UUID,
    edge_in: CausalEdgeCreate,
) -> CausalEdge:
    """Record a causal hypothesis. If a matching cause→effect pair exists, corroborate it."""
    _validate_assertion_ref(db, tenant_id, edge_in.source_assertion_id)

    # Match on structured refs + summaries to avoid merging distinct events
    existing = (
        db.query(CausalEdge)
        .filter(
            CausalEdge.tenant_id == tenant_id,
            CausalEdge.cause_type == edge_in.cause_type.value,
            CausalEdge.cause_summary == edge_in.cause_summary,
            CausalEdge.cause_ref == edge_in.cause_ref,
            CausalEdge.effect_type == edge_in.effect_type.value,
            CausalEdge.effect_summary == edge_in.effect_summary,
            CausalEdge.effect_ref == edge_in.effect_ref,
            CausalEdge.status.in_(["hypothesis", "corroborated", "confirmed"]),
        )
        .first()
    )

    if existing:
        existing.observation_count += 1
        existing.confidence = min(1.0, existing.confidence + 0.1)
        if existing.observation_count >= 3 and existing.status == "hypothesis":
            existing.status = "corroborated"
        if existing.observation_count >= 10 and existing.status == "corroborated":
            existing.status = "confirmed"
        existing.updated_at = datetime.utcnow()
        if edge_in.mechanism and not existing.mechanism:
            existing.mechanism = edge_in.mechanism
        db.commit()
        db.refresh(existing)
        return existing

    edge = CausalEdge(
        tenant_id=tenant_id,
        cause_type=edge_in.cause_type.value,
        cause_ref=edge_in.cause_ref,
        cause_summary=edge_in.cause_summary,
        effect_type=edge_in.effect_type.value,
        effect_ref=edge_in.effect_ref,
        effect_summary=edge_in.effect_summary,
        confidence=edge_in.confidence,
        mechanism=edge_in.mechanism,
        source_assertion_id=edge_in.source_assertion_id,
        agent_slug=edge_in.agent_slug,
        status="hypothesis",
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return edge


def get_causal_edge(
    db: Session,
    tenant_id: uuid.UUID,
    edge_id: uuid.UUID,
) -> Optional[CausalEdge]:
    return (
        db.query(CausalEdge)
        .filter(CausalEdge.id == edge_id, CausalEdge.tenant_id == tenant_id)
        .first()
    )


def list_causal_edges(
    db: Session,
    tenant_id: uuid.UUID,
    cause_type: Optional[str] = None,
    effect_type: Optional[str] = None,
    status: Optional[str] = None,
    agent_slug: Optional[str] = None,
    limit: int = 100,
) -> List[CausalEdge]:
    q = db.query(CausalEdge).filter(CausalEdge.tenant_id == tenant_id)
    if cause_type:
        q = q.filter(CausalEdge.cause_type == cause_type)
    if effect_type:
        q = q.filter(CausalEdge.effect_type == effect_type)
    if status:
        q = q.filter(CausalEdge.status == status)
    if agent_slug:
        q = q.filter(CausalEdge.agent_slug == agent_slug)
    return q.order_by(CausalEdge.confidence.desc(), CausalEdge.observation_count.desc()).limit(limit).all()


def disprove_edge(
    db: Session,
    tenant_id: uuid.UUID,
    edge_id: uuid.UUID,
) -> Optional[CausalEdge]:
    edge = get_causal_edge(db, tenant_id, edge_id)
    if not edge:
        return None
    edge.status = "disproven"
    edge.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(edge)
    return edge


def get_causes_for_effect(
    db: Session,
    tenant_id: uuid.UUID,
    effect_summary: str,
    limit: int = 10,
) -> List[CausalEdge]:
    """Find what actions likely caused a given outcome."""
    return (
        db.query(CausalEdge)
        .filter(
            CausalEdge.tenant_id == tenant_id,
            CausalEdge.effect_summary == effect_summary,
            CausalEdge.status.in_(["hypothesis", "corroborated", "confirmed"]),
        )
        .order_by(CausalEdge.confidence.desc())
        .limit(limit)
        .all()
    )


def get_effects_for_cause(
    db: Session,
    tenant_id: uuid.UUID,
    cause_summary: str,
    limit: int = 10,
) -> List[CausalEdge]:
    """Predict what outcomes a given action might produce."""
    return (
        db.query(CausalEdge)
        .filter(
            CausalEdge.tenant_id == tenant_id,
            CausalEdge.cause_summary == cause_summary,
            CausalEdge.status.in_(["hypothesis", "corroborated", "confirmed"]),
        )
        .order_by(CausalEdge.confidence.desc())
        .limit(limit)
        .all()
    )
