"""§3 + §3.2 — auth/setup/trust errors STOP the chain (or §3.2 fallthrough).

Two branches:

  - Default branch: NEEDS_AUTH / WORKSPACE_UNTRUSTED / API_DISABLED on
    a platform whose successor is NOT opencode → executor stops the
    chain with the actionable_hint set, never silently falls back.
    This is the user-visible behaviour change vs legacy chain walk.

  - §3.2 R1 branch: same statuses on a platform whose NEXT element in
    chain is ``opencode`` → executor falls through, calls opencode's
    adapter, AND surfaces the actionable_hint as a non-blocking
    annotation on the eventual successful ExecutionResult.
"""
from __future__ import annotations

import pytest

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.executor import ResilientExecutor
from cli_orchestrator.status import Status


class _StaticStatusAdapter:
    """Adapter whose run() returns a configurable status."""

    def __init__(self, name: str, status: Status, response_text: str = ""):
        self.name = name
        self._status = status
        self._response_text = response_text
        self.run_calls = 0

    def preflight(self, req):
        return PreflightResult.succeed()

    def run(self, req):
        self.run_calls += 1
        if self._status is Status.EXECUTION_SUCCEEDED:
            return ExecutionResult(
                status=self._status,
                platform=self.name,
                response_text=self._response_text or "ok",
                attempt_count=1,
            )
        return ExecutionResult(
            status=self._status,
            platform=self.name,
            error_message=f"{self.name} returned {self._status.value}",
            attempt_count=1,
        )

    def classify_error(self, stderr, exit_code, exc):
        return Status.UNKNOWN_FAILURE


@pytest.mark.parametrize(
    "auth_status",
    [Status.NEEDS_AUTH, Status.WORKSPACE_UNTRUSTED, Status.API_DISABLED],
    ids=lambda s: s.value,
)
def test_auth_on_lone_platform_stops_chain(auth_status):
    """When the failing platform has no successor, the chain stops with
    actionable_hint set — never silent failure."""
    failing = _StaticStatusAdapter("claude_code", auth_status)
    executor = ResilientExecutor(adapters={"claude_code": failing})
    req = ExecutionRequest(
        chain=("claude_code",),
        platform="claude_code",
        payload={},
        tenant_id="tenant-1",
    )
    result = executor.execute(req)

    assert result.status is auth_status
    assert result.actionable_hint is not None
    assert result.actionable_hint.startswith("cli.errors.")
    assert failing.run_calls == 1


@pytest.mark.parametrize(
    "auth_status",
    [Status.NEEDS_AUTH, Status.WORKSPACE_UNTRUSTED, Status.API_DISABLED],
    ids=lambda s: s.value,
)
def test_auth_with_non_opencode_successor_still_stops(auth_status):
    """When the next platform is something other than opencode, the
    chain still stops — the §3.2 fallthrough is opencode-specific."""
    failing = _StaticStatusAdapter("claude_code", auth_status)
    secondary = _StaticStatusAdapter("codex", Status.EXECUTION_SUCCEEDED, response_text="codex would have worked")
    executor = ResilientExecutor(adapters={
        "claude_code": failing, "codex": secondary,
    })
    req = ExecutionRequest(
        chain=("claude_code", "codex"),
        platform="claude_code",
        payload={},
        tenant_id="tenant-1",
    )
    result = executor.execute(req)

    assert result.status is auth_status
    assert result.actionable_hint is not None
    # Critical: codex was NOT called — auth on claude_code stopped the chain.
    assert failing.run_calls == 1
    assert secondary.run_calls == 0, (
        f"§3 invariant: chain must stop on {auth_status.value}, codex must not run"
    )


@pytest.mark.parametrize(
    "auth_status",
    [Status.NEEDS_AUTH, Status.WORKSPACE_UNTRUSTED, Status.API_DISABLED],
    ids=lambda s: s.value,
)
def test_auth_with_opencode_successor_falls_through_with_hint(auth_status):
    """§3.2 R1 — when next platform is ``opencode``, the chain falls
    through, opencode runs, and the actionable_hint from the upstream
    auth failure is surfaced on the successful result as a non-blocking
    annotation.
    """
    failing = _StaticStatusAdapter("claude_code", auth_status)
    opencode = _StaticStatusAdapter("opencode", Status.EXECUTION_SUCCEEDED, response_text="local fallback ok")
    executor = ResilientExecutor(adapters={
        "claude_code": failing, "opencode": opencode,
    })
    req = ExecutionRequest(
        chain=("claude_code", "opencode"),
        platform="claude_code",
        payload={},
        tenant_id="tenant-1",
    )
    result = executor.execute(req)

    # The chain ended in success (opencode served).
    assert result.status is Status.EXECUTION_SUCCEEDED
    assert result.platform == "opencode"
    assert result.response_text == "local fallback ok"
    # Hint preserved as non-blocking annotation.
    assert result.actionable_hint is not None
    assert result.actionable_hint.startswith("cli.errors.")
    # Both ran — claude_code first (failed), opencode second (succeeded).
    assert failing.run_calls == 1
    assert opencode.run_calls == 1
    # platform_attempted captures the chain walk.
    assert "claude_code" in result.platform_attempted
    assert "opencode" in result.platform_attempted
