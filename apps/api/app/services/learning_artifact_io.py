"""Learning-artifact write/read path (plan 2026-06-08 §7) — PR4.

A ``LearningArtifact`` is a distilled, reusable post-task learning record. It is
NOT a new table: per the review (P1-2), soft learning records live in
``agent_memory`` with a ``memory_type`` discriminator — the same lane as
metacognition (``metacog_io``) and reflections (``reflection_io``). This keeps
artifacts semantically searchable and avoids a parallel store.

Tenant isolation is the hard boundary (same discipline as ``reflection_io``):
an artifact whose tenant_id doesn't match the caller's JWT tenant is refused.
Writes are best-effort (no raise) so a flaky memory write never aborts the task.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory
from app.schemas.accountable_learning import LearningArtifact

logger = logging.getLogger(__name__)

LEARNING_ARTIFACT_MEMORY_TYPE = "learning_artifact"

_CONFIDENCE_IMPORTANCE = {"low": 0.3, "medium": 0.6, "high": 0.9}


def serialize_learning_artifact(artifact: LearningArtifact) -> str:
    return json.dumps(artifact.to_dict(), separators=(",", ":"), sort_keys=True)


def deserialize_learning_artifact(content: str) -> dict:
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {}


def write_learning_artifact(
    db: Session,
    *,
    artifact: LearningArtifact,
    agent_id: uuid.UUID,
    current_tenant_id: Optional[uuid.UUID] = None,
) -> Optional[uuid.UUID]:
    """Persist a LearningArtifact as an agent_memory row. Best-effort.

    Tags carry outcome quality, the recommended memory category, a
    ``has_failed_assumption`` marker, and source contract/commitment ids so the
    artifact is queryable without a JSON pushdown (SQLite-shim safe).
    """
    try:
        tenant_id = uuid.UUID(str(artifact.tenant_id))
    except (ValueError, AttributeError) as exc:
        logger.warning("learning_artifact_io: bad tenant UUID — %s", exc)
        return None

    if current_tenant_id is not None and tenant_id != current_tenant_id:
        logger.warning(
            "learning_artifact_io: tenant boundary violation — "
            "artifact.tenant_id=%s != current_tenant_id=%s; refusing write",
            tenant_id, current_tenant_id,
        )
        return None

    tags: List[str] = [
        "learning_artifact",
        f"quality:{artifact.outcome_quality}",
        f"mem:{artifact.memory_write_recommendation}",
    ]
    if artifact.failed_assumptions:
        tags.append("has_failed_assumption")
    if artifact.source_contract_id:
        tags.append(f"contract:{artifact.source_contract_id}")
    if artifact.source_commitment_id:
        tags.append(f"commitment:{artifact.source_commitment_id}")

    row = AgentMemory(
        tenant_id=tenant_id,
        agent_id=agent_id,
        memory_type=LEARNING_ARTIFACT_MEMORY_TYPE,
        content=serialize_learning_artifact(artifact),
        importance=_CONFIDENCE_IMPORTANCE.get(artifact.confidence, 0.5),
        confidence=1.0,
        source="accountable_learning",
        tags=tags,
    )
    try:
        db.add(row)
        db.commit()
        # AgentMemory.id has a Python-side uuid4 default; db.refresh() trips on
        # the SQLite test engine (M1 #617), so read row.id directly.
        return row.id
    except SQLAlchemyError as exc:
        logger.warning("learning_artifact_io: commit failed (%s); rolling back", exc)
        db.rollback()
        return None


def list_learning_artifacts(
    db: Session,
    tenant_id: uuid.UUID,
    agent_id: Optional[uuid.UUID] = None,
    limit: int = 100,
) -> List[dict]:
    """Return recent learning artifacts (deserialized) for a tenant."""
    q = db.query(AgentMemory).filter(
        AgentMemory.tenant_id == tenant_id,
        AgentMemory.memory_type == LEARNING_ARTIFACT_MEMORY_TYPE,
    )
    if agent_id is not None:
        q = q.filter(AgentMemory.agent_id == agent_id)
    rows = q.order_by(AgentMemory.created_at.desc()).limit(limit).all()
    return [deserialize_learning_artifact(r.content) for r in rows]


def query_failed_assumptions(
    db: Session,
    tenant_id: uuid.UUID,
    limit: int = 100,
) -> List[str]:
    """Flattened, de-duplicated failed assumptions for a tenant.

    Surfaced on similar tasks so the same mistake doesn't repeat (plan §7/§9).
    Filters in Python on the deserialized content to stay correct on both
    PostgreSQL and the SQLite test shim.
    """
    seen: List[str] = []
    for art in list_learning_artifacts(db, tenant_id, limit=limit):
        for fa in art.get("failed_assumptions", []) or []:
            if fa not in seen:
                seen.append(fa)
    return seen


__all__ = [
    "LEARNING_ARTIFACT_MEMORY_TYPE",
    "serialize_learning_artifact",
    "deserialize_learning_artifact",
    "write_learning_artifact",
    "list_learning_artifacts",
    "query_failed_assumptions",
]
