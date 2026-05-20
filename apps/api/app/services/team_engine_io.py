"""I/O layer for the Teamwork Engine — Phase 1 PR A (read paths only).

Bridges the pure-functional team_engine to agent_memory rows. Mirrors
the structure of `emotion_engine_io.py`. No write paths yet — write
paths land in PR B.

Substrate reuse rationale: per the design doc § "Substrate" + the
operator's "reuse components" directive, Phase 1 piggybacks on the
existing `agent_memory` table using `memory_type` as a discriminator.
Phase 2 may carve a dedicated table if usage proves it's needed.
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory
from app.schemas.team import TeamNorm, TeamRoleContract
from app.services.team_engine import (
    NORM_MEMORY_TYPE,
    ROLE_CONTRACT_MEMORY_TYPE,
    deserialize_norm,
    deserialize_role_contract,
    evaluate_role_contract,
    select_norm,
)

logger = logging.getLogger(__name__)


# ── Role-contract read paths ──────────────────────────────────────────


def list_role_contracts(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: Optional[uuid.UUID] = None,
) -> List[TeamRoleContract]:
    """Return all role contracts for a tenant, optionally filtered to a
    single agent. Malformed rows are skipped silently — read path must
    not crash on a single bad blob.

    Tenant-scoped: never returns contracts from another tenant even
    when callers pass the wrong agent_id. Same pattern as memories.py.
    """
    try:
        query = (
            db.query(AgentMemory)
            .filter(
                AgentMemory.tenant_id == tenant_id,
                AgentMemory.memory_type == ROLE_CONTRACT_MEMORY_TYPE,
            )
        )
        if agent_id is not None:
            query = query.filter(AgentMemory.agent_id == agent_id)
        rows = query.all()
    except SQLAlchemyError as exc:
        logger.warning(
            "team_engine_io.list_role_contracts: query failed for tenant_id=%s err=%s",
            tenant_id, exc,
        )
        return []

    out: List[TeamRoleContract] = []
    for row in rows:
        contract = deserialize_role_contract(row.content)
        if contract is None:
            logger.debug(
                "team_engine_io: skipping malformed role-contract row id=%s",
                row.id,
            )
            continue
        out.append(contract)
    return out


def get_active_role(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    scope: str,
) -> Optional[TeamRoleContract]:
    """Convenience: list_role_contracts + evaluate_role_contract. Returns
    the contract currently in effect for the given (agent, scope), or
    None if no contract applies."""
    contracts = list_role_contracts(db, tenant_id=tenant_id, agent_id=agent_id)
    return evaluate_role_contract(contracts, agent_id=str(agent_id), scope=scope)


# ── Norm read paths ───────────────────────────────────────────────────


def list_norms(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    coalition_id: Optional[uuid.UUID] = None,
) -> List[TeamNorm]:
    """Return all norms relevant to a coalition. Includes both the
    coalition-specific norms (if coalition_id provided) AND the
    tenant-wide defaults. The select_norm helper resolves precedence
    when multiple match a key.

    Tenant-scoped.
    """
    try:
        # Phase 1 stores norms in agent_memory with memory_type=NORM_MEMORY_TYPE
        # and the coalition_id encoded inside the JSON blob. We can't
        # filter at the SQL level on that JSON field portably across
        # backends without a JSONB ->> operator; fetch all candidates
        # for the tenant + filter in Python. Volume is bounded by the
        # number of norms per tenant (small) so this is fine for Phase 1.
        rows = (
            db.query(AgentMemory)
            .filter(
                AgentMemory.tenant_id == tenant_id,
                AgentMemory.memory_type == NORM_MEMORY_TYPE,
            )
            .all()
        )
    except SQLAlchemyError as exc:
        logger.warning(
            "team_engine_io.list_norms: query failed for tenant_id=%s err=%s",
            tenant_id, exc,
        )
        return []

    out: List[TeamNorm] = []
    coalition_id_str = str(coalition_id) if coalition_id else None
    for row in rows:
        norm = deserialize_norm(row.content)
        if norm is None:
            logger.debug(
                "team_engine_io: skipping malformed norm row id=%s", row.id
            )
            continue
        # Tenant-wide default (norm.coalition_id is None) OR matches
        # the requested coalition. Other coalitions' norms aren't
        # relevant to this view.
        if norm.coalition_id is None or norm.coalition_id == coalition_id_str:
            out.append(norm)
    return out


def get_norm_value(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    key: str,
    coalition_id: Optional[uuid.UUID] = None,
) -> Optional[object]:
    """Convenience: list_norms + select_norm + extract value. Returns
    the resolved value (coalition-specific override > tenant-wide
    default > None) or None if no norm matches."""
    norms = list_norms(db, tenant_id=tenant_id, coalition_id=coalition_id)
    selected = select_norm(
        norms,
        key=key,
        coalition_id=str(coalition_id) if coalition_id else None,
    )
    return selected.value if selected else None


# ── Write paths (Phase 1 PR B) ────────────────────────────────────────


def write_role_contract(
    db: Session,
    *,
    contract: TeamRoleContract,
) -> Optional[uuid.UUID]:
    """Persist a TeamRoleContract as an agent_memory row with
    memory_type=team_role_contract. Returns the new row's id on
    success, None on failure.

    Best-effort: catches SQLAlchemyError, rolls back, returns None.
    Idempotency is the caller's responsibility — see
    bootstrap_canonical_role_split for the idempotent variant.
    """
    from app.services.team_engine import serialize_role_contract

    try:
        tenant_id = uuid.UUID(contract.tenant_id)
        agent_id = uuid.UUID(contract.agent_id)
    except (ValueError, AttributeError) as exc:
        logger.warning(
            "team_engine_io.write_role_contract: bad tenant/agent UUID — %s",
            exc,
        )
        return None

    row = AgentMemory(
        tenant_id=tenant_id,
        agent_id=agent_id,
        memory_type=ROLE_CONTRACT_MEMORY_TYPE,
        content=serialize_role_contract(contract),
        importance=0.8,
        confidence=1.0,
        tags=["team_engine", "role_contract", contract.scope],
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except SQLAlchemyError as exc:
        logger.warning(
            "team_engine_io.write_role_contract: commit failed, rolling back. err=%s",
            exc,
        )
        db.rollback()
        return None


def write_norm(
    db: Session,
    *,
    norm: TeamNorm,
) -> Optional[uuid.UUID]:
    """Persist a TeamNorm as an agent_memory row with
    memory_type=team_norm. Returns the row id on success, None on
    failure.

    Norms are coalition-or-tenant-scoped, NOT agent-scoped, but
    agent_memory requires non-null agent_id. Use a stable marker UUID
    so norms are findable by memory_type without falsely attributing
    them to a real agent.
    """
    from app.services.team_engine import serialize_norm

    try:
        tenant_id = uuid.UUID(norm.tenant_id)
    except (ValueError, AttributeError) as exc:
        logger.warning(
            "team_engine_io.write_norm: bad tenant UUID — %s", exc
        )
        return None

    marker_agent_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    row = AgentMemory(
        tenant_id=tenant_id,
        agent_id=marker_agent_id,
        memory_type=NORM_MEMORY_TYPE,
        content=serialize_norm(norm),
        importance=0.7,
        confidence=1.0,
        tags=["team_engine", "norm", norm.key],
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except SQLAlchemyError as exc:
        logger.warning(
            "team_engine_io.write_norm: commit failed, rolling back. err=%s",
            exc,
        )
        db.rollback()
        return None


# ── Bootstrap helper ──────────────────────────────────────────────────


def bootstrap_canonical_role_split(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    claude_agent_id: uuid.UUID,
    luna_agent_id: uuid.UUID,
) -> dict:
    """Idempotent bootstrap of the 2026-05-19 role split as the first
    typed contracts for a tenant.

    Writes:
      1. Claude holds `driver` for `execution`, until codex_subscription_tier=team.
      2. Luna holds `reviewer` for `review`, until same.

    Idempotency: scans existing contracts; skips writing a side that
    already has a contract for that (agent, scope) pair.

    Designed to be called once per tenant at first deployment of the
    Teamwork Engine OR via an operator action. Safe to call multiple
    times.
    """
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    rationale = (
        "Canonical role split from 2026-05-19: Claude (Opus heavy "
        "model) does execution, Luna stays in reviewer role until "
        "operator bumps Codex subscription. Bootstrapped from "
        "feedback_role_split_claude_executes_luna_reviews memory + "
        "PR #589 design."
    )
    conditions = {"until_codex_subscription_tier": "team"}

    existing = list_role_contracts(db, tenant_id=tenant_id)
    has_claude_execution = any(
        c.agent_id == str(claude_agent_id) and c.scope == "execution"
        for c in existing
    )
    has_luna_review = any(
        c.agent_id == str(luna_agent_id) and c.scope == "review"
        for c in existing
    )

    result = {
        "claude_contract": "skipped (already exists)" if has_claude_execution else None,
        "luna_contract": "skipped (already exists)" if has_luna_review else None,
    }

    if not has_claude_execution:
        contract = TeamRoleContract(
            tenant_id=str(tenant_id),
            coalition_id=None,
            agent_id=str(claude_agent_id),
            role="driver",
            scope="execution",
            effective_from=now_iso,
            effective_until=None,
            conditions=conditions,
            rationale=rationale,
            superseded_by=None,
        )
        row_id = write_role_contract(db, contract=contract)
        result["claude_contract"] = (
            f"written id={row_id}" if row_id else "write failed"
        )

    if not has_luna_review:
        contract = TeamRoleContract(
            tenant_id=str(tenant_id),
            coalition_id=None,
            agent_id=str(luna_agent_id),
            role="reviewer",
            scope="review",
            effective_from=now_iso,
            effective_until=None,
            conditions=conditions,
            rationale=rationale,
            superseded_by=None,
        )
        row_id = write_role_contract(db, contract=contract)
        result["luna_contract"] = (
            f"written id={row_id}" if row_id else "write failed"
        )

    return result


__all__ = [
    "list_role_contracts",
    "get_active_role",
    "list_norms",
    "get_norm_value",
    "write_role_contract",
    "write_norm",
    "bootstrap_canonical_role_split",
]
