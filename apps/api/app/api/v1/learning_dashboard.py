"""Learning dashboard API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.services import learning_dashboard_service

router = APIRouter()


@router.get("/improvements")
def get_policy_improvements(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Show which policies improved — promoted candidates with measured impact."""
    return learning_dashboard_service.get_policy_improvement_summary(db, current_user.tenant_id)


@router.get("/stalls")
def get_learning_stalls(
    stale_days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Show where learning is stalled — decision points with no recent improvement."""
    return learning_dashboard_service.get_learning_stalls(db, current_user.tenant_id, stale_days=stale_days)


@router.get("/explore-exploit")
def get_explore_exploit_balance(
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Surface explore/exploit balance by decision point and platform."""
    return learning_dashboard_service.get_explore_exploit_balance(db, current_user.tenant_id, days=days)


@router.get("/rollouts")
def get_rollout_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Show all active and recent rollout experiments."""
    return learning_dashboard_service.get_rollout_status(db, current_user.tenant_id)
