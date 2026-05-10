"""Phase 3 commit 7 — RL mirror failure isolation tests.

Asserts the chat response is unaffected when the RL mirror raises:

  - ``log_experience`` raises → response_text still flows
  - DB connection error inside mirror → response_text still flows

Hardens the "RL mirror failure NEVER poisons the chat hot path"
invariant.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_rl_mirror_failure_does_not_poison_response():
    from app.services import agent_router as _ar
    from cli_orchestrator.adapters.base import ExecutionResult
    from cli_orchestrator.metadata import ExecutionMetadata
    from cli_orchestrator.status import Status

    canned_result = ExecutionResult(
        status=Status.EXECUTION_SUCCEEDED,
        platform="claude_code",
        response_text="hello user",
        platform_attempted=["claude_code"],
        attempt_count=1,
        run_id="r-1",
    )

    class _StubExecutor:
        def __init__(self, adapters, *, decision_point="chat_response",
                     mirror_to_rl=None, webhook_emitter=None):
            self._mirror = mirror_to_rl

        def execute(self, req):
            md = ExecutionMetadata.from_execution_result(
                result=canned_result, tenant_id=req.tenant_id, user_id=None,
                decision_point="chat_response", duration_ms=10,
            )
            # Calling the mirror should swallow exceptions internally.
            if self._mirror is not None:
                self._mirror(md)
            return canned_result

    def boom_log_experience(**kwargs):
        raise RuntimeError("RL writer DB connection lost")

    db = MagicMock()
    with (
        patch.object(_ar, "_build_routing_summary", return_value={"served_by": "claude_code"}),
        patch("cli_orchestrator.executor.ResilientExecutor", _StubExecutor),
        patch("app.services.rl_experience_service.log_experience", boom_log_experience),
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

    # Mirror raised — but the response still flowed.
    assert text == "hello user"
    assert metadata.get("status") == "execution_succeeded"


def test_webhook_failure_does_not_poison_response():
    from app.services import agent_router as _ar
    from cli_orchestrator.adapters.base import ExecutionResult
    from cli_orchestrator.status import Status

    canned_result = ExecutionResult(
        status=Status.EXECUTION_SUCCEEDED,
        platform="claude_code",
        response_text="hello",
        platform_attempted=["claude_code"],
        attempt_count=1,
        run_id="r-1",
    )

    class _StubExecutor:
        def __init__(self, adapters, *, decision_point="chat_response",
                     mirror_to_rl=None, webhook_emitter=None):
            self._emit = webhook_emitter

        def execute(self, req):
            if self._emit is not None:
                self._emit("execution.started", {"run_id": "r-1"})
                self._emit("execution.succeeded", {"run_id": "r-1"})
            return canned_result

    def boom_fire(db, tenant_id, event_type, payload):
        raise RuntimeError("webhook delivery service down")

    db = MagicMock()
    with (
        patch.object(_ar, "_build_routing_summary", return_value={"served_by": "claude_code"}),
        patch("cli_orchestrator.executor.ResilientExecutor", _StubExecutor),
        patch("app.services.webhook_connectors.fire_outbound_event", boom_fire),
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
