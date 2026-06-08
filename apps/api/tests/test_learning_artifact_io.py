"""PR4 — learning-artifact write path → agent_memory (memory_type discriminator)."""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.agent_memory import AgentMemory
from app.schemas.accountable_learning import LearningArtifact
from app.services import learning_artifact_io as lai


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    AgentMemory.__table__.create(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


TENANT = uuid.uuid4()
AGENT = uuid.uuid4()


def _artifact(**over):
    base = dict(
        tenant_id=str(TENANT),
        artifact_id=str(uuid.uuid4()),
        source_refs=["commitment:1"],
        task_summary="Promised a follow-up that slipped",
        intended_outcome="Follow-up by Friday",
        observed_outcome="Missed; no proof",
        outcome_quality="failed",
        proof_refs=[],
        failed_assumptions=["assumed calendar invite implied confirmation"],
        user_corrections=["deadline was hard"],
        memory_write_recommendation="failed_assumption",
        confidence="high",
        created_at="2026-06-08T00:00:00Z",
        source_commitment_id="commit-1",
    )
    base.update(over)
    return LearningArtifact(**base)


def test_write_then_list_roundtrip(db):
    aid = lai.write_learning_artifact(db, artifact=_artifact(), agent_id=AGENT)
    assert aid is not None
    rows = lai.list_learning_artifacts(db, TENANT)
    assert len(rows) == 1
    assert rows[0]["outcome_quality"] == "failed"
    assert rows[0]["memory_write_recommendation"] == "failed_assumption"


def test_write_persists_as_learning_artifact_memory_type(db):
    lai.write_learning_artifact(db, artifact=_artifact(), agent_id=AGENT)
    row = db.query(AgentMemory).first()
    assert row.memory_type == lai.LEARNING_ARTIFACT_MEMORY_TYPE
    assert "has_failed_assumption" in row.tags
    assert "quality:failed" in row.tags


def test_tenant_boundary_refusal(db):
    other = uuid.uuid4()
    aid = lai.write_learning_artifact(
        db, artifact=_artifact(), agent_id=AGENT, current_tenant_id=other
    )
    assert aid is None
    assert db.query(AgentMemory).count() == 0


def test_query_failed_assumptions_dedup(db):
    lai.write_learning_artifact(db, artifact=_artifact(), agent_id=AGENT)
    lai.write_learning_artifact(
        db,
        artifact=_artifact(
            failed_assumptions=[
                "assumed calendar invite implied confirmation",  # dup
                "assumed CI green meant merged",
            ]
        ),
        agent_id=AGENT,
    )
    fa = lai.query_failed_assumptions(db, TENANT)
    assert fa == [
        "assumed calendar invite implied confirmation",
        "assumed CI green meant merged",
    ]


def test_list_is_tenant_isolated(db):
    lai.write_learning_artifact(db, artifact=_artifact(), agent_id=AGENT)
    other_tenant = uuid.uuid4()
    lai.write_learning_artifact(
        db, artifact=_artifact(tenant_id=str(other_tenant)), agent_id=AGENT
    )
    assert len(lai.list_learning_artifacts(db, TENANT)) == 1
    assert len(lai.list_learning_artifacts(db, other_tenant)) == 1
