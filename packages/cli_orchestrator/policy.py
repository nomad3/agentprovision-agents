"""Fallback policy — design §3 + §3.1 + §3.2 (R1 amendment).

The policy is a **pure function** ``decide(status, attempt, parent_chain)
-> FallbackDecision``. Centralised so the chat hot path, the code-task
worker, and (eventually) the council all use the same rule. No I/O, no
clock, no global state — the executor is the only thing that knows
``cli_chain`` ordering, retry counters, and where ``opencode`` sits.

Policy rules (canonical from design §3):

    EXECUTION_SUCCEEDED       → stop (success)
    QUOTA_EXHAUSTED           → fallback (drop platform, mark cooldown)
    RETRYABLE_NETWORK_FAILURE → retry once with backoff, then fallback
    TIMEOUT                   → retry once on same platform, then fallback
    PROVIDER_UNAVAILABLE      → fallback (no cooldown)
    NEEDS_AUTH                → stop with actionable_hint
    WORKSPACE_UNTRUSTED       → stop with actionable_hint
    API_DISABLED              → stop with actionable_hint
    WORKFLOW_FAILED           → stop (preserve workflow_id + activity_id)
    UNKNOWN_FAILURE           → retry once on same platform, then stop

§3.1 — Bounded recursion. ``ResilientExecutor`` enforces the depth +
cycle gate BEFORE policy.decide is ever called; policy.decide does not
look at ``parent_chain`` for the depth/cycle decision. It is passed
along as an argument because the §3.2 R1 amendment uses
``next_platform`` (already resolved by the executor against
``parent_chain``-aware chain state) when shaping the actionable hint.

§3.2 — R1 amendment (NEEDS_AUTH → opencode-fallthrough). NEEDS_AUTH /
WORKSPACE_UNTRUSTED / API_DISABLED stop the chain UNLESS the executor's
``next_platform`` is ``opencode`` (the local floor that needs no
external creds). When the next platform IS opencode, action becomes
``fallback`` and the actionable_hint is *still* surfaced — but as a
**non-blocking annotation** on the eventual ExecutionResult. Lets us
keep "Luna always has *some* answer" while still telling the user
"by the way, your Claude subscription needs reconnecting".

Test gate: ``apps/api/tests/cli_orchestrator/test_fallback_policy_table.py``
covers every (Status, attempt, next_platform) tuple from the design
table plus the §3.2 fallthrough row.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .status import Status


# --------------------------------------------------------------------------
# Recursion budget — §3.1
# --------------------------------------------------------------------------

MAX_FALLBACK_DEPTH = 3
"""Hard ceiling on ``len(parent_chain)`` before the executor refuses any
preflight or adapter call. See ``ResilientExecutor`` for enforcement
(``parent_chain`` is the lineage of dispatching agents, not the local
CLI chain — distinct from cli_chain length)."""


# --------------------------------------------------------------------------
# FallbackDecision dataclass
# --------------------------------------------------------------------------

# Strings are part of the public contract — chat error footer + RL writer
# read them directly. Don't rename without coordinating with consumers.
FallbackAction = Literal["retry", "fallback", "stop"]


@dataclass(frozen=True)
class FallbackDecision:
    """One step's verdict from the fallback policy.

    Attributes:
        action: ``retry`` (same platform again), ``fallback`` (next
            platform in chain), or ``stop`` (terminate the chain walk).
        reason: human-readable, redaction-safe string. Used in logs and
            in the routing summary footer. NOT a wire-format key — see
            ``actionable_hint`` for the i18n key.
        actionable_hint: i18n key (e.g. ``cli.errors.needs_auth.claude_code``)
            surfaced to the UI when the chain stops on a recoverable-by-
            user error. ``None`` on retry/fallback decisions where we
            haven't given up yet, EXCEPT in the §3.2 fallthrough case
            where action=``fallback`` AND the hint is still set so the
            executor can surface it as a non-blocking annotation on the
            successful ExecutionResult.
    """

    action: FallbackAction
    reason: str
    actionable_hint: Optional[str] = None


# --------------------------------------------------------------------------
# Helpers — actionable hint key shaping
# --------------------------------------------------------------------------

# i18n key shape: cli.errors.<status_lc>[.<platform>]
# Resolved client-side. We only emit the key, never the English string.
def _hint_key(status: Status, platform: Optional[str]) -> str:
    """Build the i18n hint key for a stopping/fallthrough decision.

    The key shape mirrors what design §3 specifies: a stable
    ``cli.errors.<status>.<platform>`` form so client-side i18n
    bundles can swap renderings without a backend deploy.
    """
    base = f"cli.errors.{status.value}"
    if platform:
        return f"{base}.{platform}"
    return base


# Statuses that R1 amendment §3.2 covers — NEEDS_AUTH, WORKSPACE_UNTRUSTED,
# API_DISABLED all stop the chain UNLESS the next platform is opencode.
_R1_FALLTHROUGH_STATUSES = frozenset({
    Status.NEEDS_AUTH,
    Status.WORKSPACE_UNTRUSTED,
    Status.API_DISABLED,
})


# --------------------------------------------------------------------------
# Pure decision function — §3 table + §3.2 R1 amendment
# --------------------------------------------------------------------------

def decide(
    status: Status,
    attempt: int,
    parent_chain: tuple = (),
    *,
    platform: Optional[str] = None,
    next_platform: Optional[str] = None,
) -> FallbackDecision:
    """Decide what the executor should do given a step's outcome.

    Args:
        status: the normalised ``Status`` returned by the adapter or by
            classification of the adapter's outcome.
        attempt: 1-indexed attempt counter on the *current* platform.
            Retry-on-status rules (TIMEOUT, RETRYABLE_NETWORK_FAILURE,
            UNKNOWN_FAILURE) only fire when ``attempt == 1`` so the
            second observation of the same status falls through to
            either fallback or stop per the table.
        parent_chain: passed through for documentation symmetry with the
            executor's gate; this function does not consult it for the
            depth/cycle ruling — that's the executor's gate, evaluated
            BEFORE policy.decide, per §3.1.
        platform: the platform that just produced ``status`` (used for
            the actionable_hint i18n key).
        next_platform: the platform the executor would walk to next if
            we said ``fallback``. Only consulted for the §3.2 R1 rule
            (NEEDS_AUTH → opencode-fallthrough).

    Returns:
        ``FallbackDecision`` — pure data, no side effects.

    Notes:
        ``EXECUTION_SUCCEEDED`` is included for symmetry — the executor
        loop still reads the decision to know it should break out of
        the chain walk.
    """
    if status is Status.EXECUTION_SUCCEEDED:
        return FallbackDecision(action="stop", reason="execution succeeded")

    # ── §3.2 R1 amendment — NEEDS_AUTH / WORKSPACE_UNTRUSTED / API_DISABLED ──
    # These three normally stop the chain. EXCEPT when the next platform is
    # opencode (the local floor that needs no external creds), in which case
    # we fall through AND keep the actionable_hint so the executor can
    # surface it as a non-blocking annotation on the eventual success.
    if status in _R1_FALLTHROUGH_STATUSES:
        hint = _hint_key(status, platform)
        if next_platform == "opencode":
            return FallbackDecision(
                action="fallback",
                reason=f"{status.value} on {platform}; falling through to opencode",
                actionable_hint=hint,
            )
        return FallbackDecision(
            action="stop",
            reason=f"{status.value} on {platform}; user must reconnect",
            actionable_hint=hint,
        )

    if status is Status.QUOTA_EXHAUSTED:
        # Drop platform, mark cooldown — cooldown side effect lives in
        # the executor (mark_cli_cooldown), not here. Pure function.
        return FallbackDecision(
            action="fallback",
            reason=f"quota exhausted on {platform}",
        )

    if status is Status.PROVIDER_UNAVAILABLE:
        # Binary missing or recursion-gate exhausted. No cooldown — install
        # bug or systemic, not a transient quota issue.
        return FallbackDecision(
            action="fallback",
            reason=f"{platform} unavailable",
        )

    if status is Status.RETRYABLE_NETWORK_FAILURE:
        if attempt == 1:
            return FallbackDecision(
                action="retry",
                reason="retryable network failure; retrying with backoff",
            )
        return FallbackDecision(
            action="fallback",
            reason="retryable network failure persisted; falling back",
        )

    if status is Status.TIMEOUT:
        if attempt == 1:
            return FallbackDecision(
                action="retry",
                reason="timeout; retrying once on same platform",
            )
        return FallbackDecision(
            action="fallback",
            reason="timeout persisted; falling back",
        )

    if status is Status.WORKFLOW_FAILED:
        # Temporal-level failure — stop, don't retry. workflow_id +
        # activity_id are preserved by the executor, not the policy.
        return FallbackDecision(
            action="stop",
            reason="temporal workflow/activity failed",
            actionable_hint="cli.errors.workflow_failed",
        )

    if status is Status.UNKNOWN_FAILURE:
        if attempt == 1:
            return FallbackDecision(
                action="retry",
                reason="unknown failure; retrying once for diagnostics",
            )
        # Second unknown — surface the redacted snippet (executor builds
        # it). Stop; we don't know enough to keep walking.
        return FallbackDecision(
            action="stop",
            reason="unknown failure persisted; surfacing redacted snippet",
            actionable_hint="cli.errors.unknown_failure",
        )

    # Defensive fallthrough — a Status value we haven't enumerated. Stop
    # safely. This branch is exercised by the test suite as a guard
    # against future Status additions skipping the policy table.
    return FallbackDecision(
        action="stop",
        reason=f"unhandled status {status.value}",
        actionable_hint="cli.errors.unhandled_status",
    )


__all__ = [
    "FallbackAction",
    "FallbackDecision",
    "MAX_FALLBACK_DEPTH",
    "decide",
]
