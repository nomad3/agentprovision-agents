"""Tenant onboarding state endpoints.

Drives the auto-trigger behaviour of `ap quickstart` (CLI) and the web
`/onboarding/*` route guard. The CLI calls `GET /onboarding/status`
right after a successful `ap login`; if `onboarded` is False and
`deferred` is False, the CLI auto-launches the wedge picker. The web
SPA does the same check on dashboard mount and redirects to
`/onboarding/*` until the tenant completes (or skips).

Design: docs/plans/2026-05-11-ap-quickstart-design.md §2.1 + §7.0.

Auth: all three endpoints are user-scoped (Bearer JWT). No internal-
key variant — onboarding state mutation should always be tied to a
real user action, never a worker-side write.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.tenant import Tenant
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── response shapes ─────────────────────────────────────────────────


class OnboardingStatus(BaseModel):
    """Current onboarding state for the caller's tenant.

    `recommended_channel` is server-side intelligence — for now a
    static default; later iterations will inspect email domain,
    detected integrations, and recent activity to bias the picker.
    The CLI/web use it to highlight one row in the wedge picker; the
    user is always free to override.
    """

    onboarded: bool
    deferred: bool
    onboarded_at: Optional[datetime] = None
    onboarding_deferred_at: Optional[datetime] = None
    onboarding_source: Optional[str] = None
    recommended_channel: Literal[
        "claude_code",
        "codex",
        "gemini_cli",
        "copilot_cli",
        "opencode",
        "github_cli",
        "gmail",
        "slack",
        "whatsapp",
    ] = Field(default="gmail")
    detected_signals: Dict[str, Any] = Field(default_factory=dict)


class CompleteBody(BaseModel):
    """Optional payload on POST /onboarding/complete.

    `source` records which surface drove the completion (CLI vs web)
    for audit — no business logic keys off it. Defaults to 'cli'
    because that's the surface that should land first; the web SPA
    will pass 'web' explicitly when PR-Q6 ships.
    """

    source: Literal["cli", "web"] = "cli"


# ── routes ─────────────────────────────────────────────────────────


def _tenant_for(user: User, db: Session) -> Tenant:
    """Fetch the caller's tenant or 404. Centralised because every
    endpoint here needs the same lookup with the same error shape."""
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    if tenant is None:
        # Should never fire — JWT issuance binds tenant_id — but guard
        # so a manual JWT with a stale tenant doesn't 500 the endpoint.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


@router.get("/onboarding/status", response_model=OnboardingStatus)
def get_onboarding_status(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> OnboardingStatus:
    """Return whether the caller's tenant has completed onboarding.

    The CLI calls this after `ap login` and uses it to decide whether
    to auto-launch `ap quickstart`. The web SPA calls this on first
    dashboard mount.
    """
    tenant = _tenant_for(current_user, db)

    # Recommendation logic kept inline + minimal for PR-Q0. PR-Q3+
    # extends this with real signal (email-domain probing, prior
    # integration credentials, etc). Defaulting to gmail because it's
    # the universal non-dev wedge — a dev who picks one of the AI-CLI
    # wedges will override anyway.
    recommended: str = "gmail"
    detected: Dict[str, Any] = {}

    return OnboardingStatus(
        onboarded=tenant.onboarded_at is not None,
        deferred=tenant.onboarding_deferred_at is not None,
        onboarded_at=tenant.onboarded_at,
        onboarding_deferred_at=tenant.onboarding_deferred_at,
        onboarding_source=tenant.onboarding_source,
        recommended_channel=recommended,  # type: ignore[arg-type]
        detected_signals=detected,
    )


@router.post("/onboarding/defer", status_code=status.HTTP_204_NO_CONTENT)
def defer_onboarding(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> None:
    """Mark onboarding as 'skipped for now' — suppresses the next
    auto-trigger but does not block explicit `ap quickstart` or a
    manual visit to `/onboarding`.

    Idempotent: setting `onboarding_deferred_at` again just refreshes
    the timestamp. We don't error on a tenant that's already
    onboarded — `--force` re-running quickstart will hit this code
    path too.
    """
    tenant = _tenant_for(current_user, db)
    tenant.onboarding_deferred_at = datetime.utcnow()
    db.add(tenant)
    db.commit()
    logger.info(
        "onboarding deferred: tenant=%s user=%s",
        str(tenant.id)[:8],
        str(current_user.id)[:8],
    )


@router.post("/onboarding/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_onboarding(
    body: CompleteBody = CompleteBody(),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> None:
    """Mark onboarding as complete. Idempotent — re-completing does
    not reset the timestamp (preserves the original completion time
    for audit), but updates `onboarding_source` if a different
    surface re-completes (rare; happens if a user re-runs quickstart
    after also using the web flow).
    """
    tenant = _tenant_for(current_user, db)
    if tenant.onboarded_at is None:
        tenant.onboarded_at = datetime.utcnow()
    # Always refresh source — last surface to complete wins. Audit
    # log captures the full history via the platform's existing
    # `memory_activities` audit pattern at the caller layer; this
    # column is just the cached most-recent value.
    tenant.onboarding_source = body.source
    db.add(tenant)
    db.commit()
    logger.info(
        "onboarding completed: tenant=%s user=%s source=%s",
        str(tenant.id)[:8],
        str(current_user.id)[:8],
        body.source,
    )
