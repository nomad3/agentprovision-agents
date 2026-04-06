"""Sales module: inbound lead capture webhook.

Pipeline queries, lead listing, and stage updates are handled via existing
MCP tools (get_pipeline_summary, find_entities, update_pipeline_stage).
This module only adds endpoints that have no MCP equivalent.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.api import deps
from app.models import User
from app.services.knowledge import knowledge_service

router = APIRouter(prefix="/sales", tags=["sales"])

limiter = Limiter(key_func=get_remote_address)


class InboundLeadCreate(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = "web_form"  # web_form, email, whatsapp, workshop


class LeadResponse(BaseModel):
    id: str
    name: str
    company: Optional[str] = None
    email: Optional[str] = None
    pipeline_stage: str
    created_at: str


def _company_from_email(email: str) -> Optional[str]:
    """Infer company name from email domain."""
    if "@" not in email:
        return None
    domain = email.split("@")[-1].split(".")[0]
    return domain.title() or None


_SOURCE_MAP = {
    "email": "inbound_email",
    "inbound_email": "inbound_email",
    "email_to_lead": "inbound_email",
    "whatsapp": "inbound_whatsapp",
    "whatsapp_to_lead": "inbound_whatsapp",
    "workshop": "workshop",
}


@router.post("/inbound", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def capture_inbound_lead(
    request: Request,
    req: InboundLeadCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Capture an inbound lead from web form, email, WhatsApp, or workshop.

    This is the only endpoint here — pipeline views, lead listing, and stage
    updates all go through MCP tools (get_pipeline_summary, find_entities,
    update_pipeline_stage) so Luna can call them directly without a separate
    API layer.
    """
    company = req.company or (
        _company_from_email(req.email) if req.email else None
    )
    source = _SOURCE_MAP.get(req.source or "", "web_form")

    try:
        lead = knowledge_service.create_entity(
            db=db,
            tenant_id=current_user.tenant_id,
            name=req.name,
            entity_type="person",
            category="lead",
            description=(
                f"Inbound lead via {source}."
                + (f" Company: {company}." if company else "")
                + (f" Message: {req.message}" if req.message else "")
            ),
            properties={
                "email": req.email,
                "company": company,
                "source": source,
                "pipeline_stage": "prospect",
                "inbound_message": req.message,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create lead: {e}")

    return LeadResponse(
        id=str(lead.id),
        name=lead.name,
        company=company,
        email=req.email,
        pipeline_stage="prospect",
        created_at=lead.created_at.isoformat(),
    )
