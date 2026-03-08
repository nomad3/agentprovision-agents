"""Knowledge graph and memory tools.

Manages entities, relationships, and semantic search.
"""
from typing import Optional
import json
import uuid
import re

from services.knowledge_graph import get_knowledge_service


def _parse_json(val, default=None):
    """Parse a JSON string or return the value if already parsed."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default

_UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
_cached_default_tenant_id = None


def set_current_tenant_id(tenant_id: str) -> None:
    """Set the current tenant_id from session state (called by middleware/hooks)."""
    global _cached_default_tenant_id
    if _UUID_PATTERN.match(tenant_id):
        _cached_default_tenant_id = tenant_id


def _resolve_tenant_id(tenant_id: str) -> str:
    """Resolve tenant_id to a valid UUID string.
    If the LLM passes a non-UUID value (like 'default_tenant' or 'auto'),
    use the cached tenant from session state, or fall back to DB lookup
    preferring tenants with active skill configs (Gmail, etc.)."""
    global _cached_default_tenant_id
    if _UUID_PATTERN.match(tenant_id):
        return tenant_id
    if _cached_default_tenant_id:
        return _cached_default_tenant_id
    try:
        from sqlalchemy import create_engine, text
        from config.settings import settings
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            # Prefer tenants with active integration configs (e.g. Gmail connected)
            result = conn.execute(text(
                "SELECT DISTINCT t.id FROM tenants t "
                "JOIN integration_configs ic ON ic.tenant_id = t.id AND ic.enabled = true "
                "LIMIT 1"
            )).fetchone()
            if not result:
                result = conn.execute(text("SELECT id FROM tenants ORDER BY created_at DESC LIMIT 1")).fetchone()
            if result:
                _cached_default_tenant_id = str(result[0])
                return _cached_default_tenant_id
    except Exception:
        pass
    return tenant_id


async def create_entity(
    name: str,
    entity_type: str,
    tenant_id: str,
    properties: Optional[str] = None,
    description: Optional[str] = None,
    aliases: Optional[list[str]] = None,
    confidence: float = 1.0,
    category: str = None,
) -> dict:
    """Create a new knowledge entity.

    Args:
        name: Entity name
        entity_type: Type (customer, product, organization, person, etc.)
        tenant_id: Tenant context
        properties: Additional properties as JSON string, e.g. '{"key": "value"}'
        description: Human-readable description
        aliases: Alternative names
        confidence: Confidence score 0-1
        category: High-level category: lead, contact, investor, accelerator, signal, organization, person.

    Returns:
        Created entity with ID
    """
    kg = get_knowledge_service()
    return await kg.create_entity(
        name=name,
        entity_type=entity_type,
        tenant_id=_resolve_tenant_id(tenant_id),
        properties=_parse_json(properties, {}),
        description=description,
        aliases=aliases or [],
        confidence=confidence,
        category=category,
    )


async def find_entities(
    query: str,
    tenant_id: str,
    entity_types: Optional[list[str]] = None,
    limit: int = 10,
    min_confidence: float = 0.5,
) -> list[dict]:
    """Semantic search for entities by name, description, or properties.

    Args:
        query: Search query
        tenant_id: Tenant context
        entity_types: Filter by types
        limit: Max results
        min_confidence: Minimum confidence threshold

    Returns:
        Matching entities ranked by relevance
    """
    kg = get_knowledge_service()
    return await kg.find_entities(
        query=query,
        tenant_id=_resolve_tenant_id(tenant_id),
        entity_types=entity_types,
        limit=limit,
        min_confidence=min_confidence,
    )


async def get_entity(
    entity_id: str,
    include_relations: bool = True,
) -> dict:
    """Get entity with all its relationships.

    Args:
        entity_id: Entity UUID
        include_relations: Whether to include relationships

    Returns:
        Entity with properties and optionally relationships
    """
    kg = get_knowledge_service()
    return await kg.get_entity(
        entity_id=entity_id,
        include_relations=include_relations,
    )


async def update_entity(
    entity_id: str,
    updates: str,
    reason: Optional[str] = None,
) -> dict:
    """Update entity properties (creates version history).

    Args:
        entity_id: Entity UUID
        updates: Properties to update as JSON string, e.g. '{"name": "new_name"}'
        reason: Reason for change (for audit)

    Returns:
        Updated entity
    """
    kg = get_knowledge_service()
    return await kg.update_entity(
        entity_id=entity_id,
        updates=_parse_json(updates, {}),
        reason=reason,
    )


async def merge_entities(
    primary_entity_id: str,
    duplicate_entity_ids: list[str],
    reason: str,
) -> dict:
    """Merge duplicate entities, preserving relationships.

    Args:
        primary_entity_id: Entity to keep
        duplicate_entity_ids: Entities to merge into primary
        reason: Reason for merge

    Returns:
        Merged entity
    """
    kg = get_knowledge_service()
    return await kg.merge_entities(
        primary_entity_id=primary_entity_id,
        duplicate_entity_ids=duplicate_entity_ids,
        reason=reason,
    )


async def create_relation(
    source_entity_id: str,
    target_entity_id: str,
    relation_type: str,
    tenant_id: str,
    properties: Optional[str] = None,
    strength: float = 1.0,
    evidence: Optional[str] = None,
    bidirectional: bool = False,
) -> dict:
    """Create relationship between entities.

    Args:
        source_entity_id: Source entity UUID
        target_entity_id: Target entity UUID
        relation_type: Type (purchased, works_at, derived_from, etc.)
        tenant_id: Tenant context
        properties: Additional properties as JSON string
        strength: Relationship strength 0-1
        evidence: Supporting context
        bidirectional: If true, creates both directions

    Returns:
        Created relationship
    """
    kg = get_knowledge_service()
    return await kg.create_relation(
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relation_type=relation_type,
        tenant_id=_resolve_tenant_id(tenant_id),
        properties=_parse_json(properties, {}),
        strength=strength,
        evidence=evidence,
        bidirectional=bidirectional,
    )


async def find_relations(
    tenant_id: str,
    entity_id: Optional[str] = None,
    relation_types: Optional[list[str]] = None,
    direction: str = "both",
    min_strength: float = 0.0,
) -> list[dict]:
    """Find relationships for an entity.

    Args:
        tenant_id: Tenant context
        entity_id: Entity to find relations for (optional)
        relation_types: Filter by types
        direction: 'outgoing', 'incoming', or 'both'
        min_strength: Minimum strength threshold

    Returns:
        List of relationships
    """
    kg = get_knowledge_service()
    return await kg.find_relations(
        tenant_id=_resolve_tenant_id(tenant_id),
        entity_id=entity_id,
        relation_types=relation_types,
        direction=direction,
        min_strength=min_strength,
    )


async def get_path(
    source_entity_id: str,
    target_entity_id: str,
    max_depth: int = 4,
    relation_types: Optional[list[str]] = None,
) -> list[dict]:
    """Find shortest path between two entities through relationships.

    Args:
        source_entity_id: Starting entity
        target_entity_id: Ending entity
        max_depth: Maximum hops
        relation_types: Filter by relationship types

    Returns:
        Path as list of entities and relationships
    """
    kg = get_knowledge_service()
    return await kg.get_path(
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        max_depth=max_depth,
        relation_types=relation_types,
    )


async def get_neighborhood(
    entity_id: str,
    depth: int = 2,
    relation_types: Optional[list[str]] = None,
    entity_types: Optional[list[str]] = None,
) -> dict:
    """Get entity neighborhood graph up to N hops.

    Args:
        entity_id: Center entity
        depth: Number of hops
        relation_types: Filter relationships
        entity_types: Filter entities

    Returns:
        Subgraph with entities and relations
    """
    kg = get_knowledge_service()
    return await kg.get_neighborhood(
        entity_id=entity_id,
        depth=depth,
        relation_types=relation_types,
        entity_types=entity_types,
    )


async def search_knowledge(
    query: str,
    tenant_id: str,
    top_k: int = 5,
    filters: Optional[str] = None,
) -> list[dict]:
    """Semantic search across knowledge base using Vertex AI Vector Search.

    Args:
        query: Natural language search query
        tenant_id: Tenant context
        top_k: Number of results
        filters: Optional metadata filters as JSON string

    Returns:
        Ranked results with relevance scores
    """
    kg = get_knowledge_service()
    return await kg.search_knowledge(
        query=query,
        tenant_id=_resolve_tenant_id(tenant_id),
        top_k=top_k,
        filters=_parse_json(filters),
    )


async def store_knowledge(
    content: str,
    metadata: str,
    tenant_id: str,
) -> str:
    """Add new knowledge to vector store with text-embedding-005.

    Args:
        content: Text content to store
        metadata: Associated metadata as JSON string
        tenant_id: Tenant context

    Returns:
        ID of stored knowledge
    """
    kg = get_knowledge_service()
    return await kg.store_knowledge(
        content=content,
        metadata=_parse_json(metadata, {}),
        tenant_id=_resolve_tenant_id(tenant_id),
    )


async def record_observation(
    observation_text: str,
    tenant_id: str,
    observation_type: str = "fact",
    source_type: str = "conversation",
) -> str:
    """Record raw observation for later entity extraction.

    Args:
        observation_text: The observation to record
        tenant_id: Tenant context
        observation_type: Type (fact, opinion, question, hypothesis)
        source_type: Source (conversation, dataset, document)

    Returns:
        Observation ID
    """
    kg = get_knowledge_service()
    return await kg.record_observation(
        observation_text=observation_text,
        tenant_id=_resolve_tenant_id(tenant_id),
        observation_type=observation_type,
        source_type=source_type,
    )


async def ask_knowledge_graph(
    natural_language_question: str,
    tenant_id: str,
) -> dict:
    """Answer questions using knowledge graph traversal.

    Args:
        natural_language_question: Question to answer
        tenant_id: Tenant context

    Returns:
        Answer with supporting entities and relations
    """
    kg = get_knowledge_service()
    return await kg.ask_knowledge_graph(
        question=natural_language_question,
        tenant_id=_resolve_tenant_id(tenant_id),
    )


async def get_entity_timeline(
    entity_id: str,
    include_relations: bool = True,
) -> list[dict]:
    """Get chronological history of entity changes and interactions.

    Args:
        entity_id: Entity UUID
        include_relations: Include relationship changes

    Returns:
        Timeline of events
    """
    kg = get_knowledge_service()
    return await kg.get_entity_timeline(
        entity_id=entity_id,
        include_relations=include_relations,
    )
