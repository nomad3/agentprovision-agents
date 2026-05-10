"""ResilientExecutor — design §3 + §3.1 + §3.2 + §4.

Sync entry point that walks the CLI chain, applies preflight + retry +
fallback policy + redaction, emits Prometheus metrics, and ALWAYS
returns ``ExecutionResult``. Never raises.

Phase 2 scope (api-side hot path):

  - ``execute(req: ExecutionRequest) -> ExecutionResult``
  - §3.1 recursion gate: refuses any request where
    ``len(parent_chain) >= MAX_FALLBACK_DEPTH`` OR the dispatching
    agent appears twice in ``parent_chain``. Enforced BEFORE any
    preflight or adapter call (the gate, not a runtime check).
  - For each platform in ``req.chain`` it calls ``adapter.preflight`` —
    on a non-OK preflight the executor synthesises an ExecutionResult
    with the preflight Status, runs the policy, and either falls back
    or stops. Preflight does NOT increment ``attempt_count``.
  - For each in-policy retry/fallback it calls ``adapter.run`` and
    feeds the result into ``policy.decide(...)``. Retry: same
    platform, attempt += 1. Fallback: walk to next platform in chain,
    reset attempt to 1 on the new platform.
  - §3.2 R1 amendment: NEEDS_AUTH / WORKSPACE_UNTRUSTED / API_DISABLED
    stop the chain UNLESS the next platform is ``opencode``, in which
    case the chain falls through AND the actionable_hint is preserved
    on the eventual successful ExecutionResult as a non-blocking
    annotation.
  - Prometheus metrics emitted per terminal result (best-effort —
    metric write failures are swallowed so the hot path never
    poisons on a metric-backend outage).

Phase 3+ will extend this with:
  - ExecutionMetadata mirror to RLExperience
  - Heartbeat-aware adapter dispatch when called from inside a
    Temporal activity (today: api-side hot path only)
  - per-adapter cooldown bookkeeping (today: handled in the chain
    walker via existing cli_platform_resolver.mark_cooldown call sites)
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Mapping, Optional

from .adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
    ProviderAdapter,
)
from .policy import (
    MAX_FALLBACK_DEPTH,
    FallbackDecision,
    decide,
)
from .redaction import redact
from .status import Status

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Prometheus metrics — best-effort; missing prometheus_client is non-fatal
# --------------------------------------------------------------------------

try:
    from prometheus_client import Counter, Histogram

    _STATUS_TOTAL = Counter(
        "cli_orchestrator_status_total",
        "ResilientExecutor terminal status counter",
        ["tenant_id", "decision_point", "platform", "status"],
    )
    _DURATION_MS = Histogram(
        "cli_orchestrator_duration_ms",
        "ResilientExecutor end-to-end duration in milliseconds",
        ["tenant_id", "decision_point", "platform", "status"],
    )
    _FALLBACK_DEPTH = Histogram(
        "cli_orchestrator_fallback_depth",
        "Depth of platform chain walked",
        ["tenant_id", "decision_point"],
    )
    _ATTEMPT_COUNT = Histogram(
        "cli_orchestrator_attempt_count",
        "Total attempts per ResilientExecutor.execute",
        ["tenant_id", "decision_point", "status"],
    )
    # Phase 3 — design §6 ship gate (warm-state p95 ≤ 60ms).
    # Adapters time their preflight() bodies and emit observations here;
    # the executor itself does NOT time preflight (the executor only
    # consumes the result). Module-level so adapters in any process can
    # reuse the same Histogram instance.
    _PREFLIGHT_DURATION_MS = Histogram(
        "cli_orchestrator_preflight_duration_ms",
        "Per-helper preflight duration in milliseconds",
        ["platform", "helper"],
    )
    _METRICS_OK = True
except ImportError:
    _STATUS_TOTAL = _DURATION_MS = _FALLBACK_DEPTH = _ATTEMPT_COUNT = None  # type: ignore[assignment]
    _PREFLIGHT_DURATION_MS = None  # type: ignore[assignment]
    _METRICS_OK = False


def _emit_metrics(
    *,
    result: ExecutionResult,
    tenant_id: str,
    decision_point: str,
    duration_ms: float,
) -> None:
    """Best-effort Prometheus emit; never raises."""
    if not _METRICS_OK:
        return
    try:
        _STATUS_TOTAL.labels(  # type: ignore[union-attr]
            tenant_id=tenant_id,
            decision_point=decision_point,
            platform=result.platform,
            status=result.status.value,
        ).inc()
        _DURATION_MS.labels(  # type: ignore[union-attr]
            tenant_id=tenant_id,
            decision_point=decision_point,
            platform=result.platform,
            status=result.status.value,
        ).observe(duration_ms)
        _FALLBACK_DEPTH.labels(  # type: ignore[union-attr]
            tenant_id=tenant_id,
            decision_point=decision_point,
        ).observe(len(result.platform_attempted))
        _ATTEMPT_COUNT.labels(  # type: ignore[union-attr]
            tenant_id=tenant_id,
            decision_point=decision_point,
            status=result.status.value,
        ).observe(result.attempt_count)
    except Exception:  # noqa: BLE001
        # Metric backend hiccup — the chat hot path must continue.
        logger.debug("metric emission failed", exc_info=True)


# --------------------------------------------------------------------------
# ResilientExecutor
# --------------------------------------------------------------------------

# Hard ceilings on per-platform attempt budgets — keeps the loop bounded
# even when a misconfigured adapter keeps returning RETRY-eligible
# statuses indefinitely.
_PER_PLATFORM_ATTEMPT_CAP = 2


class ResilientExecutor:
    """Walks ``req.chain``, applies policy.decide, emits metrics, returns
    ``ExecutionResult``.

    Args:
        adapters: Mapping ``platform_name -> ProviderAdapter``. The
            executor reads ``req.chain`` and looks up each platform
            here. A platform present in the chain but missing from
            adapters synthesises a ``PROVIDER_UNAVAILABLE`` result and
            falls through to the next platform.
        decision_point: Label used for Prometheus metrics
            (chat_response / code_task / etc.).

    The constructor takes adapters by mapping rather than per-call
    discovery so callers can wire the executor once at process start
    and drive many requests through the same instance. Tests inject
    stub adapters keyed by platform name.
    """

    def __init__(
        self,
        adapters: Mapping[str, ProviderAdapter],
        *,
        decision_point: str = "chat_response",
    ) -> None:
        self._adapters = dict(adapters)
        self._decision_point = decision_point

    # ── Public entry ─────────────────────────────────────────────────

    def execute(self, req: ExecutionRequest) -> ExecutionResult:
        run_id = req.run_id or str(uuid.uuid4())
        tenant_id = req.tenant_id or "unknown"
        t0 = time.monotonic()

        # ── §3.1 recursion gate — BEFORE any preflight / adapter call ──
        gate_result = self._enforce_recursion_gate(req, run_id)
        if gate_result is not None:
            duration_ms = (time.monotonic() - t0) * 1000.0
            _emit_metrics(
                result=gate_result,
                tenant_id=tenant_id,
                decision_point=self._decision_point,
                duration_ms=duration_ms,
            )
            return gate_result

        # ── chain walk ────────────────────────────────────────────────
        chain = list(req.chain)
        platform_attempted: list[str] = []
        last_result: Optional[ExecutionResult] = None
        # Carry a non-blocking actionable_hint when §3.2 fallthrough
        # fires — surfaced on the eventual successful result.
        carry_hint: Optional[str] = None

        chain_index = 0
        while chain_index < len(chain):
            platform = chain[chain_index]
            adapter = self._adapters.get(platform)
            if adapter is None:
                # Synthesise a PROVIDER_UNAVAILABLE result and let the
                # policy decide — falls through to next platform.
                synthetic = ExecutionResult(
                    status=Status.PROVIDER_UNAVAILABLE,
                    platform=platform,
                    error_message=f"no adapter registered for {platform}",
                    platform_attempted=[platform],
                    attempt_count=0,
                    run_id=run_id,
                )
                platform_attempted.append(platform)
                last_result = synthetic
                # Continue to next platform, no policy needed for this
                # synthetic case (a missing adapter is a config issue,
                # not a transient failure).
                chain_index += 1
                continue

            # ── preflight ─────────────────────────────────────────────
            try:
                preflight = adapter.preflight(req)
            except BaseException as exc:  # noqa: BLE001
                # An adapter that raises in preflight is broken — treat
                # it as PROVIDER_UNAVAILABLE for chain-walking purposes.
                preflight = PreflightResult.fail(
                    Status.PROVIDER_UNAVAILABLE,
                    f"preflight raised {exc.__class__.__name__}",
                )

            if not preflight.ok:
                # Preflight failure does NOT increment attempt_count.
                synthetic = ExecutionResult(
                    status=preflight.status or Status.PROVIDER_UNAVAILABLE,
                    platform=platform,
                    error_message=redact(preflight.reason),
                    platform_attempted=[platform],
                    attempt_count=0,
                    run_id=run_id,
                )
                platform_attempted.append(platform)
                last_result = synthetic
                next_platform = chain[chain_index + 1] if chain_index + 1 < len(chain) else None
                decision = decide(
                    synthetic.status,
                    attempt=1,
                    parent_chain=req.parent_chain,
                    platform=platform,
                    next_platform=next_platform,
                )
                if decision.action == "stop":
                    return self._finalise_stop(
                        synthetic, decision, platform_attempted, t0,
                        tenant_id, run_id,
                    )
                if decision.actionable_hint and decision.action == "fallback":
                    # §3.2 — preserve the hint as a non-blocking annotation.
                    carry_hint = decision.actionable_hint
                # action == fallback or retry; preflight isn't retryable
                chain_index += 1
                continue

            # ── adapter.run with bounded retry ───────────────────────
            attempt = 1
            while True:
                try:
                    result = adapter.run(req)
                except BaseException as exc:  # noqa: BLE001
                    # Adapters MUST NOT raise per the contract — but
                    # defensive: treat as classified failure here.
                    status = adapter.classify_error(stderr=None, exit_code=None, exc=exc)
                    err = redact(str(exc) or exc.__class__.__name__)
                    result = ExecutionResult(
                        status=status,
                        platform=platform,
                        response_text="",
                        error_message=err,
                        stderr_summary=err,
                        platform_attempted=[platform],
                        attempt_count=attempt,
                        run_id=run_id,
                    )

                if platform not in platform_attempted:
                    platform_attempted.append(platform)
                last_result = result

                # Success → finalise
                if result.status is Status.EXECUTION_SUCCEEDED:
                    return self._finalise_success(
                        result, platform_attempted, t0,
                        tenant_id, run_id, carry_hint,
                    )

                next_platform = chain[chain_index + 1] if chain_index + 1 < len(chain) else None
                decision = decide(
                    result.status,
                    attempt=attempt,
                    parent_chain=req.parent_chain,
                    platform=platform,
                    next_platform=next_platform,
                )

                if decision.action == "stop":
                    return self._finalise_stop(
                        result, decision, platform_attempted, t0,
                        tenant_id, run_id,
                    )
                if decision.action == "retry" and attempt < _PER_PLATFORM_ATTEMPT_CAP:
                    attempt += 1
                    # Optional small backoff for retryable network failures —
                    # the policy already ruled "retry once" so we mirror that.
                    if result.status is Status.RETRYABLE_NETWORK_FAILURE:
                        time.sleep(0.25)
                    continue
                # decision.action == "fallback" (or retry exhausted);
                # the §3.2 fallthrough hint, if any, lives on the
                # decision and we stash it for the eventual success.
                if decision.actionable_hint and decision.action == "fallback":
                    carry_hint = decision.actionable_hint
                break  # walk to next platform in the chain

            chain_index += 1

        # ── chain exhausted ──────────────────────────────────────────
        if last_result is None:
            # Empty chain — configuration error.
            terminal = ExecutionResult(
                status=Status.PROVIDER_UNAVAILABLE,
                platform="(none)",
                error_message="empty chain",
                platform_attempted=[],
                attempt_count=0,
                run_id=run_id,
            )
        else:
            # Use the last result's status as the terminal outcome,
            # but stamp the full platform_attempted list.
            terminal = ExecutionResult(
                status=last_result.status,
                platform=last_result.platform,
                response_text="",
                error_message=last_result.error_message or "all CLI fallbacks failed",
                stdout_summary=last_result.stdout_summary,
                stderr_summary=last_result.stderr_summary,
                exit_code=last_result.exit_code,
                platform_attempted=platform_attempted,
                attempt_count=sum(1 for _ in platform_attempted),
                actionable_hint=carry_hint or last_result.actionable_hint,
                workflow_id=last_result.workflow_id,
                activity_id=last_result.activity_id,
                metadata=dict(last_result.metadata),
                run_id=run_id,
            )

        duration_ms = (time.monotonic() - t0) * 1000.0
        _emit_metrics(
            result=terminal,
            tenant_id=tenant_id,
            decision_point=self._decision_point,
            duration_ms=duration_ms,
        )
        return terminal

    # ── Recursion gate ───────────────────────────────────────────────

    def _enforce_recursion_gate(
        self,
        req: ExecutionRequest,
        run_id: str,
    ) -> Optional[ExecutionResult]:
        """§3.1 gate. Returns a refusal ExecutionResult on violation,
        else ``None`` (proceed)."""
        parent_chain = tuple(req.parent_chain or ())
        if len(parent_chain) >= MAX_FALLBACK_DEPTH:
            logger.warning(
                "ResilientExecutor refused request — depth %d >= %d",
                len(parent_chain), MAX_FALLBACK_DEPTH,
            )
            return ExecutionResult(
                status=Status.PROVIDER_UNAVAILABLE,
                platform=(req.chain[0] if req.chain else "(none)"),
                error_message=(
                    f"fallback chain exhausted (depth {len(parent_chain)})"
                ),
                actionable_hint="cli.errors.recursion_depth_exceeded",
                platform_attempted=[],
                attempt_count=0,
                run_id=run_id,
            )
        # Cycle detection: if any agent-id appears twice in parent_chain
        # the lineage has a loop. We refuse rather than risk a fan-out.
        if len(parent_chain) != len(set(str(x) for x in parent_chain)):
            logger.warning(
                "ResilientExecutor refused request — cycle in parent_chain %r",
                parent_chain,
            )
            return ExecutionResult(
                status=Status.PROVIDER_UNAVAILABLE,
                platform=(req.chain[0] if req.chain else "(none)"),
                error_message="cycle detected in parent_chain",
                actionable_hint="cli.errors.recursion_cycle",
                platform_attempted=[],
                attempt_count=0,
                run_id=run_id,
            )
        return None

    # ── Finalisers ───────────────────────────────────────────────────

    def _finalise_success(
        self,
        result: ExecutionResult,
        platform_attempted: list[str],
        t0: float,
        tenant_id: str,
        run_id: str,
        carry_hint: Optional[str],
    ) -> ExecutionResult:
        result.platform_attempted = list(platform_attempted)
        result.attempt_count = max(result.attempt_count, 1)
        if carry_hint and not result.actionable_hint:
            # §3.2 — preserve the upstream hint as non-blocking annotation.
            result.actionable_hint = carry_hint
        result.run_id = run_id
        duration_ms = (time.monotonic() - t0) * 1000.0
        _emit_metrics(
            result=result,
            tenant_id=tenant_id,
            decision_point=self._decision_point,
            duration_ms=duration_ms,
        )
        return result

    def _finalise_stop(
        self,
        result: ExecutionResult,
        decision: FallbackDecision,
        platform_attempted: list[str],
        t0: float,
        tenant_id: str,
        run_id: str,
    ) -> ExecutionResult:
        result.platform_attempted = list(platform_attempted)
        if decision.actionable_hint and not result.actionable_hint:
            result.actionable_hint = decision.actionable_hint
        if not result.error_message:
            result.error_message = decision.reason
        result.run_id = run_id
        duration_ms = (time.monotonic() - t0) * 1000.0
        _emit_metrics(
            result=result,
            tenant_id=tenant_id,
            decision_point=self._decision_point,
            duration_ms=duration_ms,
        )
        return result


__all__ = ["ResilientExecutor"]
