"""IO wrapper for the value layer — reads + writes + audited consult.

Pure matching lives in ``agent_value_set.py``. This module is the
production boundary every consultation-point caller uses:

  - ``read_value_set``: latest-wins read of the (tenant, agent)
    value set from agent_memory (memory_type='value_set').
  - ``write_value_set``: append-only INSERT with monotonic version.
    Concurrent writers collide on the migration-144 unique index;
    the writer retries with version+1.
  - ``is_value_layer_enabled``: per-tenant kill-switch lookup
    against tenant_features.value_layer_enabled.
  - ``consult_with_audit``: read enabled+set, call pure ``consult()``,
    record verdict to the audit log, return verdict.
  - Five thin shim callers — ``consult_routing``, ``consult_tool``,
    ``consult_reflection``, ``appraise_user_signal_with_values``,
    ``synthesize_value_observations`` — each translates its point's
    args into the canonical (action, intent) shape consult expects.

Reflection-kind-aware intent flag (design §4.2 round-3 fix):
``risk`` / ``idea`` / ``tension`` / ``creative`` are descriptive →
``intent='read'``. ``next_move`` / ``value_proposal`` propose an
action → ``intent='mutate'``. That's what makes the §8 criterion
"reflection mentions protect item but proposes touching it gets
blocked at write time" actually fire.

Audit logging is Python-logger-based for v1 (structured log line
per consult verdict). A dedicated ``audit_logs`` table write is a
follow-up; not part of the consult contract because the wrapper
must stay cheap on the chat hot path.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory
from app.services.agent_value_set import (
    AgentValueSet,
    ValueVerdict,
    consult,
)

log = logging.getLogger(__name__)

VALUE_SET_MEMORY_TYPE = "value_set"

# Reflection kinds that PROPOSE an action vs. those that describe.
# Used by ``consult_reflection`` to pick the intent flag.
_MUTATING_REFLECTION_KINDS = frozenset({"next_move", "value_proposal"})


# ── Tenant kill-switch ────────────────────────────────────────────────


def is_value_layer_enabled(
    db: Session,
    tenant_id: uuid.UUID,
) -> bool:
    """Read ``tenant_features.value_layer_enabled``. Missing row →
    False (defensive default OFF). SQL failure → False. Mirrors the
    nightly_reflection kill-switch from #631."""
    try:
        from app.models.tenant_features import TenantFeatures
        row = (
            db.query(TenantFeatures)
            .filter(TenantFeatures.tenant_id == str(tenant_id))
            .first()
        )
        if row is None:
            return False
        return bool(getattr(row, "value_layer_enabled", False))
    except SQLAlchemyError as exc:
        log.warning(
            "agent_value_set_io.is_value_layer_enabled: lookup failed "
            "tenant=%s err=%s; treating as OFF",
            tenant_id, exc,
        )
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "agent_value_set_io.is_value_layer_enabled: unexpected err "
            "tenant=%s err=%s; treating as OFF",
            tenant_id, exc,
        )
        return False


# ── Read / write ──────────────────────────────────────────────────────


def read_value_set(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> AgentValueSet:
    """Latest-wins read. Returns the most recent value-set row's
    parsed body, or ``AgentValueSet.empty()`` if none exists OR if
    the latest row's content can't be parsed (defensive — bad data
    on disk shouldn't crash the chat hot path)."""
    try:
        row = (
            db.query(AgentMemory.content)
            .filter(
                AgentMemory.tenant_id == str(tenant_id),
                AgentMemory.agent_id == str(agent_id),
                AgentMemory.memory_type == VALUE_SET_MEMORY_TYPE,
            )
            .order_by(
                AgentMemory.updated_at.desc().nullslast(),
                AgentMemory.created_at.desc(),
            )
            .first()
        )
    except SQLAlchemyError as exc:
        log.warning(
            "read_value_set: SQL failure tenant=%s agent=%s err=%s; "
            "returning empty",
            tenant_id, agent_id, exc,
        )
        return AgentValueSet.empty()

    if row is None or not row[0]:
        return AgentValueSet.empty()

    try:
        data = json.loads(row[0])
    except (TypeError, ValueError) as exc:
        log.warning(
            "read_value_set: malformed JSON in latest row tenant=%s "
            "agent=%s err=%s; returning empty (safer default)",
            tenant_id, agent_id, exc,
        )
        return AgentValueSet.empty()

    try:
        return AgentValueSet.from_dict(data)
    except (TypeError, ValueError) as exc:
        log.warning(
            "read_value_set: malformed value-set dict tenant=%s "
            "agent=%s err=%s; returning empty",
            tenant_id, agent_id, exc,
        )
        return AgentValueSet.empty()


def _next_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> int:
    """Read the current max version for this (tenant, agent) and
    return +1. The unique index from migration 144 catches collisions
    if two writers race here; the caller retries."""
    try:
        rows = (
            db.query(AgentMemory.content)
            .filter(
                AgentMemory.tenant_id == str(tenant_id),
                AgentMemory.agent_id == str(agent_id),
                AgentMemory.memory_type == VALUE_SET_MEMORY_TYPE,
            )
            .all()
        )
    except SQLAlchemyError:
        return 1

    max_v = 0
    for r in rows:
        if not r[0]:
            continue
        try:
            v = int((json.loads(r[0]) or {}).get("version") or 0)
        except (TypeError, ValueError):
            continue
        if v > max_v:
            max_v = v
    return max_v + 1


def write_value_set(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    protect: List[Dict[str, Any]],
    pursue: List[Dict[str, Any]],
    avoid: List[Dict[str, Any]],
    max_retries: int = 3,
) -> Optional[AgentValueSet]:
    """Append-only write. Computes the next version, INSERTs a new
    agent_memory row, returns the resulting AgentValueSet. On unique-
    index collision (concurrent writer beat us), retries up to
    max_retries times with version+1 each time.

    Returns the persisted AgentValueSet on success or None on
    repeated collision / SQL failure. Caller surfaces a 503 to
    the operator in that case."""
    now = datetime.now(timezone.utc).isoformat()
    for attempt in range(max_retries):
        version = _next_version(db, tenant_id=tenant_id, agent_id=agent_id)
        body = {
            "protect": protect,
            "pursue": pursue,
            "avoid": avoid,
            "version": version,
            "updated_at": now,
        }
        row = AgentMemory(
            tenant_id=tenant_id,
            agent_id=agent_id,
            memory_type=VALUE_SET_MEMORY_TYPE,
            content=json.dumps(body),
            importance=1.0,
            confidence=1.0,
            tags=["value_set", f"version:{version}"],
        )
        try:
            db.add(row)
            db.commit()
            return AgentValueSet.from_dict(body)
        except IntegrityError as exc:
            db.rollback()
            log.info(
                "write_value_set: version collision attempt=%s "
                "tenant=%s agent=%s version=%s err=%s",
                attempt, tenant_id, agent_id, version, exc,
            )
            continue
        except SQLAlchemyError as exc:
            log.warning(
                "write_value_set: SQL failure tenant=%s agent=%s err=%s",
                tenant_id, agent_id, exc,
            )
            db.rollback()
            return None
    log.warning(
        "write_value_set: gave up after %s retries tenant=%s agent=%s",
        max_retries, tenant_id, agent_id,
    )
    return None


# ── Audited consult + 5 shim callers ──────────────────────────────────


def _record_verdict(
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    action: dict,
    verdict: ValueVerdict,
) -> None:
    """Structured log of the verdict. v1 ships logging-only; a
    dedicated audit_logs table write is a Phase 1.5 follow-up
    (alongside the break-glass endpoint).

    Logged at INFO for block/warn (operator may want to see these
    in dashboards) and DEBUG for plain allow (otherwise the log
    drowns)."""
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "decision": verdict.decision,
        "reason": verdict.reason,
        "point": verdict.consultation_point,
        "matched_slug": (
            verdict.matched_item.get("slug")
            if verdict.matched_item else None
        ),
    }
    if verdict.decision in ("block", "warn"):
        log.info("value_layer.verdict %s", payload)
    else:
        log.debug("value_layer.verdict %s", payload)


def consult_with_audit(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    action: dict,
    point: str,
    intent: str,
) -> ValueVerdict:
    """Production boundary: read kill-switch + value set, call
    pure consult, record verdict.

    Every consultation-point caller invokes this (directly or
    through one of the 5 shims below)."""
    enabled = is_value_layer_enabled(db, tenant_id)
    value_set = read_value_set(db, tenant_id=tenant_id, agent_id=agent_id)
    verdict = consult(
        action, value_set,
        point=point, intent=intent, enabled=enabled,
    )
    _record_verdict(
        tenant_id=tenant_id, agent_id=agent_id,
        action=action, verdict=verdict,
    )
    return verdict


# Five shim callers — each translates its point's args into the
# canonical (action, intent) shape ``consult`` expects.


def consult_routing(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    intent_text: str,
    intent_classifier_says_mutate: bool = False,
) -> ValueVerdict:
    """Pre-dispatch routing gate (design §4.2 point 1)."""
    return consult_with_audit(
        db,
        tenant_id=tenant_id,
        agent_id=agent_id,
        action={"text": intent_text},
        point="routing",
        intent="mutate" if intent_classifier_says_mutate else "read",
    )


def consult_tool(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    tool_name: str,
    args: dict,
    is_mutating: bool,
) -> ValueVerdict:
    """Tool-call gate (design §4.2 point 2). The caller knows whether
    the tool mutates state (the MCP tool registry can carry this
    metadata; for now the caller passes the flag)."""
    return consult_with_audit(
        db,
        tenant_id=tenant_id,
        agent_id=agent_id,
        action={"tool": tool_name, "args": args},
        point="tool",
        intent="mutate" if is_mutating else "read",
    )


def consult_reflection(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    reflection_kind: str,
    reflection_content: str,
) -> ValueVerdict:
    """Reflection validator (design §4.2 point 3 + round-3 fix).

    Reflection kinds drive intent:
      - risk / idea / tension / creative → 'read' (descriptive,
        mention is fine)
      - next_move / value_proposal → 'mutate' (proposes action,
        protect matches must block)
    """
    intent = (
        "mutate" if reflection_kind in _MUTATING_REFLECTION_KINDS
        else "read"
    )
    return consult_with_audit(
        db,
        tenant_id=tenant_id,
        agent_id=agent_id,
        action={"kind": reflection_kind, "content": reflection_content},
        point="reflection",
        intent=intent,
    )


def appraise_user_signal_with_values(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    user_text: str,
) -> ValueVerdict:
    """User-signal appraisal hook (design §4.2 point 4).

    Returns the verdict; the caller (emotion_engine PR) decides
    whether to scale the PAD-pleasure delta when the verdict
    surfaces a ``pursue`` match (1.5x USER_SIGNAL_PLEASURE_GAIN,
    capped at TOOL_OUTCOME_PLEASURE_GAIN per design §4.2 Q3
    round-1 resolution).
    """
    return consult_with_audit(
        db,
        tenant_id=tenant_id,
        agent_id=agent_id,
        action={"text": user_text},
        point="user_signal",
        intent="read",
    )


def synthesize_value_observations(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    proposed_kind: str,
    proposed_content: str,
) -> ValueVerdict:
    """Phase 2 synthesis hook (design §4.2 point 5). Used by the
    reflection workflow when emitting a value_proposal kind — the
    proposal itself gets consulted to catch self-referential
    contradictions (e.g. a proposal to remove a protect that itself
    mentions the protected entity).

    Phase 1 ships the hook; the synthesize_reflections workflow
    body in Phase 2 wires it in.
    """
    intent = (
        "mutate" if proposed_kind in _MUTATING_REFLECTION_KINDS
        else "read"
    )
    return consult_with_audit(
        db,
        tenant_id=tenant_id,
        agent_id=agent_id,
        action={"kind": proposed_kind, "content": proposed_content},
        point="synthesis",
        intent=intent,
    )


__all__ = [
    "VALUE_SET_MEMORY_TYPE",
    "is_value_layer_enabled",
    "read_value_set",
    "write_value_set",
    "consult_with_audit",
    "consult_routing",
    "consult_tool",
    "consult_reflection",
    "appraise_user_signal_with_values",
    "synthesize_value_observations",
]
