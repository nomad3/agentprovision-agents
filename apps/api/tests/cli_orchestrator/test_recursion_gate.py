"""§3.1 recursion-gate tests.

The gate is enforced BEFORE any preflight or adapter call. We verify
this by registering a stub adapter with counters and asserting they
stay at zero on a refused request.

  - parent_chain length 3 → reject (no preflight, no run)
  - same agent appearing twice in parent_chain → reject
  - parent_chain length 2 (under MAX_FALLBACK_DEPTH=3, no cycle) → adapter IS called
"""
from __future__ import annotations

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.executor import ResilientExecutor
from cli_orchestrator.policy import MAX_FALLBACK_DEPTH
from cli_orchestrator.status import Status


class _CountingStubAdapter:
    """Stub adapter that counts preflight/run calls + always succeeds."""

    name = "stub"
    preflight_calls = 0
    run_calls = 0

    def preflight(self, req):
        self.preflight_calls += 1
        return PreflightResult.succeed()

    def run(self, req):
        self.run_calls += 1
        return ExecutionResult(
            status=Status.EXECUTION_SUCCEEDED,
            platform="stub",
            response_text="ok",
            attempt_count=1,
        )

    def classify_error(self, stderr, exit_code, exc):
        return Status.UNKNOWN_FAILURE


def _make_executor(adapter):
    return ResilientExecutor(adapters={"stub": adapter})


def test_parent_chain_length_three_is_refused_before_any_call():
    adapter = _CountingStubAdapter()
    executor = _make_executor(adapter)
    parent_chain = ("a", "b", "c")  # len == 3 == MAX_FALLBACK_DEPTH
    assert len(parent_chain) >= MAX_FALLBACK_DEPTH

    req = ExecutionRequest(
        chain=("stub",),
        platform="stub",
        payload={},
        parent_chain=parent_chain,
        tenant_id="tenant-1",
    )
    result = executor.execute(req)

    assert result.status is Status.PROVIDER_UNAVAILABLE
    assert "depth" in (result.error_message or "").lower()
    assert result.actionable_hint == "cli.errors.recursion_depth_exceeded"
    # Hard constraint: gate ran BEFORE any adapter call.
    assert adapter.preflight_calls == 0, "preflight should not have been called"
    assert adapter.run_calls == 0, "run should not have been called"


def test_same_agent_twice_in_parent_chain_is_refused():
    adapter = _CountingStubAdapter()
    executor = _make_executor(adapter)
    # Two distinct id values, but one repeats — clearly a cycle.
    parent_chain = ("agent-1", "agent-1")

    req = ExecutionRequest(
        chain=("stub",),
        platform="stub",
        payload={},
        parent_chain=parent_chain,
        tenant_id="tenant-1",
    )
    result = executor.execute(req)

    assert result.status is Status.PROVIDER_UNAVAILABLE
    assert "cycle" in (result.error_message or "").lower()
    assert result.actionable_hint == "cli.errors.recursion_cycle"
    assert adapter.preflight_calls == 0
    assert adapter.run_calls == 0


def test_parent_chain_length_two_no_cycle_proceeds_to_adapter():
    adapter = _CountingStubAdapter()
    executor = _make_executor(adapter)
    parent_chain = ("agent-1", "agent-2")  # len 2, no cycle

    req = ExecutionRequest(
        chain=("stub",),
        platform="stub",
        payload={},
        parent_chain=parent_chain,
        tenant_id="tenant-1",
    )
    result = executor.execute(req)

    assert result.status is Status.EXECUTION_SUCCEEDED
    assert adapter.preflight_calls == 1
    assert adapter.run_calls == 1
