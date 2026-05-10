"""Shadow-mode plumbing for the Phase 2 cutover.

Compares the LEGACY chain-walk outcome (already produced) against
what the new ResilientExecutor WOULD have produced. Flag-OFF default
runs a stubbed adapter that replays the legacy outcome cheaply (no
real Temporal/LLM dispatch); flag-ON real dispatch is the validation
mode used for ~48h on a single internal tenant.

Public API:

  - ``compute_legacy_outcome(response_text, metadata) -> LegacyOutcome``
    Derives the (final_status, final_platform) tuple from whatever the
    legacy chain walk returned. The chat path stamps the actual served
    platform on ``metadata['platform']`` (and falls back to chain head
    on autodetect — see agent_router.py:1004).

  - ``run_shadow_comparison(req, legacy_outcome, executor) -> None``
    Runs the executor against the SAME request, compares outcomes,
    emits Prometheus metrics. Catches all exceptions — the shadow
    path can NEVER poison the response. ``disagreement_kind=
    "expected_behaviour_change"`` (R4 amendment) is excluded from the
    99% agreement gate denominator.

The 99% gate denominator counts agree + disagree rows; expected
behaviour-change rows are tagged but excluded from the SLO so a
designed change (legacy fell through on auth, new path stops with
hint) doesn't tank the agreement number.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from .adapters.base import ExecutionRequest, ExecutionResult
from .status import Status

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Outcome dataclasses
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LegacyOutcome:
    """The shape extracted from the legacy chain walk's output.

    Attributes:
        final_status: Approximate ``Status`` we derive from the legacy
            metadata. Mapping is fuzzy by design — legacy used string
            labels like ``"quota"`` / ``"auth"`` / ``"missing_credential"``;
            we map those into the canonical Status enum so the diff
            against the new path is on a common axis.
        final_platform: The platform that actually served the legacy
            response (or the chain head when no platform served).
        fell_through_on: When the legacy chain WALKED PAST an auth /
            missing_credential failure on an upstream platform and
            ended elsewhere, this is the err_class string that fired
            the chain skip ("auth" or "missing_credential"). Used by
            the R4 expected_behaviour_change tag so the new-path's
            "stop with hint" outcome doesn't count as a disagreement
            against the 99% gate. ``None`` when the legacy chain
            walked cleanly without an auth-flavour fallback.
    """

    final_status: Status
    final_platform: Optional[str]
    fell_through_on: Optional[str] = None


@dataclass(frozen=True)
class ShadowVerdict:
    """Outcome of one shadow comparison.

    Attributes:
        agree: True iff (status, platform) match.
        disagreement_kind: One of:
          - "agree" (no disagreement)
          - "status_mismatch" (legacy and new disagree on status)
          - "platform_mismatch" (status agrees but platform differs)
          - "shadow_error" (the new-path executor raised — counts as
            an error, not a disagreement, for the 99% gate)
          - "expected_behaviour_change" (R4 — legacy fell through on
            auth/missing_credential, new path stops with NEEDS_AUTH /
            WORKSPACE_UNTRUSTED / API_DISABLED. EXCLUDED from the 99%
            gate denominator.)
    """

    agree: bool
    disagreement_kind: str = "agree"


# --------------------------------------------------------------------------
# Prometheus metrics — best-effort
# --------------------------------------------------------------------------

try:
    from prometheus_client import Counter

    _AGREE_TOTAL = Counter(
        "cli_orchestrator_shadow_agreement_total",
        "Shadow-mode comparison outcomes",
        ["tenant_id", "outcome"],  # outcome = agree | disagree | error | expected_behaviour_change
    )
    _DISAGREE_DETAIL = Counter(
        "cli_orchestrator_shadow_disagreement_detail",
        "Shadow-mode disagreement breakdown",
        ["tenant_id", "disagreement_kind"],
    )
    _METRICS_OK = True
except ImportError:
    _AGREE_TOTAL = _DISAGREE_DETAIL = None  # type: ignore[assignment]
    _METRICS_OK = False


def _emit_outcome(*, tenant_id: str, outcome: str, kind: str) -> None:
    """Best-effort metric emit — never raises."""
    if not _METRICS_OK:
        return
    try:
        _AGREE_TOTAL.labels(tenant_id=tenant_id, outcome=outcome).inc()  # type: ignore[union-attr]
        if outcome != "agree":
            _DISAGREE_DETAIL.labels(  # type: ignore[union-attr]
                tenant_id=tenant_id, disagreement_kind=kind,
            ).inc()
    except Exception:  # noqa: BLE001
        logger.debug("shadow metric emission failed", exc_info=True)


# --------------------------------------------------------------------------
# Legacy outcome derivation
# --------------------------------------------------------------------------

# Mapping from legacy err_class strings (the values
# `cli_platform_resolver.classify_error` historically returned and the
# values agent_router._classify_cli_error returns) to canonical Status.
_LEGACY_ERRCLASS_TO_STATUS: dict[str, Status] = {
    "quota": Status.QUOTA_EXHAUSTED,
    "auth": Status.NEEDS_AUTH,
    "missing_credential": Status.NEEDS_AUTH,
    "exception": Status.UNKNOWN_FAILURE,
    "internal_error": Status.UNKNOWN_FAILURE,
    "timeout": Status.TIMEOUT,
    "network": Status.RETRYABLE_NETWORK_FAILURE,
}


def compute_legacy_outcome(
    response_text: str,
    metadata: dict[str, Any] | None,
) -> LegacyOutcome:
    """Derive (final_status, final_platform) from a legacy chain-walk output.

    The legacy hot path stamps:
      - metadata["platform"]  — the platform that actually served (or
        the chain head when nothing served on autodetect)
      - metadata["error"]     — the last error string when nothing served
      - metadata["routing_summary"] — curated routing UI data, including
        ``fallback_reason`` (one of the legacy err_class strings)

    We map those into the canonical Status / platform tuple.
    """
    metadata = metadata or {}
    routing = metadata.get("routing_summary") or {}
    final_platform = (
        metadata.get("platform")
        or routing.get("served_by")
        or routing.get("requested")
    )
    # Detect "fell through on auth/missing_credential": the legacy chain
    # walker stamps `routing_summary.fallback_reason` whenever the chain
    # walked PAST a failure (regardless of whether it ultimately
    # succeeded). When that reason is in the auth-flavour bucket AND the
    # served platform != the requested platform, the legacy chain
    # silently fell through on auth — the canonical R4 trigger.
    fell_through_on: Optional[str] = None
    fallback_reason = routing.get("fallback_reason")
    if fallback_reason in {"auth", "missing_credential"}:
        served = routing.get("served_by")
        requested = routing.get("requested")
        if served and requested and served != requested:
            fell_through_on = fallback_reason
    if response_text:
        return LegacyOutcome(
            final_status=Status.EXECUTION_SUCCEEDED,
            final_platform=final_platform,
            fell_through_on=fell_through_on,
        )
    err_class = fallback_reason or metadata.get("err_class")
    if err_class and err_class in _LEGACY_ERRCLASS_TO_STATUS:
        return LegacyOutcome(
            final_status=_LEGACY_ERRCLASS_TO_STATUS[err_class],
            final_platform=final_platform,
            fell_through_on=fell_through_on,
        )
    # Fall through — exhausted chain with no class.
    return LegacyOutcome(
        final_status=Status.UNKNOWN_FAILURE,
        final_platform=final_platform,
        fell_through_on=fell_through_on,
    )


# --------------------------------------------------------------------------
# Shadow comparison
# --------------------------------------------------------------------------

class _ExecutorLike(Protocol):
    """Just the surface run_shadow_comparison needs from an executor."""

    def execute(self, req: ExecutionRequest) -> ExecutionResult: ...


# R4 amendment — when legacy fell through on auth/missing_credential
# AND new path stops with NEEDS_AUTH/WORKSPACE_UNTRUSTED/API_DISABLED,
# tag as expected_behaviour_change and EXCLUDE from agreement gate.
# (LegacyOutcome.fell_through_on captures the legacy-side "fell
# through" signal; this set is the new-side terminal stop bucket.)
_R4_NEW_STOP_STATUSES = frozenset({
    Status.NEEDS_AUTH,
    Status.WORKSPACE_UNTRUSTED,
    Status.API_DISABLED,
})


def _classify_disagreement(
    legacy: LegacyOutcome,
    new: ExecutionResult,
) -> ShadowVerdict:
    """Compare legacy outcome to new ExecutionResult; return verdict."""
    # R4 — expected behaviour change. Fired when legacy fell through on
    # auth / missing_credential (its chain skipped past an upstream
    # auth failure) AND the new path's status is in the
    # "user-must-reconnect" set (NEEDS_AUTH / WORKSPACE_UNTRUSTED /
    # API_DISABLED). Evaluated BEFORE the agreement check because two
    # NEEDS_AUTH outcomes would otherwise look like a trivial "agree"
    # while the legacy actually walked past it. This is the documented
    # behaviour change for Phase 2 and must NOT count against the 99%
    # agreement gate.
    if (
        legacy.fell_through_on in {"auth", "missing_credential"}
        and new.status in _R4_NEW_STOP_STATUSES
    ):
        return ShadowVerdict(
            agree=False, disagreement_kind="expected_behaviour_change",
        )

    if legacy.final_status is new.status and (
        legacy.final_platform == new.platform
        or legacy.final_platform is None
        or new.platform is None
    ):
        return ShadowVerdict(agree=True, disagreement_kind="agree")
    # If legacy succeeded on platform A, but new succeeded on platform B
    # (e.g. fallthrough to opencode under §3.2), the platform differs
    # though both succeeded. Tag separately for triage.
    if legacy.final_status is Status.EXECUTION_SUCCEEDED and new.status is Status.EXECUTION_SUCCEEDED:
        return ShadowVerdict(
            agree=False, disagreement_kind="platform_mismatch",
        )
    return ShadowVerdict(
        agree=False, disagreement_kind="status_mismatch",
    )


def run_shadow_comparison(
    req: ExecutionRequest,
    legacy_outcome: LegacyOutcome,
    executor: _ExecutorLike,
) -> ShadowVerdict:
    """Run the executor in shadow, compare to legacy, emit metrics.

    Catches all exceptions — the chat hot path must NEVER be poisoned
    by a shadow failure. Returns a ShadowVerdict (or a synthetic
    error-tagged one on shadow execution failure) so callers can log
    it; in production we discard it.
    """
    tenant_id = req.tenant_id or "unknown"
    try:
        new_result = executor.execute(req)
    except BaseException:  # noqa: BLE001  shadow MUST NOT poison
        logger.debug("shadow executor raised", exc_info=True)
        verdict = ShadowVerdict(agree=False, disagreement_kind="shadow_error")
        _emit_outcome(tenant_id=tenant_id, outcome="error", kind="shadow_error")
        return verdict

    verdict = _classify_disagreement(legacy_outcome, new_result)
    if verdict.agree:
        _emit_outcome(tenant_id=tenant_id, outcome="agree", kind="agree")
    elif verdict.disagreement_kind == "expected_behaviour_change":
        # R4 — count separately, EXCLUDE from agreement gate denominator.
        _emit_outcome(
            tenant_id=tenant_id,
            outcome="expected_behaviour_change",
            kind=verdict.disagreement_kind,
        )
    else:
        _emit_outcome(
            tenant_id=tenant_id,
            outcome="disagree",
            kind=verdict.disagreement_kind,
        )
    return verdict


__all__ = [
    "LegacyOutcome",
    "ShadowVerdict",
    "compute_legacy_outcome",
    "run_shadow_comparison",
]
