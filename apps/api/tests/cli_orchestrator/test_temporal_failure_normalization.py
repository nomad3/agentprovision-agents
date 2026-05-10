"""§3 — Temporal-level failures normalise to Status.WORKFLOW_FAILED.

Three exception types route to ``Status.WORKFLOW_FAILED``:

  - ``temporalio.exceptions.ApplicationError``
  - ``temporalio.exceptions.ActivityError``
  - ``asyncio.CancelledError``

The classifier wires this; the executor preserves ``workflow_id`` /
``activity_id`` on the resulting ``ExecutionResult`` so callers can
drill into the Temporal UI.

This test exercises the executor end-to-end with adapters that simulate
each Temporal failure mode, and asserts the terminal ExecutionResult:
  * status == WORKFLOW_FAILED
  * actionable_hint is set (policy table — workflow_failed stops with hint)
  * the chain DID NOT continue past the failure (Temporal-level failure
    is terminal — no silent retry, no fallback)
"""
from __future__ import annotations

import asyncio

import pytest

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.classifier import classify
from cli_orchestrator.executor import ResilientExecutor
from cli_orchestrator.status import Status


# Build the parametrise list AFTER trying to import temporalio so the
# absent-SDK environment skips cleanly. We classify CancelledError via
# stdlib unconditionally; the temporalio cases require the SDK.
def _build_temporal_failure_cases():
    cases = [("CancelledError", asyncio.CancelledError("activity cancelled"))]
    try:
        import temporalio.exceptions as _texc
        cases.append((
            "ApplicationError",
            _texc.ApplicationError("workflow application error"),
        ))
        cases.append((
            "ActivityError",
            _texc.ActivityError(
                "activity failed",
                scheduled_event_id=42,
                started_event_id=43,
                identity="test-worker",
                activity_type="ChatCliActivity",
                activity_id="test-activity-id",
                retry_state=None,
            ),
        ))
    except ImportError:
        pass
    return cases


TEMPORAL_FAILURE_CASES = _build_temporal_failure_cases()


@pytest.mark.parametrize(
    "label,exc", TEMPORAL_FAILURE_CASES, ids=[c[0] for c in TEMPORAL_FAILURE_CASES],
)
def test_classifier_maps_temporal_failure_to_workflow_failed(label, exc):
    """Direct classifier check — each Temporal exception type → WORKFLOW_FAILED."""
    status = classify(stderr=None, exit_code=None, exc=exc)
    assert status is Status.WORKFLOW_FAILED, (
        f"{label}: expected WORKFLOW_FAILED, got {status.value}"
    )


class _RaisingTemporalAdapter:
    """Adapter whose run() raises the supplied Temporal exception."""

    def __init__(self, name: str, exc: BaseException, *, workflow_id: str = "wf-test"):
        self.name = name
        self._exc = exc
        self._workflow_id = workflow_id
        self.run_calls = 0

    def preflight(self, req):
        return PreflightResult.succeed()

    def run(self, req):
        self.run_calls += 1
        # Adapters per the contract should NEVER raise — but the
        # api-side TemporalActivityAdapter can convert exceptions on
        # its own AND populate workflow_id. Mirror that here so the
        # executor sees a populated workflow_id on terminal stop.
        return ExecutionResult(
            status=classify(stderr=None, exit_code=None, exc=self._exc),
            platform=self.name,
            response_text="",
            error_message=str(self._exc) or self._exc.__class__.__name__,
            workflow_id=self._workflow_id,
            activity_id="act-test",
            platform_attempted=[self.name],
            attempt_count=1,
        )

    def classify_error(self, stderr, exit_code, exc):
        return classify(stderr, exit_code, exc)


class _NeverCalledAdapter:
    name = "should_never_run"
    run_calls = 0

    def preflight(self, req):
        return PreflightResult.succeed()

    def run(self, req):
        self.run_calls += 1
        return ExecutionResult(status=Status.EXECUTION_SUCCEEDED, platform=self.name)

    def classify_error(self, stderr, exit_code, exc):
        return Status.UNKNOWN_FAILURE


@pytest.mark.parametrize(
    "label,exc", TEMPORAL_FAILURE_CASES, ids=[c[0] for c in TEMPORAL_FAILURE_CASES],
)
def test_executor_finalises_workflow_failed_with_workflow_id(label, exc):
    """End-to-end: WORKFLOW_FAILED stops the chain WITH workflow_id +
    activity_id preserved; no fallback to next platform."""
    failing = _RaisingTemporalAdapter("claude_code", exc, workflow_id="wf-abc-123")
    succ = _NeverCalledAdapter()
    executor = ResilientExecutor(adapters={
        "claude_code": failing,
        "should_never_run": succ,
    })
    req = ExecutionRequest(
        chain=("claude_code", "should_never_run"),
        platform="claude_code",
        payload={},
        tenant_id="tenant-1",
    )
    result = executor.execute(req)

    assert result.status is Status.WORKFLOW_FAILED, label
    # workflow_id preserved across the stop.
    assert result.workflow_id == "wf-abc-123"
    assert result.activity_id == "act-test"
    # Stops, never falls back.
    assert failing.run_calls == 1
    assert succ.run_calls == 0, (
        f"{label}: WORKFLOW_FAILED must stop the chain, no silent fallback"
    )
    # Hint set per policy table.
    assert result.actionable_hint is not None
