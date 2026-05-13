"""Tests for ``POST /api/v1/agent-tokens/mint`` — PR-E.

User-Bearer-authenticated mint endpoint. Covers the cases from the
review S-1 matrix:

  - Cross-tenant probe → 404 (no existence oracle)
  - Missing agent → 404 (same body)
  - Viewer permission → 403
  - Editor permission → 200
  - Admin permission → 200
  - Owner (agent.owner_user_id) → 200
  - Superuser cross-tenant → 404 (tenant gate fires first — review S-2)
  - Scope passthrough into the JWT claim
  - heartbeat_timeout clamp via Pydantic ge/le → 422
  - Roundtrip mint → verify_agent_token returns matching claims
  - exp math: exp - iat == 2 * heartbeat_timeout
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from app.api import deps
from app.api.v1.agent_tokens import router as agent_tokens_router
from app.core.config import settings
from app.services.agent_token import verify_agent_token


# ── helpers ──────────────────────────────────────────────────────────


def _user_jwt(user_id: str, tenant_id: str) -> str:
    """Mint a regular `kind=access` user JWT — same shape as `/auth/login`."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "kind": "access",
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + 600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _fake_user(
    user_id: str,
    tenant_id: str,
    *,
    is_superuser: bool = False,
):
    u = MagicMock()
    u.id = uuid.UUID(user_id)
    u.tenant_id = uuid.UUID(tenant_id)
    u.is_superuser = is_superuser
    u.is_active = True
    u.email = "u@x.com"
    return u


def _fake_agent(agent_id: str, tenant_id: str, *, owner_user_id: str | None = None):
    a = MagicMock()
    a.id = uuid.UUID(agent_id)
    a.tenant_id = uuid.UUID(tenant_id)
    a.owner_user_id = uuid.UUID(owner_user_id) if owner_user_id else None
    return a


def _make_client(
    *,
    user,
    agent_lookup=None,
    permission_grant=None,
):
    """Wire a minimal FastAPI app with overrides for the deps the
    endpoint touches:

    * ``deps.get_current_active_user`` → the fixed user
    * ``deps.get_db`` → a MagicMock whose .query().filter().first()
      returns ``agent_lookup`` first, then ``permission_grant``.

    The endpoint calls .query(Agent).filter(...).first() and then,
    only if needed, .query(AgentPermission).filter(...).first().
    side_effect makes the second call return the grant.
    """
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        agent_lookup,
        permission_grant,
    ]

    app = FastAPI()
    app.include_router(agent_tokens_router, prefix="/api/v1")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user

    return TestClient(app), db


def _body(agent_id: str, *, scope=None, heartbeat_timeout_seconds=240):
    out = {"agent_id": agent_id, "heartbeat_timeout_seconds": heartbeat_timeout_seconds}
    if scope is not None:
        out["scope"] = scope
    return out


# ── cases ────────────────────────────────────────────────────────────


def test_missing_agent_returns_404():
    user_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    user = _fake_user(user_id, tenant_id)
    client, _ = _make_client(user=user, agent_lookup=None)
    resp = client.post("/api/v1/agent-tokens/mint", json=_body(str(uuid.uuid4())))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Agent not found"


def test_cross_tenant_agent_returns_404_not_403():
    """Review S-2: tenant gate fires before any other check — no oracle."""
    user_id, tenant_a = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())  # agent belongs here
    agent_id = str(uuid.uuid4())
    user = _fake_user(user_id, tenant_a)
    agent = _fake_agent(agent_id, tenant_b)  # different tenant
    client, _ = _make_client(user=user, agent_lookup=agent)
    resp = client.post("/api/v1/agent-tokens/mint", json=_body(agent_id))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Agent not found"


def test_viewer_permission_returns_403():
    """Viewer is read-only by contract — minting is side-effect-enabling."""
    user_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    user = _fake_user(user_id, tenant_id)
    agent = _fake_agent(agent_id, tenant_id, owner_user_id=None)
    # No editor/admin grant — permission_grant resolves to None.
    client, _ = _make_client(user=user, agent_lookup=agent, permission_grant=None)
    resp = client.post("/api/v1/agent-tokens/mint", json=_body(agent_id))
    assert resp.status_code == 403


def test_editor_permission_returns_200():
    user_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    user = _fake_user(user_id, tenant_id)
    agent = _fake_agent(agent_id, tenant_id, owner_user_id=None)
    grant = MagicMock()  # truthy → has_grant
    client, _ = _make_client(user=user, agent_lookup=agent, permission_grant=grant)
    resp = client.post("/api/v1/agent-tokens/mint", json=_body(agent_id))
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert body["agent_id"] == agent_id
    assert body["expires_in_seconds"] == 480  # 2 * 240


def test_owner_permission_returns_200_without_grant():
    """`agent.owner_user_id == user.id` bypasses AgentPermission lookup."""
    user_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    user = _fake_user(user_id, tenant_id)
    agent = _fake_agent(agent_id, tenant_id, owner_user_id=user_id)
    # permission_grant=None — owner shouldn't need a row.
    client, _ = _make_client(user=user, agent_lookup=agent, permission_grant=None)
    resp = client.post("/api/v1/agent-tokens/mint", json=_body(agent_id))
    assert resp.status_code == 200


def test_superuser_in_tenant_returns_200():
    user_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    user = _fake_user(user_id, tenant_id, is_superuser=True)
    agent = _fake_agent(agent_id, tenant_id, owner_user_id=None)
    client, _ = _make_client(user=user, agent_lookup=agent, permission_grant=None)
    resp = client.post("/api/v1/agent-tokens/mint", json=_body(agent_id))
    assert resp.status_code == 200


def test_superuser_cross_tenant_returns_404():
    """Review S-2: tenant check fires before superuser check.

    This is the right behaviour — a superuser running `alpha claude-code`
    against a foreign tenant's agent_id by accident shouldn't mint
    cross-tenant. The X-Internal-Key path is the only way to mint
    across tenants.
    """
    user_id, tenant_a, tenant_b = (str(uuid.uuid4()) for _ in range(3))
    agent_id = str(uuid.uuid4())
    user = _fake_user(user_id, tenant_a, is_superuser=True)
    agent = _fake_agent(agent_id, tenant_b)  # foreign tenant
    client, _ = _make_client(user=user, agent_lookup=agent)
    resp = client.post("/api/v1/agent-tokens/mint", json=_body(agent_id))
    assert resp.status_code == 404


def test_scope_passthrough_into_claim():
    user_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    user = _fake_user(user_id, tenant_id)
    agent = _fake_agent(agent_id, tenant_id, owner_user_id=user_id)
    client, _ = _make_client(user=user, agent_lookup=agent)
    scope = ["calculator", "sql_query"]
    resp = client.post(
        "/api/v1/agent-tokens/mint",
        json=_body(agent_id, scope=scope),
    )
    assert resp.status_code == 200
    # verify_agent_token returns the raw JWT payload dict (see
    # agent_token.py:147), not an `AgentTokenClaims` instance — the type
    # annotation is aspirational. Index into the dict.
    claims = verify_agent_token(resp.json()["token"])
    assert claims["scope"] == scope


def test_scope_omitted_means_none_in_claim():
    user_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    user = _fake_user(user_id, tenant_id)
    agent = _fake_agent(agent_id, tenant_id, owner_user_id=user_id)
    client, _ = _make_client(user=user, agent_lookup=agent)
    resp = client.post("/api/v1/agent-tokens/mint", json=_body(agent_id))
    assert resp.status_code == 200
    claims = verify_agent_token(resp.json()["token"])
    assert claims["scope"] is None


def test_heartbeat_below_minimum_returns_422():
    user_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    user = _fake_user(user_id, tenant_id)
    client, _ = _make_client(user=user, agent_lookup=None)
    resp = client.post(
        "/api/v1/agent-tokens/mint",
        json=_body(str(uuid.uuid4()), heartbeat_timeout_seconds=10),
    )
    assert resp.status_code == 422


def test_heartbeat_above_maximum_returns_422():
    user_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    user = _fake_user(user_id, tenant_id)
    client, _ = _make_client(user=user, agent_lookup=None)
    resp = client.post(
        "/api/v1/agent-tokens/mint",
        json=_body(str(uuid.uuid4()), heartbeat_timeout_seconds=3601),
    )
    assert resp.status_code == 422


def test_roundtrip_mint_then_verify():
    user_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    user = _fake_user(user_id, tenant_id)
    agent = _fake_agent(agent_id, tenant_id, owner_user_id=user_id)
    client, _ = _make_client(user=user, agent_lookup=agent)
    resp = client.post("/api/v1/agent-tokens/mint", json=_body(agent_id))
    assert resp.status_code == 200
    body = resp.json()
    claims = verify_agent_token(body["token"])
    assert claims["tenant_id"] == tenant_id
    assert claims["agent_id"] == agent_id
    assert claims["task_id"] == body["task_id"]
    # User dispatch is always top-level — these should be cleared.
    assert claims["parent_workflow_id"] is None
    assert claims["parent_chain"] == []
    # exp - iat == 2 * heartbeat_timeout (default 240)
    assert claims["exp"] - claims["iat"] == 480
