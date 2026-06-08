"""Regression tests for the code-review P1 fixes.

P1-1: create_commitment must persist the new ledger fields (proof path not lost).
P1-2: the ledger schema must validate risk_threshold / escalation_policy against
the same vocabulary as the OutcomeContract trace (no laxer durable record).
"""
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.commitment_record import CommitmentRecord
from app.schemas.commitment_record import CommitmentRecordCreate, CommitmentRecordUpdate
from app.services import commitment_service as cs

TENANT = uuid.uuid4()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    CommitmentRecord.__table__.create(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_create_persists_ledger_fields(db):
    c = cs.create_commitment(
        db,
        TENANT,
        CommitmentRecordCreate(
            owner_agent_slug="luna",
            title="Ship feature",
            proof_required=["merged_pr_url", "ci_run_id"],
            stakeholder_refs=["user:simon"],
            risk_threshold="high",
            escalation_policy="ask_user",
        ),
    )
    assert c.proof_required == ["merged_pr_url", "ci_run_id"]
    assert c.stakeholder_refs == ["user:simon"]
    assert c.risk_threshold == "high"
    assert c.escalation_policy == "ask_user"


def test_create_schema_rejects_bad_risk_threshold():
    with pytest.raises(ValidationError):
        CommitmentRecordCreate(
            owner_agent_slug="l", title="x", risk_threshold="catastrophic"
        )


def test_create_schema_rejects_bad_escalation_policy():
    with pytest.raises(ValidationError):
        CommitmentRecordCreate(
            owner_agent_slug="l", title="x", escalation_policy="page_everyone"
        )


def test_update_schema_validates_choices():
    with pytest.raises(ValidationError):
        CommitmentRecordUpdate(risk_threshold="nope")
    # valid values pass
    ok = CommitmentRecordUpdate(risk_threshold="irreversible", escalation_policy="none")
    assert ok.risk_threshold == "irreversible"


def test_none_values_are_allowed():
    c = CommitmentRecordCreate(owner_agent_slug="l", title="x")
    assert c.risk_threshold is None
    assert c.escalation_policy is None
