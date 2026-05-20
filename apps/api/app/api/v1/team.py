"""Teamwork Engine — observability endpoints (Phase 1 PR B).

Read-only HTTP surface for the Social Protocol primitive. Mirrors the
shape of `app.api.v1.emotion`: thin FastAPI router, tenant-scoped via
`get_current_user`, returns JSON shapes the dashboard + alpha CLI can
consume.

Write paths (POST/amend) ship in Phase 1 PR C alongside the operator-
facing verbs.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.services.team_engine_io import (
    get_active_role,
    list_norms,
    list_role_contracts,
)

router = APIRouter()


# ── Roles ─────────────────────────────────────────────────────────────


@router.get("/team/roles")
def list_team_roles(
    agent_id: Optional[uuid.UUID] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all role contracts for the current tenant, optionally
    filtered to a single agent.

    Response shape:
        {
            "tenant_id": "<uuid>",
            "agent_id_filter": "<uuid>" | null,
            "contracts": [
                {role contract JSON, including the derive-on-read
                 `is_active_now` flag},
                ...
            ]
        }

    No foreign-tenant access path — the service-layer query filters by
    `tenant_id` from the JWT.
    """
    from datetime import datetime, timezone

    contracts = list_role_contracts(
        db,
        tenant_id=current_user.tenant_id,
        agent_id=agent_id,
    )
    now = datetime.now(timezone.utc)
    out = []
    for c in contracts:
        d = c.to_dict()
        d["is_active_now"] = c.is_active_at(now)
        out.append(d)
    return {
        "tenant_id": str(current_user.tenant_id),
        "agent_id_filter": str(agent_id) if agent_id else None,
        "contracts": out,
    }


@router.get("/team/roles/active")
def get_team_active_role(
    agent_id: uuid.UUID,
    scope: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the single currently-in-effect role contract for the
    given (agent, scope), or 404 if no contract applies.

    Used by the agent_router (eventually) to gate dispatch decisions
    against the typed role split.
    """
    contract = get_active_role(
        db,
        tenant_id=current_user.tenant_id,
        agent_id=agent_id,
        scope=scope,
    )
    if contract is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No active role contract for agent_id={agent_id} "
                f"scope={scope!r} in tenant {current_user.tenant_id}"
            ),
        )
    return contract.to_dict()


# ── Norms ─────────────────────────────────────────────────────────────


@router.get("/team/norms")
def list_team_norms(
    coalition_id: Optional[uuid.UUID] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all norms relevant to the current tenant, optionally
    scoped to a coalition. Includes BOTH the coalition-specific norms
    AND the tenant-wide defaults.

    Response shape:
        {
            "tenant_id": "<uuid>",
            "coalition_id_filter": "<uuid>" | null,
            "norms": [
                {norm JSON with derive-on-read `is_stale` flag},
                ...
            ]
        }
    """
    norms = list_norms(
        db,
        tenant_id=current_user.tenant_id,
        coalition_id=coalition_id,
    )
    out = []
    for n in norms:
        d = n.to_dict()
        d["is_stale"] = n.is_stale()
        out.append(d)
    return {
        "tenant_id": str(current_user.tenant_id),
        "coalition_id_filter": str(coalition_id) if coalition_id else None,
        "norms": out,
    }
