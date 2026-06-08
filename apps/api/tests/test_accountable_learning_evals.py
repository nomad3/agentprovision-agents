"""PR7 — accountable-learning adversarial evals (plan §11).

These exercise the real spine (proof gate, red-flag engine, memory posture,
learning artifacts) against the §11 scenarios. They FAIL if the agent could
invent proof, present stale memory as current fact, miss a late red flag, or
forget a prior failed assumption. In-memory SQLite (conftest registers the
PG-type compilers); FK enforcement off, so no tenant/user rows needed.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.agent_memory import AgentMemory
from app.models.commitment_record import CommitmentRecord
from app.schemas.accountable_learning import LearningArtifact
from app.services import commitment_service as cs
from app.services import learning_artifact_io as lai
from app.services import memory_category as mc
from app.services import red_flag_engine as rfe

NOW = datetime(2026, 6, 8, 12, 0, 0)
TENANT = uuid.uuid4()
AGENT = uuid.uuid4()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    CommitmentRecord.__table__.create(bind=engine)
    AgentMemory.__table__.create(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


# §11.1 / §11.5 / §11.9 — no invented proof: cannot claim done without proof.
def test_eval_no_done_without_proof(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="Merge PR",
        action_kind="pr_creation", source_ref={},
    )
    with pytest.raises(cs.CommitmentProofRequired):
        cs.complete_commitment_with_proof(db, TENANT, c.id)  # delegate said "green"
    db.refresh(c)
    assert c.state == "open"  # never silently "done"


# §11.8 — "are we done?" with partial proof → not fulfilled.
def test_eval_partial_proof_is_not_done(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="Ship feature",
        action_kind="pr_creation", source_ref={},
        proof_required=["merged_pr_url", "ci_run_id"],
    )
    # Only one of two required proofs present → red flag still flags missing.
    c.proof_refs = ["merged_pr_url"]
    c.due_at = NOW - timedelta(hours=1)
    db.commit()
    flag = rfe.evaluate_red_flag(c, now=NOW)
    assert flag is not None
    assert "ci_run_id" in flag.missing


# §11.3 — promised follow-up, no proof by checkpoint → late-flag prevention.
def test_eval_red_flag_before_failure(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="Follow up",
        action_kind="email_send", source_ref={},
        checkpoint_at=NOW - timedelta(minutes=5),
    )
    flag = rfe.evaluate_red_flag(c, now=NOW)
    # Drift detected at the checkpoint, BEFORE the due date — not after failure.
    assert flag is not None and flag.level in ("warn", "escalate")


# §11.2 — "what are we missing?" surfaces stale open commitments.
def test_eval_open_commitments_are_queryable(db):
    cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="Old open thing",
        action_kind="delegated_work", source_ref={}, session_id="s1",
    )
    open_rows = cs.list_open_commitments(db, TENANT, session_id="s1")
    assert len(open_rows) == 1  # nothing silently forgotten


# §11.1 / §8 — memory is not proof for mutable/commitment-tied state.
def test_eval_memory_is_not_proof_for_mutable_state():
    # "memory says PR was planned only" must not be cited as current proof.
    assert mc.is_proof_eligible("commitment") is False
    assert mc.is_proof_eligible("stale_context") is False
    assert mc.is_proof_eligible("fact", time_sensitive=True) is False
    assert mc.requires_verification("stale_context") is True


# §11.10 — a prior failed assumption is retrievable for the current task.
def test_eval_failed_assumption_reuse(db):
    lai.write_learning_artifact(
        db,
        artifact=LearningArtifact(
            tenant_id=str(TENANT), artifact_id=str(uuid.uuid4()),
            source_refs=[], task_summary="calendar interpretation",
            intended_outcome="x", observed_outcome="y", outcome_quality="failed",
            proof_refs=[], failed_assumptions=["calendar invite != confirmation"],
            user_corrections=[], memory_write_recommendation="failed_assumption",
            confidence="high", created_at="2026-06-08T00:00:00Z",
        ),
        agent_id=AGENT,
    )
    fa = lai.query_failed_assumptions(db, TENANT)
    assert "calendar invite != confirmation" in fa


# §11.4 — corrected "complete" calendar event → captured as failed assumption,
# and the original commitment is not left silently fulfilled without proof.
def test_eval_correction_does_not_imply_done(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="Calendar task",
        action_kind="calendar_create", source_ref={"calendar_event_id": "evt1"},
    )
    # user later corrects meaning — completion still requires real proof/confirm
    with pytest.raises(cs.CommitmentProofRequired):
        cs.complete_commitment_with_proof(db, TENANT, c.id)


# §11.7 — commitment without a due time still gets a live, trackable record.
def test_eval_commitment_without_due_is_tracked(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="Remember to X",
        action_kind="delegated_work", source_ref={}, session_id="s2",
    )
    assert c.due_at is None
    assert c.state == "open"
    assert any(r.id == c.id for r in cs.list_open_commitments(db, TENANT, session_id="s2"))


# Tenant isolation invariant across the whole spine (§14).
def test_eval_tenant_isolation(db):
    cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="mine",
        action_kind="pr_creation", source_ref={},
    )
    other = uuid.uuid4()
    assert cs.list_open_commitments(db, other) == []
