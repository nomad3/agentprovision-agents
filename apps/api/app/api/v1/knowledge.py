"""API routes for knowledge graph"""
from fastapi import APIRouter, Depends, HTTPException
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
