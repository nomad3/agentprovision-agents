"""DB-touching tests for app.services.metacog_io (M1 of #616).

Uses a PER-TEST SQLite engine with scoped metadata containment —
NOT the shared Base.metadata pattern that bit us four times this
session (#610/#612/#613 cascade). Each test gets a fresh
`sqlite:///:memory:` engine and creates only the tables it needs.

The fixture pattern:
  1. Build a fresh engine per test
  2. Patch UUID/INET column types onto String(36) for the duration
     of the test, then restore in a try/finally so we never leak
     mutations out of the test
  3. Create only `tenants`, `agents`, `agent_memories` — the three
     tables metacog_io actually touches
  4. Drop everything on teardown so the next test starts clean
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import String, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.db.base import Base
from app.models.agent import Agent
from app.models.agent_memory import AgentMemory  # noqa: F401 — registers table
from app.models.tenant import Tenant
from app.schemas.metacog import ConfidencePrediction, OutcomeObservation
from app.services.metacog_io import (
    list_observations,
    list_predictions,
    list_traces,
    write_observation,
    write_prediction,
)


# ── Per-test SQLite isolation harness ─────────────────────────────────


class _SqliteUuidShim(TypeDecorator):
    """UUID ↔ CHAR(36) bridge for SQLite. Same shape as the version
    in test_refresh_tokens.py — but here we restore the originals in
    a try/finally so the mutation doesn't leak."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return uuid.UUID(value) if isinstance(value, str) else value


_PG_ONLY_COLUMNS_BY_TABLE = {
    "tenants": ("id",),
    "agents": ("id", "tenant_id"),
    "agent_memories": ("id", "tenant_id", "agent_id"),
}


@contextmanager
def _per_test_sqlite():
    """Yield a Session bound to a fresh in-memory SQLite engine with
    just the three tables metacog_io touches. Restores Base.metadata
    type mutations on exit so the next test sees pristine state."""
    original_types: dict[tuple[str, str], object] = {}
    try:
        for tbl_name, cols in _PG_ONLY_COLUMNS_BY_TABLE.items():
            tbl = Base.metadata.tables[tbl_name]
            for col_name in cols:
                col = tbl.c[col_name]
                original_types[(tbl_name, col_name)] = col.type
                col.type = _SqliteUuidShim()

        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(
            engine,
            tables=[
                Base.metadata.tables["tenants"],
                Base.metadata.tables["agents"],
                Base.metadata.tables["agent_memories"],
            ],
        )
        Session_ = sessionmaker(bind=engine, future=True)
        session = Session_()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()
    finally:
        for (tbl_name, col_name), original in original_types.items():
            Base.metadata.tables[tbl_name].c[col_name].type = original  # type: ignore[assignment]


@pytest.fixture
def db():
    with _per_test_sqlite() as session:
        yield session


@pytest.fixture
def tenant_with_agent(db: Session):
    """Returns (tenant, agent) — agent_memories.agent_id is a real
    FK so we need a real agent row in the tenant before any
    write_prediction / write_observation will land cleanly."""
    tenant = Tenant(name="Metacog Test Tenant")
    db.add(tenant)
    db.flush()  # populate tenant.id
    agent = Agent(tenant_id=tenant.id, name="Test Agent")
    db.add(agent)
    db.flush()
    db.commit()
    return tenant, agent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_prediction(
    tenant_id, agent_id,
    decision_id=None, predicted=0.5,
    kind="rl_route_chat_response",
) -> ConfidencePrediction:
    return ConfidencePrediction(
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        decision_id=str(decision_id or uuid.uuid4()),
        decision_kind=kind,
        predicted_confidence=predicted,
        context_hash="ctx",
        ts=_now(),
    )


def _make_observation(
    tenant_id, decision_id, reward=0.0,
) -> OutcomeObservation:
    return OutcomeObservation(
        tenant_id=str(tenant_id),
        decision_id=str(decision_id),
        actual_reward=reward,
        latency_ms=10,
        completed_at=_now(),
    )


# ── write_prediction ──────────────────────────────────────────────────


def test_write_prediction_persists_and_roundtrips(db, tenant_with_agent):
    tenant, agent = tenant_with_agent
    p = _make_prediction(tenant.id, agent.id, predicted=0.77)
    row_id = write_prediction(db, prediction=p)
    assert row_id is not None

    fetched = list_predictions(db, tenant_id=tenant.id)
    assert len(fetched) == 1
    assert fetched[0].predicted_confidence == 0.77
    assert fetched[0].decision_id == p.decision_id


def test_write_prediction_rejects_tenant_boundary_violation(
    db, tenant_with_agent,
):
    """A caller claiming to be tenant-A cannot persist a prediction
    serialized for tenant-B."""
    tenant, agent = tenant_with_agent
    other_tenant_id = uuid.uuid4()
    foreign_pred = _make_prediction(other_tenant_id, agent.id)
    row_id = write_prediction(
        db,
        prediction=foreign_pred,
        current_tenant_id=tenant.id,  # claim tenant
    )
    assert row_id is None
    # Nothing persisted for either tenant
    assert list_predictions(db, tenant_id=tenant.id) == []
    assert list_predictions(db, tenant_id=other_tenant_id) == []


def test_write_prediction_rejects_malformed_uuids(db):
    """Defensive: don't crash on garbage IDs, just return None."""
    bad = ConfidencePrediction(
        tenant_id="not-a-uuid",
        agent_id="also-not-a-uuid",
        decision_id="d",
        decision_kind="rl_route_chat_response",
        predicted_confidence=0.5,
        context_hash="x",
        ts=_now(),
    )
    assert write_prediction(db, prediction=bad) is None


# ── write_observation ─────────────────────────────────────────────────


def test_write_observation_persists_and_roundtrips(db, tenant_with_agent):
    tenant, agent = tenant_with_agent
    decision_id = uuid.uuid4()
    o = _make_observation(tenant.id, decision_id, reward=0.42)
    row_id = write_observation(db, observation=o, agent_id=agent.id)
    assert row_id is not None

    fetched = list_observations(db, tenant_id=tenant.id)
    assert len(fetched) == 1
    assert fetched[0].actual_reward == 0.42
    assert fetched[0].decision_id == str(decision_id)


def test_write_observation_rejects_tenant_boundary_violation(
    db, tenant_with_agent,
):
    tenant, agent = tenant_with_agent
    other_tenant_id = uuid.uuid4()
    foreign_obs = _make_observation(other_tenant_id, uuid.uuid4())
    row_id = write_observation(
        db,
        observation=foreign_obs,
        agent_id=agent.id,
        current_tenant_id=tenant.id,
    )
    assert row_id is None


# ── list_predictions filtering ────────────────────────────────────────


def test_list_predictions_filters_by_agent(db, tenant_with_agent):
    tenant, agent_a = tenant_with_agent
    agent_b = Agent(tenant_id=tenant.id, name="Other Agent")
    db.add(agent_b)
    db.commit()

    write_prediction(db, prediction=_make_prediction(tenant.id, agent_a.id))
    write_prediction(db, prediction=_make_prediction(tenant.id, agent_b.id))

    a_only = list_predictions(db, tenant_id=tenant.id, agent_id=agent_a.id)
    assert len(a_only) == 1
    assert a_only[0].agent_id == str(agent_a.id)


def test_list_predictions_filters_by_decision_kind(db, tenant_with_agent):
    tenant, agent = tenant_with_agent
    write_prediction(
        db,
        prediction=_make_prediction(
            tenant.id, agent.id, kind="rl_route_chat_response",
        ),
    )
    write_prediction(
        db,
        prediction=_make_prediction(
            tenant.id, agent.id, kind="affect_appraise",
        ),
    )

    chat_only = list_predictions(
        db, tenant_id=tenant.id, decision_kind="rl_route_chat_response",
    )
    assert len(chat_only) == 1
    assert chat_only[0].decision_kind == "rl_route_chat_response"


def test_list_predictions_tenant_isolated(db, tenant_with_agent):
    tenant, agent = tenant_with_agent
    write_prediction(db, prediction=_make_prediction(tenant.id, agent.id))

    other_tenant = Tenant(name="Other")
    db.add(other_tenant)
    db.commit()
    # Other tenant has no agents → can't even write a prediction there
    assert list_predictions(db, tenant_id=other_tenant.id) == []


# ── list_traces (read-side join) ──────────────────────────────────────


def test_list_traces_pairs_prediction_with_observation(
    db, tenant_with_agent,
):
    tenant, agent = tenant_with_agent
    decision_id = uuid.uuid4()
    p = _make_prediction(tenant.id, agent.id, decision_id=decision_id)
    o = _make_observation(tenant.id, decision_id, reward=0.4)

    write_prediction(db, prediction=p)
    write_observation(db, observation=o, agent_id=agent.id)

    traces = list_traces(db, tenant_id=tenant.id)
    assert len(traces) == 1
    assert traces[0].prediction.decision_id == str(decision_id)
    assert traces[0].observation.actual_reward == 0.4


def test_list_traces_drops_unpaired_predictions(db, tenant_with_agent):
    """A prediction without an observation = in-flight; not yet a
    trace. The read path silently drops it."""
    tenant, agent = tenant_with_agent
    write_prediction(db, prediction=_make_prediction(tenant.id, agent.id))
    # No observation written
    assert list_traces(db, tenant_id=tenant.id) == []


def test_list_traces_drops_unpaired_observations(db, tenant_with_agent):
    """An observation without a prediction = orphan; can't be
    calibrated. Dropped silently."""
    tenant, agent = tenant_with_agent
    write_observation(
        db,
        observation=_make_observation(tenant.id, uuid.uuid4()),
        agent_id=agent.id,
    )
    assert list_traces(db, tenant_id=tenant.id) == []
