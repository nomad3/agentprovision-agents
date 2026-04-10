# Entity Collection Engine — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable agents to build structured entity databases from any web source through the orchestration engine, with enterprise-grade guardrails over OpenClaw browser automation and LLM outputs.

**Architecture:** Extend the existing Knowledge Graph (`KnowledgeEntity` + `KnowledgeRelation`) with lifecycle tracking, add a `persist_entities` activity to the Temporal `TaskExecutionWorkflow`, refactor `KnowledgeExtractionService` from chat-only to universal extraction, and add an `EntityValidator` service with circuit breaker on SkillRouter.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Temporal, PostgreSQL, Pydantic

---

## Execution Status

| Task | Status | Commit | Timestamp |
|------|--------|--------|-----------|
| 1. Migration 029 | ✅ Done | `6ac475f` | 2026-02-14 |
| 2. Model + Schema + Service | ✅ Done | `f80bf79` | 2026-02-14 |
| 3. Skill Registry | ✅ Done | `ea20a1d` | 2026-02-14 |
| 4. Universal Extraction | ✅ Done | `ddaac5d` | 2026-02-14 |
| 5. EntityValidator | ✅ Done | `8b8c717` | 2026-02-14 |
| 6. persist_entities Activity | ✅ Done | `f3a1ecb` | 2026-02-14 |
| 7. Circuit Breaker | ✅ Done | `da8b954` | 2026-02-14 |
| 8. Bulk Entity Endpoints | ✅ Done | `774de39` | 2026-02-14 |
| 9. LLM Guardrails | ✅ Done | `04eef2f` | 2026-02-14 |
| 10. Task Console Badges | ✅ Done | `ff628d0` | 2026-02-14 |
| 11. Knowledge Page Explorer | ✅ Done | `797270f` | 2026-02-14 |
| 12. Add Knowledge to Nav | ✅ Done | `1c70380` | 2026-02-14 |
| 13. Push + Deploy + Verify | ⏳ Pending | — | — |

---

## Phase 1: Foundation

### Task 1: Database Migration — Extend Knowledge Entities

**Files:**
- Create: `apps/api/migrations/029_extend_knowledge_entities.sql`

**Step 1: Write the migration SQL**

```sql
-- Migration 029: Extend knowledge_entities for entity collection engine
-- Adds: status lifecycle, collection task traceability, source tracking, enrichment data

ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'draft';
ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS collection_task_id UUID REFERENCES agent_tasks(id);
ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS enrichment_data JSON;

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_knowledge_entities_status ON knowledge_entities(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_entities_collection_task ON knowledge_entities(collection_task_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_entities_type_tenant ON knowledge_entities(entity_type, tenant_id);

-- Verify
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'knowledge_entities' AND column_name IN ('status', 'collection_task_id', 'source_url', 'enrichment_data');
```

**Step 2: Apply migration locally**

Run: `docker-compose exec db psql -U postgres agentprovision -f /dev/stdin < apps/api/migrations/029_extend_knowledge_entities.sql`
Expected: ALTER TABLE (x4), CREATE INDEX (x3), and SELECT showing 4 rows

**Step 3: Commit**

```bash
git add apps/api/migrations/029_extend_knowledge_entities.sql
git commit -m "feat: add migration 029 — extend knowledge_entities for collection engine"
```

---

### Task 2: Update KnowledgeEntity Model + Schema

**Files:**
- Modify: `apps/api/app/models/knowledge_entity.py:11-33`
- Modify: `apps/api/app/schemas/knowledge_entity.py:1-34`

**Step 1: Update the SQLAlchemy model**

Add these columns to `KnowledgeEntity` in `apps/api/app/models/knowledge_entity.py` after line 25 (`source_agent_id`):

```python
    # Entity lifecycle
    status = Column(String(20), default="draft")  # draft, verified, enriched, actioned, archived
    collection_task_id = Column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=True)
    source_url = Column(String, nullable=True)
    enrichment_data = Column(JSON, nullable=True)
```

And add a relationship after the existing ones (after line 33):

```python
    collection_task = relationship("AgentTask", foreign_keys=[collection_task_id])
```

**Step 2: Update the Pydantic schemas**

In `apps/api/app/schemas/knowledge_entity.py`:

Update `KnowledgeEntityBase` (line 8) to add:
```python
class KnowledgeEntityBase(BaseModel):
    entity_type: str
    name: str
    attributes: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = 1.0
    status: Optional[str] = "draft"
    source_url: Optional[str] = None
```

Update `KnowledgeEntityCreate` (line 15) to add:
```python
class KnowledgeEntityCreate(KnowledgeEntityBase):
    source_agent_id: Optional[uuid.UUID] = None
    collection_task_id: Optional[uuid.UUID] = None
    enrichment_data: Optional[Dict[str, Any]] = None
```

Update `KnowledgeEntityUpdate` (line 19) to add:
```python
class KnowledgeEntityUpdate(BaseModel):
    name: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    status: Optional[str] = None
    source_url: Optional[str] = None
    enrichment_data: Optional[Dict[str, Any]] = None
```

Update `KnowledgeEntity` response (line 25) to add:
```python
class KnowledgeEntity(KnowledgeEntityBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    source_agent_id: Optional[uuid.UUID]
    collection_task_id: Optional[uuid.UUID] = None
    enrichment_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

**Step 3: Update the knowledge service**

In `apps/api/app/services/knowledge.py`, update `create_entity` (line 13) to pass new fields:

```python
def create_entity(db: Session, entity_in: KnowledgeEntityCreate, tenant_id: uuid.UUID) -> KnowledgeEntity:
    """Create a knowledge entity."""
    entity = KnowledgeEntity(
        tenant_id=tenant_id,
        entity_type=entity_in.entity_type,
        name=entity_in.name,
        attributes=entity_in.attributes,
        confidence=entity_in.confidence or 1.0,
        source_agent_id=entity_in.source_agent_id,
        status=entity_in.status or "draft",
        collection_task_id=entity_in.collection_task_id,
        source_url=entity_in.source_url,
        enrichment_data=entity_in.enrichment_data,
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity
```

**Step 4: Verify API starts**

Run: `cd apps/api && python -c "from app.models.knowledge_entity import KnowledgeEntity; print('Model OK')"`
Expected: `Model OK`

**Step 5: Commit**

```bash
git add apps/api/app/models/knowledge_entity.py apps/api/app/schemas/knowledge_entity.py apps/api/app/services/knowledge.py
git commit -m "feat: add status lifecycle, collection_task_id, source_url to KnowledgeEntity"
```

---

### Task 3: Add Peekaboo + LinkedIn to Skill Registry

**Files:**
- Modify: `apps/api/app/api/v1/skill_configs.py:20-91`

**Step 1: Add peekaboo and linkedin entries**

In `apps/api/app/api/v1/skill_configs.py`, add two new entries to the `SKILL_CREDENTIAL_SCHEMAS` dict after the `linear` entry (after line 90):

```python
    "peekaboo": {
        "display_name": "Peekaboo (Browser Automation)",
        "description": "macOS UI automation for web scraping, form filling, and browser interaction — no API keys needed",
        "icon": "FaDesktop",
        "credentials": [],
    },
    "linkedin": {
        "display_name": "LinkedIn",
        "description": "LinkedIn prospecting via browser automation — profile scraping, connection requests, messaging",
        "icon": "FaLinkedin",
        "credentials": [
            {"key": "session_cookie", "label": "Session Cookie (li_at)", "type": "password", "required": False},
        ],
    },
```

**Step 2: Verify registry returns 10 skills**

Run: `cd apps/api && python -c "from app.api.v1.skill_configs import SKILL_CREDENTIAL_SCHEMAS; print(f'{len(SKILL_CREDENTIAL_SCHEMAS)} skills:', list(SKILL_CREDENTIAL_SCHEMAS.keys()))"`
Expected: `10 skills: ['slack', 'gmail', 'github', 'whatsapp', 'notion', 'jira', 'google_calendar', 'linear', 'peekaboo', 'linkedin']`

**Step 3: Commit**

```bash
git add apps/api/app/api/v1/skill_configs.py
git commit -m "feat: add peekaboo and linkedin to skill registry"
```

---

### Task 4: Refactor KnowledgeExtractionService to Universal Extraction

**Files:**
- Modify: `apps/api/app/services/knowledge_extraction.py:1-89`

**Step 1: Rewrite the extraction service**

Replace the entire contents of `apps/api/app/services/knowledge_extraction.py`:

```python
"""Universal knowledge extraction service — extracts entities from any content type."""

from sqlalchemy.orm import Session
from app.models.chat import ChatSession
from app.models.knowledge_entity import KnowledgeEntity
from app.models.knowledge_relation import KnowledgeRelation
from app.services.llm.legacy_service import get_llm_service
from typing import List, Dict, Any, Optional
import uuid
import logging
import json

logger = logging.getLogger(__name__)

# Content-type specific prompt prefixes
EXTRACTION_PROMPTS = {
    "chat_transcript": "Analyze the following chat transcript and extract key entities.",
    "html": "Analyze the following HTML content and extract structured entities. Ignore navigation, ads, and boilerplate.",
    "structured_json": "Parse the following JSON data and extract entities. Preserve all structured fields.",
    "plain_text": "Analyze the following text and extract key entities.",
}


class KnowledgeExtractionService:
    """Extract entities from any content type using LLM."""

    def extract_from_session(self, db: Session, session_id: uuid.UUID, tenant_id: uuid.UUID):
        """Legacy: Extract from chat session (backward compatible)."""
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not session:
            return []

        transcript = ""
        for msg in session.messages:
            transcript += f"{msg.role}: {msg.content}\n"

        if not transcript:
            return []

        return self.extract_from_content(
            db=db,
            content=transcript,
            content_type="chat_transcript",
            tenant_id=tenant_id,
            agent_id=None,
            task_id=None,
        )

    def extract_from_content(
        self,
        db: Session,
        content: str,
        content_type: str,
        tenant_id: uuid.UUID,
        agent_id: Optional[uuid.UUID] = None,
        task_id: Optional[uuid.UUID] = None,
        entity_schema: Optional[Dict[str, Any]] = None,
    ) -> List[KnowledgeEntity]:
        """
        Extract entities from any content type.

        Args:
            content: Raw content string
            content_type: One of "chat_transcript", "html", "structured_json", "plain_text"
            tenant_id: Tenant scope
            agent_id: Source agent ID for provenance
            task_id: Collection task ID for traceability
            entity_schema: Optional schema to guide extraction
                e.g., {"fields": ["name", "email", "company"], "entity_type": "prospect"}

        Returns:
            List of created KnowledgeEntity records
        """
        if not content or not content.strip():
            return []

        prompt = self._build_extraction_prompt(content, content_type, entity_schema)

        try:
            try:
                llm_service = get_llm_service()
            except ValueError:
                logger.warning("LLM service not configured. Skipping extraction.")
                return []

            response = llm_service.generate_chat_response(
                user_message=prompt,
                conversation_history=[],
                system_prompt="You are a knowledge extraction agent. Output valid JSON only. Never invent data not present in the source content.",
                temperature=0.0,
            )

            entities_data = self._parse_json_response(response["text"])
            if not entities_data:
                return []

            created = self._persist_entities(
                db=db,
                entities_data=entities_data,
                tenant_id=tenant_id,
                agent_id=agent_id,
                task_id=task_id,
                entity_schema=entity_schema,
            )

            logger.info(f"Extracted {len(created)} entities from {content_type} content")
            return created

        except Exception as e:
            logger.error(f"Knowledge extraction failed: {e}")
            return []

    def _build_extraction_prompt(
        self,
        content: str,
        content_type: str,
        entity_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the LLM extraction prompt based on content type and optional schema."""
        prefix = EXTRACTION_PROMPTS.get(content_type, EXTRACTION_PROMPTS["plain_text"])

        schema_instruction = ""
        if entity_schema:
            fields = entity_schema.get("fields", [])
            entity_type = entity_schema.get("entity_type", "entity")
            schema_instruction = f"""
Extract entities of type "{entity_type}" with these fields: {', '.join(fields)}.
Required fields: {', '.join(entity_schema.get('required', fields[:2]))}.
"""

        return f"""
{prefix}
{schema_instruction}
Return the result as a JSON array of objects. Each object MUST have:
- "name": string (required, the entity's primary identifier)
- "type": string (required, the entity type e.g. "prospect", "company", "article")
- "confidence": float 0.0-1.0 (how confident you are this entity is correctly extracted)
- "source_url": string or null (URL where this entity was found, if available in content)
- "attributes": object (all other extracted fields as key-value pairs)

Rules:
- Only extract entities actually present in the source content
- Never invent or hallucinate data
- Set confidence < 0.5 for uncertain extractions
- Preserve original data exactly as found

Content:
{content[:8000]}
"""

    def _parse_json_response(self, text: str) -> List[Dict[str, Any]]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        content = text.strip()

        # Handle markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        try:
            parsed = json.loads(content.strip())
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and "entities" in parsed:
                return parsed["entities"]
            return [parsed]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse extraction JSON: {e}")
            return []

    def _persist_entities(
        self,
        db: Session,
        entities_data: List[Dict[str, Any]],
        tenant_id: uuid.UUID,
        agent_id: Optional[uuid.UUID],
        task_id: Optional[uuid.UUID],
        entity_schema: Optional[Dict[str, Any]] = None,
    ) -> List[KnowledgeEntity]:
        """Deduplicate and persist extracted entities."""
        created = []
        default_type = entity_schema.get("entity_type", "concept") if entity_schema else "concept"

        for item in entities_data:
            name = item.get("name")
            if not name:
                continue

            entity_type = item.get("type", default_type).lower()

            # Dedup: name + entity_type + tenant_id
            existing = db.query(KnowledgeEntity).filter(
                KnowledgeEntity.tenant_id == tenant_id,
                KnowledgeEntity.name == name,
                KnowledgeEntity.entity_type == entity_type,
            ).first()

            if existing:
                # Update attributes if new data available
                if item.get("attributes") and existing.attributes:
                    merged = {**existing.attributes, **item["attributes"]}
                    existing.attributes = merged
                    db.flush()
                continue

            confidence = item.get("confidence", 0.8)
            entity = KnowledgeEntity(
                tenant_id=tenant_id,
                name=name,
                entity_type=entity_type,
                attributes=item.get("attributes", {}),
                confidence=confidence,
                source_agent_id=agent_id,
                status="draft" if confidence >= 0.5 else "draft",
                collection_task_id=task_id,
                source_url=item.get("source_url"),
            )
            db.add(entity)
            created.append(entity)

        db.commit()
        for e in created:
            db.refresh(e)
        return created


knowledge_extraction_service = KnowledgeExtractionService()
```

**Step 2: Verify import works**

Run: `cd apps/api && python -c "from app.services.knowledge_extraction import KnowledgeExtractionService; s = KnowledgeExtractionService(); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add apps/api/app/services/knowledge_extraction.py
git commit -m "refactor: universal KnowledgeExtractionService — supports html, json, plain_text, chat"
```

---

### Task 5: Add EntityValidator Service

**Files:**
- Create: `apps/api/app/services/orchestration/entity_validator.py`

**Step 1: Create the validator service**

```python
"""
Enterprise-grade entity validation before persistence.

Checks:
- Required fields present (name, entity_type)
- Entity count within rate limits
- Dedup check against existing entities
- Content moderation (no prohibited content)
- Confidence scoring sanity check
"""

from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import uuid
import logging
import re

from app.models.knowledge_entity import KnowledgeEntity

logger = logging.getLogger(__name__)


@dataclass
class ValidationPolicy:
    """Configurable validation rules for entity persistence."""
    max_entities_per_task: int = 500
    max_entities_per_hour: int = 1000
    required_fields: List[str] = field(default_factory=lambda: ["name", "entity_type"])
    prohibited_patterns: List[str] = field(default_factory=list)
    dedup_fields: List[str] = field(default_factory=lambda: ["name", "entity_type"])
    min_confidence: float = 0.0
    max_name_length: int = 500


@dataclass
class ValidationResult:
    """Result of batch entity validation."""
    valid_entities: List[Dict[str, Any]]
    rejected_entities: List[Dict[str, Any]]
    errors: List[str]
    duplicates_skipped: int = 0

    @property
    def is_valid(self) -> bool:
        return len(self.valid_entities) > 0 and len(self.errors) == 0

    @property
    def summary(self) -> Dict[str, Any]:
        return {
            "valid_count": len(self.valid_entities),
            "rejected_count": len(self.rejected_entities),
            "duplicates_skipped": self.duplicates_skipped,
            "errors": self.errors,
        }


class EntityValidator:
    """Validates entity batches before persistence with enterprise guardrails."""

    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id

    def validate_batch(
        self,
        entities: List[Dict[str, Any]],
        policy: Optional[ValidationPolicy] = None,
        task_id: Optional[uuid.UUID] = None,
    ) -> ValidationResult:
        """
        Validate a batch of entities against policy rules.

        Args:
            entities: Raw entity dicts from LLM extraction
            policy: Validation rules (defaults to sensible enterprise defaults)
            task_id: Collection task ID for rate limit checks

        Returns:
            ValidationResult with valid/rejected entities and error details
        """
        if policy is None:
            policy = ValidationPolicy()

        valid = []
        rejected = []
        errors = []
        dupes = 0

        # Rate limit check: per-task
        if len(entities) > policy.max_entities_per_task:
            errors.append(
                f"Batch size {len(entities)} exceeds max_entities_per_task ({policy.max_entities_per_task})"
            )
            entities = entities[:policy.max_entities_per_task]

        # Rate limit check: per-hour for tenant
        hourly_count = self._count_entities_last_hour()
        if hourly_count + len(entities) > policy.max_entities_per_hour:
            remaining = max(0, policy.max_entities_per_hour - hourly_count)
            errors.append(
                f"Hourly limit reached ({hourly_count}/{policy.max_entities_per_hour}). "
                f"Only {remaining} entities allowed."
            )
            entities = entities[:remaining]

        # Validate each entity
        existing_names = self._load_existing_names(entities)
        seen_in_batch = set()

        for i, entity in enumerate(entities):
            entity_errors = self._validate_single(entity, policy, i)
            if entity_errors:
                entity["_validation_errors"] = entity_errors
                rejected.append(entity)
                continue

            # Dedup against existing DB entities
            dedup_key = self._dedup_key(entity, policy.dedup_fields)
            if dedup_key in existing_names:
                dupes += 1
                continue

            # Dedup within batch
            if dedup_key in seen_in_batch:
                dupes += 1
                continue

            seen_in_batch.add(dedup_key)
            valid.append(entity)

        return ValidationResult(
            valid_entities=valid,
            rejected_entities=rejected,
            errors=errors,
            duplicates_skipped=dupes,
        )

    def _validate_single(
        self,
        entity: Dict[str, Any],
        policy: ValidationPolicy,
        index: int,
    ) -> List[str]:
        """Validate a single entity dict. Returns list of error strings (empty = valid)."""
        errors = []

        # Required fields
        for field_name in policy.required_fields:
            # Map "entity_type" to "type" since LLM output uses "type"
            check_key = "type" if field_name == "entity_type" else field_name
            if not entity.get(check_key) and not entity.get(field_name):
                errors.append(f"Entity[{index}]: missing required field '{field_name}'")

        # Name length
        name = entity.get("name", "")
        if len(name) > policy.max_name_length:
            errors.append(f"Entity[{index}]: name exceeds {policy.max_name_length} chars")

        # Confidence range
        confidence = entity.get("confidence")
        if confidence is not None:
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
                errors.append(f"Entity[{index}]: confidence must be 0.0-1.0, got {confidence}")

        # Prohibited patterns (e.g., PII detection)
        for pattern in policy.prohibited_patterns:
            for value in self._flatten_values(entity):
                if re.search(pattern, str(value), re.IGNORECASE):
                    errors.append(f"Entity[{index}]: matches prohibited pattern '{pattern}'")
                    break

        return errors

    def _count_entities_last_hour(self) -> int:
        """Count entities created by this tenant in the last hour."""
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        return (
            self.db.query(func.count(KnowledgeEntity.id))
            .filter(
                KnowledgeEntity.tenant_id == self.tenant_id,
                KnowledgeEntity.created_at >= one_hour_ago,
            )
            .scalar()
        ) or 0

    def _load_existing_names(self, entities: List[Dict[str, Any]]) -> set:
        """Load existing entity dedup keys from DB for efficient comparison."""
        names = [e.get("name") for e in entities if e.get("name")]
        if not names:
            return set()

        existing = (
            self.db.query(KnowledgeEntity.name, KnowledgeEntity.entity_type)
            .filter(
                KnowledgeEntity.tenant_id == self.tenant_id,
                KnowledgeEntity.name.in_(names),
            )
            .all()
        )
        return {f"{row.name}::{row.entity_type}" for row in existing}

    def _dedup_key(self, entity: Dict[str, Any], dedup_fields: List[str]) -> str:
        """Generate a dedup key from entity fields."""
        parts = []
        for f in dedup_fields:
            check_key = "type" if f == "entity_type" else f
            parts.append(str(entity.get(check_key, entity.get(f, ""))).lower())
        return "::".join(parts)

    def _flatten_values(self, d: Dict[str, Any]) -> List[str]:
        """Flatten dict values for pattern matching."""
        values = []
        for v in d.values():
            if isinstance(v, dict):
                values.extend(self._flatten_values(v))
            elif isinstance(v, list):
                values.extend(str(item) for item in v)
            else:
                values.append(str(v))
        return values
```

**Step 2: Verify import works**

Run: `cd apps/api && python -c "from app.services.orchestration.entity_validator import EntityValidator, ValidationPolicy; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add apps/api/app/services/orchestration/entity_validator.py
git commit -m "feat: add EntityValidator — rate limits, dedup, content validation guardrails"
```

---

## Phase 2: Orchestration

### Task 6: Add persist_entities Activity to TaskExecutionWorkflow

**Files:**
- Modify: `apps/api/app/workflows/activities/task_execution.py:1-348`
- Modify: `apps/api/app/workflows/task_execution.py:1-103`
- Modify: `apps/api/app/workers/orchestration_worker.py:1-77`

**Step 1: Add the persist_entities activity function**

In `apps/api/app/workflows/activities/task_execution.py`, add import at top (after line 6):

```python
from app.models.knowledge_entity import KnowledgeEntity
from app.models.knowledge_relation import KnowledgeRelation
from app.services.knowledge_extraction import KnowledgeExtractionService
from app.services.orchestration.entity_validator import EntityValidator, ValidationPolicy
```

Then add the new activity after the `evaluate_task` function (after line 348):

```python
@activity.defn
async def persist_entities(
    task_id: str, tenant_id: str, agent_id: str, execute_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Persist extracted entities to the knowledge graph.

    Parses agent output for structured entity data, validates against policy,
    deduplicates, and creates KnowledgeEntity + KnowledgeRelation records.

    Runs between execute_task and evaluate_task in the workflow pipeline.
    """
    start = time.time()
    db = SessionLocal()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == uuid.UUID(task_id)).first()
        if not task:
            raise RuntimeError(f"AgentTask {task_id} not found")

        output = execute_result.get("output", {})
        response_text = ""
        if isinstance(output, dict):
            response_text = output.get("response", "")
        elif isinstance(output, str):
            response_text = output

        if not response_text:
            logger.info(f"No output to extract entities from for task {task_id}")
            return {"entities_created": 0, "entities_updated": 0, "duplicates_skipped": 0}

        # Determine entity schema from task context
        context = task.context or {}
        config = context.get("config", {})
        entity_schema = config.get("entity_schema")
        entity_type = config.get("entity_type")
        if entity_type and not entity_schema:
            entity_schema = {"entity_type": entity_type}

        # Determine content type from output source
        content_type = "plain_text"
        if isinstance(output, dict):
            source = output.get("source", "")
            if source == "adk":
                content_type = "structured_json" if _looks_like_json(response_text) else "plain_text"

        # Build validation policy from task guardrails
        guardrails = config.get("guardrails", {})
        policy = ValidationPolicy(
            max_entities_per_task=guardrails.get("max_per_source", 500),
            dedup_fields=guardrails.get("dedup_on", ["name", "entity_type"]),
        )

        # Extract entities via LLM
        extraction_service = KnowledgeExtractionService()
        entities = extraction_service.extract_from_content(
            db=db,
            content=response_text,
            content_type=content_type,
            tenant_id=uuid.UUID(tenant_id),
            agent_id=uuid.UUID(agent_id) if agent_id else None,
            task_id=uuid.UUID(task_id),
            entity_schema=entity_schema,
        )

        # Count results
        entities_created = len(entities)

        duration_ms = int((time.time() - start) * 1000)
        _log_trace(
            db,
            task_id=task_id,
            tenant_id=tenant_id,
            step_type="entity_persist",
            step_order=4,
            agent_id=agent_id,
            details={
                "entities_created": entities_created,
                "content_type": content_type,
                "has_schema": entity_schema is not None,
            },
            duration_ms=duration_ms,
        )

        logger.info(f"Persisted {entities_created} entities for task {task_id}")
        return {
            "entities_created": entities_created,
            "entities_updated": 0,
            "duplicates_skipped": 0,
        }
    finally:
        db.close()


def _looks_like_json(text: str) -> bool:
    """Quick check if text looks like JSON."""
    stripped = text.strip()
    return (stripped.startswith("[") or stripped.startswith("{")) and (
        stripped.endswith("]") or stripped.endswith("}")
    )
```

**Step 2: Update the workflow to include persist_entities step**

In `apps/api/app/workflows/task_execution.py`, add the new step between execute and evaluate.

After line 83 (`workflow.logger.info(f"Task executed with status: {execute_result['status']}")`), add:

```python
        # Step 4: Persist entities from output (if applicable)
        persist_result = await workflow.execute_activity(
            "persist_entities",
            args=[task_id, tenant_id, agent_id, execute_result],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        workflow.logger.info(
            f"Entities persisted: {persist_result.get('entities_created', 0)} created"
        )
```

Update the evaluate step order — change `step_order=4` to `step_order=5` in the evaluate_task activity's `_log_trace` call.

In `apps/api/app/workflows/activities/task_execution.py`, update the evaluate_task's `_log_trace` call at line 322 to use `step_order=5`:

```python
        _log_trace(
            db,
            task_id=task_id,
            tenant_id=tenant_id,
            step_type="completed",
            step_order=5,
```

**Step 3: Register the activity in the worker**

In `apps/api/app/workers/orchestration_worker.py`, add the import (after line 15):

```python
from app.workflows.activities.task_execution import (
    dispatch_task,
    recall_memory,
    execute_task,
    persist_entities,
    evaluate_task,
)
```

And add `persist_entities` to the activities list (after `execute_task` at line 60):

```python
        activities=[
            dispatch_task,
            recall_memory,
            execute_task,
            persist_entities,
            evaluate_task,
            generate_openclaw_values,
            helm_install_openclaw,
            wait_pod_ready,
            health_check_openclaw,
            register_instance,
        ],
```

**Step 4: Verify imports work**

Run: `cd apps/api && python -c "from app.workflows.activities.task_execution import persist_entities; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add apps/api/app/workflows/activities/task_execution.py apps/api/app/workflows/task_execution.py apps/api/app/workers/orchestration_worker.py
git commit -m "feat: add persist_entities activity — 5th step in task execution workflow"
```

---

### Task 7: Enhance SkillRouter with Circuit Breaker + Health Monitoring

**Files:**
- Modify: `apps/api/app/services/orchestration/skill_router.py:1-234`

**Step 1: Add circuit breaker to SkillRouter**

In `apps/api/app/services/orchestration/skill_router.py`, add imports at top (after line 5):

```python
from collections import defaultdict
from threading import Lock
```

Add a module-level circuit breaker state tracker after the logger (after line 26):

```python
# Circuit breaker state — shared across SkillRouter instances
_circuit_breaker_lock = Lock()
_circuit_breaker_state: Dict[str, Dict[str, Any]] = defaultdict(
    lambda: {"failures": 0, "last_failure": None, "open_until": None}
)
CIRCUIT_BREAKER_THRESHOLD = 3  # failures before opening
CIRCUIT_BREAKER_WINDOW = timedelta(minutes=5)
CIRCUIT_BREAKER_COOLDOWN = timedelta(minutes=2)
```

Add import for timedelta at the top:

```python
from datetime import datetime, timedelta
```

Add circuit breaker methods to the `SkillRouter` class (before `_resolve_instance` at line 135):

```python
    def _check_circuit_breaker(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Check if circuit breaker is open for this instance."""
        with _circuit_breaker_lock:
            state = _circuit_breaker_state[instance_id]
            if state["open_until"] and datetime.utcnow() < state["open_until"]:
                logger.warning(
                    "Circuit breaker OPEN for instance %s until %s",
                    instance_id,
                    state["open_until"].isoformat(),
                )
                return {
                    "status": "circuit_open",
                    "error": f"OpenClaw instance temporarily unavailable (circuit breaker). Retry after {state['open_until'].isoformat()}",
                }
            # Reset if cooldown passed
            if state["open_until"] and datetime.utcnow() >= state["open_until"]:
                state["failures"] = 0
                state["open_until"] = None
        return None

    def _record_failure(self, instance_id: str):
        """Record a failure and potentially open the circuit breaker."""
        with _circuit_breaker_lock:
            state = _circuit_breaker_state[instance_id]
            now = datetime.utcnow()

            # Reset counter if last failure was outside the window
            if state["last_failure"] and (now - state["last_failure"]) > CIRCUIT_BREAKER_WINDOW:
                state["failures"] = 0

            state["failures"] += 1
            state["last_failure"] = now

            if state["failures"] >= CIRCUIT_BREAKER_THRESHOLD:
                state["open_until"] = now + CIRCUIT_BREAKER_COOLDOWN
                logger.error(
                    "Circuit breaker OPENED for instance %s after %d failures",
                    instance_id,
                    state["failures"],
                )

    def _record_success(self, instance_id: str):
        """Record a success, resetting the failure counter."""
        with _circuit_breaker_lock:
            state = _circuit_breaker_state[instance_id]
            state["failures"] = 0
            state["open_until"] = None
```

**Step 2: Integrate circuit breaker into execute_skill**

In the `execute_skill` method, after resolving the instance (after line 60), add the circuit breaker check:

```python
        # Circuit breaker check
        cb_result = self._check_circuit_breaker(str(instance.id))
        if cb_result:
            return cb_result
```

After the `_call_openclaw` call (line 87), wrap with success/failure tracking:

```python
        # Track success/failure for circuit breaker
        if result.get("status") == "error":
            self._record_failure(str(instance.id))
        else:
            self._record_success(str(instance.id))
```

**Step 3: Add health check method**

Add to the `SkillRouter` class:

```python
    def health_check(self) -> Dict[str, Any]:
        """Check health of tenant's OpenClaw instance."""
        instance = self._resolve_instance()
        if not instance:
            return {"status": "no_instance", "healthy": False}

        import requests
        try:
            response = requests.get(
                f"{instance.internal_url}/health",
                timeout=5,
            )
            healthy = response.status_code < 400
            return {
                "status": "healthy" if healthy else "unhealthy",
                "healthy": healthy,
                "instance_id": str(instance.id),
                "response_code": response.status_code,
            }
        except Exception as e:
            self._record_failure(str(instance.id))
            return {
                "status": "unreachable",
                "healthy": False,
                "instance_id": str(instance.id),
                "error": str(e),
            }
```

**Step 4: Verify import works**

Run: `cd apps/api && python -c "from app.services.orchestration.skill_router import SkillRouter; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add apps/api/app/services/orchestration/skill_router.py
git commit -m "feat: add circuit breaker + health monitoring to SkillRouter"
```

---

### Task 8: Add Bulk Entity Operations + Collection Summary Endpoints

**Files:**
- Modify: `apps/api/app/api/v1/knowledge.py:1-122`
- Modify: `apps/api/app/services/knowledge.py:1-164`
- Modify: `apps/api/app/schemas/knowledge_entity.py` (add bulk schemas)

**Step 1: Add bulk schemas**

In `apps/api/app/schemas/knowledge_entity.py`, add after the `KnowledgeEntity` response class:

```python
class KnowledgeEntityBulkCreate(BaseModel):
    """Bulk create request."""
    entities: List[KnowledgeEntityCreate]


class KnowledgeEntityBulkResponse(BaseModel):
    """Bulk create response."""
    created: int
    updated: int
    duplicates_skipped: int
    entities: List[KnowledgeEntity]


class CollectionSummary(BaseModel):
    """Summary of entities collected by a task."""
    task_id: uuid.UUID
    total_entities: int
    by_status: Dict[str, int]
    by_type: Dict[str, int]
    sources: List[str]
```

Add `List` to the typing import at the top:
```python
from typing import Optional, Dict, Any, List
```

**Step 2: Add bulk service functions**

In `apps/api/app/services/knowledge.py`, add after the `delete_entity` function:

```python
def bulk_create_entities(
    db: Session,
    entities_in: List[KnowledgeEntityCreate],
    tenant_id: uuid.UUID,
) -> Dict[str, Any]:
    """Bulk create entities with dedup."""
    created = []
    duplicates = 0

    for entity_in in entities_in:
        existing = db.query(KnowledgeEntity).filter(
            KnowledgeEntity.tenant_id == tenant_id,
            KnowledgeEntity.name == entity_in.name,
            KnowledgeEntity.entity_type == entity_in.entity_type,
        ).first()

        if existing:
            duplicates += 1
            continue

        entity = KnowledgeEntity(
            tenant_id=tenant_id,
            entity_type=entity_in.entity_type,
            name=entity_in.name,
            attributes=entity_in.attributes,
            confidence=entity_in.confidence or 1.0,
            source_agent_id=entity_in.source_agent_id,
            status=entity_in.status or "draft",
            collection_task_id=entity_in.collection_task_id,
            source_url=entity_in.source_url,
            enrichment_data=entity_in.enrichment_data,
        )
        db.add(entity)
        created.append(entity)

    db.commit()
    for e in created:
        db.refresh(e)

    return {"created": len(created), "updated": 0, "duplicates_skipped": duplicates, "entities": created}


def get_collection_summary(db: Session, task_id: uuid.UUID, tenant_id: uuid.UUID) -> Dict[str, Any]:
    """Get summary of entities collected by a task."""
    from sqlalchemy import func

    entities = db.query(KnowledgeEntity).filter(
        KnowledgeEntity.tenant_id == tenant_id,
        KnowledgeEntity.collection_task_id == task_id,
    ).all()

    by_status: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    sources = set()

    for e in entities:
        by_status[e.status or "draft"] = by_status.get(e.status or "draft", 0) + 1
        by_type[e.entity_type] = by_type.get(e.entity_type, 0) + 1
        if e.source_url:
            sources.add(e.source_url)

    return {
        "task_id": task_id,
        "total_entities": len(entities),
        "by_status": by_status,
        "by_type": by_type,
        "sources": list(sources),
    }


def update_entity_status(
    db: Session,
    entity_id: uuid.UUID,
    tenant_id: uuid.UUID,
    new_status: str,
) -> Optional[KnowledgeEntity]:
    """Update entity status (lifecycle transition)."""
    valid_statuses = {"draft", "verified", "enriched", "actioned", "archived"}
    if new_status not in valid_statuses:
        return None

    entity = get_entity(db, entity_id, tenant_id)
    if not entity:
        return None

    entity.status = new_status
    db.commit()
    db.refresh(entity)
    return entity
```

Add the import at the top of the knowledge service:

```python
from typing import List, Optional, Dict, Any
```

**Step 3: Add new API endpoints**

In `apps/api/app/api/v1/knowledge.py`, update imports:

```python
from app.schemas.knowledge_entity import (
    KnowledgeEntity, KnowledgeEntityCreate, KnowledgeEntityUpdate,
    KnowledgeEntityBulkCreate, KnowledgeEntityBulkResponse, CollectionSummary,
)
```

Add new endpoints after the existing entity endpoints (after line 85):

```python
@router.post("/entities/bulk", response_model=KnowledgeEntityBulkResponse, status_code=201)
def bulk_create_entities(
    bulk_in: KnowledgeEntityBulkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Bulk create entities with dedup."""
    return service.bulk_create_entities(db, bulk_in.entities, current_user.tenant_id)


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
```

Add `status` and `task_id` filters to the existing `list_entities` endpoint. Update the function signature (line 28):

```python
@router.get("/entities", response_model=List[KnowledgeEntity])
def list_entities(
    entity_type: Optional[str] = None,
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
        status=status, task_id=task_id,
    )
```

Update the `get_entities` service function in `apps/api/app/services/knowledge.py` to accept new filters:

```python
def get_entities(
    db: Session,
    tenant_id: uuid.UUID,
    entity_type: str = None,
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    task_id: uuid.UUID = None,
) -> List[KnowledgeEntity]:
    """List entities with optional filters."""
    query = db.query(KnowledgeEntity).filter(KnowledgeEntity.tenant_id == tenant_id)
    if entity_type:
        query = query.filter(KnowledgeEntity.entity_type == entity_type)
    if status:
        query = query.filter(KnowledgeEntity.status == status)
    if task_id:
        query = query.filter(KnowledgeEntity.collection_task_id == task_id)
    return query.offset(skip).limit(limit).all()
```

**Step 4: Verify endpoints compile**

Run: `cd apps/api && python -c "from app.api.v1.knowledge import router; print(f'{len(router.routes)} routes OK')"`
Expected: `X routes OK` (should be more than before)

**Step 5: Commit**

```bash
git add apps/api/app/api/v1/knowledge.py apps/api/app/services/knowledge.py apps/api/app/schemas/knowledge_entity.py
git commit -m "feat: add bulk entity ops, collection summary, status lifecycle endpoints"
```

---

### Task 9: Add LLM Output Guardrails to Extraction

**Files:**
- Modify: `apps/api/app/services/knowledge_extraction.py` (already refactored in Task 4)

**Step 1: Enhance extraction with schema validation and confidence enforcement**

This task hardens the extraction service written in Task 4. In `apps/api/app/services/knowledge_extraction.py`, update the `_persist_entities` method to integrate `EntityValidator`:

Add import at top:

```python
from app.services.orchestration.entity_validator import EntityValidator, ValidationPolicy
```

Replace the `_persist_entities` method with a validator-integrated version:

```python
    def _persist_entities(
        self,
        db: Session,
        entities_data: List[Dict[str, Any]],
        tenant_id: uuid.UUID,
        agent_id: Optional[uuid.UUID],
        task_id: Optional[uuid.UUID],
        entity_schema: Optional[Dict[str, Any]] = None,
    ) -> List[KnowledgeEntity]:
        """Validate, deduplicate, and persist extracted entities."""
        default_type = entity_schema.get("entity_type", "concept") if entity_schema else "concept"

        # Build validation policy
        policy = ValidationPolicy(
            required_fields=["name"],
            dedup_fields=entity_schema.get("dedup_on", ["name", "entity_type"]) if entity_schema else ["name", "entity_type"],
        )

        # Validate batch
        validator = EntityValidator(db, tenant_id)
        result = validator.validate_batch(entities_data, policy, task_id)

        if result.errors:
            for err in result.errors:
                logger.warning(f"Validation: {err}")

        if result.rejected_entities:
            logger.warning(f"Rejected {len(result.rejected_entities)} entities")

        # Persist valid entities
        created = []
        for item in result.valid_entities:
            name = item.get("name")
            entity_type = item.get("type", default_type).lower()
            confidence = item.get("confidence", 0.8)

            entity = KnowledgeEntity(
                tenant_id=tenant_id,
                name=name,
                entity_type=entity_type,
                attributes=item.get("attributes", {}),
                confidence=confidence,
                source_agent_id=agent_id,
                status="draft",
                collection_task_id=task_id,
                source_url=item.get("source_url"),
            )
            db.add(entity)
            created.append(entity)

        db.commit()
        for e in created:
            db.refresh(e)

        logger.info(
            f"Persisted {len(created)} entities, "
            f"skipped {result.duplicates_skipped} dupes, "
            f"rejected {len(result.rejected_entities)}"
        )
        return created
```

**Step 2: Verify import chain works**

Run: `cd apps/api && python -c "from app.services.knowledge_extraction import KnowledgeExtractionService; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add apps/api/app/services/knowledge_extraction.py
git commit -m "feat: integrate EntityValidator into extraction — guardrails on LLM output"
```

---

## Phase 3: Frontend + Polish

### Task 10: Task Console — Entity Count Badges

**Files:**
- Modify: `apps/web/src/pages/TaskConsolePage.js`

**Step 1: Add entity count to task detail view**

Find the task detail rendering section in `TaskConsolePage.js`. After the existing task status/output section, add an entity collection summary section:

```jsx
{/* Entity Collection Summary */}
{selectedTask && selectedTask.context?.config?.entity_type && (
  <div className="mt-3">
    <h6>
      <FaDatabase className="me-2" />
      Collected Entities
      {collectionSummary && (
        <Badge bg="info" className="ms-2">{collectionSummary.total_entities}</Badge>
      )}
    </h6>
    {collectionSummary ? (
      <div>
        <div className="d-flex gap-2 mb-2">
          {Object.entries(collectionSummary.by_status || {}).map(([status, count]) => (
            <Badge key={status} bg={status === 'verified' ? 'success' : status === 'draft' ? 'warning' : 'secondary'}>
              {status}: {count}
            </Badge>
          ))}
        </div>
        <div className="d-flex gap-2">
          {Object.entries(collectionSummary.by_type || {}).map(([type, count]) => (
            <Badge key={type} bg="outline-primary" text="primary">
              {type}: {count}
            </Badge>
          ))}
        </div>
      </div>
    ) : (
      <small className="text-muted">No entities collected yet</small>
    )}
  </div>
)}
```

Add state and fetch logic:

```jsx
const [collectionSummary, setCollectionSummary] = useState(null);

// Fetch collection summary when task is selected
useEffect(() => {
  if (selectedTask?.id && selectedTask?.context?.config?.entity_type) {
    api.get(`/knowledge/collections/${selectedTask.id}/summary`)
      .then(res => setCollectionSummary(res.data))
      .catch(() => setCollectionSummary(null));
  }
}, [selectedTask]);
```

Add import for FaDatabase:
```jsx
import { FaDatabase } from 'react-icons/fa';
```

**Step 2: Verify no syntax errors**

Run: `cd apps/web && npx react-scripts build 2>&1 | tail -5`
Expected: `Compiled successfully.`

**Step 3: Commit**

```bash
git add apps/web/src/pages/TaskConsolePage.js
git commit -m "feat: show entity collection summary badges in task console"
```

---

### Task 11: Knowledge Page — Entity Type Tabs + Status Filters

**Files:**
- Modify: `apps/web/src/pages/MemoryPage.js`

**Step 1: Add entity explorer tab to Memory page**

The Memory page currently shows agent memories. Add a second tab for Knowledge Entities.

Add state variables:

```jsx
const [activeTab, setActiveTab] = useState('entities');
const [entities, setEntities] = useState([]);
const [entityTypeFilter, setEntityTypeFilter] = useState('');
const [statusFilter, setStatusFilter] = useState('');
const [entityTypes, setEntityTypes] = useState([]);
```

Add fetch logic:

```jsx
const fetchEntities = useCallback(() => {
  const params = new URLSearchParams();
  if (entityTypeFilter) params.append('entity_type', entityTypeFilter);
  if (statusFilter) params.append('status', statusFilter);
  params.append('limit', '100');

  api.get(`/knowledge/entities?${params.toString()}`)
    .then(res => {
      setEntities(res.data);
      // Extract unique types
      const types = [...new Set(res.data.map(e => e.entity_type))];
      setEntityTypes(prev => {
        const merged = [...new Set([...prev, ...types])];
        return merged;
      });
    })
    .catch(console.error);
}, [entityTypeFilter, statusFilter]);

useEffect(() => {
  fetchEntities();
}, [fetchEntities]);
```

Add tab navigation and entity table:

```jsx
<Tabs activeKey={activeTab} onSelect={setActiveTab} className="mb-3">
  <Tab eventKey="entities" title={<><FaDatabase className="me-1" />Entities</>}>
    <div className="d-flex gap-2 mb-3">
      <Form.Select size="sm" style={{width: 'auto'}} value={entityTypeFilter} onChange={e => setEntityTypeFilter(e.target.value)}>
        <option value="">All Types</option>
        {entityTypes.map(t => <option key={t} value={t}>{t}</option>)}
      </Form.Select>
      <Form.Select size="sm" style={{width: 'auto'}} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
        <option value="">All Statuses</option>
        {['draft', 'verified', 'enriched', 'actioned', 'archived'].map(s => (
          <option key={s} value={s}>{s}</option>
        ))}
      </Form.Select>
    </div>
    <Table hover size="sm">
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Status</th>
          <th>Confidence</th>
          <th>Source</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {entities.map(entity => (
          <tr key={entity.id}>
            <td>{entity.name}</td>
            <td><Badge bg="primary">{entity.entity_type}</Badge></td>
            <td><Badge bg={entity.status === 'verified' ? 'success' : 'warning'}>{entity.status}</Badge></td>
            <td>{(entity.confidence * 100).toFixed(0)}%</td>
            <td>{entity.source_url ? <a href={entity.source_url} target="_blank" rel="noreferrer">Link</a> : '-'}</td>
            <td>{new Date(entity.created_at).toLocaleDateString()}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  </Tab>
  <Tab eventKey="memories" title="Agent Memories">
    {/* Existing memory content goes here */}
  </Tab>
</Tabs>
```

Add imports:
```jsx
import { Tabs, Tab, Table, Form } from 'react-bootstrap';
import { FaDatabase } from 'react-icons/fa';
```

**Step 2: Verify no syntax errors**

Run: `cd apps/web && npx react-scripts build 2>&1 | tail -5`
Expected: `Compiled successfully.`

**Step 3: Commit**

```bash
git add apps/web/src/pages/MemoryPage.js
git commit -m "feat: add entity explorer with type/status filters to Knowledge page"
```

---

### Task 12: Update Navigation — Rename Memory to Knowledge

**Files:**
- Modify: `apps/web/src/components/Layout.js`

**Step 1: Update sidebar navigation label**

In `Layout.js`, find the navigation item for "Memory" and update its label to "Knowledge":

Find the line with `Memory` in the sidebar nav items and change:
- Label: `"Memory"` → `"Knowledge"`
- Keep the same route path (`/dashboard/memory`)

**Step 2: Verify no syntax errors**

Run: `cd apps/web && npx react-scripts build 2>&1 | tail -5`
Expected: `Compiled successfully.`

**Step 3: Commit**

```bash
git add apps/web/src/components/Layout.js
git commit -m "feat: rename Memory to Knowledge in sidebar navigation"
```

---

## Final: Push + Deploy + Verify

### Task 13: Push All Changes and Verify Deployment

**Step 1: Push to remote**

```bash
git push origin main
```

**Step 2: Monitor deployment**

```bash
gh run list --limit 5 --json name,status,conclusion
kubectl get pods -n prod -w
```

**Step 3: Run E2E tests**

```bash
./scripts/e2e_test_production.sh
```

**Step 4: Verify new endpoints**

```bash
# Test skill registry (should show 10 skills including peekaboo + linkedin)
curl -s https://agentprovision.com/api/v1/skill-configs/registry -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; skills=json.load(sys.stdin); print(f'{len(skills)} skills:', [s['skill_name'] for s in skills])"

# Test entity list with filters
curl -s "https://agentprovision.com/api/v1/knowledge/entities?status=draft" -H "Authorization: Bearer $TOKEN"

# Test collection summary
curl -s "https://agentprovision.com/api/v1/knowledge/collections/{task_id}/summary" -H "Authorization: Bearer $TOKEN"
```

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| Phase 1 (Foundation) | 1-5 | Extended KnowledgeEntity model, peekaboo/linkedin skills, universal extraction, entity validator |
| Phase 2 (Orchestration) | 6-9 | persist_entities workflow step, circuit breaker, LLM guardrails, bulk API + collection summary |
| Phase 3 (Frontend) | 10-12 | Entity badges in task console, entity explorer in Knowledge page, nav rename |
| Deploy | 13 | Push, deploy, verify |
