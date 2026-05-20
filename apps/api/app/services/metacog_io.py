"""Metacognition I/O layer (M1 of #616).

Bridges the pure-function metacog service to the database via the
`agent_memory` substrate — same pattern as team_engine_io (#608).
Write paths are best-effort: SQLAlchemy errors roll back and return
None. Read paths are tenant-scoped.

Phase 1 ships read/write helpers + tenant boundary enforcement. The
runtime wire (Phase 2 — M2 hook in cli_session_manager) is a separate
PR so the substrate can land first and be exercised by tests without
the chat hot path in the loop.
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory
from app.schemas.metacog import (
    ConfidencePrediction,
    MetacogTrace,
    OutcomeObservation,
)
from app.services.metacog import (
    OBSERVATION_MEMORY_TYPE,
    PREDICTION_MEMORY_TYPE,
    deserialize_observation,
    deserialize_prediction,
    join_traces,
    serialize_observation,
    serialize_prediction,
)

logger = logging.getLogger(__name__)


# ── Write paths ───────────────────────────────────────────────────────


def write_prediction(
    db: Session,
    *,
    prediction: ConfidencePrediction,
    current_tenant_id: Optional[uuid.UUID] = None,
) -> Optional[uuid.UUID]:
    """Persist a ConfidencePrediction as an agent_memory row.

    `current_tenant_id` enforces the tenant boundary — same pattern
    Luna locked in for team_engine_io.write_role_contract: when the
    caller (HTTP / RL hook) passes the JWT-derived tenant, we refuse
    to write a row whose serialized tenant_id doesn't match. Internal
    callers that construct the prediction with the loop-local
    tenant_id can omit the argument.

    Best-effort: returns None on bad UUID or commit failure.
    """
    try:
        tenant_id = uuid.UUID(prediction.tenant_id)
        agent_id = uuid.UUID(prediction.agent_id)
    except (ValueError, AttributeError) as exc:
        logger.warning(
            "metacog_io.write_prediction: bad tenant/agent UUID — %s",
            exc,
        )
        return None

    if current_tenant_id is not None and tenant_id != current_tenant_id:
        logger.warning(
            "metacog_io.write_prediction: tenant boundary violation — "
            "prediction.tenant_id=%s != current_tenant_id=%s; "
            "refusing write",
            tenant_id, current_tenant_id,
        )
        return None

    row = AgentMemory(
        tenant_id=tenant_id,
        agent_id=agent_id,
        memory_type=PREDICTION_MEMORY_TYPE,
        content=serialize_prediction(prediction),
        importance=prediction.predicted_confidence,
        confidence=1.0,
        tags=["metacog", "prediction", prediction.decision_kind],
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except SQLAlchemyError as exc:
        logger.warning(
            "metacog_io.write_prediction: commit failed, rolling back. "
            "err=%s",
            exc,
        )
        db.rollback()
        return None


def write_observation(
    db: Session,
    *,
    observation: OutcomeObservation,
    agent_id: uuid.UUID,
    current_tenant_id: Optional[uuid.UUID] = None,
) -> Optional[uuid.UUID]:
    """Persist an OutcomeObservation as an agent_memory row.

    `agent_id` is passed separately because OutcomeObservation
    intentionally doesn't carry the agent_id — the observation binds
    to a decision_id, and the decision_id already resolves to an
    agent via its paired ConfidencePrediction. We still need a real
    agent_id for the agent_memory FK (no marker UUIDs — Luna review
    BLOCKER lesson from #604).

    Same tenant-boundary discipline as write_prediction.
    """
    try:
        tenant_id = uuid.UUID(observation.tenant_id)
    except (ValueError, AttributeError) as exc:
        logger.warning(
            "metacog_io.write_observation: bad tenant UUID — %s", exc
        )
        return None

    if current_tenant_id is not None and tenant_id != current_tenant_id:
        logger.warning(
            "metacog_io.write_observation: tenant boundary violation — "
            "observation.tenant_id=%s != current_tenant_id=%s; "
            "refusing write",
            tenant_id, current_tenant_id,
        )
        return None

    # Rescale [-1, 1] reward to [0, 1] for the importance column.
    importance = max(0.0, min(1.0, (observation.actual_reward + 1.0) / 2.0))

    row = AgentMemory(
        tenant_id=tenant_id,
        agent_id=agent_id,
        memory_type=OBSERVATION_MEMORY_TYPE,
        content=serialize_observation(observation),
        importance=importance,
        confidence=1.0,
        tags=(
            ["metacog", "observation", "error"]
            if observation.error else ["metacog", "observation"]
        ),
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except SQLAlchemyError as exc:
        logger.warning(
            "metacog_io.write_observation: commit failed, rolling back. "
            "err=%s",
            exc,
        )
        db.rollback()
        return None


# ── Read paths ────────────────────────────────────────────────────────


def list_predictions(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: Optional[uuid.UUID] = None,
    decision_kind: Optional[str] = None,
) -> List[ConfidencePrediction]:
    """Return predictions in the tenant, optionally filtered to a
    specific agent and/or decision_kind. Order by created_at DESC so
    consumers see freshest first."""
    try:
        q = db.query(AgentMemory).filter(
            AgentMemory.tenant_id == tenant_id,
            AgentMemory.memory_type == PREDICTION_MEMORY_TYPE,
        )
        if agent_id is not None:
            q = q.filter(AgentMemory.agent_id == agent_id)
        rows = q.order_by(AgentMemory.created_at.desc()).all()
    except SQLAlchemyError as exc:
        logger.warning(
            "metacog_io.list_predictions: query failed tenant=%s err=%s",
            tenant_id, exc,
        )
        return []

    out: List[ConfidencePrediction] = []
    for row in rows:
        p = deserialize_prediction(row.content)
        if p is None:
            continue
        if decision_kind is not None and p.decision_kind != decision_kind:
            continue
        out.append(p)
    return out


def list_observations(
    db: Session,
    *,
    tenant_id: uuid.UUID,
) -> List[OutcomeObservation]:
    """Return observations in the tenant. Order by created_at DESC."""
    try:
        rows = (
            db.query(AgentMemory)
            .filter(
                AgentMemory.tenant_id == tenant_id,
                AgentMemory.memory_type == OBSERVATION_MEMORY_TYPE,
            )
            .order_by(AgentMemory.created_at.desc())
            .all()
        )
    except SQLAlchemyError as exc:
        logger.warning(
            "metacog_io.list_observations: query failed tenant=%s err=%s",
            tenant_id, exc,
        )
        return []

    out: List[OutcomeObservation] = []
    for row in rows:
        o = deserialize_observation(row.content)
        if o is None:
            continue
        out.append(o)
    return out


def list_traces(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: Optional[uuid.UUID] = None,
    decision_kind: Optional[str] = None,
) -> List[MetacogTrace]:
    """Convenience: list_predictions + list_observations + join_traces.

    Filters apply to predictions; observations are joined by
    decision_id regardless of their own metadata. Unpaired predictions
    and observations are silently dropped (handled by join_traces).
    """
    predictions = list_predictions(
        db,
        tenant_id=tenant_id,
        agent_id=agent_id,
        decision_kind=decision_kind,
    )
    observations = list_observations(db, tenant_id=tenant_id)
    return join_traces(predictions, observations)


__all__ = [
    "write_prediction",
    "write_observation",
    "list_predictions",
    "list_observations",
    "list_traces",
]
