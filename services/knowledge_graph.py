"""Knowledge graph service for entity and relationship management.

Uses PostgreSQL with pgvector for storage and Vertex AI for embeddings.
"""
from typing import Optional, Any
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import uuid

from config.settings import settings
from memory.vertex_vector import get_embedding_service


def _serialize_row(row_mapping) -> dict:
    """Convert a SQLAlchemy row mapping to a JSON-safe dict."""
    result = {}
    for k, v in dict(row_mapping).items():
        if isinstance(v, uuid.UUID):
            result[k] = str(v)
        elif isinstance(v, (datetime, date)):
            result[k] = v.isoformat()
        elif isinstance(v, Decimal):
            result[k] = float(v)
        else:
            result[k] = v
    return result


class KnowledgeGraphService:
    """Manages knowledge entities and relationships in PostgreSQL."""

    def __init__(self):
        self.engine = create_engine(settings.database_url)
        self.Session = sessionmaker(bind=self.engine)
        self.embedding_service = get_embedding_service()
        self._pgvector_available = None

    def _check_pgvector(self) -> bool:
        """Check if pgvector extension is available."""
        if self._pgvector_available is None:
            try:
                with self.Session() as session:
                    result = session.execute(
                        text("SELECT 1 FROM pg_extension WHERE extname='vector'")
                    ).fetchone()
                    self._pgvector_available = result is not None
            except Exception:
                self._pgvector_available = False
        return self._pgvector_available

    async def create_entity(
        self,
        name: str,
        entity_type: str,
        tenant_id: str,
        properties: dict = None,
        description: str = None,
        aliases: list = None,
        confidence: float = 1.0,
        category: str = None,
    ) -> dict:
        """Create a new knowledge entity."""
        entity_id = str(uuid.uuid4())
        import json

        with self.Session() as session:
            if self._check_pgvector():
                text_for_embedding = f"{name} {description or ''}"
                embedding = await self.embedding_service.get_embedding(text_for_embedding)
                session.execute(
                    text("""
                        INSERT INTO knowledge_entities
                        (id, tenant_id, name, entity_type, category, description, properties, aliases, confidence, embedding, created_at, updated_at)
                        VALUES (:id, :tenant_id, :name, :entity_type, :category, :description, :properties, :aliases, :confidence, :embedding, NOW(), NOW())
                    """),
                    {
                        "id": entity_id,
                        "tenant_id": tenant_id,
                        "name": name,
                        "entity_type": entity_type,
                        "category": category,
                        "description": description,
                        "properties": json.dumps(properties or {}),
                        "aliases": json.dumps(aliases or []),
                        "confidence": confidence,
                        "embedding": embedding,
                    }
                )
            else:
                session.execute(
                    text("""
                        INSERT INTO knowledge_entities
                        (id, tenant_id, name, entity_type, category, description, properties, aliases, confidence, created_at, updated_at)
                        VALUES (:id, :tenant_id, :name, :entity_type, :category, :description, :properties, :aliases, :confidence, NOW(), NOW())
                    """),
                    {
                        "id": entity_id,
                        "tenant_id": tenant_id,
                        "name": name,
                        "entity_type": entity_type,
                        "category": category,
                        "description": description,
                        "properties": json.dumps(properties or {}),
                        "aliases": json.dumps(aliases or []),
                        "confidence": confidence,
                    }
                )
            session.commit()

        return {"id": entity_id, "name": name, "entity_type": entity_type, "category": category}

    async def find_entities(
        self,
        query: str,
        tenant_id: str,
        entity_types: list = None,
        limit: int = 10,
        min_confidence: float = 0.5,
    ) -> list[dict]:
        """Search for entities using vector similarity or text fallback."""
        with self.Session() as session:
            type_filter = ""
            if entity_types:
                type_list = ",".join(f"'{t}'" for t in entity_types)
                type_filter = f"AND entity_type IN ({type_list})"

            if self._check_pgvector():
                query_embedding = await self.embedding_service.get_embedding(query)
                result = session.execute(
                    text(f"""
                        SELECT id, name, entity_type, category, description, confidence,
                               1 - (embedding <=> :embedding) as similarity
                        FROM knowledge_entities
                        WHERE tenant_id = :tenant_id
                        AND confidence >= :min_confidence
                        {type_filter}
                        ORDER BY embedding <=> :embedding
                        LIMIT :limit
                    """),
                    {
                        "tenant_id": tenant_id,
                        "embedding": query_embedding,
                        "min_confidence": min_confidence,
                        "limit": limit,
                    }
                )
            else:
                # Text-based fallback when pgvector is not available
                result = session.execute(
                    text(f"""
                        SELECT id, name, entity_type, category, description, confidence,
                               1.0 as similarity
                        FROM knowledge_entities
                        WHERE tenant_id = :tenant_id
                        AND confidence >= :min_confidence
                        AND (name ILIKE :query OR description ILIKE :query)
                        {type_filter}
                        ORDER BY confidence DESC
                        LIMIT :limit
                    """),
                    {
                        "tenant_id": tenant_id,
                        "query": f"%{query}%",
                        "min_confidence": min_confidence,
                        "limit": limit,
                    }
                )

            return [_serialize_row(row._mapping) for row in result]

    async def get_entity(
        self,
        entity_id: str,
        include_relations: bool = True,
    ) -> dict:
        """Get entity by ID with optional relationships."""
        with self.Session() as session:
            result = session.execute(
                text("""
                    SELECT id, tenant_id, name, entity_type, category, description,
                           properties, aliases, confidence, created_at, updated_at
                    FROM knowledge_entities
                    WHERE id = :entity_id
                """),
                {"entity_id": entity_id}
            ).fetchone()

            if not result:
                return {"error": "Entity not found"}

            entity = _serialize_row(result._mapping)

            if include_relations:
                relations = session.execute(
                    text("""
                        SELECT r.id, r.relation_type, r.strength, r.evidence,
                               e.id as target_id, e.name as target_name, e.entity_type as target_type
                        FROM knowledge_relations r
                        JOIN knowledge_entities e ON r.to_entity_id = e.id
                        WHERE r.from_entity_id = :entity_id
                        UNION ALL
                        SELECT r.id, r.relation_type, r.strength, r.evidence,
                               e.id as target_id, e.name as target_name, e.entity_type as target_type
                        FROM knowledge_relations r
                        JOIN knowledge_entities e ON r.from_entity_id = e.id
                        WHERE r.to_entity_id = :entity_id
                    """),
                    {"entity_id": entity_id}
                )
                entity["relations"] = [_serialize_row(row._mapping) for row in relations]

            return entity

    async def update_entity(
        self,
        entity_id: str,
        updates: dict,
        reason: str = None,
    ) -> dict:
        """Update entity and create history record."""
        with self.Session() as session:
            # Get current state for history
            current = session.execute(
                text("SELECT properties FROM knowledge_entities WHERE id = :id"),
                {"id": entity_id}
            ).fetchone()

            import json

            if current:
                # Create history record
                props = current.properties
                if isinstance(props, dict):
                    props = json.dumps(props)
                session.execute(
                    text("""
                        INSERT INTO knowledge_entity_history
                        (entity_id, version, properties_snapshot, change_reason)
                        SELECT :entity_id, COALESCE(MAX(version), 0) + 1, :properties, :reason
                        FROM knowledge_entity_history WHERE entity_id = :entity_id
                    """),
                    {
                        "entity_id": entity_id,
                        "properties": props,
                        "reason": reason,
                    }
                )
            # Update entity
            session.execute(
                text("""
                    UPDATE knowledge_entities
                    SET properties = :updates, updated_at = NOW()
                    WHERE id = :entity_id
                """),
                {"entity_id": entity_id, "updates": json.dumps(updates)}
            )
            session.commit()

        return await self.get_entity(entity_id, include_relations=False)

    async def merge_entities(
        self,
        primary_entity_id: str,
        duplicate_entity_ids: list[str],
        reason: str,
    ) -> dict:
        """Merge duplicate entities into primary."""
        with self.Session() as session:
            for dup_id in duplicate_entity_ids:
                # Move relations to primary
                session.execute(
                    text("""
                        UPDATE knowledge_relations
                        SET from_entity_id = :primary_id
                        WHERE from_entity_id = :dup_id
                    """),
                    {"primary_id": primary_entity_id, "dup_id": dup_id}
                )
                session.execute(
                    text("""
                        UPDATE knowledge_relations
                        SET to_entity_id = :primary_id
                        WHERE to_entity_id = :dup_id
                    """),
                    {"primary_id": primary_entity_id, "dup_id": dup_id}
                )

                # Delete duplicate
                session.execute(
                    text("DELETE FROM knowledge_entities WHERE id = :id"),
                    {"id": dup_id}
                )

            session.commit()

        return await self.get_entity(primary_entity_id)

    async def create_relation(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        tenant_id: str,
        properties: dict = None,
        strength: float = 1.0,
        evidence: str = None,
        bidirectional: bool = False,
    ) -> dict:
        """Create relationship between entities."""
        import json
        relation_id = str(uuid.uuid4())

        with self.Session() as session:
            session.execute(
                text("""
                    INSERT INTO knowledge_relations
                    (id, tenant_id, from_entity_id, to_entity_id, relation_type,
                     strength, evidence, created_at)
                    VALUES (:id, :tenant_id, :source_id, :target_id, :relation_type,
                            :strength, :evidence, NOW())
                """),
                {
                    "id": relation_id,
                    "tenant_id": tenant_id,
                    "source_id": source_entity_id,
                    "target_id": target_entity_id,
                    "relation_type": relation_type,
                    "strength": strength,
                    "evidence": json.dumps({"text": evidence, "properties": properties or {}}),
                }
            )
            session.commit()

        return {"id": relation_id, "relation_type": relation_type}

    async def find_relations(
        self,
        tenant_id: str,
        entity_id: str = None,
        relation_types: list = None,
        direction: str = "both",
        min_strength: float = 0.0,
    ) -> list[dict]:
        """Find relationships."""
        with self.Session() as session:
            conditions = ["r.tenant_id = :tenant_id", "r.strength >= :min_strength"]
            params = {"tenant_id": tenant_id, "min_strength": min_strength}

            if entity_id:
                if direction == "outgoing":
                    conditions.append("r.from_entity_id = :entity_id")
                elif direction == "incoming":
                    conditions.append("r.to_entity_id = :entity_id")
                else:
                    conditions.append("(r.from_entity_id = :entity_id OR r.to_entity_id = :entity_id)")
                params["entity_id"] = entity_id

            if relation_types:
                type_list = ",".join(f"'{t}'" for t in relation_types)
                conditions.append(f"r.relation_type IN ({type_list})")

            where_clause = " AND ".join(conditions)

            result = session.execute(
                text(f"""
                    SELECT r.id, r.tenant_id, r.from_entity_id as source_entity_id,
                           r.to_entity_id as target_entity_id, r.relation_type,
                           r.strength, r.evidence, r.created_at,
                           s.name as source_name, s.entity_type as source_type,
                           t.name as target_name, t.entity_type as target_type
                    FROM knowledge_relations r
                    JOIN knowledge_entities s ON r.from_entity_id = s.id
                    JOIN knowledge_entities t ON r.to_entity_id = t.id
                    WHERE {where_clause}
                """),
                params
            )

            return [_serialize_row(row._mapping) for row in result]

    async def get_path(
        self,
        source_entity_id: str,
        target_entity_id: str,
        max_depth: int = 4,
        relation_types: list = None,
    ) -> list[dict]:
        """Find shortest path between entities using BFS."""
        # Simplified BFS implementation
        visited = set()
        queue = [(source_entity_id, [])]

        while queue and len(visited) < 1000:  # Safety limit
            current_id, path = queue.pop(0)

            if current_id == target_entity_id:
                return path

            if current_id in visited or len(path) >= max_depth:
                continue

            visited.add(current_id)

            relations = await self.find_relations(
                tenant_id="",  # Need to pass from context
                entity_id=current_id,
                relation_types=relation_types,
            )

            for rel in relations:
                next_id = rel["target_entity_id"] if rel["source_entity_id"] == current_id else rel["source_entity_id"]
                if next_id not in visited:
                    queue.append((next_id, path + [rel]))

        return []  # No path found

    async def get_neighborhood(
        self,
        entity_id: str,
        depth: int = 2,
        relation_types: list = None,
        entity_types: list = None,
    ) -> dict:
        """Get entity neighborhood graph."""
        entities = {}
        relations = []

        async def expand(eid: str, current_depth: int):
            if current_depth > depth or eid in entities:
                return

            entity = await self.get_entity(eid, include_relations=False)
            if entity_types and entity.get("entity_type") not in entity_types:
                return

            entities[eid] = entity

            rels = await self.find_relations(
                tenant_id=entity.get("tenant_id", ""),
                entity_id=eid,
                relation_types=relation_types,
            )

            for rel in rels:
                relations.append(rel)
                next_id = rel["target_entity_id"] if rel["source_entity_id"] == eid else rel["source_entity_id"]
                await expand(next_id, current_depth + 1)

        await expand(entity_id, 0)

        return {
            "entities": list(entities.values()),
            "relations": relations,
        }

    async def search_knowledge(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 5,
        filters: dict = None,
    ) -> list[dict]:
        """Semantic search using vector similarity."""
        return await self.find_entities(
            query=query,
            tenant_id=tenant_id,
            entity_types=filters.get("entity_types") if filters else None,
            limit=top_k,
        )

    async def store_knowledge(
        self,
        content: str,
        metadata: dict,
        tenant_id: str,
    ) -> str:
        """Store knowledge as an entity."""
        entity = await self.create_entity(
            name=metadata.get("name", content[:100]),
            entity_type=metadata.get("type", "fact"),
            tenant_id=tenant_id,
            description=content,
            properties=metadata,
            category=metadata.get("category"),
        )
        return entity["id"]

    async def record_observation(
        self,
        observation_text: str,
        tenant_id: str,
        observation_type: str = "fact",
        source_type: str = "conversation",
    ) -> str:
        """Record observation for later processing."""
        obs_id = str(uuid.uuid4())

        with self.Session() as session:
            if self._check_pgvector():
                embedding = await self.embedding_service.get_embedding(observation_text)
                session.execute(
                    text("""
                        INSERT INTO knowledge_observations
                        (id, tenant_id, observation_text, observation_type, source_type, embedding)
                        VALUES (:id, :tenant_id, :text, :type, :source, :embedding)
                    """),
                    {
                        "id": obs_id,
                        "tenant_id": tenant_id,
                        "text": observation_text,
                        "type": observation_type,
                        "source": source_type,
                        "embedding": embedding,
                    }
                )
            else:
                session.execute(
                    text("""
                        INSERT INTO knowledge_observations
                        (id, tenant_id, observation_text, observation_type, source_type)
                        VALUES (:id, :tenant_id, :text, :type, :source)
                    """),
                    {
                        "id": obs_id,
                        "tenant_id": tenant_id,
                        "text": observation_text,
                        "type": observation_type,
                        "source": source_type,
                    }
                )
            session.commit()

        return obs_id

    async def ask_knowledge_graph(
        self,
        question: str,
        tenant_id: str,
    ) -> dict:
        """Answer question using knowledge graph."""
        # Find relevant entities
        entities = await self.find_entities(
            query=question,
            tenant_id=tenant_id,
            limit=5,
        )

        # Get relations for top entities
        relations = []
        for entity in entities[:3]:
            rels = await self.find_relations(
                tenant_id=tenant_id,
                entity_id=entity["id"],
            )
            relations.extend(rels[:5])

        return {
            "question": question,
            "relevant_entities": entities,
            "relevant_relations": relations,
            "note": "Agent should synthesize answer from this context",
        }

    async def get_entity_timeline(
        self,
        entity_id: str,
        include_relations: bool = True,
    ) -> list[dict]:
        """Get entity history timeline."""
        with self.Session() as session:
            result = session.execute(
                text("""
                    SELECT version, properties_snapshot, change_reason, changed_at
                    FROM knowledge_entity_history
                    WHERE entity_id = :entity_id
                    ORDER BY changed_at DESC
                """),
                {"entity_id": entity_id}
            )

            return [_serialize_row(row._mapping) for row in result]


# Singleton instance
_service: Optional[KnowledgeGraphService] = None


def get_knowledge_service() -> KnowledgeGraphService:
    """Get or create knowledge graph service singleton."""
    global _service
    if _service is None:
        _service = KnowledgeGraphService()
    return _service
