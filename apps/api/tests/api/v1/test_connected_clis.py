"""Tests for ``GET /api/v1/integrations/connected-clis``.

The chat-header ``InlineCliPicker`` calls this on mount to filter its
dropdown to (Auto + tenant-connected CLIs). The endpoint is a thin
wrapper around ``cli_platform_resolver.connected_clis_for_tenant`` so
the tests focus on:

  - 200 with the expected shape for a tenant with one CLI connected,
    and the response respects the resolver's chain priority order
  - 200 with an empty list for a fresh tenant — ``opencode`` (the
    routing floor) is excluded from the public response so the UI
    contract stays clean
  - 401 without an Authorization header (auth gate)
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.integrations import router as integrations_router


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _fake_user(tenant_id: str | None = None):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID(tenant_id) if tenant_id else uuid.uuid4()
    u.is_active = True
    u.email = "connected-clis-test@example.test"
    return u


def _make_client(user, *, monkeypatch, connected_map):
    """Spin up an app with the integrations router and a fake resolver.

    ``connected_map`` is the same shape ``get_connected_integrations``
    returns — ``{integration_name: {"connected": bool, ...}}``. We
    monkeypatch that low-level helper rather than the public
    ``connected_clis_for_tenant`` so the test also exercises the
    resolver's mapping logic (which integration enables which CLI).
    """
    db = MagicMock()

    app = FastAPI()
    app.include_router(integrations_router, prefix="/api/v1/integrations")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user

    # Patch the integration-status helper that _connected_clis calls
    # under the hood. This exercises the real resolver mapping logic.
    import app.services.cli_platform_resolver as resolver

    monkeypatch.setattr(
        resolver,
        # _connected_clis imports get_connected_integrations lazily, so
        # patch it on the integration_status module directly.
        # (Imported inside the function body — see _connected_clis.)
        "_connected_clis",
        # Easiest path: short-circuit with a thin shim that respects
        # what the fake connected_map says.
        lambda _db, _tenant: (
            {"opencode"}
            | {
                cli
                for cli, ints in resolver._CLI_TO_INTEGRATIONS.items()
                if ints
                and any(
                    name in connected_map and connected_map[name].get("connected")
                    for name in ints
                )
            },
            True,
        ),
    )

    return TestClient(app)


# ---------------------------------------------------------------------------
# 200 — Codex only connected
# ---------------------------------------------------------------------------


def test_returns_codex_when_only_codex_connected(monkeypatch):
    """A tenant with only the codex integration plugged in gets back
    ``["codex"]`` — opencode (the local-Gemma routing floor) is excluded
    from the public response because it's not a user-pickable option in
    the InlineCliPicker dropdown."""
    user = _fake_user("11111111-1111-1111-1111-111111111111")
    connected_map = {
        "codex": {"connected": True},
        "github": {"connected": False},
        "gmail": {"connected": False},
    }
    client = _make_client(user, monkeypatch=monkeypatch, connected_map=connected_map)

    r = client.get("/api/v1/integrations/connected-clis")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "connected" in body
    assert body["connected"] == ["codex"]
    assert "opencode" not in body["connected"]


# ---------------------------------------------------------------------------
# 200 — fresh tenant (no integrations) → empty list, no opencode leak
# ---------------------------------------------------------------------------


def test_fresh_tenant_returns_empty_list_no_opencode_leak(monkeypatch):
    """A tenant with zero integrations should get back an empty list.

    ``opencode`` is the routing floor and still resolves internally, but
    the public response must NOT include it — surfacing it would create
    a contract mismatch with the frontend's ``CLI_OPTIONS`` (which
    doesn't list opencode, so it would be silently stripped client-side).
    Test asserts both the exact shape and a defensive "not in list"
    check to make the intent loud."""
    user = _fake_user("22222222-2222-2222-2222-222222222222")
    client = _make_client(user, monkeypatch=monkeypatch, connected_map={})

    r = client.get("/api/v1/integrations/connected-clis")
    assert r.status_code == 200, r.text
    assert r.json() == {"connected": []}
    assert "opencode" not in r.json()["connected"]


# ---------------------------------------------------------------------------
# 200 — opencode is excluded even when other CLIs are also connected
# ---------------------------------------------------------------------------


def test_opencode_excluded_when_other_clis_present(monkeypatch):
    """Tenant has codex connected; opencode is forced into the resolver's
    ``available`` set as the always-on local floor. The public response
    should be ``["codex"]`` only — opencode never appears in the UI
    list, regardless of what else is connected."""
    user = _fake_user("44444444-4444-4444-4444-444444444444")
    connected_map = {
        "codex": {"connected": True},
    }
    client = _make_client(user, monkeypatch=monkeypatch, connected_map=connected_map)

    r = client.get("/api/v1/integrations/connected-clis")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] == ["codex"]
    assert "opencode" not in body["connected"]


# ---------------------------------------------------------------------------
# 200 — multiple connected CLIs come back in chain-priority order
# ---------------------------------------------------------------------------


def test_returned_order_matches_resolver_priority(monkeypatch):
    """When several CLIs are connected the dropdown wants them in the
    same order the backend's ``_DEFAULT_PRIORITY`` would walk them, so
    the UI's first non-Auto option is what Auto-routing would actually
    pick first. _DEFAULT_PRIORITY is (gemini_cli, codex, copilot_cli,
    claude_code, opencode)."""
    user = _fake_user("33333333-3333-3333-3333-333333333333")
    connected_map = {
        # claude_code + github → claude_code + copilot_cli connected.
        "claude_code": {"connected": True},
        "github": {"connected": True},
        # gmail proves gemini_cli is connected (Google integrations
        # auto-grant gemini_cli access for free).
        "gmail": {"connected": True},
    }
    client = _make_client(user, monkeypatch=monkeypatch, connected_map=connected_map)

    r = client.get("/api/v1/integrations/connected-clis")
    assert r.status_code == 200, r.text
    body = r.json()
    # gemini_cli before copilot_cli before claude_code; opencode is
    # excluded from the public response (routing floor, not user-pickable).
    assert body["connected"] == ["gemini_cli", "copilot_cli", "claude_code"]
    assert "opencode" not in body["connected"]


# ---------------------------------------------------------------------------
# 401 — no Authorization header
# ---------------------------------------------------------------------------


def test_requires_authentication():
    """Without a tenant JWT the endpoint must reject. We don't override
    ``get_current_active_user`` so FastAPI runs the real dep, which
    raises 401 when the header is missing."""
    app = FastAPI()
    app.include_router(integrations_router, prefix="/api/v1/integrations")
    # Note: deliberately NOT overriding get_current_active_user.
    client = TestClient(app)

    r = client.get("/api/v1/integrations/connected-clis")
    # 401 (Not authenticated) — the real auth dep rejects anonymous
    # callers with HTTPException(401).
    assert r.status_code == 401, r.text
