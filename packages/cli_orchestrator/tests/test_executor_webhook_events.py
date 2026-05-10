"""Executor webhook-event emission tests — Phase 3 commit 5.

Asserts ``webhook_emitter`` is called with the right (event_name,
payload) tuples per state transition:

  - happy path: started + succeeded
  - preflight-failure-then-fallback: started + attempt_failed + fallback_triggered + succeeded
  - quota-then-fallback: started + attempt_failed + fallback_triggered + ...
  - terminal failure: started + attempt_failed + failed
  - heartbeat_missed is NOT emitted by the executor (commit 8 worker-side)

Plus 512B truncation for non-failed events.
"""
from __future__ import annotations

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.executor import ResilientExecutor
from cli_orchestrator.metadata import _WEBHOOK_TRUNCATE_BYTES
from cli_orchestrator.status import Status
from cli_orchestrator.webhook_events import (
    EVENT_ATTEMPT_FAILED,
    EVENT_FAILED,
    EVENT_FALLBACK_TRIGGERED,
    EVENT_STARTED,
    EVENT_SUCCEEDED,
)


class _StubAdapter:
    def __init__(self, name: str, result, *, preflight_result=None):
        self.name = name
        self._result = result
        self._preflight = preflight_result or PreflightResult.succeed()

    def preflight(self, req):
        return self._preflight

    def run(self, req):
        return self._result

    def classify_error(self, stderr=None, exit_code=None, exc=None):
        return Status.UNKNOWN_FAILURE


def _success(platform="claude_code", **kw) -> ExecutionResult:
    return ExecutionResult(
        status=Status.EXECUTION_SUCCEEDED, platform=platform,
        response_text="ok", stdout_summary="ok",
        platform_attempted=[platform], attempt_count=1, run_id="r-1",
        **kw,
    )


def _fail(platform: str, status: Status) -> ExecutionResult:
    return ExecutionResult(
        status=status, platform=platform,
        response_text="", error_message=f"{status.value}",
        stderr_summary=f"{status.value} stderr",
        platform_attempted=[platform], attempt_count=1, run_id="r-1",
    )


def test_happy_path_emits_started_and_succeeded():
    captured: list[tuple[str, dict]] = []
    adapters = {"claude_code": _StubAdapter("claude_code", _success())}
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        webhook_emitter=lambda evt, payload: captured.append((evt, payload)),
    )
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={"message": "hi"}, tenant_id="t",
    )
    executor.execute(req)
    events = [e for e, _ in captured]
    assert events == [EVENT_STARTED, EVENT_SUCCEEDED]


def test_quota_fallback_emits_attempt_failed_then_fallback_then_succeeded():
    captured: list[tuple[str, dict]] = []
    adapters = {
        "claude_code": _StubAdapter(
            "claude_code", _fail("claude_code", Status.QUOTA_EXHAUSTED),
        ),
        "codex": _StubAdapter("codex", _success("codex")),
    }
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        webhook_emitter=lambda evt, payload: captured.append((evt, payload)),
    )
    req = ExecutionRequest(
        chain=("claude_code", "codex"), platform="claude_code",
        payload={}, tenant_id="t",
    )
    executor.execute(req)
    events = [e for e, _ in captured]
    assert events == [
        EVENT_STARTED,
        EVENT_ATTEMPT_FAILED,
        EVENT_FALLBACK_TRIGGERED,
        EVENT_SUCCEEDED,
    ]


def test_preflight_failure_emits_attempt_failed_with_zero_attempt_index():
    captured: list[tuple[str, dict]] = []
    adapters = {
        "claude_code": _StubAdapter(
            "claude_code", _success(),
            preflight_result=PreflightResult.fail(
                Status.PROVIDER_UNAVAILABLE, "binary missing",
            ),
        ),
        "codex": _StubAdapter("codex", _success("codex")),
    }
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        webhook_emitter=lambda evt, payload: captured.append((evt, payload)),
    )
    req = ExecutionRequest(
        chain=("claude_code", "codex"), platform="claude_code",
        payload={}, tenant_id="t",
    )
    executor.execute(req)
    # First non-success is the preflight failure with attempt_index=0.
    attempt_failed = [
        (e, p) for e, p in captured if e == EVENT_ATTEMPT_FAILED
    ]
    assert len(attempt_failed) >= 1
    assert attempt_failed[0][1]["attempt_index"] == 0
    assert attempt_failed[0][1]["status"] == "provider_unavailable"


def test_terminal_failure_emits_failed_event():
    captured: list[tuple[str, dict]] = []
    adapters = {
        "claude_code": _StubAdapter(
            "claude_code", _fail("claude_code", Status.NEEDS_AUTH),
        ),
    }
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        webhook_emitter=lambda evt, payload: captured.append((evt, payload)),
    )
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={}, tenant_id="t",
    )
    executor.execute(req)
    events = [e for e, _ in captured]
    # NEEDS_AUTH stops the chain (no opencode next), so we go through
    # _finalise_stop which fires EVENT_FAILED.
    assert EVENT_STARTED in events
    assert EVENT_FAILED in events


def test_attempt_failed_payload_truncates_stderr_to_512b():
    big = "x" * 5000
    fail_result = ExecutionResult(
        status=Status.QUOTA_EXHAUSTED,
        platform="claude_code",
        response_text="", error_message="quota",
        stderr_summary=big,
        platform_attempted=["claude_code"], attempt_count=1, run_id="r-1",
    )
    captured: list[tuple[str, dict]] = []
    adapters = {"claude_code": _StubAdapter("claude_code", fail_result)}
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        webhook_emitter=lambda evt, payload: captured.append((evt, payload)),
    )
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={}, tenant_id="t",
    )
    executor.execute(req)
    attempt_failed = [(e, p) for e, p in captured if e == EVENT_ATTEMPT_FAILED]
    assert attempt_failed
    payload = attempt_failed[0][1]
    assert len(payload["stderr_summary"]) <= _WEBHOOK_TRUNCATE_BYTES + 32


def test_failed_event_keeps_full_stderr():
    big = "x" * 5000
    fail_result = ExecutionResult(
        status=Status.NEEDS_AUTH,
        platform="claude_code",
        response_text="", error_message="auth bad",
        stderr_summary=big,
        platform_attempted=["claude_code"], attempt_count=1, run_id="r-1",
    )
    captured: list[tuple[str, dict]] = []
    adapters = {"claude_code": _StubAdapter("claude_code", fail_result)}
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        webhook_emitter=lambda evt, payload: captured.append((evt, payload)),
    )
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={}, tenant_id="t",
    )
    executor.execute(req)
    failed = [(e, p) for e, p in captured if e == EVENT_FAILED]
    assert failed
    payload = failed[0][1]
    # 4KB cap in stdout/stderr summaries from the executor itself, but
    # this stub bypasses that — verify failed payload didn't truncate
    # at the 512B webhook cap.
    assert len(payload["stderr_summary"]) > _WEBHOOK_TRUNCATE_BYTES


def test_emitter_failure_does_not_poison_response():
    """Webhook emitter raising must not affect the returned ExecutionResult."""
    def boom(evt, payload):
        raise RuntimeError("webhook delivery down")

    adapters = {"claude_code": _StubAdapter("claude_code", _success())}
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        webhook_emitter=boom,
    )
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={}, tenant_id="t",
    )
    result = executor.execute(req)
    assert result.status is Status.EXECUTION_SUCCEEDED


def test_no_webhook_emitter_does_not_break_executor():
    """No webhook_emitter arg → executor still works."""
    adapters = {"claude_code": _StubAdapter("claude_code", _success())}
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
    )
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={}, tenant_id="t",
    )
    result = executor.execute(req)
    assert result.status is Status.EXECUTION_SUCCEEDED


def test_started_event_payload_shape():
    captured: list[tuple[str, dict]] = []
    adapters = {"claude_code": _StubAdapter("claude_code", _success())}
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        webhook_emitter=lambda evt, payload: captured.append((evt, payload)),
    )
    req = ExecutionRequest(
        chain=("claude_code", "codex"), platform="claude_code",
        payload={"parent_task_id": "task-9"}, tenant_id="t-7",
    )
    executor.execute(req)
    started = [p for e, p in captured if e == EVENT_STARTED]
    assert len(started) == 1
    assert started[0]["tenant_id"] == "t-7"
    assert started[0]["decision_point"] == "chat_response"
    assert started[0]["platform_chain"] == ["claude_code", "codex"]
    assert started[0]["parent_task_id"] == "task-9"
