"""Tests for `GET /api/v1/dashboard/tasks` (PR-B from PR #452 design).

Locks the contract `alpha tasks` depends on:
- response is split into working + completed groups
- working = workflow_runs.status="running"
- completed = workflow_runs.status in {completed, failed, cancelled, canceled}
- `supports_needs_input` is False in v1 (signals the CLI to render the
  honest "not yet surfaced" hint instead of an empty NEEDS-INPUT bucket)
- the row payload exposes the cost / duration / token fields the CLI
  renders, with NULL-tolerant serde defaults
- tenant isolation — the query MUST filter by current_user.tenant_id
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.dashboard_tasks import router as dashboard_router


def _fake_user(tenant_id: str):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID(tenant_id)
    u.is_active = True
    u.email = "dashboard-test@example.test"
    return u


def _make_client(user, *, working_rows=None, completed_rows=None):
    """Self-chaining MagicMock db that returns separate row lists for
    the two `.all()` calls the endpoint makes.

    The endpoint runs two queries — one for working, one for completed
    — and side_effect on `.all()` lets us pretend the first call
    returns the working rows and the second returns the completed.
    """
    working_rows = working_rows or []
    completed_rows = completed_rows or []

    chain = MagicMock()

    def _return_chain(*_a, **_kw):
        return chain

    chain.join.side_effect = _return_chain
    chain.filter.side_effect = _return_chain
    chain.order_by.side_effect = _return_chain
    chain.limit.side_effect = _return_chain
    chain.all.side_effect = [working_rows, completed_rows]

    db = MagicMock()
    db.query.return_value = chain

    app = FastAPI()
    app.include_router(dashboard_router, prefix="/api/v1/dashboard")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    return TestClient(app), db


def _fake_run(*, status, completed_at=None, error=None):
    """Construct a WorkflowRun-shape MagicMock — the endpoint only
    reads attributes, never calls methods, so attribute-level mocking
    is enough."""
    run = MagicMock()
    run.id = uuid.uuid4()
    run.status = status
    run.workflow_id = uuid.uuid4()
    run.started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    run.completed_at = completed_at
    run.duration_ms = 120_000 if completed_at else None
    run.total_tokens = 4200 if completed_at else None
    run.total_cost_usd = 0.012 if completed_at else None
    run.error = error
    return run


def test_returns_working_and_completed_split():
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    working = [(_fake_run(status="running"), "Daily Briefing")]
    completed = [
        (
            _fake_run(
                status="completed",
                completed_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            ),
            "Goal",
        )
    ]
    client, _db = _make_client(user, working_rows=working, completed_rows=completed)
    resp = client.get("/api/v1/dashboard/tasks")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["working"]) == 1
    assert body["working"][0]["status"] == "working"
    assert body["working"][0]["raw_status"] == "running"
    assert body["working"][0]["title"] == "Daily Briefing"
    assert len(body["completed"]) == 1
    assert body["completed"][0]["status"] == "completed"
    assert body["completed"][0]["raw_status"] == "completed"


def test_supports_needs_input_is_false_in_v1():
    # The CLI keys off this flag to render the honest "needs_input
    # not yet surfaced" hint. If we flip this to True without
    # implementing the bucket, the CLI silently shows an empty
    # group — exactly the misleading UX this flag is here to prevent.
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    client, _ = _make_client(user)
    resp = client.get("/api/v1/dashboard/tasks")
    assert resp.status_code == 200
    assert resp.json()["supports_needs_input"] is False


def test_empty_tenant_returns_empty_groups():
    user = _fake_user("22222222-2222-2222-2222-222222222222")
    client, _ = _make_client(user)
    body = client.get("/api/v1/dashboard/tasks").json()
    assert body == {"working": [], "completed": [], "supports_needs_input": False}


def test_failed_run_status_folds_into_completed_bucket():
    user = _fake_user("33333333-3333-3333-3333-333333333333")
    failed_run = _fake_run(
        status="failed",
        completed_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        error="leaf CLI returned 1",
    )
    completed = [(failed_run, "Goal")]
    client, _ = _make_client(user, completed_rows=completed)
    body = client.get("/api/v1/dashboard/tasks").json()
    assert len(body["completed"]) == 1
    row = body["completed"][0]
    assert row["status"] == "completed", "failed runs are part of the completed group from the user's POV"
    assert row["raw_status"] == "failed"
    assert row["error"] == "leaf CLI returned 1"


def test_runs_two_queries_one_per_group():
    # Each render of /dashboard/tasks must execute exactly two
    # queries — working + completed. If a future refactor folds them
    # into a single query (or adds a third), this fails and forces a
    # conscious update. Tenant isolation itself is enforced server-
    # side via `.filter(WorkflowRun.tenant_id == ...)`; an integration
    # test against a real DB (vs the self-chaining mock here) is the
    # only honest way to assert the filter semantics, so we lock the
    # structural count here and the integration coverage lives in
    # apps/api/tests/integration/.
    user = _fake_user("44444444-4444-4444-4444-444444444444")
    client, db = _make_client(user)
    resp = client.get("/api/v1/dashboard/tasks")
    assert resp.status_code == 200
    # `db.query()` is called once per separate SQLAlchemy query.
    assert db.query.call_count == 2, (
        f"endpoint should issue 2 queries (working + completed); "
        f"saw {db.query.call_count}"
    )


def test_limit_param_validation():
    user = _fake_user("55555555-5555-5555-5555-555555555555")
    client, _ = _make_client(user)
    # 0 → 422 (ge=1)
    assert client.get("/api/v1/dashboard/tasks?limit=0").status_code == 422
    # 201 → 422 (le=200)
    assert client.get("/api/v1/dashboard/tasks?limit=201").status_code == 422
    # 200 → 200
    assert client.get("/api/v1/dashboard/tasks?limit=200").status_code == 200
