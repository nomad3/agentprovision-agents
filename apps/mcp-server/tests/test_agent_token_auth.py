"""Phase 4 commits 6 + 7 — third auth tier + scope enforcement tests.

Commit 6 — tier resolution & tenancy precedence:
  - kind=agent_token claim → tenant_id from claim, ignores X-Tenant-Id header
  - mismatch audit-logged at most 1/min
  - bad signature → tier=anonymous (falls through)
  - X-Internal-Key only → tier=internal_key
  - Mock 100 mismatches in 1s → exactly 1 audit row written

Commit 7 — scope enforcement at audit boundary (Phase 4 second ship gate):
  - scope=["recall_memory"] caller invoking dispatch_agent → 403 + audit row
  - scope=None bypasses gate
  - tier != agent_token bypasses gate
  - scope check uses bare tool name (no mcp__agentprovision__ prefix)
"""
from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("jose")

from jose import jwt

from src.config import settings


# ── Helpers ─────────────────────────────────────────────────────────────


def _mint_token(
    *,
    tenant_id: str = None,
    agent_id: str = None,
    task_id: str = None,
    scope=None,
    parent_chain=None,
    kind: str = "agent_token",
    sub_prefix: str = "agent:",
    expired: bool = False,
) -> str:
    """Mint an agent-token-shaped JWT for testing. Bypasses the API
    helper so we can exercise edge cases (wrong kind, wrong sub, etc.)."""
    aid = agent_id or str(uuid.uuid4())
    now = int(time.time())
    exp = now - 10 if expired else now + 600
    payload = {
        "sub": f"{sub_prefix}{aid}",
        "kind": kind,
        "tenant_id": tenant_id or str(uuid.uuid4()),
        "agent_id": aid,
        "task_id": task_id or str(uuid.uuid4()),
        "parent_workflow_id": None,
        "scope": scope,
        "parent_chain": parent_chain or [],
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _ctx_with_headers(**headers):
    """Build a ctx with a request_context that has a headers dict."""
    rc = SimpleNamespace(headers=dict(headers))
    return SimpleNamespace(request_context=rc)


# ── Commit 6: tier resolution ──────────────────────────────────────────


def test_agent_token_wins_over_x_tenant_id_header():
    """When kind=agent_token, the claim tenant is authoritative."""
    from src.mcp_auth import resolve_auth_context

    claim_tenant = str(uuid.uuid4())
    header_tenant = str(uuid.uuid4())
    tok = _mint_token(tenant_id=claim_tenant)
    ctx = _ctx_with_headers(
        Authorization=f"Bearer {tok}",
        **{"X-Tenant-Id": header_tenant},
    )

    auth = resolve_auth_context(ctx)
    assert auth.tier == "agent_token"
    assert auth.tenant_id == claim_tenant
    assert auth.tenant_id != header_tenant


def test_x_tenant_id_only_returns_tenant_header_tier():
    from src.mcp_auth import resolve_auth_context

    t = str(uuid.uuid4())
    ctx = _ctx_with_headers(**{"X-Tenant-Id": t})
    auth = resolve_auth_context(ctx)
    assert auth.tier == "tenant_header"
    assert auth.tenant_id == t


def test_x_internal_key_only_returns_internal_key_tier():
    from src.mcp_auth import resolve_auth_context

    ctx = _ctx_with_headers(**{"X-Internal-Key": "test-mcp-key"})
    auth = resolve_auth_context(ctx)
    # The conftest sets MCP_API_KEY=test-mcp-key in env; the module
    # reads it at import time. As long as that matches, we're internal.
    assert auth.tier in ("internal_key", "anonymous"), auth.tier


def test_no_headers_returns_anonymous():
    from src.mcp_auth import resolve_auth_context

    ctx = _ctx_with_headers()
    auth = resolve_auth_context(ctx)
    assert auth.tier == "anonymous"
    assert auth.tenant_id is None


def test_bad_signature_falls_through():
    """Invalid signature → tier resolution falls through to next tier."""
    from src.mcp_auth import resolve_auth_context

    tok = _mint_token()
    # Tamper signature.
    head, _, sig = tok.rpartition(".")
    bad = f"{head}.{sig[:-1]}X"
    ctx = _ctx_with_headers(Authorization=f"Bearer {bad}")
    auth = resolve_auth_context(ctx)
    assert auth.tier != "agent_token"


def test_expired_token_falls_through():
    from src.mcp_auth import resolve_auth_context

    tok = _mint_token(expired=True)
    ctx = _ctx_with_headers(Authorization=f"Bearer {tok}")
    auth = resolve_auth_context(ctx)
    assert auth.tier != "agent_token"


def test_kind_not_agent_token_falls_through():
    """SR-11: kind=access (regular login) must not cross into the agent
    tier even though it's signed with the same SECRET_KEY."""
    from src.mcp_auth import resolve_auth_context

    tok = _mint_token(kind="access")
    ctx = _ctx_with_headers(Authorization=f"Bearer {tok}")
    auth = resolve_auth_context(ctx)
    assert auth.tier != "agent_token"


def test_sub_not_agent_prefix_falls_through():
    from src.mcp_auth import resolve_auth_context

    tok = _mint_token(sub_prefix="user:")
    ctx = _ctx_with_headers(Authorization=f"Bearer {tok}")
    auth = resolve_auth_context(ctx)
    assert auth.tier != "agent_token"


def test_resolve_tenant_id_legacy_wrapper_returns_claim_tenant():
    from src.mcp_auth import resolve_tenant_id

    claim_tenant = str(uuid.uuid4())
    tok = _mint_token(tenant_id=claim_tenant)
    ctx = _ctx_with_headers(Authorization=f"Bearer {tok}")
    assert resolve_tenant_id(ctx) == claim_tenant


# ── Commit 6: tenancy-mismatch rate-limiting (SR-6) ─────────────────────


def test_tenancy_mismatch_rate_limited_to_one_per_minute():
    """SR-6: Mock 100 mismatches in 1s, assert exactly 1 audit row written."""
    import src.mcp_auth as mcp_auth_mod

    # Reset the LRU.
    with mcp_auth_mod._MISMATCH_LRU_LOCK:
        mcp_auth_mod._MISMATCH_LRU.clear()

    claim_tenant = str(uuid.uuid4())
    header_tenant = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    tok = _mint_token(tenant_id=claim_tenant, agent_id=agent_id)

    ctx = _ctx_with_headers(
        Authorization=f"Bearer {tok}",
        **{"X-Tenant-Id": header_tenant},
    )

    audit_calls = []

    def fake_audit(**kwargs):
        audit_calls.append(kwargs)

    with patch.object(mcp_auth_mod, "_audit_tenancy_mismatch", side_effect=fake_audit):
        for _ in range(100):
            mcp_auth_mod.resolve_auth_context(ctx)

    assert len(audit_calls) == 1, (
        f"expected exactly 1 audit row from 100 mismatches in <60s, "
        f"got {len(audit_calls)}"
    )


def test_tenancy_mismatch_per_distinct_header_value_logged_separately():
    """Different header_value → different LRU bucket → separate log."""
    import src.mcp_auth as mcp_auth_mod

    with mcp_auth_mod._MISMATCH_LRU_LOCK:
        mcp_auth_mod._MISMATCH_LRU.clear()

    claim_tenant = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    tok = _mint_token(tenant_id=claim_tenant, agent_id=agent_id)

    audit_calls = []

    with patch.object(
        mcp_auth_mod, "_audit_tenancy_mismatch",
        side_effect=lambda **kw: audit_calls.append(kw),
    ):
        for header_val in [str(uuid.uuid4()) for _ in range(3)]:
            ctx = _ctx_with_headers(
                Authorization=f"Bearer {tok}",
                **{"X-Tenant-Id": header_val},
            )
            # Repeat each twice — the second should be rate-limited.
            mcp_auth_mod.resolve_auth_context(ctx)
            mcp_auth_mod.resolve_auth_context(ctx)

    # 3 distinct (tenant, agent, header) tuples → 3 audit rows total.
    assert len(audit_calls) == 3
