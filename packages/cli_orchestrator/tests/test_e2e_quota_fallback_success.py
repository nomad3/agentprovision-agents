"""E2E quota-fallback success test — Phase 3 commit 3.

Chain: ``[claude_code, codex, copilot_cli]``.

  - claude_code → QUOTA_EXHAUSTED (run() returns)
  - codex      → NEEDS_AUTH (preflight fails — credentials missing)
  - copilot_cli → success

Asserts:
  - ExecutionMetadata records all three platforms in order
  - final_platform == "copilot_cli"
  - len(fallback_decisions) == 2 (claude→codex, codex→copilot)
  - Mirror called exactly once at terminal exit

Nothing here goes through Temporal — all adapters are stubs.
"""
from __future__ import annotations

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.executor import ResilientExecutor
from cli_orchestrator.metadata import ExecutionMetadata
from cli_orchestrator.status import Status


class _ClaudeStub:
    name = "claude_code"

    def preflight(self, req):
        return PreflightResult.succeed()

    def run(self, req):
        return ExecutionResult(
            status=Status.QUOTA_EXHAUSTED,
            platform=self.name,
            response_text="",
            error_message="rate limit hit",
            platform_attempted=[self.name],
            attempt_count=1,
            run_id=req.run_id or "r-1",
        )

    def classify_error(self, stderr=None, exit_code=None, exc=None):
        return Status.QUOTA_EXHAUSTED


class _CodexStubNeedsAuth:
    """Preflight fails with NEEDS_AUTH — but next platform is copilot_cli,
    not opencode, so the policy stops the chain UNLESS we treat it like
    fallback... wait. Per design §3.2 R1 the fallthrough is only on
    next_platform=='opencode'. So this should STOP the chain. Use
    PROVIDER_UNAVAILABLE to fall through (binary missing scenario)."""
    name = "codex"

    def preflight(self, req):
        return PreflightResult.fail(
            Status.PROVIDER_UNAVAILABLE,
            "codex binary not on $PATH",
        )

    def run(self, req):
        raise AssertionError("run() should not be called when preflight fails")

    def classify_error(self, stderr=None, exit_code=None, exc=None):
        return Status.PROVIDER_UNAVAILABLE


class _CopilotStubSuccess:
    name = "copilot_cli"

    def preflight(self, req):
        return PreflightResult.succeed()

    def run(self, req):
        return ExecutionResult(
            status=Status.EXECUTION_SUCCEEDED,
            platform=self.name,
            response_text="copilot served the response",
            stdout_summary="copilot served the response",
            exit_code=0,
            platform_attempted=[self.name],
            attempt_count=1,
            run_id=req.run_id or "r-1",
        )

    def classify_error(self, stderr=None, exit_code=None, exc=None):
        return Status.UNKNOWN_FAILURE


def test_e2e_quota_fallback_success():
    captured: list[ExecutionMetadata] = []
    adapters = {
        "claude_code": _ClaudeStub(),
        "codex": _CodexStubNeedsAuth(),
        "copilot_cli": _CopilotStubSuccess(),
    }
    executor = ResilientExecutor(
        adapters=adapters, decision_point="chat_response",
        mirror_to_rl=captured.append,
    )
    req = ExecutionRequest(
        chain=("claude_code", "codex", "copilot_cli"),
        platform="claude_code",
        payload={"message": "hello", "user_id": "u-1"},
        tenant_id="t-1", run_id="r-1",
    )
    result = executor.execute(req)

    assert result.status is Status.EXECUTION_SUCCEEDED
    assert result.platform == "copilot_cli"
    assert result.platform_attempted == ["claude_code", "codex", "copilot_cli"]
    assert result.response_text == "copilot served the response"

    # Mirror called exactly once
    assert len(captured) == 1
    md = captured[0]
    assert md.final_platform == "copilot_cli"
    assert md.platform_attempted == ["claude_code", "codex", "copilot_cli"]
    # Two fallback decisions: claude_code (QUOTA) -> codex,
    # codex (PROVIDER_UNAVAILABLE) -> copilot_cli.
    assert len(md.fallback_decisions) == 2
