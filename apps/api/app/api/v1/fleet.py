"""Fleet endpoints — Luna OS podium boot snapshot + briefing.

`GET /fleet/snapshot` returns everything the spatial Podium scene needs in a
single round-trip. `GET /fleet/briefing` summarizes "what happened since
you last looked" for the morning overture / evening finale animations.

No new database tables. Pure read-only aggregation over existing models.
"""
from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.core.rate_limit import limiter
from app.models.user import User as UserModel
from app.services import briefing_service, fleet_snapshot_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/snapshot")
@limiter.limit("60/minute")
def get_fleet_snapshot(
    request: Request,
    *,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """Return the full podium boot payload for the current user's tenant."""
    return fleet_snapshot_service.build_snapshot(db, current_user.tenant_id)


@router.get("/briefing")
@limiter.limit("30/minute")
def get_fleet_briefing(
    request: Request,
    since: str | None = Query(default=None, description="ISO 8601 — defaults to 12h ago"),
    *,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """Return a compact briefing of activity since `since` (default last 12h).

    Used by the spatial podium's Movements zone to animate the morning
    overture (briefing on first podium visit of the day) and the evening
    finale (daily review on demand).
    """
    parsed_since = None
    if since:
        try:
            parsed_since = datetime.fromisoformat(since.replace("Z", "+00:00"))
            # Convert tz-aware → naive UTC to match service layer convention
            if parsed_since.tzinfo is not None:
                parsed_since = parsed_since.astimezone(parsed_since.tzinfo).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=422, detail="`since` must be ISO 8601")
    return briefing_service.build_briefing(db, current_user.tenant_id, since=parsed_since)
