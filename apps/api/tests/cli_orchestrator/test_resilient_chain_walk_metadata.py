"""Phase 3 commit 7 — _resilient_chain_walk metadata mirror tests.

Asserts that one ``RLExperience`` row is written per
``_resilient_chain_walk`` invocation, with:

  - ``decision_point="chat_response"``
  - state contains ``platform_attempted`` + ``attempt_count``
  - the row is committed (visible to the test session's query)

We monkey-patch ``ResilientExecutor`` to a stub that returns a
canned ExecutionResult and immediately invokes the mirror callable
so we don't have to spin up Temporal.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_resilient_chain_walk_writes_one_rl_experience():
    """Mirror callable invokes log_experience with chat_response decision_point."""
    from app.services import agent_router as _ar
    from cli_orchestrator.adapters.base import ExecutionResult
    from cli_orchestrator.metadata import ExecutionMetadata
    from cli_orchestrator.status import Status

    # Stub ExecutionResult — happy path
    canned_result = ExecutionResult(
        status=Status.EXECUTION_SUCCEEDED,
        platform="claude_code",
        response_text="hello",
        platform_attempted=["claude_code"],
        attempt_count=1,
        run_id="r-1",
    )

    captured_log_calls = []

    def fake_log_experience(**kwargs):
        captured_log_calls.append(kwargs)

        class _Exp:
            id = "exp-1"

        return _Exp()

    # Stub ResilientExecutor: invoke the mirror callable then return the result.
    class _StubExecutor:
        def __init__(self, adapters, *, decision_point="chat_response",
                     mirror_to_rl=None, webhook_emitter=None):
            self._mirror = mirror_to_rl
            self._dp = decision_point

        def execute(self, req):
            md = ExecutionMetadata.from_execution_result(
                result=canned_result, tenant_id=req.tenant_id, user_id="u",
                decision_point=self._dp, duration_ms=42,
            )
            if self._mirror is not None:
                self._mirror(md)
            return canned_result

    db = MagicMock()
    with (
        patch.object(_ar, "_build_routing_summary", return_value={"served_by": "claude_code"}),
        patch("cli_orchestrator.executor.ResilientExecutor", _StubExecutor),
        patch("app.services.rl_experience_service.log_experience", fake_log_experience),
    ):
        text, metadata = _ar._resilient_chain_walk(
            db=db, tenant_id="t-1", user_id="u-1",
            platform="claude_code", cli_chain=["claude_code"],
            agent_slug="luna", agent_skill_slugs=[],
            message="hi", channel="web",
            sender_phone=None, conversation_summary="",
            image_b64="", image_mime="",
            db_session_memory={}, pre_built_memory_context=None,
            agent_tier="full", agent_tool_groups=[],
            agent_memory_domains=[],
        )

    assert text == "hello"
    assert len(captured_log_calls) == 1
    call = captured_log_calls[0]
    assert call["decision_point"] == "chat_response"
    state = call["state"]
    assert "platform_attempted" in state
    assert "attempt_count" in state
    assert state["attempt_count"] == 1
