"""Veterinary practice MVP dashboard endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.provisioning.vet_manifest import get_manifest
from app.services.vet_practice_dashboard import build_vet_practice_dashboard

router = APIRouter()


@router.get("/dashboard")
def get_vet_practice_dashboard(
    variant: str = Query("gp_full", description="Vet manifest variant"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Return the tenant-scoped veterinary MVP dashboard.

    Default is the Angelo / GP-practice file-first cut. Unknown variants
    return a controlled 400 instead of leaking a KeyError traceback.
    """
    try:
        get_manifest(variant)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return build_vet_practice_dashboard(
        db,
        current_user.tenant_id,
        variant=variant,
    )
