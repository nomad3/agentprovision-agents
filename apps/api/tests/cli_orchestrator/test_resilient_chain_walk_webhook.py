"""Phase 3 commit 7 — _resilient_chain_walk webhook fire tests.

Asserts that registered outbound webhooks subscribed to
``execution.*`` receive **2** deliveries on the happy path
(``execution.started`` + ``execution.succeeded``).

We monkey-patch ``ResilientExecutor`` to invoke the webhook_emitter
closure for the right events without going through Temporal.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_resilient_chain_walk_emits_started_and_succeeded():
    from app.services import agent_router as _ar
    from cli_orchestrator.adapters.base import ExecutionResult
    from cli_orchestrator.metadata import ExecutionMetadata
    from cli_orchestrator.status import Status
    from cli_orchestrator.webhook_events import (
        EVENT_STARTED, EVENT_SUCCEEDED,
    )

    canned_result = ExecutionResult(
        status=Status.EXECUTION_SUCCEEDED,
        platform="claude_code",
        response_text="ok",
        platform_attempted=["claude_code"],
        attempt_count=1,
        run_id="r-1",
    )

    captured_fire = []

    def fake_fire(db, tenant_id, event_type, payload):
        captured_fire.append((event_type, payload))
        return [{"delivered": True}]

    class _StubExecutor:
        def __init__(self, adapters, *, decision_point="chat_response",
                     mirror_to_rl=None, webhook_emitter=None):
            self._emit = webhook_emitter

        def execute(self, req):
            if self._emit is not None:
                self._emit(EVENT_STARTED, {"run_id": "r-1"})
                md = ExecutionMetadata.from_execution_result(
                    result=canned_result, tenant_id=req.tenant_id,
                    user_id=None, decision_point="chat_response",
                    duration_ms=42,
                )
                self._emit(EVENT_SUCCEEDED, md.to_webhook_payload(EVENT_SUCCEEDED))
            return canned_result

    db = MagicMock()
    with (
        patch.object(_ar, "_build_routing_summary", return_value={"served_by": "claude_code"}),
        patch("cli_orchestrator.executor.ResilientExecutor", _StubExecutor),
        patch("app.services.webhook_connectors.fire_outbound_event", fake_fire),
    ):
        _ar._resilient_chain_walk(
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

    events = [e for e, _ in captured_fire]
    assert events == [EVENT_STARTED, EVENT_SUCCEEDED]
