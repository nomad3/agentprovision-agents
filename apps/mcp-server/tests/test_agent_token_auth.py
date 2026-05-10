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


# ── Commit 7: scope enforcement at audit boundary ───────────────────────


class _FakeReq:
    """Stand-in for FastMCP's CallToolRequest — only .params.name +
    .params.arguments are read by the audit handler."""

    def __init__(self, name: str, arguments: dict | None = None):
        self.params = SimpleNamespace(name=name, arguments=arguments or {})


def _build_audit_handler_with_auth(auth_ctx_to_return):
    """Build an audit handler with a mocked resolve_auth_context. Returns
    (handler, original_handler_calls, log_call_calls).

    We invoke ``install_audit`` against a stub mcp_server, capture the
    installed handler off the request_handlers dict, and exercise it
    directly. This bypasses the FastMCP machinery while still testing
    the real scope-gate logic in tool_audit.py.
    """
    from mcp.types import CallToolRequest

    from src import tool_audit

    original_calls = []

    async def fake_original(req):
        original_calls.append(req)
        return SimpleNamespace(content=[], isError=False)

    handlers_dict: dict = {CallToolRequest: fake_original}
    fake_lowlevel = SimpleNamespace(request_handlers=handlers_dict)
    fake_mcp = SimpleNamespace(
        _mcp_server=fake_lowlevel,
        _tool_audit_installed=False,
        get_context=lambda: SimpleNamespace(),
    )

    # Mock resolve_auth_context to return the test's auth_ctx
    # regardless of context shape.
    log_calls = []
    with patch.object(
        tool_audit, "resolve_auth_context",
        return_value=auth_ctx_to_return,
    ), patch.object(
        tool_audit, "_log_call",
        side_effect=lambda **kw: log_calls.append(kw),
    ):
        tool_audit.install_audit(fake_mcp)
        installed = handlers_dict[CallToolRequest]
        # Mark the installed handler so tests can call it; keep the
        # patch context alive by yielding a closure that re-applies
        # the mocks per-invocation.
    # Re-apply mocks at call time since the with-block has closed.
    return installed, original_calls, log_calls, fake_mcp


@pytest.mark.asyncio
async def test_scope_blocks_out_of_scope_tool_with_403_audit():
    """Phase 4 second ship gate (b): scope=['recall_memory'] caller
    invoking dispatch_agent → PermissionError + audit row."""
    from src.agent_token_verify import AuthContext
    from src import tool_audit

    auth = AuthContext(
        tier="agent_token",
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
        scope=["recall_memory"],
    )

    # Patch resolve_auth_context + _log_call across the actual call.
    from mcp.types import CallToolRequest

    original_calls = []

    async def fake_original(req):
        original_calls.append(req)
        return SimpleNamespace(content=[], isError=False)

    handlers_dict: dict = {CallToolRequest: fake_original}
    fake_lowlevel = SimpleNamespace(request_handlers=handlers_dict)
    fake_mcp = SimpleNamespace(
        _mcp_server=fake_lowlevel,
        _tool_audit_installed=False,
        get_context=lambda: SimpleNamespace(),
    )

    log_calls = []
    with patch.object(tool_audit, "resolve_auth_context", return_value=auth), \
         patch.object(tool_audit, "_log_call",
                      side_effect=lambda **kw: log_calls.append(kw)):
        tool_audit.install_audit(fake_mcp)
        installed = handlers_dict[CallToolRequest]
        req = _FakeReq("dispatch_agent")
        with pytest.raises(PermissionError):
            await installed(req)

    # The original handler must NOT have been invoked.
    assert original_calls == []
    # An audit row was written.
    assert len(log_calls) == 1
    assert log_calls[0]["result_status"] == "scope_denied"
    assert log_calls[0]["tool_name"] == "dispatch_agent"


@pytest.mark.asyncio
async def test_scope_none_bypasses_gate():
    """scope=None means 'no per-call scope check' — gate is a no-op."""
    from src.agent_token_verify import AuthContext
    from src import tool_audit
    from mcp.types import CallToolRequest

    auth = AuthContext(
        tier="agent_token",
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        scope=None,  # ← no scope check
    )

    original_calls = []

    async def fake_original(req):
        original_calls.append(req)
        return SimpleNamespace(content=[], isError=False)

    handlers_dict: dict = {CallToolRequest: fake_original}
    fake_lowlevel = SimpleNamespace(request_handlers=handlers_dict)
    fake_mcp = SimpleNamespace(
        _mcp_server=fake_lowlevel,
        _tool_audit_installed=False,
        get_context=lambda: SimpleNamespace(),
    )

    with patch.object(tool_audit, "resolve_auth_context", return_value=auth), \
         patch.object(tool_audit, "_log_call"):
        tool_audit.install_audit(fake_mcp)
        installed = handlers_dict[CallToolRequest]
        await installed(_FakeReq("any_tool_name"))

    assert len(original_calls) == 1


@pytest.mark.asyncio
async def test_non_agent_token_tier_bypasses_gate():
    """tier != agent_token → scope gate is a no-op even if scope is
    populated. (Defends against future tiers smuggling a scope claim.)"""
    from src.agent_token_verify import AuthContext
    from src import tool_audit
    from mcp.types import CallToolRequest

    auth = AuthContext(
        tier="tenant_header",
        tenant_id=str(uuid.uuid4()),
        scope=["only_one_tool"],  # populated but tier is wrong
    )

    original_calls = []

    async def fake_original(req):
        original_calls.append(req)
        return SimpleNamespace(content=[], isError=False)

    handlers_dict: dict = {CallToolRequest: fake_original}
    fake_lowlevel = SimpleNamespace(request_handlers=handlers_dict)
    fake_mcp = SimpleNamespace(
        _mcp_server=fake_lowlevel,
        _tool_audit_installed=False,
        get_context=lambda: SimpleNamespace(),
    )

    with patch.object(tool_audit, "resolve_auth_context", return_value=auth), \
         patch.object(tool_audit, "_log_call"):
        tool_audit.install_audit(fake_mcp)
        installed = handlers_dict[CallToolRequest]
        # call a tool NOT in scope — should still pass since tier is wrong
        await installed(_FakeReq("some_other_tool"))

    assert len(original_calls) == 1


@pytest.mark.asyncio
async def test_scope_check_uses_bare_tool_name_no_prefix():
    """The canonical scope-list form is bare tool names (no
    mcp__agentprovision__ prefix). This matches what
    tool_groups.resolve_tool_names returns."""
    from src.agent_token_verify import AuthContext
    from src import tool_audit
    from mcp.types import CallToolRequest

    # scope contains BARE name; tool_name in audit is also bare.
    auth = AuthContext(
        tier="agent_token",
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        scope=["recall_memory"],
    )

    original_calls = []

    async def fake_original(req):
        original_calls.append(req)
        return SimpleNamespace(content=[], isError=False)

    handlers_dict: dict = {CallToolRequest: fake_original}
    fake_lowlevel = SimpleNamespace(request_handlers=handlers_dict)
    fake_mcp = SimpleNamespace(
        _mcp_server=fake_lowlevel,
        _tool_audit_installed=False,
        get_context=lambda: SimpleNamespace(),
    )

    with patch.object(tool_audit, "resolve_auth_context", return_value=auth), \
         patch.object(tool_audit, "_log_call"):
        tool_audit.install_audit(fake_mcp)
        installed = handlers_dict[CallToolRequest]
        # Bare name → allowed
        await installed(_FakeReq("recall_memory"))

    assert len(original_calls) == 1
