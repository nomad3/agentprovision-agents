"""Tests for ``/api/v1/onboarding/*`` — PR-Q0.

Tenant onboarding state surface. Covers:

  - GET /status: un-onboarded → returns {onboarded: false, deferred: false}
  - GET /status: completed → returns the stamped timestamps + source
  - GET /status: deferred but not onboarded → returns {deferred: true}
  - GET /status: tenant 404 → 404
  - POST /defer: stamps onboarding_deferred_at, idempotent
  - POST /complete: stamps onboarded_at + source, idempotent
  - POST /complete: re-completion preserves original onboarded_at but
    updates source
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.onboarding import router as onboarding_router


# ── helpers ──────────────────────────────────────────────────────────


def _fake_user(user_id: str, tenant_id: str):
    u = MagicMock()
    u.id = uuid.UUID(user_id)
    u.tenant_id = uuid.UUID(tenant_id)
    u.is_active = True
    u.email = "u@x.com"
    return u


def _fake_tenant(
    tenant_id: str,
    *,
    onboarded_at: datetime | None = None,
    onboarding_deferred_at: datetime | None = None,
    onboarding_source: str | None = None,
):
    t = MagicMock()
    t.id = uuid.UUID(tenant_id)
    t.onboarded_at = onboarded_at
    t.onboarding_deferred_at = onboarding_deferred_at
    t.onboarding_source = onboarding_source
    return t


def _make_client(*, user, tenant):
    """Wire a minimal FastAPI app with a MagicMock db whose tenant
    lookup returns ``tenant`` (or None to simulate a missing tenant).
    """
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = tenant

    app = FastAPI()
    app.include_router(onboarding_router, prefix="/api/v1")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user

    return TestClient(app), db, tenant


# ── cases ────────────────────────────────────────────────────────────


def test_status_unonboarded():
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    tenant = _fake_tenant(tid)
    client, *_ = _make_client(user=user, tenant=tenant)
    resp = client.get("/api/v1/onboarding/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["onboarded"] is False
    assert body["deferred"] is False
    assert body["onboarded_at"] is None
    # Defaults to a non-empty recommendation so the picker has a hint.
    assert body["recommended_channel"] in {
        "claude_code", "codex", "gemini_cli", "copilot_cli",
        "opencode", "github_cli", "gmail", "slack", "whatsapp",
    }


def test_status_completed():
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    when = datetime(2026, 5, 11, 21, 0, 0)
    tenant = _fake_tenant(tid, onboarded_at=when, onboarding_source="cli")
    client, *_ = _make_client(user=user, tenant=tenant)
    resp = client.get("/api/v1/onboarding/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["onboarded"] is True
    assert body["onboarding_source"] == "cli"
    assert body["onboarded_at"].startswith("2026-05-11T21:00:00")


def test_status_deferred_but_not_onboarded():
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    when = datetime(2026, 5, 11, 12, 0, 0)
    tenant = _fake_tenant(tid, onboarding_deferred_at=when)
    client, *_ = _make_client(user=user, tenant=tenant)
    resp = client.get("/api/v1/onboarding/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["onboarded"] is False
    assert body["deferred"] is True


def test_status_tenant_404():
    user = _fake_user(str(uuid.uuid4()), str(uuid.uuid4()))
    client, *_ = _make_client(user=user, tenant=None)
    resp = client.get("/api/v1/onboarding/status")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Tenant not found"


def test_defer_stamps_timestamp_and_commits():
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    tenant = _fake_tenant(tid)
    client, db, t = _make_client(user=user, tenant=tenant)
    assert t.onboarding_deferred_at is None
    resp = client.post("/api/v1/onboarding/defer")
    assert resp.status_code == 204
    assert t.onboarding_deferred_at is not None
    assert isinstance(t.onboarding_deferred_at, datetime)
    db.commit.assert_called_once()


def test_defer_is_idempotent_and_refreshes():
    """Calling defer a second time refreshes the timestamp (newer
    win); this is intentional so the next auto-trigger suppression
    starts from the most recent skip."""
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    earlier = datetime.utcnow() - timedelta(hours=1)
    tenant = _fake_tenant(tid, onboarding_deferred_at=earlier)
    client, _, t = _make_client(user=user, tenant=tenant)
    resp = client.post("/api/v1/onboarding/defer")
    assert resp.status_code == 204
    assert t.onboarding_deferred_at > earlier


def test_complete_stamps_onboarded_at_and_source():
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    tenant = _fake_tenant(tid)
    client, db, t = _make_client(user=user, tenant=tenant)
    resp = client.post("/api/v1/onboarding/complete", json={"source": "cli"})
    assert resp.status_code == 204
    assert t.onboarded_at is not None
    assert t.onboarding_source == "cli"
    db.commit.assert_called_once()


def test_complete_recompletion_preserves_onboarded_at_but_updates_source():
    """If the user runs `alpha quickstart --force` (or the web flow
    re-completes), preserve the original onboarded_at timestamp for
    audit clarity but update onboarding_source to the latest
    surface that completed."""
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    original = datetime(2026, 4, 1, 12, 0, 0)
    tenant = _fake_tenant(tid, onboarded_at=original, onboarding_source="cli")
    client, _, t = _make_client(user=user, tenant=tenant)
    resp = client.post("/api/v1/onboarding/complete", json={"source": "web"})
    assert resp.status_code == 204
    assert t.onboarded_at == original  # preserved
    assert t.onboarding_source == "web"  # updated


def test_complete_default_source_is_cli():
    """The CLI is the primary surface for onboarding; defaulting the
    `source` payload keeps the CLI client's POST body terse."""
    tid = str(uuid.uuid4())
    user = _fake_user(str(uuid.uuid4()), tid)
    tenant = _fake_tenant(tid)
    client, _, t = _make_client(user=user, tenant=tenant)
    resp = client.post("/api/v1/onboarding/complete")  # no body
    assert resp.status_code == 204
    assert t.onboarding_source == "cli"
