"""ExecutionMetadata dataclass tests — Phase 3 commit 3.

Verifies:
  - shape of the dataclass
  - from_execution_result conversion
  - to_rl_experience_state / to_rl_experience_action shape
  - to_webhook_payload truncation rules (512B for non-failed, 4KB for failed)
"""
from __future__ import annotations

from cli_orchestrator.adapters.base import ExecutionResult
from cli_orchestrator.metadata import (
    ExecutionMetadata,
    _truncate_for_webhook,
    _WEBHOOK_TRUNCATE_BYTES,
)
from cli_orchestrator.policy import FallbackDecision
from cli_orchestrator.status import Status


def _make_result(**overrides) -> ExecutionResult:
    base = dict(
        status=Status.EXECUTION_SUCCEEDED,
        platform="claude_code",
        response_text="ok",
        stdout_summary="hello world",
        stderr_summary="",
        platform_attempted=["claude_code"],
        attempt_count=1,
        run_id="r-1",
        metadata={"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001},
    )
    base.update(overrides)
    return ExecutionResult(**base)


def test_from_execution_result_success_shape():
    r = _make_result()
    md = ExecutionMetadata.from_execution_result(
        result=r, tenant_id="t-1", user_id="u-1",
        decision_point="chat_response", duration_ms=42,
    )
    assert md.run_id == "r-1"
    assert md.tenant_id == "t-1"
    assert md.user_id == "u-1"
    assert md.decision_point == "chat_response"
    assert md.platform_attempted == ["claude_code"]
    assert md.final_platform == "claude_code"  # success path
    assert md.attempt_count == 1
    assert md.status is Status.EXECUTION_SUCCEEDED
    assert md.duration_ms == 42
    assert md.tokens_in == 100
    assert md.tokens_out == 50
    assert md.cost_usd == 0.001


def test_from_execution_result_failure_no_final_platform():
    r = _make_result(
        status=Status.NEEDS_AUTH, response_text="",
        actionable_hint="cli.errors.needs_auth.claude_code",
    )
    md = ExecutionMetadata.from_execution_result(
        result=r, tenant_id="t-1", user_id=None,
        decision_point="chat_response", duration_ms=10,
    )
    assert md.final_platform is None
    assert md.actionable_hint == "cli.errors.needs_auth.claude_code"
    assert md.status is Status.NEEDS_AUTH


def test_to_rl_experience_state_shape():
    r = _make_result(
        platform_attempted=["claude_code", "codex"],
        attempt_count=2,
    )
    md = ExecutionMetadata.from_execution_result(
        result=r, tenant_id="t", user_id="u",
        decision_point="chat_response", duration_ms=999,
        retry_decisions=[
            FallbackDecision(action="retry", reason="net flake"),
        ],
        fallback_decisions=[
            FallbackDecision(action="fallback", reason="quota"),
        ],
    )
    state = md.to_rl_experience_state()
    assert state["decision_point"] == "chat_response"
    assert state["platform_attempted"] == ["claude_code", "codex"]
    assert state["attempt_count"] == 2
    assert state["duration_ms"] == 999
    assert state["retry_count"] == 1
    assert state["fallback_count"] == 1


def test_to_rl_experience_action_shape():
    r = _make_result(workflow_id="wf-1", activity_id="ac-1")
    md = ExecutionMetadata.from_execution_result(
        result=r, tenant_id="t", user_id="u",
        decision_point="chat_response", duration_ms=10,
    )
    action = md.to_rl_experience_action()
    assert action["final_platform"] == "claude_code"
    assert action["status"] == "execution_succeeded"
    assert action["platform_chain"] == ["claude_code"]
    assert action["tokens_in"] == 100
    assert action["workflow_id"] == "wf-1"
    assert action["activity_id"] == "ac-1"


def test_to_webhook_payload_truncates_non_failed_to_512b():
    big = "x" * 5000
    r = _make_result(stdout_summary=big, stderr_summary=big)
    md = ExecutionMetadata.from_execution_result(
        result=r, tenant_id="t", user_id=None,
        decision_point="chat_response", duration_ms=10,
    )
    payload = md.to_webhook_payload("execution.succeeded")
    assert len(payload["stdout_summary"]) <= _WEBHOOK_TRUNCATE_BYTES + 32  # +ellipsis
    assert payload["stdout_summary"].endswith("(truncated)")


def test_to_webhook_payload_failed_keeps_full_summary():
    big = "x" * 5000
    r = _make_result(
        status=Status.UNKNOWN_FAILURE,
        stdout_summary=big, stderr_summary=big,
    )
    md = ExecutionMetadata.from_execution_result(
        result=r, tenant_id="t", user_id=None,
        decision_point="chat_response", duration_ms=10,
    )
    payload = md.to_webhook_payload("execution.failed")
    # Full 5000 chars survive on failed events
    assert payload["stdout_summary"] == big
    assert payload["stderr_summary"] == big


def test_to_state_text_redaction_safe():
    r = _make_result()
    md = ExecutionMetadata.from_execution_result(
        result=r, tenant_id="t", user_id="u",
        decision_point="chat_response", duration_ms=10,
    )
    state_text = md.to_state_text()
    assert "decision_point=chat_response" in state_text
    assert "chain=claude_code" in state_text
    assert "status=execution_succeeded" in state_text


def test_truncate_for_webhook_short_text_unchanged():
    assert _truncate_for_webhook("hello") == "hello"
    assert _truncate_for_webhook("") == ""


def test_truncate_for_webhook_long_text_capped():
    big = "x" * 1000
    out = _truncate_for_webhook(big)
    assert out.startswith("x" * 512)
    assert out.endswith("(truncated)")
