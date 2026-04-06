"""Sales module: lead pipeline management and inbound capture."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.models import User
from app.models.knowledge_entity import KnowledgeEntity
from app.services.knowledge import knowledge_service


def _verify_internal_key(x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key")):
    if x_internal_key not in (settings.API_INTERNAL_KEY, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")

router = APIRouter(prefix="/sales", tags=["sales"])

limiter = Limiter(key_func=get_remote_address)

# Pipeline stage ordering for display
STAGE_ORDER = ["prospect", "qualified", "proposal", "negotiation", "closed_won", "closed_lost", "unassigned"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class InboundLeadCreate(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = "web_form"


class LeadResponse(BaseModel):
    id: str
    name: str
    company: Optional[str] = None
    email: Optional[str] = None
    pipeline_stage: str
    score: Optional[float] = None
    deal_value: Optional[float] = None
    created_at: str


class StageUpdateRequest(BaseModel):
    stage: str
    reason: Optional[str] = None


class PipelineStageStats(BaseModel):
    stage: str
    count: int
    total_value: Optional[float] = None


class PipelineSummaryResponse(BaseModel):
    total_leads: int
    stages: List[PipelineStageStats]
    total_value: Optional[float] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _company_from_email(email: str) -> Optional[str]:
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


def _entity_to_lead_response(entity: KnowledgeEntity) -> LeadResponse:
    props = entity.properties or {}
    return LeadResponse(
        id=str(entity.id),
        name=entity.name,
        company=props.get("company"),
        email=props.get("email"),
        pipeline_stage=props.get("pipeline_stage", "prospect"),
        score=entity.score,
        deal_value=props.get("deal_value"),
        created_at=entity.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Pipeline summary (SQL-backed — fast and accurate)
# ---------------------------------------------------------------------------

@router.get("/pipeline", response_model=PipelineSummaryResponse)
def get_pipeline(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Get pipeline funnel: lead counts and total deal value per stage."""
    rows = db.execute(
        text("""
            SELECT
                COALESCE(properties->>'pipeline_stage', 'unassigned') AS stage,
                COUNT(*) AS cnt,
                SUM(CAST(NULLIF(properties->>'deal_value', '') AS FLOAT)) AS total_value
            FROM knowledge_entities
            WHERE tenant_id = :tid
              AND category = 'lead'
              AND deleted_at IS NULL
            GROUP BY stage
        """),
        {"tid": str(current_user.tenant_id)},
    ).fetchall()

    stage_map = {r.stage: r for r in rows}
    stages = []
    for s in STAGE_ORDER:
        if s in stage_map:
            stages.append(PipelineStageStats(
                stage=s,
                count=stage_map[s].cnt,
                total_value=stage_map[s].total_value,
            ))
    # Any stages not in our ordered list go last
    for r in rows:
        if r.stage not in STAGE_ORDER:
            stages.append(PipelineStageStats(stage=r.stage, count=r.cnt, total_value=r.total_value))

    total = sum(s.count for s in stages)
    total_value = sum(s.total_value or 0 for s in stages) or None

    return PipelineSummaryResponse(total_leads=total, stages=stages, total_value=total_value)


# ---------------------------------------------------------------------------
# Internal pipeline summary (called by MCP tool)
# ---------------------------------------------------------------------------

@router.get("/internal/pipeline-summary")
def get_pipeline_summary_internal(
    tenant_id: str = Query(...),
    category: str = Query(default="lead"),
    _auth: None = Depends(_verify_internal_key),
    db: Session = Depends(deps.get_db),
):
    """Internal endpoint for MCP get_pipeline_summary tool (SQL-backed)."""
    rows = db.execute(
        text("""
            SELECT
                COALESCE(properties->>'pipeline_stage', 'unassigned') AS stage,
                COUNT(*) AS cnt,
                SUM(CAST(NULLIF(properties->>'deal_value', '') AS FLOAT)) AS total_value
            FROM knowledge_entities
            WHERE tenant_id = :tid
              AND category = :cat
              AND deleted_at IS NULL
            GROUP BY stage
        """),
        {"tid": tenant_id, "cat": category},
    ).fetchall()

    total = sum(r.cnt for r in rows)
    stages = [{"stage": r.stage, "count": r.cnt, "total_value": r.total_value} for r in rows]
    stages.sort(key=lambda x: STAGE_ORDER.index(x["stage"]) if x["stage"] in STAGE_ORDER else 99)

    return {"total_leads": total, "stages": stages, "category": category, "status": "success"}


# ---------------------------------------------------------------------------
# Leads CRUD
# ---------------------------------------------------------------------------

@router.get("/leads", response_model=List[LeadResponse])
def list_leads(
    stage: Optional[str] = Query(default=None),
    min_score: Optional[float] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """List leads with optional filters by stage and minimum score."""
    q = db.query(KnowledgeEntity).filter(
        KnowledgeEntity.tenant_id == current_user.tenant_id,
        KnowledgeEntity.category == "lead",
    )
    if stage:
        q = q.filter(KnowledgeEntity.properties["pipeline_stage"].astext == stage)
    if min_score is not None:
        q = q.filter(KnowledgeEntity.score >= min_score)

    leads = q.order_by(KnowledgeEntity.created_at.desc()).offset(offset).limit(limit).all()
    return [_entity_to_lead_response(e) for e in leads]


@router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_lead(
    lead_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Get a single lead by ID."""
    import uuid as _uuid
    try:
        lid = _uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead_id")

    entity = db.query(KnowledgeEntity).filter(
        KnowledgeEntity.id == lid,
        KnowledgeEntity.tenant_id == current_user.tenant_id,
        KnowledgeEntity.category == "lead",
    ).first()

    if not entity:
        raise HTTPException(status_code=404, detail="Lead not found")

    return _entity_to_lead_response(entity)


@router.patch("/leads/{lead_id}/stage", response_model=LeadResponse)
def update_lead_stage(
    lead_id: str,
    req: StageUpdateRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Move a lead to a new pipeline stage."""
    import uuid as _uuid
    from datetime import datetime

    try:
        lid = _uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead_id")

    entity = db.query(KnowledgeEntity).filter(
        KnowledgeEntity.id == lid,
        KnowledgeEntity.tenant_id == current_user.tenant_id,
        KnowledgeEntity.category == "lead",
    ).first()

    if not entity:
        raise HTTPException(status_code=404, detail="Lead not found")

    props = dict(entity.properties or {})
    old_stage = props.get("pipeline_stage", "prospect")
    history = props.get("stage_history", [])
    history.append({"from": old_stage, "to": req.stage, "reason": req.reason, "at": datetime.utcnow().isoformat()})
    props["pipeline_stage"] = req.stage
    props["stage_history"] = history
    entity.properties = props
    db.commit()

    return _entity_to_lead_response(entity)


# ---------------------------------------------------------------------------
# Inbound capture webhook
# ---------------------------------------------------------------------------

@router.post("/inbound", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def capture_inbound_lead(
    request: Request,
    req: InboundLeadCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Capture an inbound lead from web form, email, WhatsApp, or workshop."""
    company = req.company or (_company_from_email(req.email) if req.email else None)
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
