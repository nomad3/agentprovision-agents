"""Unit tests for external_agent_adapter helpers.

Exercises the pure helpers (_stringify_mcp_result, _join_content) and the
control-flow of _dispatch_mcp_sse via a fake _mcp_sse_call. The actual SSE
client is exercised in an integration test against a local fixture; here we
just lock in the dispatch contract.
"""
import os
os.environ["TESTING"] = "True"

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.external_agent_adapter import (
    ExternalAgentAdapter,
    _join_content,
    _stringify_mcp_result,
)


def _agent(**overrides):
    """Build an ExternalAgent-like object minus the ORM."""
    base = dict(
        id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        protocol="mcp_sse",
        endpoint_url="https://example.test/sse",
        credential_id=None,
        metadata_={},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# _join_content / _stringify_mcp_result
# ---------------------------------------------------------------------------

def test_join_content_handles_none():
    assert _join_content(None) == ""


def test_join_content_passes_through_strings():
    assert _join_content("hello") == "hello"


def test_join_content_concatenates_text_blocks():
    blocks = [SimpleNamespace(text="line one"), SimpleNamespace(text="line two")]
    assert _join_content(blocks) == "line one\nline two"


def test_join_content_falls_back_to_repr_for_unknown_blocks():
    # Non-text blocks (image, embedded resource) shouldn't silently drop.
    block = SimpleNamespace(type="image", data="...")
    out = _join_content([block])
    assert "image" in out


def test_stringify_mcp_result_raises_on_remote_error():
    err_result = SimpleNamespace(isError=True, content="boom")
    with pytest.raises(RuntimeError, match="mcp_sse tool returned error"):
        _stringify_mcp_result(err_result)


def test_stringify_mcp_result_returns_joined_text():
    ok_result = SimpleNamespace(
        isError=False,
        content=[SimpleNamespace(text="alpha"), SimpleNamespace(text="beta")],
    )
    assert _stringify_mcp_result(ok_result) == "alpha\nbeta"


# ---------------------------------------------------------------------------
# _dispatch_mcp_sse — control flow
# ---------------------------------------------------------------------------

def test_dispatch_mcp_sse_uses_context_tool_name_first():
    """context['tool_name'] beats agent.metadata_['tool_name']."""
    adapter = ExternalAgentAdapter()
    captured = {}

    async def fake(*, endpoint, bearer, tool_name, arguments, timeout_s):
        captured.update({"tool_name": tool_name, "arguments": arguments, "timeout_s": timeout_s})
        return "ok"

    agent = _agent(metadata_={"tool_name": "from_metadata"})
    with patch.object(ExternalAgentAdapter, "_mcp_sse_call", staticmethod(fake)):
        result = adapter._dispatch_mcp_sse(
            agent,
            task="hello",
            context={"tool_name": "from_context", "arguments": {"k": "v"}},
            db=None,
        )

    assert result == "ok"
    assert captured["tool_name"] == "from_context"
    assert captured["arguments"] == {"k": "v"}


def test_dispatch_mcp_sse_falls_back_to_metadata_tool_name():
    adapter = ExternalAgentAdapter()
    captured = {}

    async def fake(*, endpoint, bearer, tool_name, arguments, timeout_s):
        captured.update({"tool_name": tool_name, "arguments": arguments})
        return "ok"

    agent = _agent(metadata_={"tool_name": "from_metadata"})
    with patch.object(ExternalAgentAdapter, "_mcp_sse_call", staticmethod(fake)):
        adapter._dispatch_mcp_sse(agent, "task body", {}, db=None)

    assert captured["tool_name"] == "from_metadata"
    # Default arguments wrap the task as {"input": ...}.
    assert captured["arguments"] == {"input": "task body"}


def test_dispatch_mcp_sse_passes_timeout_from_metadata():
    adapter = ExternalAgentAdapter()
    captured = {}

    async def fake(*, endpoint, bearer, tool_name, arguments, timeout_s):
        captured["timeout_s"] = timeout_s
        return ""

    agent = _agent(metadata_={"tool_name": "x", "timeout": 90})
    with patch.object(ExternalAgentAdapter, "_mcp_sse_call", staticmethod(fake)):
        adapter._dispatch_mcp_sse(agent, "t", {}, db=None)
    assert captured["timeout_s"] == 90


def test_dispatch_mcp_sse_default_timeout_when_unset():
    adapter = ExternalAgentAdapter()
    captured = {}

    async def fake(*, endpoint, bearer, tool_name, arguments, timeout_s):
        captured["timeout_s"] = timeout_s
        return ""

    agent = _agent(metadata_={"tool_name": "x"})
    with patch.object(ExternalAgentAdapter, "_mcp_sse_call", staticmethod(fake)):
        adapter._dispatch_mcp_sse(agent, "t", {}, db=None)
    # Matches _MCP_SSE_DEFAULT_TIMEOUT
    assert captured["timeout_s"] == 30


def test_dispatch_mcp_sse_wraps_unknown_exceptions_as_runtime_error():
    adapter = ExternalAgentAdapter()

    async def fake(**_kwargs):
        raise ValueError("network blew up")

    agent = _agent(metadata_={"tool_name": "x"})
    with patch.object(ExternalAgentAdapter, "_mcp_sse_call", staticmethod(fake)):
        with pytest.raises(RuntimeError, match="mcp_sse request failed"):
            adapter._dispatch_mcp_sse(agent, "t", {}, db=None)


def test_dispatch_mcp_sse_passes_runtime_errors_through_unwrapped():
    """RuntimeError raised by remote MCP shouldn't be re-wrapped — keeps the
    contract uniform with openai_chat / webhook dispatch.
    """
    adapter = ExternalAgentAdapter()

    async def fake(**_kwargs):
        raise RuntimeError("remote server returned 500")

    agent = _agent(metadata_={"tool_name": "x"})
    with patch.object(ExternalAgentAdapter, "_mcp_sse_call", staticmethod(fake)):
        with pytest.raises(RuntimeError, match="^remote server returned 500$"):
            adapter._dispatch_mcp_sse(agent, "t", {}, db=None)


def test_dispatch_routes_mcp_sse_to_handler():
    """Top-level dispatch() routes mcp_sse protocol to the new handler."""
    adapter = ExternalAgentAdapter()
    seen = {}

    def fake_handler(self, agent, task, context, db):
        seen["called"] = True
        return "handler-result"

    agent = _agent(protocol="mcp_sse")
    with patch.object(ExternalAgentAdapter, "_dispatch_mcp_sse", fake_handler):
        out = adapter.dispatch(agent, "t", {}, db=None)
    assert out == "handler-result"
    assert seen["called"] is True
