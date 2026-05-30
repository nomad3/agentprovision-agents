"""Vet-practice provisioner — operator-run internal endpoint (v1).

Thin HTTP route that delegates to the single Python entrypoint
``provision_vet_practice`` (Alpha-CLI-kernel pattern: no business logic
in the route). v1 is operator-run only — reuses the ``verify_internal_key``
``X-Internal-Key`` + ``X-Tenant-Id`` dependency from the dynamic-workflows
internal routes (the canonical service-to-service auth shape).

Deferred (plan §1.1 / §9, out of scope here):
  - the ``alpha provision vet-practice <tenant>`` verb (operator UX) —
    a thin client over this same endpoint;
  - the self-serve register hook in ``create_user_with_tenant`` — blocked
    because ``TenantCreate`` is ``name``-only (no ``practice_type``); v1 is
    operator-run anyway, so the schema change + hook are a follow-up.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
# Reuse the canonical internal-key dep so there's one source of truth for
# the X-Internal-Key / X-Tenant-Id contract across internal routes.
from app.api.v1.dynamic_workflows import verify_internal_key
from app.services.provisioning.vet_practice import (
    VetPracticeProfile,
    provision_vet_practice,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class VetPracticeProvisionRequest(BaseModel):
    """Per-tenant binding for an operator-triggered provisioning run.

    The tenant comes from the ``X-Tenant-Id`` header (via
    ``verify_internal_key``), not the body, so an operator can't provision
    a tenant they didn't authenticate for."""

    practice_name: str = Field(..., description="e.g. 'BB Cardiology'")
    practice_type: str = Field("cardiology", description="cardiology|gp|multi_specialty")
    fleet_variant: str = Field("cardiology_v1", description="manifest variant to apply")
    owner_user_id: Optional[uuid.UUID] = Field(
        None, description="owner of every seeded agent; falls back to tenant admin"
    )
    intake_mailbox: Optional[str] = Field(
        None, description="e.g. 'btcvetmobile@gmail.com'"
    )
    lead_clinician_name: Optional[str] = Field(
        None, description="e.g. 'Dr. Brett Boorstin'"
    )
    dry_run: bool = Field(
        False, description="return the plan without writing anything"
    )


@router.post("/vet-practice/internal")
def provision_vet_practice_internal(
    payload: VetPracticeProvisionRequest,
    db: Session = Depends(deps.get_db),
    tenant_id: uuid.UUID = Depends(verify_internal_key),
):
    """Operator-run: idempotently provision a vet practice on the tenant
    named by ``X-Tenant-Id``. Returns the per-object created/updated/
    unchanged (or planned, on dry-run) summary."""
    profile = VetPracticeProfile(
        practice_name=payload.practice_name,
        practice_type=payload.practice_type,
        owner_user_id=payload.owner_user_id,
        intake_mailbox=payload.intake_mailbox,
        lead_clinician_name=payload.lead_clinician_name,
        fleet_variant=payload.fleet_variant,
    )
    logger.info(
        "provision/vet-practice/internal tenant=%s variant=%s dry_run=%s",
        tenant_id, payload.fleet_variant, payload.dry_run,
    )
    return provision_vet_practice(
        db, tenant_id, profile=profile, dry_run=payload.dry_run
    )
