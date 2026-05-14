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

    Captures every `.filter(*args)` invocation in `chain.filter_args`
    so tests can assert tenant-isolation clauses are present in the
    query (PR #454 review BLOCKER B2).
    """
    working_rows = working_rows or []
    completed_rows = completed_rows or []

    chain = MagicMock()
    chain.filter_args = []  # type: ignore[attr-defined]

    def _return_chain(*_a, **_kw):
        return chain

    def _capture_filter(*args, **_kw):
        # Stringify each BinaryExpression — the str() rendering preserves
        # the column name ("workflow_runs.tenant_id") and the bound
        # value (the UUID), which is what the B2 assertion needs.
        for a in args:
            chain.filter_args.append(str(a))
        return chain

    chain.join.side_effect = _return_chain
    chain.filter.side_effect = _capture_filter
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
    # conscious update.
    user = _fake_user("44444444-4444-4444-4444-444444444444")
    client, db = _make_client(user)
    resp = client.get("/api/v1/dashboard/tasks")
    assert resp.status_code == 200
    # `db.query()` is called once per separate SQLAlchemy query.
    assert db.query.call_count == 2, (
        f"endpoint should issue 2 queries (working + completed); "
        f"saw {db.query.call_count}"
    )


def test_filters_by_tenant_id_on_both_queries():
    # PR #454 review BLOCKER B2: tenant isolation must be enforced on
    # EVERY query. `workflow_runs` has no Postgres row-level security
    # policy — dropping the `tenant_id` clause from a future refactor
    # would silently leak rows across tenants. SQLAlchemy renders the
    # captured filter expressions with bind-parameter placeholders
    # (e.g. `workflow_runs.tenant_id = :tenant_id_1`), so we assert on
    # the column reference rather than the bound UUID value.
    user = _fake_user("44444444-4444-4444-4444-444444444444")
    client, db = _make_client(user)
    resp = client.get("/api/v1/dashboard/tasks")
    assert resp.status_code == 200
    rendered = db.query.return_value.filter_args
    tenant_clauses = [s for s in rendered if "workflow_runs.tenant_id =" in s]
    # Two queries (working + completed) → at least two tenant clauses.
    assert len(tenant_clauses) >= 2, (
        "expected at least one tenant_id clause per query "
        f"(2 queries); saw {len(tenant_clauses)} in: {rendered!r}"
    )
    # Also confirm the bound value matches the current user — without
    # this guard a future bug could compare to a constant by mistake.
    # The bound value lives in `chain.filter` call_args, not in the
    # rendered string, so dig into the BinaryExpression's right side.
    chain = db.query.return_value
    bound_uuids = set()
    for call in chain.filter.call_args_list:
        for clause in call.args:
            # SQLAlchemy BinaryExpression: .right is a BindParameter
            # whose `.value` is the bound python object.
            if hasattr(clause, "right") and hasattr(clause.right, "value"):
                bound_uuids.add(str(clause.right.value))
    assert str(user.tenant_id) in bound_uuids, (
        f"tenant_id clause must bind the current user's tenant_id "
        f"({user.tenant_id}); saw bound values: {bound_uuids!r}"
    )


def test_started_at_emits_with_utc_offset():
    # PR #454 review BLOCKER B1: server MUST emit tz-aware datetimes
    # so the Rust CLI's chrono::DateTime<Utc> deserialises. A naive
    # datetime serialises as "2026-05-13T12:00:00" (no offset), which
    # the CLI rejects at parse time. Force a NAIVE source datetime
    # through the endpoint and assert the wire payload has a UTC
    # offset attached.
    user = _fake_user("66666666-6666-6666-6666-666666666666")
    naive_run = _fake_run(status="running")
    naive_run.started_at = datetime(2026, 5, 13, 12, 0, 0)  # NO tzinfo
    working = [(naive_run, "Daily Briefing")]
    client, _ = _make_client(user, working_rows=working)
    body = client.get("/api/v1/dashboard/tasks").json()
    iso = body["working"][0]["started_at"]
    # Pydantic v2 with tz-aware UTC datetimes renders either "Z" or
    # "+00:00" — accept both.
    assert iso.endswith("Z") or iso.endswith("+00:00"), (
        f"expected tz offset suffix on started_at, got {iso!r}"
    )


def test_completed_at_null_does_not_surface_ancient_rows():
    # PR #454 review IMPORTANT I1: a crashed-mid-step run from months
    # ago (completed_at IS NULL, started_at far in the past) used to
    # surface in the completed bucket forever. The fixed filter
    # requires `started_at >= cutoff` when completed_at is NULL. We
    # can't easily assert what the DB returned (the mock doesn't run
    # SQL), so instead inspect the filter expression text for the
    # presence of both clauses joined under OR/AND.
    user = _fake_user("77777777-7777-7777-7777-777777777777")
    client, db = _make_client(user)
    resp = client.get("/api/v1/dashboard/tasks")
    assert resp.status_code == 200
    rendered = " ".join(db.query.return_value.filter_args)
    # The completed-query filter must reference BOTH completed_at and
    # started_at within a single OR expression.
    assert (
        "workflow_runs.completed_at" in rendered
        and "workflow_runs.started_at" in rendered
    ), f"expected completed_at AND started_at gating in: {rendered!r}"


def test_working_bucket_has_started_at_floor():
    # PR #454 review IMPORTANT I2: zombie status='running' rows from
    # workers that crashed before writing terminal status used to live
    # in the dashboard forever. The working query now floors on
    # started_at >= now - WORKING_FLOOR. Verify the column appears in
    # the captured filter args.
    user = _fake_user("88888888-8888-8888-8888-888888888888")
    client, db = _make_client(user)
    resp = client.get("/api/v1/dashboard/tasks")
    assert resp.status_code == 200
    rendered = " ".join(db.query.return_value.filter_args)
    # Both queries reference started_at; the working query references
    # it for the floor (>=) while the completed query references it
    # for the OR-fallback. So multiple references is correct — assert
    # presence rather than a specific count.
    assert (
        rendered.count("workflow_runs.started_at") >= 2
    ), f"expected started_at gating on both queries: {rendered!r}"


def test_limit_param_validation():
    user = _fake_user("55555555-5555-5555-5555-555555555555")
    client, _ = _make_client(user)
    # 0 → 422 (ge=1)
    assert client.get("/api/v1/dashboard/tasks?limit=0").status_code == 422
    # 201 → 422 (le=200)
    assert client.get("/api/v1/dashboard/tasks?limit=201").status_code == 422
    # 200 → 200
    assert client.get("/api/v1/dashboard/tasks?limit=200").status_code == 200
