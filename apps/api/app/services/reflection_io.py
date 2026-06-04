"""Nightly reflection I/O layer — O1 substrate.

Bridges the pure-function reflection service to the database via the
`agent_memory` substrate. Same shape and discipline as
`metacog_io.py` (M1 of #616):

  - tenant boundary enforcement on write (current_tenant_id arg
    matches the JWT-derived tenant; mismatched writes are refused)
  - anchor on agent_id (real FK to agents.id), persist content as
    JSON in agent_memory with memory_type='nightly_reflection'
  - read paths return [] on SQLAlchemy error rather than raising
  - UUID filter values cast to str so the bind processor works under
    both Postgres and the SQLite test shim (lesson from PR #617)
  - NO db.refresh(row) — AgentMemory.id has a Python-side uuid4
    default so row.id is already populated; refresh() trips on the
    SQLite test engine
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory
from app.schemas.reflection import NightlyReflection, ReflectionStep
from app.services.reflection import (
    REFLECTION_MEMORY_TYPE,
    REFLECTION_STEP_MEMORY_TYPE,
    deserialize_reflection,
    deserialize_reflection_step,
    serialize_reflection,
    serialize_reflection_step,
)

logger = logging.getLogger(__name__)


_RISK_IMPORTANCE = {
    "low": 0.35,
    "medium": 0.55,
    "high": 0.8,
    "irreversible": 1.0,
}


# ── Write path ────────────────────────────────────────────────────────


def write_reflection(
    db: Session,
    *,
    reflection: NightlyReflection,
    current_tenant_id: Optional[uuid.UUID] = None,
) -> Optional[uuid.UUID]:
    """Persist a NightlyReflection as an agent_memory row.

    `current_tenant_id` enforces the tenant boundary — same discipline
    as `metacog_io.write_prediction`. When the caller passes a
    JWT-derived tenant, a reflection whose serialized tenant_id
    doesn't match is refused. The offline-synthesis runtime (O2) will
    construct reflections with the loop-local tenant_id and may omit
    the kwarg.

    Anchors on agent_id — the synthesising agent (Luna by default).
    Best-effort: returns None on bad UUID or commit failure (no
    raise, mirroring the metacog IO contract).
    """
    try:
        tenant_id = uuid.UUID(reflection.tenant_id)
        agent_id = uuid.UUID(reflection.agent_id)
    except (ValueError, AttributeError) as exc:
        logger.warning(
            "reflection_io.write_reflection: bad tenant/agent UUID — %s",
            exc,
        )
        return None

    if current_tenant_id is not None and tenant_id != current_tenant_id:
        logger.warning(
            "reflection_io.write_reflection: tenant boundary violation — "
            "reflection.tenant_id=%s != current_tenant_id=%s; "
            "refusing write",
            tenant_id, current_tenant_id,
        )
        return None

    row = AgentMemory(
        tenant_id=tenant_id,
        agent_id=agent_id,
        memory_type=REFLECTION_MEMORY_TYPE,
        content=serialize_reflection(reflection),
        importance=reflection.confidence,
        confidence=1.0,
        # Tags carry both the day and the kind so the Postgres
        # JSON-contains pushdown in list_reflections can filter
        # without scanning every reflection in the tenant.
        tags=[
            "reflection",
            reflection.kind,
            f"day:{reflection.day}",
        ],
    )
    try:
        db.add(row)
        db.commit()
        # AgentMemory.id has Python-side uuid4 default — row.id is
        # already populated at construction. db.refresh() trips on
        # SQLite test engine (lesson from M1 #617).
        return row.id
    except SQLAlchemyError as exc:
        logger.warning(
            "reflection_io.write_reflection: commit failed, rolling back. "
            "err=%s",
            exc,
        )
        db.rollback()
        return None


def write_reflection_step(
    db: Session,
    *,
    step: ReflectionStep,
    current_tenant_id: Optional[uuid.UUID] = None,
) -> Optional[uuid.UUID]:
    """Persist a ReflectionStep as an agent_memory trace row.

    PR 1 is trace-only: writing a row never blocks the action by
    itself. The hard boundary here is tenant isolation. If a caller
    passes the JWT-derived tenant and the step carries a different
    tenant_id, the write is refused.
    """
    try:
        tenant_id = uuid.UUID(step.tenant_id)
        agent_id = uuid.UUID(step.agent_id)
    except (ValueError, AttributeError) as exc:
        logger.warning(
            "reflection_io.write_reflection_step: bad tenant/agent UUID — %s",
            exc,
        )
        return None

    if current_tenant_id is not None and tenant_id != current_tenant_id:
        logger.warning(
            "reflection_io.write_reflection_step: tenant boundary "
            "violation — step.tenant_id=%s != current_tenant_id=%s; "
            "refusing write",
            tenant_id, current_tenant_id,
        )
        return None

    row = AgentMemory(
        tenant_id=tenant_id,
        agent_id=agent_id,
        memory_type=REFLECTION_STEP_MEMORY_TYPE,
        content=serialize_reflection_step(step),
        importance=_RISK_IMPORTANCE.get(step.risk_level, 0.5),
        confidence=1.0,
        source="trusted_teammate_reflection_step",
        tags=[
            "reflection_step",
            step.action_kind,
            f"session:{step.session_id}",
            f"risk:{step.risk_level}",
            f"affordance:{step.recommended_affordance}",
        ],
    )
    try:
        db.add(row)
        db.commit()
        return row.id
    except SQLAlchemyError as exc:
        logger.warning(
            "reflection_io.write_reflection_step: commit failed, "
            "rolling back. err=%s",
            exc,
        )
        db.rollback()
        return None


# ── Read paths ────────────────────────────────────────────────────────


def list_reflections(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    day: Optional[str] = None,
    kind: Optional[str] = None,
    agent_id: Optional[uuid.UUID] = None,
) -> List[NightlyReflection]:
    """Return reflections in the tenant, optionally filtered.

    Filters:
      - day:    exact match on YYYY-MM-DD, applied after deserialization.
      - kind:   one of REFLECTION_KINDS, applied after deserialization.
      - agent_id: real FK column, pushed down to SQL.

    The tag column is generic JSON, not JSONB/ARRAY, so SQLAlchemy's
    tags.contains(...) does not compile to valid containment SQL on
    Postgres. Reflections are low-volume tenant rows, so day/kind stay
    as Python post-filters for consistent Postgres + SQLite behavior.

    UUID filters cast to str so the ORM's compiled bind processor
    works under both Postgres (native uuid column) and SQLite
    (TEXT-monkey-patched in tests). Without the cast,
    `Column == uuid.UUID(...)` silently returns zero rows under
    SQLite — PR #617 lesson.

    Ordered by created_at DESC so the morning-review surface sees
    freshest first.
    """
    tenant_id_param = str(tenant_id)
    agent_id_param = str(agent_id) if agent_id is not None else None
    try:
        q = db.query(AgentMemory).filter(
            AgentMemory.tenant_id == tenant_id_param,
            AgentMemory.memory_type == REFLECTION_MEMORY_TYPE,
        )
        if agent_id_param is not None:
            q = q.filter(AgentMemory.agent_id == agent_id_param)

        rows = q.order_by(AgentMemory.created_at.desc()).all()
    except SQLAlchemyError as exc:
        logger.warning(
            "reflection_io.list_reflections: query failed tenant=%s err=%s",
            tenant_id, exc,
        )
        return []

    out: List[NightlyReflection] = []
    for row in rows:
        r = deserialize_reflection(row.content)
        if r is None:
            continue
        if kind is not None and r.kind != kind:
            continue
        if day is not None and r.day != day:
            continue
        out.append(r)
    return out


def list_reflection_steps(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    session_id: Optional[str] = None,
    action_kind: Optional[str] = None,
    agent_id: Optional[uuid.UUID] = None,
) -> List[ReflectionStep]:
    """Return pre-action reflection traces for a tenant.

    Mirrors list_reflections: tenant/agent filters are pushed down,
    while tag-derived filters stay as Python post-filters because the
    tags column is generic JSON. Tenant_id is always caller-derived.
    """
    tenant_id_param = str(tenant_id)
    agent_id_param = str(agent_id) if agent_id is not None else None
    try:
        q = db.query(AgentMemory).filter(
            AgentMemory.tenant_id == tenant_id_param,
            AgentMemory.memory_type == REFLECTION_STEP_MEMORY_TYPE,
        )
        if agent_id_param is not None:
            q = q.filter(AgentMemory.agent_id == agent_id_param)

        rows = q.order_by(AgentMemory.created_at.desc()).all()
    except SQLAlchemyError as exc:
        logger.warning(
            "reflection_io.list_reflection_steps: query failed tenant=%s "
            "err=%s",
            tenant_id, exc,
        )
        return []

    out: List[ReflectionStep] = []
    for row in rows:
        step = deserialize_reflection_step(row.content)
        if step is None:
            continue
        if action_kind is not None and step.action_kind != action_kind:
            continue
        if session_id is not None and step.session_id != session_id:
            continue
        out.append(step)
    return out


def get_reflection_count(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    day: Optional[str] = None,
) -> int:
    """Convenience for the morning-dashboard surface: how many
    reflections did we synthesise (overall, or for a specific day)?

    Goes through `list_reflections` so the filtering semantics stay
    in one place; this is a count of N small rows once a day, not a
    hot path.
    """
    return len(list_reflections(db, tenant_id=tenant_id, day=day))


__all__ = [
    "write_reflection",
    "write_reflection_step",
    "list_reflections",
    "list_reflection_steps",
    "get_reflection_count",
]
