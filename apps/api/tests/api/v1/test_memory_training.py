"""Tests for `/api/v1/memory/training/*` — PR-Q1.

Covers:
    - POST /bulk-ingest: 200 on first call, 200 + deduplicated=True on re-post,
                          400 on unknown source, dispatches Temporal workflow
    - GET  /{run_id}:    200 on owned run, 404 on cross-tenant probe,
                          404 on missing run
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.memory_training import router as training_router


# ── helpers ──────────────────────────────────────────────────────────


def _fake_user(user_id: str, tenant_id: str):
    u = MagicMock()
    u.id = uuid.UUID(user_id)
    u.tenant_id = uuid.UUID(tenant_id)
    u.is_active = True
    u.email = "u@x.com"
    return u


def _fake_run(
    run_id: str,
    tenant_id: str,
    *,
    source: str = "local_ai_cli",
    snapshot_id: str | None = None,
    status: str = "pending",
    items_total: int = 0,
    items_processed: int = 0,
):
    """Build a TrainingRun-shaped MagicMock that survives ORM access
    patterns the endpoint uses (.progress_fraction(), attribute reads).
    """
    r = MagicMock()
    r.id = uuid.UUID(run_id)
    r.tenant_id = uuid.UUID(tenant_id)
    r.source = source
    r.snapshot_id = uuid.UUID(snapshot_id) if snapshot_id else uuid.uuid4()
    r.status = status
    r.items_total = items_total
    r.items_processed = items_processed
    r.error = None
    r.workflow_id = None
    r.created_at = datetime(2026, 5, 11, 23, 0, 0)
    r.started_at = None
    r.completed_at = None
    # The endpoint calls run.progress_fraction(); make it return None
    # by default to mirror the "items_total == 0" branch.
    r.progress_fraction = MagicMock(return_value=None)
    return r


def _make_client(*, user, existing_run=None, expect_create: bool = False):
    """Wire a minimal app with a MagicMock db.

    `existing_run` — what the idempotency lookup returns.
    `expect_create` — when the endpoint will INSERT a fresh row, the
        mock db.add() captures it so we can assert post-create state.
    """
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing_run

    created: list = []
    if expect_create:
        # In real life Postgres + SQLAlchemy populates server-side defaults
        # (`id = uuid.uuid4`, `created_at = now()`) on flush/refresh. With a
        # MagicMock db those callbacks never fire, so the endpoint sees a
        # TrainingRun with `id=None` and Pydantic blows up at response
        # serialization. Simulate the flush by stamping id + created_at on
        # `db.add()`.
        def _add(obj):
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.utcnow()
            created.append(obj)
        db.add.side_effect = _add
        db.refresh.side_effect = lambda o: None

    app = FastAPI()
    app.include_router(training_router, prefix="/api/v1")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user

    return TestClient(app), db, created


# ── POST /bulk-ingest ───────────────────────────────────────────────


def test_bulk_ingest_rejects_unknown_source():
    user = _fake_user(str(uuid.uuid4()), str(uuid.uuid4()))
    client, *_ = _make_client(user=user)
    body = {
        "source": "myspace",  # not in TRAINING_RUN_SOURCES
        "items": [{}],
        "snapshot_id": str(uuid.uuid4()),
    }
    resp = client.post("/api/v1/memory/training/bulk-ingest", json=body)
    # Pydantic literal validation fires first → 422. Either 400 or 422
    # is correct ("unknown source" guard would yield 400 if literal
    # accepted it).
    assert resp.status_code in (400, 422)


def test_bulk_ingest_deduplicates_on_existing_snapshot():
    """Re-POSTing the same snapshot returns the existing run without
    starting a parallel workflow."""
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    rid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    existing = _fake_run(rid, tid, snapshot_id=sid, items_total=42, status="running")
    client, db, _ = _make_client(user=user, existing_run=existing)

    body = {
        "source": "local_ai_cli",
        "items": [{"x": 1}] * 7,
        "snapshot_id": sid,
    }
    resp = client.post("/api/v1/memory/training/bulk-ingest", json=body)
    assert resp.status_code == 200
    j = resp.json()
    assert j["deduplicated"] is True
    assert j["run"]["id"] == rid
    assert j["run"]["status"] == "running"
    # The dispatch path must NOT have run — no workflow client was hit
    db.add.assert_not_called()
    db.commit.assert_not_called()


@patch("temporalio.client.Client.connect", new_callable=AsyncMock)
def test_bulk_ingest_starts_workflow_on_first_post(mock_connect):
    """First call inserts a new run row and dispatches the workflow."""
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    client, db, created = _make_client(user=user, existing_run=None, expect_create=True)

    # The Temporal client is async; mock its `.start_workflow` so the
    # endpoint dispatch path doesn't actually open a connection.
    mock_client = MagicMock()
    mock_client.start_workflow = AsyncMock(return_value=None)
    mock_connect.return_value = mock_client

    sid = str(uuid.uuid4())
    body = {
        "source": "local_ai_cli",
        "items": [{"i": i} for i in range(35)],
        "snapshot_id": sid,
    }
    resp = client.post("/api/v1/memory/training/bulk-ingest", json=body)
    assert resp.status_code == 200, resp.text
    j = resp.json()
    assert j["deduplicated"] is False
    assert j["run"]["items_total"] == 35
    # estimated_seconds: 35 items / 20 per batch = 2 batches × 3s = 6s
    assert j["estimated_seconds"] == 6
    # The endpoint asked the Temporal client for a workflow start
    mock_client.start_workflow.assert_awaited_once()
    # And persisted at least one row + a status update
    assert len(created) == 1
    assert db.commit.call_count >= 1


@patch("temporalio.client.Client.connect", new_callable=AsyncMock)
def test_bulk_ingest_rolls_back_when_workflow_dispatch_fails(mock_connect):
    """A Temporal-side failure deletes the freshly-inserted row so the
    caller can retry without tripping the unique index."""
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    client, db, created = _make_client(user=user, existing_run=None, expect_create=True)

    mock_connect.side_effect = RuntimeError("temporal unreachable")

    body = {
        "source": "local_ai_cli",
        "items": [{}, {}],
        "snapshot_id": str(uuid.uuid4()),
    }
    resp = client.post("/api/v1/memory/training/bulk-ingest", json=body)
    assert resp.status_code == 500
    assert "failed to start training workflow" in resp.json()["detail"]
    # The row that was added gets deleted on dispatch failure
    assert db.delete.called


# ── GET /{run_id} ───────────────────────────────────────────────────


def test_get_run_returns_owned_run():
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    rid = str(uuid.uuid4())
    run = _fake_run(rid, tid, status="complete", items_total=10, items_processed=10)
    run.progress_fraction = MagicMock(return_value=1.0)
    client, *_ = _make_client(user=user, existing_run=run)

    resp = client.get(f"/api/v1/memory/training/{rid}")
    assert resp.status_code == 200
    j = resp.json()
    assert j["id"] == rid
    assert j["status"] == "complete"
    assert j["progress_fraction"] == 1.0


def test_get_run_404_on_missing():
    user = _fake_user(str(uuid.uuid4()), str(uuid.uuid4()))
    client, *_ = _make_client(user=user, existing_run=None)
    resp = client.get(f"/api/v1/memory/training/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_run_404_on_cross_tenant_probe():
    """Returning the same 404 shape regardless of cause prevents a
    cross-tenant probe from oracle-ing run existence."""
    user = _fake_user(str(uuid.uuid4()), str(uuid.uuid4()))
    other_tenant = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    foreign_run = _fake_run(rid, other_tenant)
    client, *_ = _make_client(user=user, existing_run=foreign_run)

    resp = client.get(f"/api/v1/memory/training/{rid}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Training run not found"
