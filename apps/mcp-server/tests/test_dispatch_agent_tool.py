"""Tests for dispatch_agent + request_human_approval MCP tools — Phase 4 commit 8."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import pytest


@pytest.fixture
def agent_ctx():
    """Build a fake context whose resolve_auth_context returns an
    agent_token AuthContext with empty parent_chain."""
    from src.agent_token_verify import AuthContext
    return AuthContext(
        tier="agent_token",
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
        scope=None,
        parent_chain=(),
    )


@pytest.fixture
def deep_agent_ctx():
    """parent_chain length 2 so caller's append takes us to 3."""
    from src.agent_token_verify import AuthContext
    return AuthContext(
        tier="agent_token",
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        scope=None,
        parent_chain=(str(uuid.uuid4()), str(uuid.uuid4())),
    )


def _mock_httpx_post(status_code: int, json_payload: dict):
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self.text = ""

        def json(self):
            return json_payload

    class _AsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return _Resp()

    return _AsyncClient


@pytest.mark.asyncio
async def test_dispatch_agent_appends_caller_id_to_parent_chain(agent_ctx):
    """Caller agent_id must be appended to parent_chain on the
    /tasks/internal/dispatch payload (Phase 4 review C-FINAL-1: was
    /tasks/dispatch which is JWT-gated)."""
    from src.mcp_tools import agents

    captured: dict = {}

    class _Capture:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return SimpleNamespace(
                status_code=201,
                json=lambda: {"task_id": "tid", "workflow_id": "wid"},
            )

    with patch.object(agents, "resolve_auth_context", return_value=agent_ctx), \
         patch.object(agents.httpx, "AsyncClient", _Capture):
        result = await agents.dispatch_agent(
            target_agent_id=str(uuid.uuid4()),
            objective="Investigate something",
            ctx=SimpleNamespace(),
        )

    assert result == {"task_id": "tid", "workflow_id": "wid"}
    assert captured["json"]["parent_chain"] == [agent_ctx.agent_id]
    # Critical: must hit the INTERNAL endpoint, not the JWT-gated one.
    assert "/tasks/internal/dispatch" in captured["url"]
    assert captured["url"].endswith("/tasks/internal/dispatch")
    # Auth tier is X-Internal-Key + X-Tenant-Id, NO Authorization header.
    assert "X-Internal-Key" in captured["headers"]
    assert captured["headers"]["X-Tenant-Id"] == agent_ctx.tenant_id
    assert "Authorization" not in captured["headers"]


@pytest.mark.asyncio
async def test_dispatch_agent_at_depth_3_surfaces_recursion_error(deep_agent_ctx):
    """When the caller is at depth 2, dispatch_agent appends → depth 3.
    The /tasks/internal/dispatch endpoint refuses with 503; the tool
    surfaces that as a structured error dict."""
    from src.mcp_tools import agents

    class _Refuse:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            # Mimic the dispatch endpoint refusing the call.
            return SimpleNamespace(
                status_code=503,
                json=lambda: {
                    "detail": {
                        "status": "provider_unavailable",
                        "actionable_hint": "cli.errors.recursion_depth_exceeded",
                        "error_message": "fallback chain exhausted (depth 3)",
                    }
                },
                text="",
            )

    with patch.object(agents, "resolve_auth_context", return_value=deep_agent_ctx), \
         patch.object(agents.httpx, "AsyncClient", _Refuse):
        result = await agents.dispatch_agent(
            target_agent_id=str(uuid.uuid4()),
            objective="Make it deeper",
            ctx=SimpleNamespace(),
        )

    assert result["error"] == "DISPATCH_FAILED_503"
    assert result["detail"]["actionable_hint"] == "cli.errors.recursion_depth_exceeded"


@pytest.mark.asyncio
async def test_dispatch_agent_requires_agent_token_tier():
    """A caller with tier='tenant_header' is rejected, even if the
    request body shape is valid."""
    from src.mcp_tools import agents
    from src.agent_token_verify import AuthContext

    non_agent = AuthContext(
        tier="tenant_header",
        tenant_id=str(uuid.uuid4()),
    )
    with patch.object(agents, "resolve_auth_context", return_value=non_agent):
        result = await agents.dispatch_agent(
            target_agent_id=str(uuid.uuid4()),
            objective="x",
            ctx=SimpleNamespace(),
        )
    assert result["error"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_request_human_approval_round_trips(agent_ctx):
    """Phase 4 review C1: posts to the internal request-approval
    endpoint (NOT /workflow-approve, which is JWT-gated and rejects
    decision='requested'). Body is {"reason": ...}. Headers include
    X-Internal-Key + X-Tenant-Id."""
    from src.mcp_tools import agents

    captured: dict = {}
    task_id = str(uuid.uuid4())
    notif_id = str(uuid.uuid4())

    class _Capture:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "status": "requested",
                    "task_id": task_id,
                    "notification_id": notif_id,
                },
            )

    with patch.object(agents, "resolve_auth_context", return_value=agent_ctx), \
         patch.object(agents.httpx, "AsyncClient", _Capture):
        result = await agents.request_human_approval(
            task_id=task_id,
            reason="needs admin signoff",
            ctx=SimpleNamespace(),
        )

    assert result["status"] == "requested"
    assert result["task_id"] == task_id
    assert result["notification_id"] == notif_id
    # Body is {"reason": ...} — NOT decision/comment.
    assert captured["json"] == {"reason": "needs admin signoff"}
    # Auth headers must be present.
    assert "X-Internal-Key" in captured["headers"]
    assert captured["headers"]["X-Tenant-Id"] == agent_ctx.tenant_id
    # URL must hit the internal endpoint, not /workflow-approve.
    assert "/tasks/internal/" in captured["url"]
    assert "/request-approval" in captured["url"]
    assert "/workflow-approve" not in captured["url"]


@pytest.mark.asyncio
async def test_request_human_approval_requires_agent_token_tier():
    from src.mcp_tools import agents
    from src.agent_token_verify import AuthContext

    bad = AuthContext(tier="internal_key")
    with patch.object(agents, "resolve_auth_context", return_value=bad):
        result = await agents.request_human_approval(
            task_id=str(uuid.uuid4()),
            reason="x",
            ctx=SimpleNamespace(),
        )
    assert result["error"] == "PERMISSION_DENIED"
