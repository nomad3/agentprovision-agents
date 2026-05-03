"""Tests for src.mcp_auth header resolvers.

These helpers are called on every MCP tool invocation to extract
``X-Tenant-Id``, ``X-User-Id`` and verify ``X-Internal-Key`` from the
FastMCP request context.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from src import mcp_auth


# ---------------------------------------------------------------------------
# resolve_tenant_id / resolve_user_id
# ---------------------------------------------------------------------------

def test_resolve_tenant_id_returns_none_for_missing_ctx():
    assert mcp_auth.resolve_tenant_id(None) is None
    assert mcp_auth.resolve_user_id(None) is None


def test_resolve_tenant_id_returns_none_when_no_request_context():
    ctx = SimpleNamespace()  # no .request_context attribute
    assert mcp_auth.resolve_tenant_id(ctx) is None


def test_resolve_tenant_id_from_dict_request_context():
    ctx = SimpleNamespace(request_context={"X-Tenant-Id": "t-1"})
    assert mcp_auth.resolve_tenant_id(ctx) == "t-1"


def test_resolve_tenant_id_from_dict_lowercase_key():
    ctx = SimpleNamespace(request_context={"x-tenant-id": "t-2"})
    assert mcp_auth.resolve_tenant_id(ctx) == "t-2"


def test_resolve_tenant_id_from_headers_dict():
    rc = SimpleNamespace(headers={"X-Tenant-Id": "t-3"})
    ctx = SimpleNamespace(request_context=rc)
    assert mcp_auth.resolve_tenant_id(ctx) == "t-3"


def test_resolve_tenant_id_from_headers_object_with_get():
    class _Headers:
        def __init__(self, m):
            self._m = m

        def get(self, k, default=None):
            return self._m.get(k.lower(), default)

    rc = SimpleNamespace(headers=_Headers({"x-tenant-id": "t-4"}))
    ctx = SimpleNamespace(request_context=rc)
    assert mcp_auth.resolve_tenant_id(ctx) == "t-4"


def test_resolve_tenant_id_falls_back_to_attribute():
    rc = SimpleNamespace(headers=None, x_tenant_id="t-5")
    ctx = SimpleNamespace(request_context=rc)
    assert mcp_auth.resolve_tenant_id(ctx) == "t-5"


def test_resolve_tenant_id_falls_back_to_tenant_id_alias():
    ctx = SimpleNamespace(request_context={"tenant_id": "t-alias"})
    # "X-Tenant-Id" is missing, falls back to "tenant_id"
    assert mcp_auth.resolve_tenant_id(ctx) == "t-alias"


def test_resolve_user_id_uses_x_user_id_header():
    ctx = SimpleNamespace(request_context={"X-User-Id": "u-1"})
    assert mcp_auth.resolve_user_id(ctx) == "u-1"


def test_resolve_user_id_falls_back_to_user_id_alias():
    ctx = SimpleNamespace(request_context={"user_id": "u-alias"})
    assert mcp_auth.resolve_user_id(ctx) == "u-alias"


# ---------------------------------------------------------------------------
# verify_internal_key
# ---------------------------------------------------------------------------

def test_verify_internal_key_missing_header_returns_false():
    ctx = SimpleNamespace(request_context={})
    assert mcp_auth.verify_internal_key(ctx) is False


def test_verify_internal_key_matches(monkeypatch):
    monkeypatch.setattr(mcp_auth, "INTERNAL_KEY", "secret-123")
    ctx = SimpleNamespace(request_context={"X-Internal-Key": "secret-123"})
    assert mcp_auth.verify_internal_key(ctx) is True


def test_verify_internal_key_rejects_mismatch(monkeypatch):
    monkeypatch.setattr(mcp_auth, "INTERNAL_KEY", "secret-123")
    ctx = SimpleNamespace(request_context={"X-Internal-Key": "wrong"})
    assert mcp_auth.verify_internal_key(ctx) is False


def test_verify_internal_key_accepts_alias_internal_key(monkeypatch):
    monkeypatch.setattr(mcp_auth, "INTERNAL_KEY", "abc")
    ctx = SimpleNamespace(request_context={"internal_key": "abc"})
    assert mcp_auth.verify_internal_key(ctx) is True
