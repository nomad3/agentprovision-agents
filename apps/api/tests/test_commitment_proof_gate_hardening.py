"""PR-F — proof-gate hardening (adversarial-review HIGH + LOW findings).

HIGH: the gate checked list emptiness, not content, so proof_refs=[""] (a
blank/whitespace string) is a truthy list and passed the gate — a commitment
could be marked `fulfilled` with no real evidence and no user confirmation,
nullifying the §6/§14 invariant. Both completion paths
(complete_commitment_with_proof and update_commitment state=fulfilled) must
strip blanks before the emptiness check and persist the cleaned list.

LOW: scan_open_commitments silently mapped an unrecognized min_level to `warn`
(_LEVEL_RANK.get(min_level, 1)), over-disclosing lower-severity rows. It now
rejects unknown levels (the API boundary uses a Literal; the service raises as
defense-in-depth).

Same in-memory SQLite harness as test_commitment_proof_gate.py.
"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.commitment_record import CommitmentRecord
from app.schemas.commitment_record import CommitmentRecordUpdate, CommitmentState
from app.services import commitment_service as cs
from app.services import red_flag_engine as rfe


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


def _mk(db, **kw):
    return cs.record_action_commitment(
        db, TENANT, owner_agent_slug="luna", title="x",
        action_kind="delegated_work", source_ref={}, **kw,
    )


# ── HIGH: blank/whitespace proof must not satisfy the gate ──────────────
def test_blank_proof_string_is_rejected(db):
    c = _mk(db)
    with pytest.raises(cs.CommitmentProofRequired):
        cs.complete_commitment_with_proof(db, TENANT, c.id, proof_refs=[""])
    db.refresh(c)
    assert c.state == "open"  # not falsely fulfilled


def test_whitespace_only_proof_string_is_rejected(db):
    c = _mk(db)
    with pytest.raises(cs.CommitmentProofRequired):
        cs.complete_commitment_with_proof(db, TENANT, c.id, proof_refs=["   "])
    db.refresh(c)
    assert c.state == "open"


def test_real_proof_is_stored_stripped(db):
    c = _mk(db)
    done = cs.complete_commitment_with_proof(db, TENANT, c.id, proof_refs=["  ci:123  "])
    assert done.state == "fulfilled"
    assert done.proof_refs == ["ci:123"]


def test_mixed_blank_and_real_keeps_only_real(db):
    c = _mk(db)
    done = cs.complete_commitment_with_proof(db, TENANT, c.id, proof_refs=["", "ci:9", "  "])
    assert done.state == "fulfilled"
    assert done.proof_refs == ["ci:9"]


def test_update_to_fulfilled_with_blank_proof_is_blocked(db):
    c = _mk(db)
    with pytest.raises(cs.CommitmentProofRequired):
        cs.update_commitment(
            db, TENANT, c.id,
            CommitmentRecordUpdate(state=CommitmentState.FULFILLED, proof_refs=[""]),
        )
    db.refresh(c)
    assert c.state == "open"


def test_user_confirmed_still_completes_without_proof(db):
    """The explicit-confirmation escape hatch is preserved."""
    c = _mk(db)
    done = cs.complete_commitment_with_proof(db, TENANT, c.id, user_confirmed=True)
    assert done.state == "fulfilled"


# ── LOW: unknown min_level must not silently widen to warn ──────────────
def test_scan_rejects_unknown_min_level(db):
    with pytest.raises(ValueError):
        rfe.scan_open_commitments(db, TENANT, min_level="critical")


def test_scan_accepts_known_min_level(db):
    # Known level must not raise (returns a list, possibly empty).
    assert isinstance(rfe.scan_open_commitments(db, TENANT, min_level="escalate"), list)
