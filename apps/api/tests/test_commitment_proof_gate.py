"""PR2 — commitment capture + proof-gated completion.

Core invariant (plan §6/§14): a commitment cannot be marked done without
proof_refs or explicit user confirmation. Uses an in-memory SQLite session with
just the commitment_records table (the conftest registers the PG-type SQLite
compilers at import). FK enforcement is off on SQLite, so no tenants/users rows
are needed.
"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.commitment_record import CommitmentRecord
from app.schemas.commitment_record import CommitmentRecordUpdate, CommitmentState
from app.services import commitment_service as cs


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    CommitmentRecord.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()


def test_record_action_commitment_derives_proof_and_session(db):
    c = cs.record_action_commitment(
        db,
        TENANT,
        owner_agent_slug="luna",
        title="Open PR #999",
        action_kind="pr_creation",
        source_ref={"pr_number": 999},
        session_id="sess-1",
    )
    assert c.state == "open"
    assert c.proof_required == ["merged_pr_url", "ci_run_id"]
    assert c.source_ref["session_id"] == "sess-1"
    assert c.proof_refs == []


def test_complete_with_proof_marks_fulfilled(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="x",
        action_kind="pr_creation", source_ref={},
    )
    done = cs.complete_commitment_with_proof(
        db, TENANT, c.id, proof_refs=["https://github.com/x/y/pull/999"]
    )
    assert done.state == "fulfilled"
    assert done.proof_refs == ["https://github.com/x/y/pull/999"]
    assert done.fulfilled_at is not None
    assert done.last_verified_at is not None


def test_complete_without_proof_but_user_confirmed(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="x",
        action_kind="delegated_work", source_ref={},
    )
    done = cs.complete_commitment_with_proof(db, TENANT, c.id, user_confirmed=True)
    assert done.state == "fulfilled"


def test_complete_without_proof_or_confirmation_is_blocked(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="x",
        action_kind="email_send", source_ref={},
    )
    with pytest.raises(cs.CommitmentProofRequired):
        cs.complete_commitment_with_proof(db, TENANT, c.id)
    db.refresh(c)
    assert c.state == "open"  # unchanged — no false "done"


def test_update_to_fulfilled_without_proof_is_blocked(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="x",
        action_kind="pr_creation", source_ref={},
    )
    with pytest.raises(cs.CommitmentProofRequired):
        cs.update_commitment(
            db, TENANT, c.id, CommitmentRecordUpdate(state=CommitmentState.FULFILLED)
        )


def test_update_to_fulfilled_with_proof_in_same_update(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="x",
        action_kind="pr_creation", source_ref={},
    )
    updated = cs.update_commitment(
        db, TENANT, c.id,
        CommitmentRecordUpdate(
            state=CommitmentState.FULFILLED, proof_refs=["ci:12345"]
        ),
    )
    assert updated.state == "fulfilled"
    assert updated.proof_refs == ["ci:12345"]


def test_at_risk_and_blocked_are_live_states(db):
    c = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="x",
        action_kind="pr_creation", source_ref={}, session_id="sess-9",
    )
    cs.update_commitment(db, TENANT, c.id, CommitmentRecordUpdate(state=CommitmentState.AT_RISK))
    open_rows = cs.list_open_commitments(db, TENANT)
    assert any(r.id == c.id for r in open_rows)  # at_risk is still "live"


def test_list_open_commitments_session_scoped_and_tenant_isolated(db):
    a = cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="a",
        action_kind="pr_creation", source_ref={}, session_id="sess-A",
    )
    cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="b",
        action_kind="pr_creation", source_ref={}, session_id="sess-B",
    )
    cs.record_action_commitment(
        db, OTHER_TENANT, owner_agent_slug="luna", title="c",
        action_kind="pr_creation", source_ref={}, session_id="sess-A",
    )
    # tenant + session scoped
    rows = cs.list_open_commitments(db, TENANT, session_id="sess-A")
    assert [r.id for r in rows] == [a.id]
    # tenant only
    all_tenant = cs.list_open_commitments(db, TENANT)
    assert {r.title for r in all_tenant} == {"a", "b"}
    # other tenant isolated
    other = cs.list_open_commitments(db, OTHER_TENANT)
    assert {r.title for r in other} == {"c"}
