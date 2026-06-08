"""Service layer for commitment records with tenant isolation."""

from datetime import datetime
from typing import List, Optional
import uuid

from sqlalchemy.orm import Session

from app.models.commitment_record import CommitmentRecord
from app.schemas.commitment_record import (
    CommitmentRecordCreate,
    CommitmentRecordUpdate,
    CommitmentState,
)


class CommitmentProofRequired(ValueError):
    """Raised when a commitment is marked done without proof or user confirmation.

    Core invariant of the Accountable Learning & Commitment System (plan §6,
    §14): "Luna must not say a commitment is done unless the ledger entry has
    proof_refs or the user explicitly confirms completion in the current
    context."
    """


# Open/at-risk lifecycle states the red-flag engine and queries treat as "live".
OPEN_COMMITMENT_STATES = ("open", "in_progress", "blocked", "at_risk")


def _validate_goal_ref(
    db: Session,
    tenant_id: uuid.UUID,
    goal_id: Optional[uuid.UUID],
) -> None:
    if not goal_id:
        return
    from app.models.goal_record import GoalRecord
    goal = (
        db.query(GoalRecord)
        .filter(GoalRecord.id == goal_id, GoalRecord.tenant_id == tenant_id)
        .first()
    )
    if not goal:
        raise ValueError(f"Goal {goal_id} not found in this tenant")


def create_commitment(
    db: Session,
    tenant_id: uuid.UUID,
    commitment_in: CommitmentRecordCreate,
    created_by: Optional[uuid.UUID] = None,
) -> CommitmentRecord:
    _validate_goal_ref(db, tenant_id, commitment_in.goal_id)
    commitment = CommitmentRecord(
        tenant_id=tenant_id,
        owner_agent_slug=commitment_in.owner_agent_slug,
        created_by=created_by,
        title=commitment_in.title,
        description=commitment_in.description,
        commitment_type=commitment_in.commitment_type.value,
        priority=commitment_in.priority.value,
        state="open",
        source_type=commitment_in.source_type.value,
        source_ref=commitment_in.source_ref,
        due_at=commitment_in.due_at,
        goal_id=commitment_in.goal_id,
        related_entity_ids=commitment_in.related_entity_ids,
    )
    db.add(commitment)
    db.commit()
    db.refresh(commitment)
    return commitment


def get_commitment(
    db: Session,
    tenant_id: uuid.UUID,
    commitment_id: uuid.UUID,
) -> Optional[CommitmentRecord]:
    return (
        db.query(CommitmentRecord)
        .filter(
            CommitmentRecord.id == commitment_id,
            CommitmentRecord.tenant_id == tenant_id,
        )
        .first()
    )


def list_commitments(
    db: Session,
    tenant_id: uuid.UUID,
    owner_agent_slug: Optional[str] = None,
    state: Optional[str] = None,
    goal_id: Optional[uuid.UUID] = None,
    limit: int = 100,
) -> List[CommitmentRecord]:
    q = db.query(CommitmentRecord).filter(CommitmentRecord.tenant_id == tenant_id)
    if owner_agent_slug:
        q = q.filter(CommitmentRecord.owner_agent_slug == owner_agent_slug)
    if state:
        q = q.filter(CommitmentRecord.state == state)
    if goal_id:
        q = q.filter(CommitmentRecord.goal_id == goal_id)
    return q.order_by(CommitmentRecord.created_at.desc()).limit(limit).all()


def update_commitment(
    db: Session,
    tenant_id: uuid.UUID,
    commitment_id: uuid.UUID,
    commitment_in: CommitmentRecordUpdate,
) -> Optional[CommitmentRecord]:
    commitment = get_commitment(db, tenant_id, commitment_id)
    if not commitment:
        return None

    update_data = commitment_in.model_dump(exclude_unset=True)

    if "goal_id" in update_data:
        _validate_goal_ref(db, tenant_id, update_data["goal_id"])

    if "state" in update_data:
        new_state = update_data["state"]
        if isinstance(new_state, CommitmentState):
            new_state = new_state.value
        update_data["state"] = new_state

        if new_state == "fulfilled":
            # Proof gate (plan §6/§14): cannot transition to done without
            # proof_refs (present on the record or set in this same update).
            # The explicit user-confirmation escape lives in
            # complete_commitment_with_proof(user_confirmed=True).
            proof_after = update_data.get("proof_refs")
            if proof_after is None:
                proof_after = list(commitment.proof_refs or [])
            if not proof_after:
                raise CommitmentProofRequired(
                    "Cannot mark commitment fulfilled without proof_refs; use "
                    "complete_commitment_with_proof(user_confirmed=True) for "
                    "explicit user confirmation."
                )
            update_data["fulfilled_at"] = datetime.utcnow()
            update_data["broken_at"] = None
            update_data["broken_reason"] = None
        elif new_state == "broken":
            update_data["broken_at"] = datetime.utcnow()
            update_data["fulfilled_at"] = None
        elif new_state in ("open", "in_progress"):
            update_data["fulfilled_at"] = None
            update_data["broken_at"] = None
            update_data["broken_reason"] = None
        elif new_state in ("blocked", "at_risk", "renegotiated"):
            # Transitional live states — not done, not broken.
            update_data["fulfilled_at"] = None
        elif new_state == "cancelled":
            update_data["fulfilled_at"] = None
            update_data["broken_at"] = None

    for key, value in update_data.items():
        if hasattr(commitment, key):
            setattr(commitment, key, value)

    commitment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(commitment)
    return commitment


def delete_commitment(
    db: Session,
    tenant_id: uuid.UUID,
    commitment_id: uuid.UUID,
) -> bool:
    commitment = get_commitment(db, tenant_id, commitment_id)
    if not commitment:
        return False
    db.delete(commitment)
    db.commit()
    return True


def list_open_commitments_for_agent(
    db: Session,
    tenant_id: uuid.UUID,
    agent_slug: str,
) -> List[CommitmentRecord]:
    """Load open and in-progress commitments for runtime injection."""
    return (
        db.query(CommitmentRecord)
        .filter(
            CommitmentRecord.tenant_id == tenant_id,
            CommitmentRecord.owner_agent_slug == agent_slug,
            CommitmentRecord.state.in_(["open", "in_progress"]),
        )
        .order_by(CommitmentRecord.due_at.asc().nullslast(), CommitmentRecord.created_at.asc())
        .all()
    )


def list_overdue_commitments(
    db: Session,
    tenant_id: uuid.UUID,
    owner_agent_slug: Optional[str] = None,
) -> List[CommitmentRecord]:
    """Find commitments past their due date that are still open."""
    q = (
        db.query(CommitmentRecord)
        .filter(
            CommitmentRecord.tenant_id == tenant_id,
            CommitmentRecord.state.in_(["open", "in_progress"]),
            CommitmentRecord.due_at.isnot(None),
            CommitmentRecord.due_at < datetime.utcnow(),
        )
    )
    if owner_agent_slug:
        q = q.filter(CommitmentRecord.owner_agent_slug == owner_agent_slug)
    return q.order_by(CommitmentRecord.due_at.asc()).all()


# ── Accountable Learning & Commitment System: PR2 write path ──────────
#
# Commitments are captured from EXPLICIT high-impact tool actions (PR creation,
# calendar create, email send, delegated work) — never by regex over Luna's
# response text. Regex auto-extraction was deliberately disabled (see the no-op
# `commitment_extractor.py`) because it caused self-referential loops and false
# positives. Do not re-introduce it.

# Default proof requirements per side-effect action kind. Used so a captured
# commitment cannot later be marked "done" on vibes.
_PROOF_REQUIRED_BY_ACTION = {
    "pr_creation": ["merged_pr_url", "ci_run_id"],
    "calendar_create": ["calendar_event_id"],
    "email_send": ["sent_message_id"],
    "delegated_work": ["handoff_result_ref"],
    "deploy": ["deployed_version"],
}


def record_action_commitment(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    owner_agent_slug: str,
    title: str,
    action_kind: str,
    source_ref: dict,
    session_id: Optional[str] = None,
    proof_required: Optional[List[str]] = None,
    due_at: Optional[datetime] = None,
    checkpoint_at: Optional[datetime] = None,
    risk_threshold: Optional[str] = None,
    escalation_policy: Optional[str] = None,
    created_by: Optional[uuid.UUID] = None,
    description: Optional[str] = None,
) -> CommitmentRecord:
    """Capture a commitment from an explicit high-impact action (PR2).

    `source_ref` carries the action anchor (and `session_id` for session-scoped
    queries). `proof_required` defaults from `action_kind` so completion is
    proof-gated.
    """
    ref = dict(source_ref or {})
    if session_id and "session_id" not in ref:
        ref["session_id"] = session_id
    proofs = proof_required if proof_required is not None else list(
        _PROOF_REQUIRED_BY_ACTION.get(action_kind, [])
    )
    commitment = CommitmentRecord(
        tenant_id=tenant_id,
        owner_agent_slug=owner_agent_slug,
        created_by=created_by,
        title=title,
        description=description,
        commitment_type="action",
        priority="normal",
        state="open",
        source_type="tool_call",
        source_ref=ref,
        proof_required=proofs,
        proof_refs=[],
        due_at=due_at,
        checkpoint_at=checkpoint_at,
        risk_threshold=risk_threshold,
        escalation_policy=escalation_policy,
    )
    db.add(commitment)
    db.commit()
    db.refresh(commitment)
    return commitment


def complete_commitment_with_proof(
    db: Session,
    tenant_id: uuid.UUID,
    commitment_id: uuid.UUID,
    proof_refs: Optional[List[str]] = None,
    *,
    user_confirmed: bool = False,
) -> Optional[CommitmentRecord]:
    """Canonical proof-gated completion path (plan §6/§14).

    Marks a commitment `fulfilled` ONLY if `proof_refs` are supplied OR the user
    explicitly confirmed completion in the current context. Otherwise raises
    `CommitmentProofRequired`. Never invents proof.
    """
    commitment = get_commitment(db, tenant_id, commitment_id)
    if not commitment:
        return None

    proofs = list(proof_refs or []) or list(commitment.proof_refs or [])
    if not proofs and not user_confirmed:
        raise CommitmentProofRequired(
            f"Commitment {commitment_id} cannot be completed without proof_refs "
            "or explicit user confirmation."
        )

    now = datetime.utcnow()
    commitment.proof_refs = proofs
    commitment.state = "fulfilled"
    commitment.fulfilled_at = now
    commitment.last_verified_at = now
    commitment.broken_at = None
    commitment.broken_reason = None
    commitment.updated_at = now
    db.commit()
    db.refresh(commitment)
    return commitment


def list_open_commitments(
    db: Session,
    tenant_id: uuid.UUID,
    session_id: Optional[str] = None,
    limit: int = 200,
) -> List[CommitmentRecord]:
    """Open/live commitments for a tenant, optionally scoped to a session.

    Session scoping reads `source_ref['session_id']` in Python to stay correct
    on both PostgreSQL and the SQLite test shim (no JSONB operators).
    """
    rows = (
        db.query(CommitmentRecord)
        .filter(
            CommitmentRecord.tenant_id == tenant_id,
            CommitmentRecord.state.in_(OPEN_COMMITMENT_STATES),
        )
        .order_by(
            CommitmentRecord.due_at.asc().nullslast(),
            CommitmentRecord.created_at.asc(),
        )
        .limit(limit)
        .all()
    )
    if session_id is None:
        return rows
    return [r for r in rows if (r.source_ref or {}).get("session_id") == session_id]
