"""Tests for `apps/api/app/api/v1/tasks_fanout.py` (Phase 1 CLI prototype).

Pin the security and correctness guarantees of the prototype endpoint:

  MT-1 (round-2): cross-tenant /status leak regression — the B1 attack
      vector. User in tenant A dispatches a task; user in tenant B
      attempts /status with the same task_id and gets 404, NOT 200.

  MT-2 (round-2): MAX_TASKS_PER_TENANT cap returns 429 once exceeded.

  MT-3 (round-2): TTL eviction works in isolation via direct
      manipulation of the record's `created_at` (time.monotonic mock
      not needed at this scope — the sweep walks the dict and uses
      the recorded timestamp).

  L2-3 (round-2): whitespace-only providers + a real fanout is valid
      (strip_provider_names runs first and reduces providers to [],
      then the model_validator sees [] ∧ ["claude"] which is fine).

  M2-1 (round-2): X-Tenant-Id header mismatch returns 400.

These tests use FastAPI TestClient with a `get_current_user` override
so they run without a live Postgres backend.
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import tasks_fanout as tf
from app.models.user import User


def _user(tenant_id: Optional[str] = None) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"user-{uuid.uuid4().hex[:6]}@test.com",
        tenant_id=uuid.UUID(tenant_id) if tenant_id else uuid.uuid4(),
        is_active=True,
        is_superuser=False,
        hashed_password="x",
    )


def _make_client(user: User) -> TestClient:
    """Build a TestClient with `get_current_user` overridden to `user`.
    The `tasks_fanout` router is mounted at `/api/v1/tasks-fanout` to
    match production routing."""
    app = FastAPI()
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.include_router(tf.router, prefix="/api/v1/tasks-fanout")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _isolate_state():
    """Clear the module-level ledger between tests so cap counts and
    tenant-task accounting don't leak across cases."""
    tf._TASKS.clear()
    tf._TENANT_COUNTS.clear()
    yield
    tf._TASKS.clear()
    tf._TENANT_COUNTS.clear()


# ── MT-1: cross-tenant /status leak (B1 regression) ─────────────────


def test_cross_tenant_status_returns_404():
    """User in tenant A dispatches a task. User in tenant B attempts
    /status with that same task_id; must receive 404 (not 200, not
    403). 404 specifically — we do not leak existence."""

    user_a = _user()
    client_a = _make_client(user_a)
    resp = client_a.post(
        "/api/v1/tasks-fanout/run",
        json={"prompt": "tenant-A task"},
    )
    assert resp.status_code == 200, resp.text
    parent_task_id = resp.json()["task_id"]

    # Tenant B user — guess (or rather, know via leaked log) the task_id.
    user_b = _user()
    assert user_b.tenant_id != user_a.tenant_id
    client_b = _make_client(user_b)
    resp = client_b.get(f"/api/v1/tasks-fanout/{parent_task_id}/status")
    assert resp.status_code == 404, (
        f"Cross-tenant /status leak — expected 404 to avoid existence "
        f"oracle, got {resp.status_code}: {resp.text}"
    )


def test_cross_tenant_cancel_returns_404():
    """Same B1 attack against /cancel. Tenant B cannot delete tenant A's
    task even with the exact task_id."""

    user_a = _user()
    client_a = _make_client(user_a)
    resp = client_a.post("/api/v1/tasks-fanout/run", json={"prompt": "x"})
    parent_task_id = resp.json()["task_id"]

    user_b = _user()
    client_b = _make_client(user_b)
    resp = client_b.post(f"/api/v1/tasks-fanout/{parent_task_id}/cancel")
    assert resp.status_code == 404

    # And the task is still there for the rightful owner.
    resp = client_a.get(f"/api/v1/tasks-fanout/{parent_task_id}/status")
    assert resp.status_code == 200


# ── MT-2: MAX_TASKS_PER_TENANT cap ────────────────────────────────────


def test_cap_returns_429_after_max(monkeypatch):
    """Dispatching MAX + 1 single-task requests under the same tenant
    must 429 on the last. We monkeypatch MAX_TASKS_PER_TENANT down to 3
    so the test is fast."""

    monkeypatch.setattr(tf, "MAX_TASKS_PER_TENANT", 3)

    user = _user()
    client = _make_client(user)

    for i in range(3):
        resp = client.post("/api/v1/tasks-fanout/run", json={"prompt": f"task-{i}"})
        assert resp.status_code == 200, f"task #{i} should succeed: {resp.text}"

    # 4th must be rejected.
    resp = client.post("/api/v1/tasks-fanout/run", json={"prompt": "task-4"})
    assert resp.status_code == 429, resp.text
    assert "too many in-flight tasks" in resp.json()["detail"].lower()


def test_cap_counts_fanout_children(monkeypatch):
    """Parent + N children count separately. With MAX=4 and fanout=[a,b,c]
    one dispatch consumes 4 slots (parent + 3 children); a second dispatch
    of the same shape must 429."""

    monkeypatch.setattr(tf, "MAX_TASKS_PER_TENANT", 4)

    user = _user()
    client = _make_client(user)

    resp = client.post(
        "/api/v1/tasks-fanout/run",
        json={"prompt": "first fanout", "fanout": ["a", "b", "c"]},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["children"]) == 3

    # Cap is exhausted; second dispatch (any shape) must 429.
    resp = client.post("/api/v1/tasks-fanout/run", json={"prompt": "second"})
    assert resp.status_code == 429


# ── MT-3: TTL eviction ───────────────────────────────────────────────


def test_ttl_eviction_drops_expired_records():
    """Direct test of `_sweep_expired_tasks`. Mutate a record's
    `created_at` to a time before TASK_TTL_SECONDS ago; sweep must
    evict it and decrement the tenant counter."""

    user = _user()
    client = _make_client(user)

    resp = client.post("/api/v1/tasks-fanout/run", json={"prompt": "soon-to-expire"})
    task_id = resp.json()["task_id"]
    tenant_id = str(user.tenant_id)
    assert tf._TENANT_COUNTS.get(tenant_id) == 1
    assert task_id in tf._TASKS

    # Fast-forward the record's birth past the TTL.
    tf._TASKS[task_id]["created_at"] = time.monotonic() - (tf.TASK_TTL_SECONDS + 1.0)

    evicted = tf._sweep_expired_tasks()
    assert evicted == 1
    assert task_id not in tf._TASKS
    # Counter dropped to 0 -> key removed by _evict_record.
    assert tenant_id not in tf._TENANT_COUNTS


# ── L2-3: whitespace-only providers + fanout is valid ────────────────


def test_whitespace_only_providers_with_fanout_is_valid():
    """`{"providers": [" ", ""], "fanout": ["claude"]}` should NOT
    return 422 — the strip validator collapses providers to [] before
    the mutual-exclusion check sees it, so [] ∧ ["claude"] is fine."""

    user = _user()
    client = _make_client(user)
    resp = client.post(
        "/api/v1/tasks-fanout/run",
        json={
            "prompt": "x",
            "providers": [" ", ""],
            "fanout": ["claude"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["children"][0]["provider"] == "claude"


# ── M2-1: X-Tenant-Id header mismatch ────────────────────────────────


def test_x_tenant_id_mismatch_returns_400():
    """If the client sends X-Tenant-Id and it does not match the JWT
    tenant, return 400. This catches stale `~/.ap/config.toml` after
    a tenant switch."""

    user = _user()
    client = _make_client(user)
    resp = client.post(
        "/api/v1/tasks-fanout/run",
        json={"prompt": "x"},
        headers={"X-Tenant-Id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 400, resp.text
    assert "x-tenant-id" in resp.json()["detail"].lower()


def test_x_tenant_id_matching_is_accepted():
    """Matching X-Tenant-Id should not be rejected (the contract is
    'must equal', not 'must be absent')."""

    user = _user()
    client = _make_client(user)
    resp = client.post(
        "/api/v1/tasks-fanout/run",
        json={"prompt": "x"},
        headers={"X-Tenant-Id": str(user.tenant_id)},
    )
    assert resp.status_code == 200, resp.text


# ── Additional defense-in-depth: model_validator (M4) regression ─────


def test_providers_and_fanout_together_returns_422():
    """Round-1 M4: the model_validator must reject the combo at the
    schema level with 422 + structured field error."""

    user = _user()
    client = _make_client(user)
    resp = client.post(
        "/api/v1/tasks-fanout/run",
        json={"prompt": "x", "providers": ["claude"], "fanout": ["codex"]},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "mutually exclusive" in str(body).lower()


def test_cancelling_child_removes_it_from_parent_status():
    """Round-2 M2-2: cancelling a child task surgically removes it
    from the parent's children list so /status no longer reports
    the stale child."""

    user = _user()
    client = _make_client(user)
    resp = client.post(
        "/api/v1/tasks-fanout/run",
        json={"prompt": "x", "fanout": ["claude", "codex"]},
    )
    parent_id = resp.json()["task_id"]
    child_to_cancel = resp.json()["children"][0]["task_id"]

    # Cancel one child.
    resp = client.post(f"/api/v1/tasks-fanout/{child_to_cancel}/cancel")
    assert resp.status_code == 204

    # Parent /status no longer surfaces the cancelled child.
    resp = client.get(f"/api/v1/tasks-fanout/{parent_id}/status")
    assert resp.status_code == 200
    children = resp.json()["children"]
    assert all(c["task_id"] != child_to_cancel for c in children)
    assert len(children) == 1  # the other one still there
