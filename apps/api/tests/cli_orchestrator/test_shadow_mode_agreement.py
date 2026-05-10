"""Shadow-mode agreement metric tests — Phase 2 cutover gate.

Validates:
  - agree / disagree / shadow_error outcomes increment correctly
  - R4 amendment: expected_behaviour_change is tagged separately and
    EXCLUDED from the 99% agreement-gate denominator
  - shadow comparison NEVER raises (executor exceptions captured into
    a ShadowVerdict tagged shadow_error)
"""
from __future__ import annotations

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.shadow import (
    LegacyOutcome,
    ShadowVerdict,
    compute_legacy_outcome,
    run_shadow_comparison,
)
from cli_orchestrator.status import Status


# --------------------------------------------------------------------------
# compute_legacy_outcome — fuzzy mapping
# --------------------------------------------------------------------------

def test_legacy_outcome_success():
    outcome = compute_legacy_outcome(
        response_text="hello",
        metadata={"platform": "claude_code"},
    )
    assert outcome.final_status is Status.EXECUTION_SUCCEEDED
    assert outcome.final_platform == "claude_code"


def test_legacy_outcome_failure_quota():
    outcome = compute_legacy_outcome(
        response_text="",
        metadata={
            "platform": "codex",
            "routing_summary": {"fallback_reason": "quota", "served_by": None},
        },
    )
    assert outcome.final_status is Status.QUOTA_EXHAUSTED
    assert outcome.final_platform == "codex"


def test_legacy_outcome_failure_missing_credential_maps_to_needs_auth():
    outcome = compute_legacy_outcome(
        response_text="",
        metadata={
            "platform": "claude_code",
            "routing_summary": {"fallback_reason": "missing_credential"},
        },
    )
    assert outcome.final_status is Status.NEEDS_AUTH


# --------------------------------------------------------------------------
# Shadow executor stubs
# --------------------------------------------------------------------------

class _ReplayExecutor:
    """Returns a pre-built ExecutionResult — used to simulate shadow path."""

    def __init__(self, result: ExecutionResult):
        self._result = result

    def execute(self, req):
        return self._result


class _RaisingExecutor:
    def execute(self, req):
        raise RuntimeError("shadow exploded")


def _req() -> ExecutionRequest:
    return ExecutionRequest(
        chain=("claude_code",),
        platform="claude_code",
        payload={},
        tenant_id="tenant-1",
    )


# --------------------------------------------------------------------------
# Agreement classification
# --------------------------------------------------------------------------

def test_shadow_agree_success_same_platform():
    legacy = LegacyOutcome(
        final_status=Status.EXECUTION_SUCCEEDED, final_platform="claude_code",
    )
    new = ExecutionResult(
        status=Status.EXECUTION_SUCCEEDED,
        platform="claude_code",
        response_text="ok",
    )
    verdict = run_shadow_comparison(_req(), legacy, _ReplayExecutor(new))
    assert verdict.agree
    assert verdict.disagreement_kind == "agree"


def test_shadow_disagree_status_mismatch():
    legacy = LegacyOutcome(
        final_status=Status.EXECUTION_SUCCEEDED, final_platform="claude_code",
    )
    new = ExecutionResult(
        status=Status.QUOTA_EXHAUSTED, platform="claude_code",
    )
    verdict = run_shadow_comparison(_req(), legacy, _ReplayExecutor(new))
    assert not verdict.agree
    assert verdict.disagreement_kind == "status_mismatch"


def test_shadow_disagree_platform_mismatch_on_double_success():
    """Both paths succeeded but on different platforms — tag for triage,
    NOT an agreement."""
    legacy = LegacyOutcome(
        final_status=Status.EXECUTION_SUCCEEDED, final_platform="claude_code",
    )
    new = ExecutionResult(
        status=Status.EXECUTION_SUCCEEDED, platform="opencode", response_text="ok",
    )
    verdict = run_shadow_comparison(_req(), legacy, _ReplayExecutor(new))
    assert not verdict.agree
    assert verdict.disagreement_kind == "platform_mismatch"


# --------------------------------------------------------------------------
# R4 amendment — expected_behaviour_change excluded from 99% gate
# --------------------------------------------------------------------------

def test_r4_legacy_fell_through_on_auth_new_stops_is_expected_behaviour_change():
    """Legacy chain walked PAST a missing_credential / auth on
    claude_code and ended successfully on codex (silent fallthrough).
    The new path STOPS with NEEDS_AUTH + actionable_hint instead. This
    is the documented behaviour change — must NOT count against the
    99% agreement gate denominator.
    """
    legacy = LegacyOutcome(
        final_status=Status.EXECUTION_SUCCEEDED,
        final_platform="codex",
        fell_through_on="missing_credential",
    )
    new = ExecutionResult(
        status=Status.NEEDS_AUTH,
        platform="claude_code",
        actionable_hint="cli.errors.needs_auth.claude_code",
    )
    verdict = run_shadow_comparison(_req(), legacy, _ReplayExecutor(new))
    assert not verdict.agree
    assert verdict.disagreement_kind == "expected_behaviour_change"


def test_r4_legacy_fell_through_on_auth_new_workspace_untrusted_excluded():
    """Same R4 spirit — different new-status in the user-reconnect set."""
    legacy = LegacyOutcome(
        final_status=Status.EXECUTION_SUCCEEDED,
        final_platform="opencode",
        fell_through_on="auth",
    )
    new = ExecutionResult(
        status=Status.WORKSPACE_UNTRUSTED, platform="codex",
    )
    verdict = run_shadow_comparison(_req(), legacy, _ReplayExecutor(new))
    assert not verdict.agree
    assert verdict.disagreement_kind == "expected_behaviour_change"


def test_r4_compute_legacy_outcome_detects_fell_through_on_auth():
    """The compute_legacy_outcome helper sets fell_through_on when the
    routing_summary shows a missing_credential fallback that ended on a
    different platform than the requested one — the canonical R4
    trigger surface from agent_router."""
    metadata = {
        "platform": "codex",
        "routing_summary": {
            "served_by": "codex",
            "requested": "claude_code",
            "fallback_reason": "missing_credential",
        },
    }
    outcome = compute_legacy_outcome(response_text="hello", metadata=metadata)
    assert outcome.fell_through_on == "missing_credential"
    assert outcome.final_status is Status.EXECUTION_SUCCEEDED


# --------------------------------------------------------------------------
# Shadow path NEVER raises
# --------------------------------------------------------------------------

def test_shadow_executor_exception_does_not_propagate():
    legacy = LegacyOutcome(
        final_status=Status.EXECUTION_SUCCEEDED, final_platform="claude_code",
    )
    # _RaisingExecutor's execute() raises; run_shadow_comparison must catch.
    verdict = run_shadow_comparison(_req(), legacy, _RaisingExecutor())
    assert isinstance(verdict, ShadowVerdict)
    assert verdict.disagreement_kind == "shadow_error"
    assert not verdict.agree
