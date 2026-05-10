"""Table-driven fallback-policy tests — design §3 + §3.1 + §3.2 (R1).

Every (Status, attempt) row in the design §3 table appears here as one
named test case. The §3.2 R1 amendment (NEEDS_AUTH / WORKSPACE_UNTRUSTED
/ API_DISABLED → opencode-fallthrough) gets its own block — both the
"stops the chain" branch AND the "falls through with non-blocking
hint" branch are covered.

The test runs the imported ``decide()`` from the canonical
``cli_orchestrator.policy`` module — apps/api uses the canonical
package directly via the ``conftest.py`` ``sys.path`` rigging.
"""
from __future__ import annotations

import pytest

from cli_orchestrator.policy import (
    MAX_FALLBACK_DEPTH,
    FallbackDecision,
    decide,
)
from cli_orchestrator.status import Status


# --------------------------------------------------------------------------
# §3 baseline table — every status x attempt combination
# --------------------------------------------------------------------------

# (test_id, status, attempt, expected_action, expected_hint_set)
BASELINE_CASES: list[tuple[str, Status, int, str, bool]] = [
    # success
    ("success_stops_chain", Status.EXECUTION_SUCCEEDED, 1, "stop", False),

    # quota — fallback always (cooldown is executor's side effect)
    ("quota_first_attempt_falls_back", Status.QUOTA_EXHAUSTED, 1, "fallback", False),
    ("quota_second_attempt_falls_back", Status.QUOTA_EXHAUSTED, 2, "fallback", False),

    # provider unavailable — fallback always
    ("provider_unavailable_falls_back", Status.PROVIDER_UNAVAILABLE, 1, "fallback", False),

    # retryable network — retry first, fallback after
    ("network_attempt1_retries", Status.RETRYABLE_NETWORK_FAILURE, 1, "retry", False),
    ("network_attempt2_falls_back", Status.RETRYABLE_NETWORK_FAILURE, 2, "fallback", False),

    # timeout — retry first, fallback after
    ("timeout_attempt1_retries", Status.TIMEOUT, 1, "retry", False),
    ("timeout_attempt2_falls_back", Status.TIMEOUT, 2, "fallback", False),

    # workflow_failed — stop, hint set
    ("workflow_failed_stops_with_hint", Status.WORKFLOW_FAILED, 1, "stop", True),

    # unknown_failure — retry first, then stop with hint
    ("unknown_attempt1_retries", Status.UNKNOWN_FAILURE, 1, "retry", False),
    ("unknown_attempt2_stops_with_hint", Status.UNKNOWN_FAILURE, 2, "stop", True),
]


@pytest.mark.parametrize(
    "case", BASELINE_CASES, ids=lambda c: c[0],
)
def test_fallback_policy_baseline(case):
    test_id, status, attempt, expected_action, expected_hint_set = case
    decision = decide(status, attempt, parent_chain=(), platform="claude_code")
    assert isinstance(decision, FallbackDecision), test_id
    assert decision.action == expected_action, (
        f"{test_id}: expected action={expected_action} got {decision.action}"
    )
    if expected_hint_set:
        assert decision.actionable_hint, (
            f"{test_id}: expected actionable_hint set, got None"
        )
    else:
        assert decision.actionable_hint is None or decision.action == "stop", (
            f"{test_id}: hint should be unset on retry/fallback unless §3.2"
        )


# --------------------------------------------------------------------------
# §3 NEEDS_AUTH / WORKSPACE_UNTRUSTED / API_DISABLED — default = stop
# --------------------------------------------------------------------------

# Without next_platform=opencode, all three stop the chain with hint.
NEEDS_AUTH_STOP_CASES: list[tuple[str, Status]] = [
    ("needs_auth_stops_default", Status.NEEDS_AUTH),
    ("workspace_untrusted_stops_default", Status.WORKSPACE_UNTRUSTED),
    ("api_disabled_stops_default", Status.API_DISABLED),
]


@pytest.mark.parametrize(
    "case", NEEDS_AUTH_STOP_CASES, ids=lambda c: c[0],
)
def test_fallback_policy_auth_stops_chain(case):
    test_id, status = case
    decision = decide(status, attempt=1, parent_chain=(), platform="claude_code")
    assert decision.action == "stop", test_id
    assert decision.actionable_hint, f"{test_id}: hint must be set"
    assert decision.actionable_hint.startswith("cli.errors."), (
        f"{test_id}: hint must be an i18n key"
    )


# Same again with a non-opencode next_platform → still stops.
@pytest.mark.parametrize(
    "next_platform", ["claude_code", "codex", "gemini_cli", "copilot_cli", None],
)
def test_fallback_policy_auth_stops_when_next_is_not_opencode(next_platform):
    decision = decide(
        Status.NEEDS_AUTH,
        attempt=1,
        parent_chain=(),
        platform="claude_code",
        next_platform=next_platform,
    )
    assert decision.action == "stop"
    assert decision.actionable_hint is not None


# --------------------------------------------------------------------------
# §3.2 R1 amendment — NEEDS_AUTH/WORKSPACE_UNTRUSTED/API_DISABLED + opencode
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status",
    [Status.NEEDS_AUTH, Status.WORKSPACE_UNTRUSTED, Status.API_DISABLED],
    ids=lambda s: s.value,
)
def test_r1_fallthrough_to_opencode_keeps_hint(status):
    """§3.2 — when next_platform is opencode, action becomes ``fallback``
    AND the actionable_hint is preserved so the executor can surface it
    as a non-blocking annotation on the eventual successful result.
    """
    decision = decide(
        status,
        attempt=1,
        parent_chain=(),
        platform="claude_code",
        next_platform="opencode",
    )
    assert decision.action == "fallback", (
        f"{status.value}: §3.2 says fall through when next is opencode"
    )
    assert decision.actionable_hint is not None, (
        f"{status.value}: hint must remain set on §3.2 fallthrough"
    )
    assert decision.actionable_hint.startswith("cli.errors."), (
        "hint must be a structured i18n key"
    )


# --------------------------------------------------------------------------
# Sanity — the depth ceiling is the documented value
# --------------------------------------------------------------------------

def test_max_fallback_depth_is_three():
    """§3.1 — the recursion budget is wired at module load time; the
    executor enforces it as a gate. This test pins the constant so a
    silent change requires a coordinated test failure.
    """
    assert MAX_FALLBACK_DEPTH == 3
