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


def _make_client(user, *, monkeypatch, existing_config=None):
    """Wire a minimal app + a self-chaining db mock.

    Returns (client, db, captured_calls, query_filter_calls).
    """
    # IntegrationConfig query chain: .filter(...).first() → existing config
    # or None. The endpoint creates one on None.
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.first.return_value = existing_config
    # `_revoke_other_claude_credentials` runs `.filter(...).update(...)`
    # against the same chain — return-value-of-update doesn't matter, but
    # the chain must remain self-chaining.
    chain.update.return_value = None

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
    # `monkeypatch.setattr` undoes the mutation at test teardown, so the
    # next test (or anything else importing claude_auth in the same
    # pytest process) sees the real function again.
    import app.api.v1.claude_auth as ca

    monkeypatch.setattr(ca, "store_credential", fake_store_credential)

    return TestClient(app), db, captured_calls, chain


def test_happy_path_stores_credential_as_api_key(monkeypatch):
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    client, db, calls, chain = _make_client(user, monkeypatch=monkeypatch)
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
    # Tenant isolation: store_credential MUST receive the caller's
    # tenant_id, not anything else. A regression that dropped tenant_id
    # from the WHERE clause would silently pass without this assertion.
    assert kw["tenant_id"] == user.tenant_id


def test_filters_integration_config_by_tenant_id(monkeypatch):
    """The IntegrationConfig lookup must include `tenant_id == user.tenant_id`.

    Inspects `db.query(...).filter(...)` call args to confirm a
    BinaryExpression referencing the tenant_id column landed in the
    filter chain (rather than e.g. a global integration_name match).
    """
    user = _fake_user("22222222-2222-2222-2222-222222222222")
    client, _, _, chain = _make_client(user, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "sk-ant-api03-tenant-filter-test-1234567"},
    )
    assert resp.status_code == 200, resp.text
    # chain.filter was called at least twice (config lookup + revoke).
    # The first call (config lookup) must include a tenant predicate.
    first_filter_args = chain.filter.call_args_list[0].args
    rendered = " ".join(str(a) for a in first_filter_args)
    assert "tenant_id" in rendered.lower()


def test_rejects_non_anthropic_prefix(monkeypatch):
    """OpenAI keys / Claude.ai cookies / random strings → 400 with a
    pointer at console.anthropic.com so the user knows where to get
    the right key."""
    user = _fake_user()
    client, _, calls, _ = _make_client(user, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "sk-proj-1234567890abcdefghij"},  # OpenAI shape
    )
    assert resp.status_code == 400
    assert "sk-ant-" in resp.json()["detail"]
    assert "console.anthropic.com" in resp.json()["detail"]
    # No store_credential call on failure.
    assert calls == []


def test_strips_env_var_prefix_paste_artifact(monkeypatch):
    """User pastes from a `.env` line: `ANTHROPIC_API_KEY=sk-ant-...`.
    We strip the prefix before validation so it succeeds."""
    user = _fake_user()
    client, _, calls, _ = _make_client(user, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "ANTHROPIC_API_KEY=sk-ant-api03-XXXXYYYYZZZZAAAA1111"},
    )
    assert resp.status_code == 200, resp.text
    assert calls[0]["kwargs"]["plaintext_value"].startswith("sk-ant-")
    # Confirm the prefix is gone, not just hiding.
    assert "ANTHROPIC_API_KEY" not in calls[0]["kwargs"]["plaintext_value"]


def test_strips_export_shell_prefix(monkeypatch):
    """`export ANTHROPIC_API_KEY=sk-ant-...` (shell history paste)."""
    user = _fake_user()
    client, _, calls, _ = _make_client(user, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "export ANTHROPIC_API_KEY=sk-ant-api03-shell-history-1234"},
    )
    assert resp.status_code == 200, resp.text
    stored = calls[0]["kwargs"]["plaintext_value"]
    assert stored.startswith("sk-ant-")
    assert "export" not in stored


def test_strips_x_api_key_header_prefix(monkeypatch):
    """`x-api-key: sk-ant-...` (curl-from-docs paste)."""
    user = _fake_user()
    client, _, calls, _ = _make_client(user, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "x-api-key: sk-ant-api03-curl-paste-1234567"},
    )
    assert resp.status_code == 200, resp.text
    stored = calls[0]["kwargs"]["plaintext_value"]
    assert stored.startswith("sk-ant-")
    assert "x-api-key" not in stored.lower()


def test_strips_bearer_prefix_paste_artifact(monkeypatch):
    user = _fake_user()
    client, _, calls, _ = _make_client(user, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "Bearer sk-ant-api03-XXXXYYYYZZZZAAAA2222"},
    )
    assert resp.status_code == 200, resp.text
    assert calls[0]["kwargs"]["plaintext_value"].startswith("sk-ant-")


def test_strips_uppercase_bearer_prefix(monkeypatch):
    """Case-insensitive prefix matching: `BEARER sk-ant-...` works too."""
    user = _fake_user()
    client, _, calls, _ = _make_client(user, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "BEARER sk-ant-api03-caps-bearer-1234567"},
    )
    assert resp.status_code == 200, resp.text
    stored = calls[0]["kwargs"]["plaintext_value"]
    assert stored.startswith("sk-ant-")
    assert not stored.lower().startswith("bearer")


def test_strips_dotenv_double_quote_wrapping(monkeypatch):
    """`KEY="sk-ant-..."` → store unquoted."""
    user = _fake_user()
    client, _, calls, _ = _make_client(user, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": '"sk-ant-api03-XXXXYYYYZZZZAAAA3333"'},
    )
    assert resp.status_code == 200, resp.text
    stored = calls[0]["kwargs"]["plaintext_value"]
    assert stored.startswith("sk-ant-")
    assert not stored.startswith('"')
    assert not stored.endswith('"')


def test_strips_yaml_extra_whitespace(monkeypatch):
    """`ANTHROPIC_API_KEY:    sk-ant-...` (YAML-style multi-space)."""
    user = _fake_user()
    client, _, calls, _ = _make_client(user, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "ANTHROPIC_API_KEY:    sk-ant-api03-yaml-1234567"},
    )
    assert resp.status_code == 200, resp.text
    stored = calls[0]["kwargs"]["plaintext_value"]
    assert stored.startswith("sk-ant-")


def test_rejects_below_min_length_boundary(monkeypatch):
    """Pydantic `min_length=20` boundary: 19 chars rejected, 20 accepted.

    Without testing both sides of the boundary, a regression that
    relaxed `min_length` to e.g. 10 would slip through.
    """
    user = _fake_user()
    client, _, _, _ = _make_client(user, monkeypatch=monkeypatch)
    # 19 chars — must be < min_length to fail
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "x" * 19},
    )
    assert resp.status_code == 422


def test_min_length_boundary_accepts_at_exactly_20(monkeypatch):
    """Exactly 20 chars passes Pydantic; prefix check still applies."""
    user = _fake_user()
    client, _, _, _ = _make_client(user, monkeypatch=monkeypatch)
    # 20 chars but wrong prefix → 400 (passes pydantic, fails prefix).
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "x" * 20},
    )
    assert resp.status_code == 400  # NOT 422 — proves length passed.


def test_reuses_existing_integration_config(monkeypatch):
    """If `IntegrationConfig(integration_name='claude_code')` already
    exists, don't create a new row — flip enabled=True if needed and
    use the existing id."""
    existing = MagicMock()
    existing.id = uuid.uuid4()
    existing.enabled = True

    user = _fake_user()
    client, db, calls, _ = _make_client(user, monkeypatch=monkeypatch, existing_config=existing)
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


def test_revokes_cross_flow_session_token_before_storing(monkeypatch):
    """B1 regression guard: the new /api-key endpoint must run the
    cross-key revoke (`_revoke_other_claude_credentials(keep='api_key')`)
    before `store_credential`. Without it, an OAuth `session_token`
    sitting in the same IntegrationConfig stays active and
    downstream readers silently prefer it. A regression that drops
    the revoke call would otherwise pass all happy-path tests.
    """
    user = _fake_user()
    client, db, _, chain = _make_client(user, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/claude-auth/api-key",
        json={"api_key": "sk-ant-api03-cross-key-revoke-test-1"},
    )
    assert resp.status_code == 200, resp.text
    # The cross-key revoke uses `.update({"status": "revoked"}, ...)`.
    # Assert it ran with the right payload.
    chain.update.assert_called_once()
    update_payload = chain.update.call_args.args[0]
    assert update_payload == {"status": "revoked"}, (
        f"Expected revoke-payload {{'status': 'revoked'}}; got {update_payload}"
    )


def test_normalise_api_key_paste_is_idempotent():
    """Re-running the normaliser on its own output is a no-op."""
    from app.api.v1.claude_auth import _normalise_api_key_paste

    inputs = [
        "sk-ant-api03-AAAABBBBCCCCDDDDEEEE",
        'ANTHROPIC_API_KEY="sk-ant-api03-AAAABBBBCCCC"',
        "Bearer sk-ant-api03-AAAABBBBCCCC",
        "  sk-ant-api03-AAAABBBBCCCC  ",
        "x-api-key: sk-ant-api03-AAAABBBBCCCC",
    ]
    for raw in inputs:
        first = _normalise_api_key_paste(raw)
        second = _normalise_api_key_paste(first)
        assert first == second, f"non-idempotent for {raw!r}: {first!r} → {second!r}"
        assert first.startswith("sk-ant-"), f"failed to peel {raw!r} → {first!r}"
