from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.db.safe_ops import safe_rollback
from app.models.user import User as UserModel
from app.schemas import user as user_schema

router = APIRouter()


class ProfileUpdate(BaseModel):
    """Allowed fields for self-service profile update.

    Email and tenant_id are deliberately not editable here — those go
    through admin / re-registration flows. Password change goes through
    the existing /password-recovery + /reset-password flow."""

    full_name: Optional[str] = None


@router.get("/me", response_model=user_schema.User)
def read_users_me(
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """Get current user."""
    return current_user


@router.put("/me", response_model=user_schema.User)
def update_users_me(
    payload: ProfileUpdate,
    *,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """Update self-editable fields on the current user.

    Today only `full_name`. Email + password go through dedicated flows."""
    try:
        if payload.full_name is not None:
            current_user.full_name = payload.full_name.strip() or None
        db.commit()
        db.refresh(current_user)
        return current_user
    except Exception:
        safe_rollback(db)
        raise HTTPException(status_code=500, detail="Could not update profile")


@router.get("", response_model=List[user_schema.User])
def list_tenant_users(
    *,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """List members of the current tenant.

    Any authenticated user can see who else is in their tenant — that's
    the same level of access already granted by the chat / agent /
    integration UI, where members are visible by virtue of being on the
    same workspace. Admin-only fields (is_superuser) are part of the
    schema; the UI decides what to show.
    """
    return (
        db.query(UserModel)
        .filter(UserModel.tenant_id == current_user.tenant_id)
        .order_by(UserModel.is_superuser.desc(), UserModel.email.asc())
        .all()
    )
