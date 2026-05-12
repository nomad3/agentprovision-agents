"""API routes for knowledge graph"""
from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.knowledge_entity import (
    KnowledgeEntity, KnowledgeEntityCreate, KnowledgeEntityUpdate,
    KnowledgeEntityBulkCreate, KnowledgeEntityBulkResponse, CollectionSummary,
)
from app.schemas.knowledge_relation import KnowledgeRelation, KnowledgeRelationCreate, KnowledgeRelationWithEntities
from app.services import knowledge as service

router = APIRouter()


@router.get("/quality-stats")
def get_quality_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Entity quality statistics: total entities, embedding coverage, top/bottom by usefulness, per-platform extraction stats."""
    return service.get_quality_stats(db, current_user.tenant_id)


@router.get("/scoring-rubrics")
def list_scoring_rubrics(current_user: User = Depends(get_current_user)):
    """List all available scoring rubrics."""
    from app.services.scoring_rubrics import list_rubrics
    return list_rubrics()


# Entity endpoints
@router.post("/entities", response_model=KnowledgeEntity, status_code=201)
def create_entity(
    entity_in: KnowledgeEntityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new knowledge entity."""
    return service.create_entity(db, entity_in, current_user.tenant_id)


@router.get("/entities", response_model=List[KnowledgeEntity])
def list_entities(
    entity_type: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    task_id: Optional[uuid.UUID] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List entities with optional filters."""
    return service.get_entities(
        db, current_user.tenant_id, entity_type, skip, limit,
        status=status, task_id=task_id, category=category,
    )


@router.get("/entities/search", response_model=List[KnowledgeEntity])
def search_entities(
    q: str,
    entity_type: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Search entities by name."""
    return service.search_entities(db, current_user.tenant_id, q, entity_type, category=category)


# ---------------------------------------------------------------------------
# Manual Knowledge Extraction (Memory > Entities "Run Knowledge Extraction")
# ---------------------------------------------------------------------------

class ExtractRequest(BaseModel):
    session_id: Optional[uuid.UUID] = None  # if None, runs over N most recent sessions
    max_sessions: int = 5                    # cap on batch


class ExtractResponse(BaseModel):
    sessions_processed: int
    entities_created: int
    relations_created: int
    memories_created: int


@router.post("/extract", response_model=ExtractResponse)
def extract_knowledge(
    payload: ExtractRequest = Body(default_factory=ExtractRequest),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Extract entities/relations/memories from recent chat sessions.

    If session_id is provided, processes that single session; otherwise processes
    the tenant's N most recent sessions (capped at max_sessions, default 5, max 20).
    Triggered by the Memory > Entities "Run Knowledge Extraction" button.
    """
    from app.services.knowledge_extraction import knowledge_extraction_service
    from app.models.chat import ChatSession, ChatMessage
    from sqlalchemy import func

    if payload.session_id:
        target_ids = [payload.session_id]
    else:
        # Sort by last message activity (not session creation) so a freshly-created
        # empty session doesn't outrank an older session with real history.
        # extract_from_session early-returns on empty sessions, so ordering by
        # creation could waste the whole batch on blank tabs.
        recent = (
            db.query(ChatSession.id)
            .join(ChatMessage, ChatMessage.session_id == ChatSession.id)
            .filter(ChatSession.tenant_id == current_user.tenant_id)
            .group_by(ChatSession.id)
            .order_by(func.max(ChatMessage.created_at).desc())
            .limit(max(1, min(payload.max_sessions, 20)))
            .all()
        )
        target_ids = [r.id for r in recent]

    totals = {"entities": 0, "relations": 0, "memories": 0}
    processed = 0
    for sid in target_ids:
        try:
            result = knowledge_extraction_service.extract_from_session(
                db, sid, current_user.tenant_id
            )
        except Exception:
            # One bad session must not abort the batch — caller still gets partial totals.
            continue
        totals["entities"] += len(result.get("entities", []))
        totals["relations"] += len(result.get("relations", []))
        totals["memories"] += len(result.get("memories", []))
        processed += 1

    return ExtractResponse(
        sessions_processed=processed,
        entities_created=totals["entities"],
        relations_created=totals["relations"],
        memories_created=totals["memories"],
    )


@router.post("/entities/bulk", response_model=KnowledgeEntityBulkResponse, status_code=201)
def bulk_create_entities(
    bulk_in: KnowledgeEntityBulkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Bulk create entities with dedup."""
    return service.bulk_create_entities(db, bulk_in.entities, current_user.tenant_id)


@router.get("/entities/{entity_id}", response_model=KnowledgeEntity)
def get_entity(
    entity_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get entity by ID."""
    entity = service.get_entity(db, entity_id, current_user.tenant_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


# ── internal getters/updaters ────────────────────────────────────────
# Used by MCP-server tools (sales.qualify_lead, etc.) that need to read
# or mutate entities outside a user-Bearer context. The MCP server
# passes X-Internal-Key + tenant_id; we mount these under the resource
# path (not /api/v1/internal/*) because the MCP tool URLs were already
# written that way before the surface existed — adding them here means
# the long-broken qualify_lead flow starts working without touching
# every caller. Cloudflared blocks /api/v1/*/internal($|/) from the
# public internet so this is safe to expose at the resource path.

def _verify_internal_key_kg(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    from app.core.config import settings as _s
    if x_internal_key not in (_s.API_INTERNAL_KEY, _s.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")


@router.get("/entities/internal", response_model=List[KnowledgeEntity])
def list_entities_internal(
    tenant_id: uuid.UUID,
    entity_type: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    exclude_archived: bool = False,
    limit: int = 100,
    _auth: None = Depends(_verify_internal_key_kg),
    db: Session = Depends(get_db),
):
    """Internal list endpoint for MCP-server tools.

    Mirrors ``GET /entities`` but auths via X-Internal-Key with an
    explicit ``tenant_id`` query param. The competitor monitor MCP
    tool (apps/mcp-server/src/mcp_tools/competitor.py:160) has been
    calling this for months and hitting 404 — every poll cycle
    spammed the api logs with HTTPStatusError tracebacks.

    ``exclude_archived=true`` is sugar for ``status != 'archived'``.
    It's a separate boolean (not a magic status value) because the
    common case for the competitor list is "everything that isn't
    archived" — making callers pass ``status='draft|verified|enriched|actioned'``
    via a multi-value query string would be hostile UX for the
    intended consumer. Mutually exclusive with an explicit ``status``
    filter: if both are given, the explicit one wins.
    """
    if status:
        results = service.get_entities(
            db, tenant_id, entity_type, skip=0, limit=limit,
            status=status, category=category,
        )
    else:
        # No explicit status: pull everything, then drop archived
        # in Python if exclude_archived=true. Doing it in Python
        # rather than chaining `query.filter(status != 'archived')`
        # keeps the service signature unchanged — there's no SQL-
        # level NULL-vs-'archived' edge case to worry about.
        results = service.get_entities(
            db, tenant_id, entity_type, skip=0, limit=limit,
            category=category,
        )
        if exclude_archived:
            results = [e for e in results if (e.status or "") != "archived"]
    return results


@router.post("/entities/internal", response_model=KnowledgeEntity, status_code=201)
def create_entity_internal(
    payload: dict,
    _auth: None = Depends(_verify_internal_key_kg),
    db: Session = Depends(get_db),
):
    """Internal entity create for MCP-server tools.

    Body shape: ``tenant_id`` plus the fields of ``KnowledgeEntityCreate``.
    The MCP competitor tool (competitor.py:117) calls this when the
    user runs ``add_competitor`` from chat — failure here meant the
    user got an MCP error and the entity never persisted.

    Validates tenant_id, strips it from the payload, then routes the
    rest through the normal Pydantic validator. Same error shapes as
    the existing internal endpoints (422 on bad UUID / bad body).
    """
    tenant_id_raw = payload.get("tenant_id")
    if not tenant_id_raw:
        raise HTTPException(status_code=422, detail="tenant_id is required")
    try:
        tenant_id = uuid.UUID(str(tenant_id_raw))
    except ValueError:
        raise HTTPException(status_code=422, detail="tenant_id must be a UUID")

    create_fields = {k: v for k, v in payload.items() if k != "tenant_id"}
    try:
        entity_in = KnowledgeEntityCreate(**create_fields)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"invalid create body: {e}")
    return service.create_entity(db, entity_in, tenant_id)


@router.get("/entities/internal/search", response_model=List[KnowledgeEntity])
def search_entities_internal(
    tenant_id: uuid.UUID,
    q: str,
    entity_type: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50,
    _auth: None = Depends(_verify_internal_key_kg),
    db: Session = Depends(get_db),
):
    """Internal name-search for MCP-server tools.

    Mirrors ``GET /entities/search`` but X-Internal-Key + explicit
    ``tenant_id``. Used by ``remove_competitor`` and ``get_competitor_report``
    to resolve a competitor's UUID from a chat-supplied name string —
    those two tools were the primary source of the 2026-05-12 traceback
    spam (`competitor.py:271` and `:207`).
    """
    return service.search_entities(
        db, tenant_id, q, entity_type, category=category, limit=limit,
    )


@router.get("/entities/{entity_id}/internal", response_model=KnowledgeEntity)
def get_entity_internal(
    entity_id: uuid.UUID,
    tenant_id: uuid.UUID,
    include_relations: bool = False,  # noqa: ARG001 — kept for caller compat
    _auth: None = Depends(_verify_internal_key_kg),
    db: Session = Depends(get_db),
):
    """Internal read of an entity for MCP-server tools.

    Same semantics as ``GET /entities/{id}`` but auth is X-Internal-Key
    instead of user-Bearer, and tenant_id comes through as a query
    param (the caller knows it; we just validate the entity row matches).
    """
    entity = service.get_entity(db, entity_id, tenant_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.patch("/entities/{entity_id}/internal", response_model=KnowledgeEntity)
def update_entity_internal(
    entity_id: uuid.UUID,
    payload: dict,
    _auth: None = Depends(_verify_internal_key_kg),
    db: Session = Depends(get_db),
):
    """Internal partial-update for MCP-server tools.

    The body shape is open — ``tenant_id`` is required, ``reason`` is
    optional, every other key is treated as a field update routed
    through ``KnowledgeEntityUpdate``. Used by sales.qualify_lead to
    write the BANT qualification back to entity.properties.
    """
    tenant_id_raw = payload.get("tenant_id")
    if not tenant_id_raw:
        raise HTTPException(status_code=422, detail="tenant_id is required")
    try:
        tenant_id = uuid.UUID(str(tenant_id_raw))
    except ValueError:
        raise HTTPException(status_code=422, detail="tenant_id must be a UUID")
    # Strip helper keys before validating the update body. `reason`
    # would have been useful to wire into the audit log; the existing
    # `update_entity` service signature doesn't take one, so we drop
    # it silently rather than break the contract.
    updates = {k: v for k, v in payload.items() if k not in ("tenant_id", "reason")}
    try:
        entity_in = KnowledgeEntityUpdate(**updates)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"invalid update body: {e}")
    entity = service.update_entity(db, entity_id, tenant_id, entity_in)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.post("/entities/{entity_id}/internal/archive", response_model=KnowledgeEntity)
def archive_entity_internal(
    entity_id: uuid.UUID,
    payload: dict,
    _auth: None = Depends(_verify_internal_key_kg),
    db: Session = Depends(get_db),
):
    """Internal archive — sets status='archived' on the entity.

    Convenience wrapper over the update path so the MCP competitor
    tool (competitor.py:230) gets a single round-trip for the common
    ``remove_competitor`` flow instead of having to:
      1. PATCH /entities/{id}/internal with `{"status":"archived"}`
      2. handle the open dict shape

    Body: ``{"tenant_id": "<uuid>", "reason": "<optional>"}``.
    Always sets ``status='archived'``; if the entity is already
    archived this is a no-op (returns the row unchanged, 200).
    """
    tenant_id_raw = payload.get("tenant_id")
    if not tenant_id_raw:
        raise HTTPException(status_code=422, detail="tenant_id is required")
    try:
        tenant_id = uuid.UUID(str(tenant_id_raw))
    except ValueError:
        raise HTTPException(status_code=422, detail="tenant_id must be a UUID")

    entity_in = KnowledgeEntityUpdate(status="archived")
    entity = service.update_entity(db, entity_id, tenant_id, entity_in)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.get("/entities/{entity_id}/internal/timeline")
def entity_timeline_internal(
    entity_id: uuid.UUID,
    tenant_id: uuid.UUID,
    limit: int = 100,
    _auth: None = Depends(_verify_internal_key_kg),
    db: Session = Depends(get_db),
):
    """Internal entity-history feed — returns ``knowledge_entity_history``
    rows for the given entity, newest first.

    The MCP competitor tool (competitor.py:301) calls this after
    resolving the competitor UUID to render a chronological view of
    what changed (price moves, ad-creative refreshes, status flips).

    Response: ``{"history": [<row>, ...], "count": N}``. Empty list
    when the entity exists but has no history rows yet — distinct
    from 404 (entity doesn't exist at all in this tenant).
    """
    from app.models.knowledge_entity_history import KnowledgeEntityHistory

    # Tenant-scope check first — refuse to leak history rows for an
    # entity that belongs to a different tenant. ``get_entity`` does
    # this filter for us.
    entity = service.get_entity(db, entity_id, tenant_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    rows = (
        db.query(KnowledgeEntityHistory)
        .filter(KnowledgeEntityHistory.entity_id == entity_id)
        .order_by(KnowledgeEntityHistory.changed_at.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    # Serialise via dict() — the history model has stable columns
    # and the caller is the MCP tool, not a Pydantic-validated SDK.
    # Keeping the shape open here matches `_api_get`'s consumption
    # at competitor.py:304 (`timeline_result.get("history", [])`).
    return {
        "count": len(rows),
        "history": [
            {
                "id": str(r.id),
                "entity_id": str(r.entity_id),
                "version": r.version,
                "properties_snapshot": r.properties_snapshot,
                "attributes_snapshot": r.attributes_snapshot,
                "change_reason": r.change_reason,
                "changed_by_platform": r.changed_by_platform,
                "changed_at": r.changed_at.isoformat() if r.changed_at else None,
            }
            for r in rows
        ],
    }


@router.put("/entities/{entity_id}", response_model=KnowledgeEntity)
def update_entity(
    entity_id: uuid.UUID,
    entity_in: KnowledgeEntityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an entity."""
    entity = service.update_entity(db, entity_id, current_user.tenant_id, entity_in)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.delete("/entities/{entity_id}", status_code=204)
def delete_entity(
    entity_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an entity and its relations."""
    if not service.delete_entity(db, entity_id, current_user.tenant_id):
        raise HTTPException(status_code=404, detail="Entity not found")


@router.post("/entities/{entity_id}/score")
def score_entity(
    entity_id: uuid.UUID,
    rubric_id: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Compute and store a lead score for an entity using a configurable rubric."""
    result = service.score_entity(db, entity_id, current_user.tenant_id, rubric_id=rubric_id)
    if not result:
        raise HTTPException(status_code=404, detail="Entity not found or scoring failed")
    return result


@router.post("/entities/score/batch")
def score_entities_batch(
    limit: int = 50,
    rubric_id: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Score all unscored entities for the tenant."""
    from app.models.knowledge_entity import KnowledgeEntity as KE

    entities = (
        db.query(KE)
        .filter(
            KE.tenant_id == current_user.tenant_id,
            KE.score.is_(None),
            KE.status != "archived",
        )
        .limit(limit)
        .all()
    )

    results = []
    for entity in entities:
        result = service.score_entity(
            db, entity.id, current_user.tenant_id, rubric_id=rubric_id,
        )
        if result:
            results.append(result)

    return {"scored": len(results), "results": results}


@router.put("/entities/{entity_id}/status", response_model=KnowledgeEntity)
def update_entity_status(
    entity_id: uuid.UUID,
    status_update: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update entity lifecycle status."""
    new_status = status_update.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="'status' field required")
    entity = service.update_entity_status(db, entity_id, current_user.tenant_id, new_status)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found or invalid status")
    return entity


@router.get("/collections/{task_id}/summary", response_model=CollectionSummary)
def get_collection_summary(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get collection summary for a task."""
    return service.get_collection_summary(db, task_id, current_user.tenant_id)


# Relation endpoints
@router.get("/relations", response_model=List[KnowledgeRelationWithEntities])
def list_relations(
    relation_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all relations for the tenant with entity names."""
    relations = service.get_all_relations(
        db, current_user.tenant_id, relation_type, skip, limit
    )
    results = []
    for rel in relations:
        base = KnowledgeRelation.model_validate(rel)
        data = KnowledgeRelationWithEntities(
            **base.model_dump(),
            from_entity_name=rel.from_entity.name if rel.from_entity else None,
            from_entity_category=rel.from_entity.category if rel.from_entity else None,
            to_entity_name=rel.to_entity.name if rel.to_entity else None,
            to_entity_category=rel.to_entity.category if rel.to_entity else None,
        )
        results.append(data)
    return results


@router.post("/relations", response_model=KnowledgeRelation, status_code=201)
def create_relation(
    relation_in: KnowledgeRelationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a relation between entities."""
    try:
        return service.create_relation(db, relation_in, current_user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/entities/{entity_id}/relations", response_model=List[KnowledgeRelation])
def get_entity_relations(
    entity_id: uuid.UUID,
    direction: str = "both",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all relations for an entity."""
    return service.get_entity_relations(db, entity_id, current_user.tenant_id, direction)


@router.delete("/relations/{relation_id}", status_code=204)
def delete_relation(
    relation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a relation."""
    if not service.delete_relation(db, relation_id, current_user.tenant_id):
        raise HTTPException(status_code=404, detail="Relation not found")


# ---------------------------------------------------------------------------
# Git History / PR Outcome
# ---------------------------------------------------------------------------

class PROutcomeRequest(BaseModel):
    repo: str
    pr_number: int
    outcome: str  # merged, closed, reverted
    title: str = ""
    review_comments: List[str] = []


@router.post("/pr-outcome")
def report_pr_outcome(
    payload: PROutcomeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Report a PR outcome for RL reward assignment and knowledge observation.

    Called by code-worker or nightly polling when a PR is merged/closed/reverted.
    Stores a git_pr observation and returns the suggested RL reward.
    """
    if payload.outcome not in ("merged", "closed", "reverted"):
        raise HTTPException(status_code=400, detail="outcome must be merged, closed, or reverted")

    result = service.store_pr_outcome(
        db,
        tenant_id=current_user.tenant_id,
        repo=payload.repo,
        pr_number=payload.pr_number,
        outcome=payload.outcome,
        title=payload.title,
        review_comments=payload.review_comments,
    )

    # Try to assign RL reward to the code_task experience
    try:
        from app.services import rl_experience_service
        from sqlalchemy import text as sql_text

        exp = db.execute(
            sql_text("""
                SELECT id FROM rl_experiences
                WHERE tenant_id = CAST(:tid AS uuid)
                AND decision_point = 'code_task'
                AND (state->>'pr_number')::int = :pr_num
                AND reward IS NULL
                ORDER BY created_at DESC LIMIT 1
            """),
            {
                "tid": str(current_user.tenant_id),
                "pr_num": payload.pr_number,
            },
        ).fetchone()

        if exp:
            rl_experience_service.assign_reward(
                db,
                experience_id=exp.id,
                reward=result["rl_reward"],
                reward_components={
                    "pr_outcome": payload.outcome,
                    "pr_number": payload.pr_number,
                    "review_count": len(payload.review_comments),
                },
                reward_source="git_pr_outcome",
            )
            result["rl_experience_rewarded"] = True
    except Exception:
        pass

    return result


@router.get("/git-context")
def get_git_context(
    q: str = "",
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get recent git context (commits, PRs, hotspots) relevant to a query."""
    from app.services.memory_recall import get_recent_git_context
    return get_recent_git_context(db, current_user.tenant_id, q, limit=limit)


# ---------------------------------------------------------------------------
# Embedding Backfill
# ---------------------------------------------------------------------------

@router.post("/backfill-embeddings")
async def trigger_backfill(
    current_user: User = Depends(get_current_user),
):
    """Start an embedding backfill workflow (admin only)."""
    from app.services.dynamic_workflow_launcher import start_dynamic_workflow_by_name

    temporal_wf_id = await start_dynamic_workflow_by_name(
        "Embedding Backfill", str(current_user.tenant_id),
    )
    return {"workflow_id": temporal_wf_id, "status": "started"}


# ---------------------------------------------------------------------------
# Memory Consolidation
# ---------------------------------------------------------------------------

@router.post("/consolidation/start")
async def start_consolidation(
    current_user: User = Depends(get_current_user),
):
    """Start the nightly memory consolidation workflow."""
    from app.services.dynamic_workflow_launcher import start_dynamic_workflow_by_name

    temporal_wf_id = await start_dynamic_workflow_by_name(
        "Memory Consolidation", str(current_user.tenant_id),
    )
    return {"workflow_id": temporal_wf_id, "status": "started"}


@router.post("/consolidation/stop")
async def stop_consolidation(
    current_user: User = Depends(get_current_user),
):
    """Stop the memory consolidation workflow."""
    from temporalio.client import Client
    from app.core.config import settings as app_settings

    client = await Client.connect(app_settings.TEMPORAL_ADDRESS)
    workflow_id = f"memory-consolidation-{current_user.tenant_id}"
    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.cancel()
        return {"status": "stopped"}
    except Exception as e:
        return {"status": "not_running", "error": str(e)}


@router.get("/consolidation/status")
async def get_consolidation_status(
    current_user: User = Depends(get_current_user),
):
    """Check if the consolidation workflow is running."""
    from temporalio.client import Client
    from app.core.config import settings as app_settings

    client = await Client.connect(app_settings.TEMPORAL_ADDRESS)
    workflow_id = f"memory-consolidation-{current_user.tenant_id}"
    try:
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        return {"status": str(desc.status), "workflow_id": workflow_id}
    except Exception:
        return {"status": "not_running"}
