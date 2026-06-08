"""Red-flag engine (plan 2026-06-08 §9) — PR3 MVP.

Detects commitment drift before deadlines or trust failures. The level is a
*deterministic pure function* of ledger fields so it is cheap to test and can
run from both scheduled checks (extend the "Goal Review" reviewer on
``agentprovision-orchestration``) and event-driven updates.

Gated by a per-tenant kill-switch, default OFF and fail-closed — the same
discipline as ``reflection_killswitch`` (an autonomous loop must never run on
accident).

The message contract (§9) is short and actionable:
    Commitment / Risk / Evidence / Missing / Decision needed / Recommended next.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Union

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# Default "due soon" horizon used when a commitment has no explicit checkpoint.
DEFAULT_WARN_WINDOW = timedelta(hours=24)

_TERMINAL_STATES = {"fulfilled", "broken", "cancelled", "renegotiated"}
_HIGH_RISK = {"high", "irreversible"}

# watch < warn < escalate < block
_LEVEL_RANK = {"watch": 0, "warn": 1, "escalate": 2, "block": 3}


@dataclass(frozen=True)
class RedFlag:
    """A single red-flag finding for one commitment (the §9 message contract)."""

    commitment_id: str
    level: str  # watch | warn | escalate | block
    risk: str
    evidence: str
    missing: List[str]
    decision_needed: str
    recommended_next_action: str
    triggers: List[str] = field(default_factory=list)


def _as_list(v) -> list:
    return list(v) if v else []


def evaluate_red_flag(
    commitment,
    now: Optional[datetime] = None,
    warn_window: timedelta = DEFAULT_WARN_WINDOW,
) -> Optional[RedFlag]:
    """Deterministically classify one commitment. Returns ``None`` when there is
    nothing to flag (terminal state, or live work with no time horizon/risk).

    ``commitment`` is duck-typed: any object exposing the ledger fields
    (state, due_at, checkpoint_at, escalation_at, stale_after, proof_refs,
    proof_required, risk_threshold, blocker_refs).
    """
    now = now or datetime.utcnow()
    state = getattr(commitment, "state", "open")
    if state in _TERMINAL_STATES:
        return None

    due_at = getattr(commitment, "due_at", None)
    checkpoint_at = getattr(commitment, "checkpoint_at", None)
    escalation_at = getattr(commitment, "escalation_at", None)
    stale_after = getattr(commitment, "stale_after", None)
    proof_refs = _as_list(getattr(commitment, "proof_refs", None))
    proof_required = _as_list(getattr(commitment, "proof_required", None))
    risk = getattr(commitment, "risk_threshold", None)
    blocker_refs = _as_list(getattr(commitment, "blocker_refs", None))

    overdue = due_at is not None and due_at < now
    due_soon = due_at is not None and now <= due_at <= now + warn_window
    checkpoint_passed = checkpoint_at is not None and checkpoint_at <= now
    escalation_passed = escalation_at is not None and escalation_at <= now
    stale = stale_after is not None and stale_after <= now
    blocked = state == "blocked" or bool(blocker_refs)
    high_risk = risk in _HIGH_RISK
    missing = [p for p in proof_required if p not in proof_refs]

    triggers: List[str] = []
    if overdue and not proof_refs:
        triggers.append("overdue_without_proof")
    if escalation_passed:
        triggers.append("escalation_point_reached")
    if checkpoint_passed:
        triggers.append("checkpoint_passed")
    if stale:
        triggers.append("stale_evidence")
    if blocked:
        triggers.append("blocked_dependency")
    if state == "at_risk":
        triggers.append("marked_at_risk")
    if due_soon and not proof_refs:
        triggers.append("due_soon_without_proof")

    # Deterministic ladder, highest severity first.
    if risk == "irreversible" and overdue and not proof_refs:
        level, risk_txt = "block", "Irreversible commitment overdue with no proof"
    elif escalation_passed or (overdue and not proof_refs) or (high_risk and (overdue or blocked)):
        level, risk_txt = "escalate", "Commitment likely to slip without intervention"
    elif checkpoint_passed or stale or blocked or state == "at_risk" or (due_soon and not proof_refs):
        level, risk_txt = "warn", "Material risk or missing proof"
    elif due_at or checkpoint_at or escalation_at:
        level, risk_txt = "watch", "Drift possible; tracking"
    else:
        return None  # live, but no horizon and no risk — nothing to flag

    evidence = (
        f"{len(proof_refs)} proof ref(s); state={state}"
        + (f"; due {due_at.isoformat()}" if due_at else "")
    )
    decision = {
        "block": "Stop and confirm scope/owner before any irreversible action.",
        "escalate": "Ask the owner/user to renegotiate scope, timeline, or owner.",
        "warn": "Confirm the next action or supply the missing proof.",
        "watch": "No action yet; recheck at the next checkpoint.",
    }[level]
    recommended = {
        "block": "Block the action and surface the blocker.",
        "escalate": "Raise to the user/owner now with a decision request.",
        "warn": "Notify the owner with the missing proof and next step.",
        "watch": "Continue; re-evaluate on the next scan.",
    }[level]

    return RedFlag(
        commitment_id=str(getattr(commitment, "id", "")),
        level=level,
        risk=risk_txt,
        evidence=evidence,
        missing=missing,
        decision_needed=decision,
        recommended_next_action=recommended,
        triggers=triggers,
    )


def is_red_flag_engine_enabled(db: Session, tenant_id: Union[str, uuid.UUID]) -> bool:
    """Operator opt-in for the red-flag engine. Default FALSE; fail-closed.

    Mirrors ``reflection_killswitch.is_nightly_reflection_enabled`` — an
    autonomous scheduled loop must never run on accident.
    """
    try:
        from app.models.tenant_features import TenantFeatures
        row = (
            db.query(TenantFeatures)
            .filter(TenantFeatures.tenant_id == str(tenant_id))
            .first()
        )
        if row is None:
            return False
        return bool(getattr(row, "red_flag_engine_enabled", False))
    except SQLAlchemyError as exc:
        log.warning(
            "red_flag_killswitch: lookup failed tenant=%s err=%s; treating as OFF",
            tenant_id, exc,
        )
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "red_flag_killswitch: unexpected error tenant=%s err=%s; treating as OFF",
            tenant_id, exc,
        )
        return False


def scan_open_commitments(
    db: Session,
    tenant_id: uuid.UUID,
    now: Optional[datetime] = None,
    session_id: Optional[str] = None,
    min_level: str = "warn",
) -> List[RedFlag]:
    """Scan a tenant's open commitments and return red flags >= ``min_level``.

    Returns [] when the engine is disabled for the tenant (fail-closed). The
    actual notification + dedup of unchanged conditions lives in the operator
    surface (PR6); this scan is pure detection.

    Raises ValueError on an unrecognized ``min_level`` rather than silently
    defaulting to ``warn`` (adversarial-review LOW finding) — an operator asking
    for escalate-only must never get warn rows back from a typo'd filter. The
    API boundary additionally constrains it with a Literal (422 on bad input).
    """
    # Validate BEFORE the killswitch early-return so a bad level always errors,
    # regardless of whether the engine is enabled for this tenant.
    if min_level not in _LEVEL_RANK:
        raise ValueError(
            f"unknown min_level {min_level!r}; expected one of "
            f"{sorted(_LEVEL_RANK)}"
        )
    if not is_red_flag_engine_enabled(db, tenant_id):
        return []
    from app.services import commitment_service as cs

    now = now or datetime.utcnow()
    threshold = _LEVEL_RANK[min_level]
    flags: List[RedFlag] = []
    for c in cs.list_open_commitments(db, tenant_id, session_id=session_id):
        flag = evaluate_red_flag(c, now=now)
        if flag and _LEVEL_RANK[flag.level] >= threshold:
            flags.append(flag)
    return flags


__all__ = [
    "RedFlag",
    "evaluate_red_flag",
    "is_red_flag_engine_enabled",
    "scan_open_commitments",
    "DEFAULT_WARN_WINDOW",
]
