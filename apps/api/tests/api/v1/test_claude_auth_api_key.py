"""Tests for `POST /api/v1/claude-auth/api-key` (option a from the
claude_auth review).

The subscription-OAuth flow above (`/start`, `/status`, `/cancel`) is
architecturally broken inside the api container — claude CLI can't
receive its localhost callback. This endpoint is the fast-path
escape hatch: paste an Anthropic Console API key, land in the same
credential vault slot.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.claude_auth import router as claude_auth_router


def _fake_user(tenant_id: str | None = None):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID(tenant_id) if tenant_id else uuid.uuid4()
    u.is_active = True
    u.email = "claude-auth-test@example.test"
    return u


def _make_client(user, *, existing_config=None):
    """Wire a minimal app + a self-chaining db mock.

    Returns (client, db, captured_store_credential_calls).
    """
    # IntegrationConfig query chain: .filter(...).first() → existing config
    # or None. The endpoint creates one on None.
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.first.return_value = existing_config

    db = MagicMock()
    db.query.return_value = chain

    # Capture store_credential calls without actually running the
    # vault encryption path (that needs the Fernet key + DB session).
    captured_calls = []

    def fake_store_credential(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})

    app = FastAPI()
    app.include_router(claude_auth_router, prefix="/api/v1/claude-auth")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user

    # Monkey-patch the vault function on the module the endpoint uses.
    import app.api.v1.claude_auth as ca

    ca.store_credential = fake_store_credential  # type: ignore[assignment]

    return TestClient(app), db, captured_calls


def test_happy_path_stores_credential_as_api_key():
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    client, db, calls = _make_client(user)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHH"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"status": "connected", "connected": True, "credential_type": "api_key"}
    # store_credential called exactly once with credential_type='api_key'.
    assert len(calls) == 1
    kw = calls[0]["kwargs"]
    assert kw["credential_type"] == "api_key"
    assert kw["credential_key"] == "api_key"
    assert kw["plaintext_value"].startswith("sk-ant-")


def test_rejects_non_anthropic_prefix():
    """OpenAI keys / Claude.ai cookies / random strings → 400 with a
    pointer at console.anthropic.com so the user knows where to get
    the right key."""
    user = _fake_user()
    client, _, calls = _make_client(user)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "sk-proj-1234567890abcdefghij"},  # OpenAI shape
    )
    assert resp.status_code == 400
    assert "sk-ant-" in resp.json()["detail"]
    assert "console.anthropic.com" in resp.json()["detail"]
    # No store_credential call on failure.
    assert calls == []


def test_strips_env_var_prefix_paste_artifact():
    """User pastes from a `.env` line: `ANTHROPIC_API_KEY=sk-ant-...`.
    We strip the prefix before validation so it succeeds."""
    user = _fake_user()
    client, _, calls = _make_client(user)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "ANTHROPIC_API_KEY=sk-ant-api03-XXXXYYYYZZZZAAAA1111"},
    )
    assert resp.status_code == 200, resp.text
    assert calls[0]["kwargs"]["plaintext_value"].startswith("sk-ant-")
    # Confirm the prefix is gone, not just hiding.
    assert "ANTHROPIC_API_KEY" not in calls[0]["kwargs"]["plaintext_value"]


def test_strips_bearer_prefix_paste_artifact():
    user = _fake_user()
    client, _, calls = _make_client(user)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "Bearer sk-ant-api03-XXXXYYYYZZZZAAAA2222"},
    )
    assert resp.status_code == 200, resp.text
    assert calls[0]["kwargs"]["plaintext_value"].startswith("sk-ant-")


def test_strips_dotenv_double_quote_wrapping():
    """`KEY="sk-ant-..."` → store unquoted."""
    user = _fake_user()
    client, _, calls = _make_client(user)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": '"sk-ant-api03-XXXXYYYYZZZZAAAA3333"'},
    )
    assert resp.status_code == 200, resp.text
    stored = calls[0]["kwargs"]["plaintext_value"]
    assert stored.startswith("sk-ant-")
    assert not stored.startswith('"')
    assert not stored.endswith('"')


def test_rejects_short_string():
    """Pydantic `min_length=20` catches obvious typos before we get to
    the prefix check. Without this guard, `sk-ant-` alone would pass
    the prefix test and fail later when the agent tries to call
    Anthropic with an invalid key."""
    user = _fake_user()
    client, _, _ = _make_client(user)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "sk-ant-x"},
    )
    assert resp.status_code == 422  # FastAPI validation


def test_reuses_existing_integration_config():
    """If `IntegrationConfig(integration_name='claude_code')` already
    exists, don't create a new row — flip enabled=True if needed and
    use the existing id."""
    existing = MagicMock()
    existing.id = uuid.uuid4()
    existing.enabled = True

    user = _fake_user()
    client, db, calls = _make_client(user, existing_config=existing)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "sk-ant-api03-XXXXYYYYZZZZAAAA4444"},
    )
    assert resp.status_code == 200, resp.text
    # store_credential reuses existing.id, not a new id.
    assert calls[0]["kwargs"]["integration_config_id"] == existing.id
    # No db.add(IntegrationConfig) call when row exists.
    added_configs = [c for c in db.add.call_args_list if hasattr(c.args[0], "integration_name")]
    assert added_configs == []
