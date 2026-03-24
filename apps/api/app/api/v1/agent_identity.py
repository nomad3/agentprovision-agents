"""Tenant-scoped agent identity profile API endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.agent_identity_profile import (
    AgentIdentityProfileCreate,
    AgentIdentityProfileInDB,
    AgentIdentityProfileUpdate,
)
from app.services import agent_identity_service

router = APIRouter()


@router.get("", response_model=List[AgentIdentityProfileInDB])
def list_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all agent identity profiles for the current tenant."""
    return agent_identity_service.list_profiles(db, current_user.tenant_id)


@router.get("/{agent_slug}", response_model=AgentIdentityProfileInDB)
def get_profile(
    agent_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get or bootstrap an identity profile for an agent."""
    return agent_identity_service.get_or_create_profile(
        db, current_user.tenant_id, agent_slug
    )


@router.put("", response_model=AgentIdentityProfileInDB)
def upsert_profile(
    profile_in: AgentIdentityProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create or fully replace an agent identity profile."""
    return agent_identity_service.upsert_profile(
        db, current_user.tenant_id, profile_in
    )


@router.patch("/{agent_slug}", response_model=AgentIdentityProfileInDB)
def update_profile(
    agent_slug: str,
    profile_in: AgentIdentityProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partially update an agent identity profile."""
    profile = agent_identity_service.update_profile(
        db, current_user.tenant_id, agent_slug, profile_in
    )
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity profile for '{agent_slug}' not found",
        )
    return profile


@router.delete("/{agent_slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    agent_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an agent identity profile."""
    deleted = agent_identity_service.delete_profile(
        db, current_user.tenant_id, agent_slug
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity profile for '{agent_slug}' not found",
        )
    return None
