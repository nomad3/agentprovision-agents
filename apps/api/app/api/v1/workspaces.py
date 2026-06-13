"""Tenant-scoped workspace pack endpoints."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.workspace_registry import (
    disable_workspace_install,
    get_workspace_detail,
    get_workspace_pack,
    get_workspace_widget,
    install_workspace_pack,
    list_catalog,
    list_enabled_workspaces,
    update_workspace_install,
)

router = APIRouter()


class WorkspaceInstallRequest(BaseModel):
    display_order: Optional[int] = Field(None, ge=0)
    pinned: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)
    status: str = Field("enabled", pattern="^(enabled|disabled)$")
    reason: Optional[str] = None


class WorkspaceInstallUpdateRequest(BaseModel):
    status: Optional[str] = Field(None, pattern="^(enabled|disabled)$")
    display_order: Optional[int] = Field(None, ge=0)
    pinned: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


def _require_workspace_manager(user: User) -> None:
    # There is no tenant-admin role model yet. For the native-pack MVP,
    # management is platform-superuser only; provisioning uses the internal
    # route and regular tenant users can view only their installed packs.
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace pack management requires a superuser",
        )


@router.get("")
def list_workspaces(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Return lightweight descriptors enabled for the current tenant."""
    return {
        "workspaces": list_enabled_workspaces(
            db,
            current_user.tenant_id,
            user_id=current_user.id,
        )
    }


@router.get("/catalog")
def catalog_workspaces(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Return native packs available for this tenant to install."""
    packs = list_catalog(db, current_user.tenant_id, user_id=current_user.id)
    return {
        "packs": [
            {
                **pack,
                "can_install": bool(current_user.is_superuser),
            }
            for pack in packs
        ]
    }


@router.get("/{slug}")
def get_workspace(
    slug: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    detail = get_workspace_detail(
        db,
        current_user.tenant_id,
        slug,
        user_id=current_user.id,
        include_widgets=True,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return detail


@router.get("/{slug}/widgets/{widget_key}")
def get_widget(
    slug: str,
    widget_key: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    payload = get_workspace_widget(
        db,
        current_user.tenant_id,
        slug,
        widget_key,
        user_id=current_user.id,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return payload


@router.post("/{slug}/install")
def install_workspace(
    slug: str,
    payload: WorkspaceInstallRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    _require_workspace_manager(current_user)
    if get_workspace_pack(slug) is None:
        raise HTTPException(status_code=404, detail="Workspace pack not found")
    try:
        install = install_workspace_pack(
            db,
            current_user.tenant_id,
            slug,
            actor_user_id=current_user.id,
            display_order=payload.display_order,
            pinned=payload.pinned,
            config=payload.config,
            status=payload.status,
            reason=payload.reason,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "workspace": get_workspace_detail(
            db,
            current_user.tenant_id,
            slug,
            user_id=current_user.id,
            include_widgets=False,
        ),
        "install_id": str(install.id),
    }


@router.patch("/{slug}/install")
def update_workspace(
    slug: str,
    payload: WorkspaceInstallUpdateRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    _require_workspace_manager(current_user)
    try:
        install = update_workspace_install(
            db,
            current_user.tenant_id,
            slug,
            actor_user_id=current_user.id,
            status=payload.status,
            display_order=payload.display_order,
            pinned=payload.pinned,
            config=payload.config,
            reason=payload.reason,
        )
        if install is None:
            raise HTTPException(status_code=404, detail="Workspace install not found")
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "workspace": get_workspace_detail(
            db,
            current_user.tenant_id,
            slug,
            user_id=current_user.id,
            include_widgets=False,
        )
    }


@router.delete("/{slug}/install")
def disable_workspace(
    slug: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    _require_workspace_manager(current_user)
    install = disable_workspace_install(
        db,
        current_user.tenant_id,
        slug,
        actor_user_id=current_user.id,
        reason="Disabled from workspace management API",
    )
    if install is None:
        raise HTTPException(status_code=404, detail="Workspace install not found")
    db.commit()
    return {"status": "disabled", "workspace_slug": slug}
