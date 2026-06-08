"""PR3 — red-flag engine: deterministic level + fail-closed gating.

The evaluator is a pure function over ledger fields (duck-typed), so most tests
need no DB. The kill-switch is fail-closed: a missing tenant_features row OR any
SQL error yields OFF, and a disabled tenant scans to no flags.
"""
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.commitment_record import CommitmentRecord
from app.services import red_flag_engine as rfe

NOW = datetime(2026, 6, 8, 12, 0, 0)


def _c(**over):
    base = dict(
        id=uuid.uuid4(),
        state="open",
        due_at=None,
        checkpoint_at=None,
        escalation_at=None,
        stale_after=None,
        proof_refs=[],
        proof_required=[],
        risk_threshold="medium",
        blocker_refs=[],
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_terminal_states_never_flag():
    for s in ("fulfilled", "broken", "cancelled", "renegotiated"):
        assert rfe.evaluate_red_flag(_c(state=s), now=NOW) is None


def test_no_horizon_no_risk_is_not_flagged():
    assert rfe.evaluate_red_flag(_c(), now=NOW) is None


def test_watch_for_future_due_without_proof():
    f = rfe.evaluate_red_flag(_c(due_at=NOW + timedelta(days=7)), now=NOW)
    assert f is not None and f.level == "watch"


def test_warn_on_due_soon_without_proof():
    f = rfe.evaluate_red_flag(_c(due_at=NOW + timedelta(hours=3)), now=NOW)
    assert f.level == "warn"
    assert "due_soon_without_proof" in f.triggers


def test_warn_on_checkpoint_passed():
    f = rfe.evaluate_red_flag(_c(checkpoint_at=NOW - timedelta(hours=1)), now=NOW)
    assert f.level == "warn"
    assert "checkpoint_passed" in f.triggers


def test_warn_on_stale_evidence():
    f = rfe.evaluate_red_flag(_c(stale_after=NOW - timedelta(minutes=1)), now=NOW)
    assert f.level == "warn"


def test_warn_on_blocked_dependency():
    f = rfe.evaluate_red_flag(_c(state="blocked", blocker_refs=["pr:1"]), now=NOW)
    assert f.level == "warn"
    assert "blocked_dependency" in f.triggers


def test_escalate_on_overdue_without_proof():
    f = rfe.evaluate_red_flag(_c(due_at=NOW - timedelta(hours=2)), now=NOW)
    assert f.level == "escalate"
    assert "overdue_without_proof" in f.triggers


def test_escalate_on_escalation_point_reached():
    f = rfe.evaluate_red_flag(
        _c(escalation_at=NOW - timedelta(minutes=5), due_at=NOW + timedelta(days=1)),
        now=NOW,
    )
    assert f.level == "escalate"


def test_block_on_irreversible_overdue_without_proof():
    f = rfe.evaluate_red_flag(
        _c(risk_threshold="irreversible", due_at=NOW - timedelta(hours=1)), now=NOW
    )
    assert f.level == "block"


def test_overdue_with_proof_is_not_escalated():
    # Proof present → not an overdue-without-proof escalation.
    f = rfe.evaluate_red_flag(
        _c(due_at=NOW - timedelta(hours=1), proof_refs=["merged:pr/1"]), now=NOW
    )
    assert f is None or f.level in ("watch", "warn")


def test_missing_proofs_listed():
    f = rfe.evaluate_red_flag(
        _c(
            due_at=NOW - timedelta(hours=1),
            proof_required=["merged_pr_url", "ci_run_id"],
            proof_refs=["merged_pr_url"],
        ),
        now=NOW,
    )
    assert f.missing == ["ci_run_id"]


def test_message_contract_fields_present():
    f = rfe.evaluate_red_flag(_c(due_at=NOW - timedelta(hours=1)), now=NOW)
    assert f.risk and f.evidence and f.decision_needed and f.recommended_next_action


# ── fail-closed gating ────────────────────────────────────────────────

def _empty_db():
    engine = create_engine("sqlite:///:memory:")
    CommitmentRecord.__table__.create(bind=engine)  # no tenant_features table
    return sessionmaker(bind=engine)()


def test_killswitch_fail_closed_when_no_features_table():
    db = _empty_db()
    # tenant_features table absent → SQLAlchemyError caught → OFF
    assert rfe.is_red_flag_engine_enabled(db, uuid.uuid4()) is False


def test_scan_returns_nothing_when_disabled():
    db = _empty_db()
    tenant = uuid.uuid4()
    db.add(
        CommitmentRecord(
            tenant_id=tenant, owner_agent_slug="luna", title="overdue",
            commitment_type="action", state="open", priority="normal",
            source_type="tool_call", source_ref={}, related_entity_ids=[],
            proof_required=[], proof_refs=[], stakeholder_refs=[], blocker_refs=[],
            due_at=NOW - timedelta(days=1),
        )
    )
    db.commit()
    # Engine disabled (no features row / table) → fail-closed empty.
    assert rfe.scan_open_commitments(db, tenant, now=NOW) == []
