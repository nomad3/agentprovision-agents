"""Tests for the gh-style device-flow login endpoints used by the
``agentprovision`` CLI binary.

Three endpoints round-trip via Redis state:

  1. POST /api/v1/auth/device-code     — CLI mints (no auth)
  2. POST /api/v1/auth/device-approve  — Web UI binds an access_token (JWT auth)
  3. POST /api/v1/auth/device-token    — CLI polls (no auth)

Tests use a fakeredis-style MagicMock to keep this hermetic.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.auth import router as auth_router
from app.core.config import settings


# ── In-memory fake Redis ──────────────────────────────────────────────────


class _FakeRedis:
    """Just enough Redis surface for the device-flow code path."""

    def __init__(self):
        self._store: dict[str, bytes] = {}

    def set(self, key: str, value, ex: int | None = None):
        if isinstance(value, str):
            value = value.encode("utf-8")
        self._store[key] = value

    def get(self, key: str):
        return self._store.get(key)

    def delete(self, key: str):
        self._store.pop(key, None)


@pytest.fixture
def fake_redis():
    return _FakeRedis()


@pytest.fixture
def client(fake_redis):
    """TestClient with the auth router mounted and Redis stubbed."""
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    # Patch the redis factory function used inside auth.py.
    with patch("app.api.v1.auth._device_redis", return_value=fake_redis):
        yield TestClient(app)


@pytest.fixture
def fake_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.tenant_id = uuid.uuid4()
    user.is_active = True
    return user


# ── /device-code ──────────────────────────────────────────────────────────


def test_device_code_returns_required_fields(client):
    """The CLI must receive enough to print + poll."""
    resp = client.post("/api/v1/auth/device-code")
    assert resp.status_code == 200
    body = resp.json()
    for k in (
        "device_code",
        "user_code",
        "verification_uri",
        "verification_uri_complete",
        "expires_in",
        "interval",
    ):
        assert k in body, f"missing field: {k}"
    # user_code is XXXX-XXXX (8 chars + 1 dash from the friendly alphabet).
    assert "-" in body["user_code"]
    assert len(body["user_code"]) == 9
    # device_code is opaque, urlsafe base64
    assert len(body["device_code"]) >= 32


def test_device_code_503_when_redis_down():
    """If Redis is unavailable, fail closed — CLI falls back to password."""
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    with patch("app.api.v1.auth._device_redis", return_value=None):
        c = TestClient(app)
        resp = c.post("/api/v1/auth/device-code")
    assert resp.status_code == 503


# ── /device-token (polling) ──────────────────────────────────────────────


def test_device_token_authorization_pending_when_unapproved(client, fake_redis):
    """Before the user approves, polling returns 400 + authorization_pending —
    matches GitHub's wire model so any gh-style polling client works."""
    init = client.post("/api/v1/auth/device-code").json()
    resp = client.post(
        "/api/v1/auth/device-token",
        json={"device_code": init["device_code"]},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "authorization_pending"


def test_device_token_expired_when_unknown_device_code(client):
    resp = client.post(
        "/api/v1/auth/device-token",
        json={"device_code": "this-was-never-minted"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "expired_token"


def test_device_token_invalid_request_when_empty_code(client):
    resp = client.post("/api/v1/auth/device-token", json={"device_code": ""})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "invalid_request"


def test_device_token_returns_access_token_when_approved(client, fake_redis):
    """Hand-prime the Redis state to 'approved' (skipping the JWT-gated
    /device-approve which requires a real DB)."""
    init = client.post("/api/v1/auth/device-code").json()
    state_key = f"auth:device:{init['device_code']}"
    primed = json.dumps(
        {
            "user_code": init["user_code"],
            "status": "approved",
            "access_token": "fake-jwt-from-approve",
        }
    )
    fake_redis.set(state_key, primed)

    resp = client.post(
        "/api/v1/auth/device-token",
        json={"device_code": init["device_code"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "fake-jwt-from-approve"
    assert body["token_type"] == "bearer"


def test_device_token_one_shot_consumed_on_first_success(client, fake_redis):
    """Defence in depth: a leaked device_code in transit cannot be replayed —
    the device_code is deleted from Redis on first successful 200."""
    init = client.post("/api/v1/auth/device-code").json()
    state_key = f"auth:device:{init['device_code']}"
    user_key = f"auth:device:user:{init['user_code']}"
    fake_redis.set(
        state_key,
        json.dumps(
            {
                "user_code": init["user_code"],
                "status": "approved",
                "access_token": "single-use-jwt",
            }
        ),
    )
    fake_redis.set(user_key, init["device_code"])

    # First poll succeeds.
    resp1 = client.post(
        "/api/v1/auth/device-token",
        json={"device_code": init["device_code"]},
    )
    assert resp1.status_code == 200
    # Second poll with the same device_code → 400 expired.
    resp2 = client.post(
        "/api/v1/auth/device-token",
        json={"device_code": init["device_code"]},
    )
    assert resp2.status_code == 400
    assert resp2.json()["detail"]["error"] == "expired_token"


def test_device_token_access_denied(client, fake_redis):
    """If the user clicks 'Reject' in the web UI, status flips to 'denied'."""
    init = client.post("/api/v1/auth/device-code").json()
    state_key = f"auth:device:{init['device_code']}"
    fake_redis.set(
        state_key,
        json.dumps(
            {"user_code": init["user_code"], "status": "denied", "access_token": None}
        ),
    )
    resp = client.post(
        "/api/v1/auth/device-token",
        json={"device_code": init["device_code"]},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "access_denied"


def test_device_token_corrupted_approved_state_returns_expired(client, fake_redis):
    """Defence: status='approved' but no token in state (race / corruption) →
    400 expired (NEVER 500). CLI re-bootstraps cleanly."""
    init = client.post("/api/v1/auth/device-code").json()
    state_key = f"auth:device:{init['device_code']}"
    fake_redis.set(
        state_key,
        json.dumps(
            {"user_code": init["user_code"], "status": "approved", "access_token": None}
        ),
    )
    resp = client.post(
        "/api/v1/auth/device-token",
        json={"device_code": init["device_code"]},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "expired_token"


# ── /device-approve (JWT-gated) ──────────────────────────────────────────


def test_device_approve_requires_existing_user_code(client, fake_user):
    """user_code that was never minted → 404, not info-leaky 200."""
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    app.dependency_overrides[deps.get_current_active_user] = lambda: fake_user

    with patch("app.api.v1.auth._device_redis", return_value=_FakeRedis()):
        c = TestClient(app)
        resp = c.post(
            "/api/v1/auth/device-approve",
            json={"user_code": "FAKE-CODE"},
        )
    assert resp.status_code == 404


def test_device_approve_round_trip_binds_token(fake_user):
    """End-to-end: mint → approve (as logged-in user) → poll → token."""
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    app.dependency_overrides[deps.get_current_active_user] = lambda: fake_user

    fr = _FakeRedis()
    with patch("app.api.v1.auth._device_redis", return_value=fr):
        c = TestClient(app)
        init = c.post("/api/v1/auth/device-code").json()

        # 'I' and 'O' are excluded from the alphabet; user_code is uppercase.
        approve_resp = c.post(
            "/api/v1/auth/device-approve",
            json={"user_code": init["user_code"]},
        )
        assert approve_resp.status_code == 200, approve_resp.text
        assert approve_resp.json() == {"approved": True}

        token_resp = c.post(
            "/api/v1/auth/device-token",
            json={"device_code": init["device_code"]},
        )
        assert token_resp.status_code == 200
        body = token_resp.json()
        assert body["token_type"] == "bearer"
        # access_token is a real JWT minted via security.create_access_token.
        # Just sanity-check the JWT shape (3 parts separated by '.').
        assert len(body["access_token"].split(".")) == 3


def test_device_approve_lowercase_user_code_normalises(fake_user):
    """The /device-code endpoint returns uppercase XXXX-XXXX. Accept lowercase
    too — users will retype + autocorrect will mangle the case."""
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    app.dependency_overrides[deps.get_current_active_user] = lambda: fake_user

    fr = _FakeRedis()
    with patch("app.api.v1.auth._device_redis", return_value=fr):
        c = TestClient(app)
        init = c.post("/api/v1/auth/device-code").json()

        resp = c.post(
            "/api/v1/auth/device-approve",
            json={"user_code": init["user_code"].lower()},
        )
    assert resp.status_code == 200
