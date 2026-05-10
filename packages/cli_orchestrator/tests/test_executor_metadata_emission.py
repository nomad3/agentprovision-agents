"""Executor metadata-emission tests — Phase 3 commit 3.

Verifies that ResilientExecutor invokes ``mirror_to_rl`` with an
ExecutionMetadata at each terminal exit point:

  - happy path → one mirror call, status=EXECUTION_SUCCEEDED
  - fallback chain → one mirror call at terminal exit
  - workflow_failed → one mirror call, status=WORKFLOW_FAILED
  - mirror_to_rl raising does NOT poison the response

Plus the executor's accumulators (retry_decisions, fallback_decisions)
are populated correctly during the chain walk.
"""
from __future__ import annotations

from typing import Optional

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.executor import ResilientExecutor
from cli_orchestrator.metadata import ExecutionMetadata
from cli_orchestrator.status import Status


class _StubAdapter:
    def __init__(self, name: str, result: ExecutionResult):
        self.name = name
        self._result = result

    def preflight(self, req):
        return PreflightResult.succeed()

    def run(self, req):
        return self._result

    def classify_error(self, stderr=None, exit_code=None, exc=None):
        return Status.UNKNOWN_FAILURE


def _success(platform: str = "claude_code") -> ExecutionResult:
    return ExecutionResult(
        status=Status.EXECUTION_SUCCEEDED,
        platform=platform,
        response_text="hi",
        platform_attempted=[platform],
        attempt_count=1,
        run_id="r-1",
    )


def _fail(platform: str, status: Status) -> ExecutionResult:
    return ExecutionResult(
        status=status, platform=platform,
        response_text="", error_message=f"{status.value} on {platform}",
        platform_attempted=[platform], attempt_count=1, run_id="r-1",
    )


def test_mirror_called_on_happy_path():
    captured: list[ExecutionMetadata] = []
    adapters = {"claude_code": _StubAdapter("claude_code", _success())}
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        mirror_to_rl=captured.append,
    )
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={"message": "hi", "user_id": "u-1"}, tenant_id="t-1",
    )
    result = executor.execute(req)
    assert result.status is Status.EXECUTION_SUCCEEDED
    assert len(captured) == 1
    md = captured[0]
    assert md.tenant_id == "t-1"
    assert md.user_id == "u-1"
    assert md.decision_point == "chat_response"
    assert md.final_platform == "claude_code"
    assert md.status is Status.EXECUTION_SUCCEEDED


def test_mirror_called_on_fallback_chain_exhausted():
    captured: list[ExecutionMetadata] = []
    adapters = {
        "claude_code": _StubAdapter(
            "claude_code", _fail("claude_code", Status.QUOTA_EXHAUSTED),
        ),
        "codex": _StubAdapter(
            "codex", _fail("codex", Status.QUOTA_EXHAUSTED),
        ),
    }
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        mirror_to_rl=captured.append,
    )
    req = ExecutionRequest(
        chain=("claude_code", "codex"), platform="claude_code",
        payload={"message": "hi", "user_id": "u-1"}, tenant_id="t-1",
    )
    result = executor.execute(req)
    assert result.status is Status.QUOTA_EXHAUSTED  # last attempt
    assert len(captured) == 1
    md = captured[0]
    # fallback_decisions accumulated for 1 fallback (claude_code -> codex);
    # the second platform also returned QUOTA but had no next platform
    # to fallback to so no decision was added.
    assert len(md.fallback_decisions) >= 1


def test_mirror_called_on_workflow_failed_stop():
    captured: list[ExecutionMetadata] = []
    adapters = {
        "claude_code": _StubAdapter(
            "claude_code", _fail("claude_code", Status.WORKFLOW_FAILED),
        ),
    }
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        mirror_to_rl=captured.append,
    )
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={"message": "hi"}, tenant_id="t-1",
    )
    result = executor.execute(req)
    assert result.status is Status.WORKFLOW_FAILED
    assert len(captured) == 1
    assert captured[0].status is Status.WORKFLOW_FAILED


def test_mirror_failure_does_not_poison_response():
    """RL mirror raising must not affect the returned ExecutionResult."""
    def boom(md):
        raise RuntimeError("RL writer down")

    adapters = {"claude_code": _StubAdapter("claude_code", _success())}
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        mirror_to_rl=boom,
    )
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={"message": "hi"}, tenant_id="t-1",
    )
    result = executor.execute(req)
    assert result.status is Status.EXECUTION_SUCCEEDED  # unaffected
    assert result.response_text == "hi"


def test_mirror_called_on_recursion_gate_refusal():
    """§3.1 recursion gate refusal also mirrors."""
    captured: list[ExecutionMetadata] = []
    adapters = {"claude_code": _StubAdapter("claude_code", _success())}
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        mirror_to_rl=captured.append,
    )
    # parent_chain length >= MAX_FALLBACK_DEPTH (3) → refusal
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={}, tenant_id="t-1",
        parent_chain=("a", "b", "c"),
    )
    result = executor.execute(req)
    assert result.actionable_hint == "cli.errors.recursion_depth_exceeded"
    assert len(captured) == 1


def test_mirror_omitted_when_no_callable_provided():
    """No mirror_to_rl arg → executor still works."""
    adapters = {"claude_code": _StubAdapter("claude_code", _success())}
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
    )
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={}, tenant_id="t-1",
    )
    result = executor.execute(req)
    assert result.status is Status.EXECUTION_SUCCEEDED
