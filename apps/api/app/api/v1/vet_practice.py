"""Veterinary practice MVP dashboard endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.provisioning.vet_manifest import get_manifest
from app.services.vet_practice_dashboard import build_vet_practice_dashboard
from app.services.workspace_registry import get_workspace_detail

router = APIRouter()


@router.get("/dashboard")
def get_vet_practice_dashboard(
    variant: Optional[str] = Query(None, description="Vet manifest variant"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Return the tenant-scoped veterinary MVP dashboard.

    Default is the Angelo / GP-practice file-first cut. Unknown variants
    return a controlled 400 instead of leaking a KeyError traceback.
    """
    detail = get_workspace_detail(
        db,
        current_user.tenant_id,
        "vet-practice",
        user_id=current_user.id,
        include_widgets=False,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    install = detail["descriptor"].get("install") or {}
    config = install.get("config") or {}
    installed_variant = config.get("fleet_variant") or "gp_full"
    requested_variant = variant or installed_variant

    try:
        get_manifest(requested_variant)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if requested_variant != installed_variant:
        raise HTTPException(
            status_code=400,
            detail=f"Variant {requested_variant} is not installed for this tenant",
        )
    return build_vet_practice_dashboard(
        db,
        current_user.tenant_id,
        variant=requested_variant,
    )
