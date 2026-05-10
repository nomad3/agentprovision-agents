"""api-side shadow-mode wiring — Phase 2 cutover gate.

Wraps the canonical ``cli_orchestrator.shadow`` plumbing for the chat
hot path. Two responsibilities:

  1. Read the per-tenant flags from ``tenant_features``:
     ``use_resilient_executor`` (hard cutover gate) and
     ``shadow_mode_real_dispatch`` (sub-flag for stubbed-vs-real shadow).

  2. Provide ``maybe_run_shadow(...)`` — fired AFTER the legacy chain
     walk returns. When ``use_resilient_executor`` is FALSE (default
     for the cutover), runs the new path in shadow against a stubbed
     adapter that replays the legacy outcome (cheap, no real dispatch)
     unless ``shadow_mode_real_dispatch`` is TRUE (real adapter
     dispatch — ~2x cost; only ~48h on internal tenant for validation).

Wrapped in try/except — the shadow path can NEVER poison the response.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.executor import ResilientExecutor
from cli_orchestrator.shadow import (
    LegacyOutcome,
    compute_legacy_outcome,
    run_shadow_comparison,
)
from cli_orchestrator.status import Status

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Flag access — never raises; missing tenant_features row → defaults FALSE
# --------------------------------------------------------------------------

def read_flags(db: Session, tenant_id) -> tuple[bool, bool]:
    """Read (use_resilient_executor, shadow_mode_real_dispatch) for tenant.

    Returns (False, False) on any DB error or missing row. Defensive —
    the chat hot path must keep running even if tenant_features is
    momentarily unavailable.
    """
    try:
        from app.models.tenant_features import TenantFeatures

        row = (
            db.query(TenantFeatures)
            .filter(TenantFeatures.tenant_id == tenant_id)
            .first()
        )
        # ``isinstance`` rather than ``is None`` — defends against test
        # MagicMock dbs whose .first() returns a truthy MagicMock that
        # would otherwise turn flag=False into flag=True via
        # bool(getattr(MagicMock, ...)).
        if not isinstance(row, TenantFeatures):
            return False, False
        use = row.use_resilient_executor
        real = row.shadow_mode_real_dispatch
        # Coerce to plain bool — sqlalchemy can hand back NULL on legacy
        # rows pre-migration; the model has nullable=False but
        # defensive coercion keeps None-safety.
        return (bool(use) if use is not None else False,
                bool(real) if real is not None else False)
    except Exception:  # noqa: BLE001
        logger.debug("read_flags failed — defaulting to (False, False)", exc_info=True)
        return False, False


# --------------------------------------------------------------------------
# Replay adapter — used when shadow_mode_real_dispatch is FALSE
# --------------------------------------------------------------------------

class _ReplayAdapter:
    """Stub adapter that replays the legacy outcome — no real dispatch.

    The cheap mass-deployable shadow path uses this so we can exercise
    the executor's metrics + classifier surface across all production
    traffic without paying for a second dispatch.
    """

    def __init__(self, name: str, legacy_outcome: LegacyOutcome, response_text: str):
        self.name = name
        self._legacy = legacy_outcome
        self._response_text = response_text

    def preflight(self, req):
        return PreflightResult.succeed()

    def run(self, req):
        if self._legacy.final_status is Status.EXECUTION_SUCCEEDED:
            return ExecutionResult(
                status=Status.EXECUTION_SUCCEEDED,
                platform=self.name,
                response_text=self._response_text,
                attempt_count=1,
            )
        return ExecutionResult(
            status=self._legacy.final_status,
            platform=self.name,
            error_message=f"replay: legacy {self._legacy.final_status.value}",
            attempt_count=1,
        )

    def classify_error(self, stderr, exit_code, exc):
        from cli_orchestrator.classifier import classify
        return classify(stderr, exit_code, exc)


# --------------------------------------------------------------------------
# Public entry — fired from cli_session_manager.run_agent_session
# --------------------------------------------------------------------------

def maybe_run_shadow(
    *,
    db: Session,
    tenant_id,
    platform: str,
    response_text: Optional[str],
    metadata: Dict[str, Any],
) -> None:
    """Fire shadow comparison if the tenant has shadow mode enabled.

    Called AFTER the legacy run_agent_session returns. Wrapped in a
    broad try/except — never raises, never modifies the response or
    metadata.
    """
    try:
        use_resilient, real_dispatch = read_flags(db, tenant_id)
        # When the resilient path is ON we don't shadow — the resilient
        # path IS the path. Shadow only runs alongside the legacy path.
        if use_resilient:
            return

        legacy_outcome = compute_legacy_outcome(
            response_text=response_text or "",
            metadata=metadata or {},
        )

        # Build a one-element chain reflecting the platform that
        # actually served (or the requested platform when nothing did).
        served_platform = legacy_outcome.final_platform or platform
        chain = (served_platform,)

        if real_dispatch:
            # Real-dispatch shadow — only used during ~48h internal
            # tenant validation. We don't construct a real adapter here
            # in apps/api because that would couple the api process to
            # the worker-side adapters; the real-dispatch shadow path
            # uses the api-side TemporalActivityAdapter instead.
            from cli_orchestrator.adapters.temporal_activity import TemporalActivityAdapter

            adapter = TemporalActivityAdapter(platform=served_platform)
            executor = ResilientExecutor(adapters={served_platform: adapter})
        else:
            # Cheap stubbed shadow — replay the legacy outcome through
            # the executor so we exercise the executor's metrics +
            # classifier surface without burning 2x cost.
            adapter = _ReplayAdapter(
                name=served_platform,
                legacy_outcome=legacy_outcome,
                response_text=response_text or "",
            )
            executor = ResilientExecutor(adapters={served_platform: adapter})

        req = ExecutionRequest(
            chain=chain,
            platform=served_platform,
            payload={"message": (metadata or {}).get("message", "")},
            tenant_id=str(tenant_id),
            run_id=str(uuid.uuid4()),
        )
        run_shadow_comparison(req, legacy_outcome, executor)
    except BaseException:  # noqa: BLE001  shadow MUST NOT poison response
        logger.debug("maybe_run_shadow swallowed exception", exc_info=True)


__all__ = ["read_flags", "maybe_run_shadow"]
