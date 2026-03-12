# Skills Marketplace v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a vector-powered skills marketplace with three-tier skill system, auto-trigger, chaining, versioning, and semantic memory using pgvector + Gemini Embedding 2.

**Architecture:** Unified file-on-disk + DB metadata system. pgvector on Cloud SQL stores 768-dim Gemini embeddings. Single `embeddings` table serves skills, knowledge, memory, and chat. Luna gets automatic semantic context assembly before every LLM call.

**Tech Stack:** PostgreSQL + pgvector, Gemini Embedding 2 (`gemini-embedding-2-preview`, 768 dims), `google-genai` Python SDK, SQLAlchemy, FastAPI, React 18.

**Design doc:** `docs/plans/2026-03-12-skills-marketplace-v2-design.md`

---

## Phase 1: Database Foundation

### Task 1: pgvector Extension + Embeddings Table

**Files:**
- Create: `apps/api/migrations/042_add_pgvector_and_embeddings.sql`

**Step 1: Write migration**

```sql
-- Migration 042: Add pgvector extension and embeddings table
-- Requires Cloud SQL pgvector extension to be enabled first:
--   gcloud sql instances patch <INSTANCE> --database-flags=cloudsql.enable_pgvector=on

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    content_type VARCHAR(50) NOT NULL,
    content_id VARCHAR(255) NOT NULL,
    embedding vector(768) NOT NULL,
    text_content TEXT,
    task_type VARCHAR(50) DEFAULT 'RETRIEVAL_DOCUMENT',
    model VARCHAR(100) DEFAULT 'gemini-embedding-2-preview',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_embeddings_tenant_type ON embeddings(tenant_id, content_type);
CREATE INDEX idx_embeddings_content ON embeddings(content_type, content_id);

-- IVFFlat index for vector similarity search
-- lists=100 is good for up to ~100k vectors; increase for larger datasets
CREATE INDEX idx_embeddings_vector ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

**Step 2: Run migration against local DB**

Run: `docker-compose exec db psql -U postgres servicetsunami -f /dev/stdin < apps/api/migrations/042_add_pgvector_and_embeddings.sql`
Expected: CREATE EXTENSION, CREATE TABLE, CREATE INDEX x3

**Step 3: Commit**

```bash
git add apps/api/migrations/042_add_pgvector_and_embeddings.sql
git commit -m "feat: add pgvector extension and embeddings table (migration 042)"
```

---

### Task 2: Skill Registry Table

**Files:**
- Create: `apps/api/migrations/043_add_skill_registry.sql`

**Step 1: Write migration**

```sql
-- Migration 043: Add skill_registry table for unified skill metadata
CREATE TABLE IF NOT EXISTS skill_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    slug VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    tier VARCHAR(20) NOT NULL DEFAULT 'native',
    category VARCHAR(50) NOT NULL DEFAULT 'general',
    tags JSONB DEFAULT '[]'::jsonb,
    auto_trigger_description TEXT,
    chain_to JSONB DEFAULT '[]'::jsonb,
    engine VARCHAR(20) NOT NULL DEFAULT 'python',
    is_published BOOLEAN DEFAULT FALSE,
    source_repo VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_skill_registry_slug_tenant UNIQUE (slug, tenant_id)
);

CREATE INDEX idx_skill_registry_tenant ON skill_registry(tenant_id);
CREATE INDEX idx_skill_registry_tier ON skill_registry(tier);
CREATE INDEX idx_skill_registry_category ON skill_registry(category);
```

**Step 2: Run migration**

Run: `docker-compose exec db psql -U postgres servicetsunami -f /dev/stdin < apps/api/migrations/043_add_skill_registry.sql`
Expected: CREATE TABLE, CREATE INDEX x3

**Step 3: Commit**

```bash
git add apps/api/migrations/043_add_skill_registry.sql
git commit -m "feat: add skill_registry table (migration 043)"
```

---

### Task 3: Embedding + SkillRegistry SQLAlchemy Models

**Files:**
- Create: `apps/api/app/models/embedding.py`
- Create: `apps/api/app/models/skill_registry.py`
- Modify: `apps/api/app/models/__init__.py`

**Step 1: Create Embedding model**

Create `apps/api/app/models/embedding.py`:

```python
"""Embedding model — stores vector embeddings for semantic search."""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base_class import Base


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    content_type = Column(String(50), nullable=False, index=True)
    content_id = Column(String(255), nullable=False)
    embedding = Column(Vector(768), nullable=False)
    text_content = Column(Text, nullable=True)
    task_type = Column(String(50), default="RETRIEVAL_DOCUMENT")
    model = Column(String(100), default="gemini-embedding-2-preview")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Step 2: Create SkillRegistry model**

Create `apps/api/app/models/skill_registry.py`:

```python
"""SkillRegistry model — DB metadata index for file-based skills."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base_class import Base


class SkillRegistry(Base):
    __tablename__ = "skill_registry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    slug = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    tier = Column(String(20), nullable=False, default="native")
    category = Column(String(50), nullable=False, default="general")
    tags = Column(JSONB, default=[])
    auto_trigger_description = Column(Text, nullable=True)
    chain_to = Column(JSONB, default=[])
    engine = Column(String(20), nullable=False, default="python")
    is_published = Column(Boolean, default=False)
    source_repo = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Step 3: Register models in `__init__.py`**

Modify `apps/api/app/models/__init__.py` — add imports:

```python
from app.models.embedding import Embedding
from app.models.skill_registry import SkillRegistry
```

**Step 4: Add pgvector to requirements**

Modify `apps/api/requirements.txt` — add:

```
pgvector>=0.3.6
google-genai>=1.0.0
```

**Step 5: Commit**

```bash
git add apps/api/app/models/embedding.py apps/api/app/models/skill_registry.py apps/api/app/models/__init__.py apps/api/requirements.txt
git commit -m "feat: add Embedding and SkillRegistry models with pgvector dependency"
```

---

## Phase 2: Embedding Service

### Task 4: Gemini Embedding Service

**Files:**
- Create: `apps/api/app/services/embedding_service.py`
- Modify: `apps/api/app/core/config.py`

**Step 1: Add GOOGLE_API_KEY to config**

Modify `apps/api/app/core/config.py` — add field to Settings class:

```python
GOOGLE_API_KEY: str = ""
```

**Step 2: Create embedding service**

Create `apps/api/app/services/embedding_service.py`:

```python
"""Embedding service — Gemini Embedding 2 via google-genai SDK."""
import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.config import settings
from app.models.embedding import Embedding

logger = logging.getLogger(__name__)

# Lazy-init client to avoid import errors when key not set
_client = None

EMBEDDING_MODEL = "gemini-embedding-2-preview"
EMBEDDING_DIMS = 768


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    return _client


def embed_text(text_content: str, task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[List[float]]:
    """Generate embedding for text using Gemini Embedding 2."""
    if not settings.GOOGLE_API_KEY:
        logger.warning("GOOGLE_API_KEY not set, skipping embedding")
        return None
    try:
        from google.genai import types
        client = _get_client()
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text_content[:8000],  # 8192 token limit, truncate conservatively
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBEDDING_DIMS,
            ),
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        return None


def embed_and_store(
    db: Session,
    tenant_id: Optional[str],
    content_type: str,
    content_id: str,
    text_content: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> Optional[Embedding]:
    """Embed text and store in the embeddings table. Replaces existing embedding for same content."""
    vector = embed_text(text_content, task_type)
    if vector is None:
        return None

    # Delete existing embedding for this content
    db.query(Embedding).filter(
        Embedding.content_type == content_type,
        Embedding.content_id == str(content_id),
    ).delete()

    embedding = Embedding(
        tenant_id=tenant_id,
        content_type=content_type,
        content_id=str(content_id),
        embedding=vector,
        text_content=text_content,
        task_type=task_type,
        model=EMBEDDING_MODEL,
    )
    db.add(embedding)
    db.flush()
    return embedding


def search_similar(
    db: Session,
    tenant_id: Optional[str],
    content_types: Optional[List[str]],
    query_text: str,
    limit: int = 10,
) -> List[Dict]:
    """Search for similar content using cosine distance."""
    query_vector = embed_text(query_text, task_type="RETRIEVAL_QUERY")
    if query_vector is None:
        return []

    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    where_clauses = []
    params = {"limit": limit, "vector": vector_str}

    if tenant_id:
        where_clauses.append("(tenant_id = :tenant_id OR tenant_id IS NULL)")
        params["tenant_id"] = str(tenant_id)

    if content_types:
        placeholders = ", ".join(f":ct_{i}" for i in range(len(content_types)))
        where_clauses.append(f"content_type IN ({placeholders})")
        for i, ct in enumerate(content_types):
            params[f"ct_{i}"] = ct

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    sql = text(f"""
        SELECT id, tenant_id, content_type, content_id, text_content,
               1 - (embedding <=> :vector::vector) AS similarity
        FROM embeddings
        WHERE {where_sql}
        ORDER BY embedding <=> :vector::vector
        LIMIT :limit
    """)

    rows = db.execute(sql, params).fetchall()
    return [
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            "content_type": row.content_type,
            "content_id": row.content_id,
            "text_content": row.text_content,
            "similarity": float(row.similarity),
        }
        for row in rows
    ]


def recall(
    db: Session,
    tenant_id: str,
    query: str,
    limit: int = 20,
) -> List[Dict]:
    """Unified semantic search across ALL content types for a tenant."""
    return search_similar(db, tenant_id, content_types=None, query_text=query, limit=limit)


def delete_embedding(db: Session, content_type: str, content_id: str) -> None:
    """Delete embedding for a content item."""
    db.query(Embedding).filter(
        Embedding.content_type == content_type,
        Embedding.content_id == str(content_id),
    ).delete()
```

**Step 3: Commit**

```bash
git add apps/api/app/services/embedding_service.py apps/api/app/core/config.py
git commit -m "feat: add Gemini Embedding 2 service with embed, store, search, recall"
```

---

### Task 5: Wire Embeddings into Knowledge Entities

**Files:**
- Modify: `apps/api/app/services/knowledge.py`

**Step 1: Add embedding on entity create**

In `apps/api/app/services/knowledge.py`, import embedding service at top:

```python
from app.services import embedding_service
```

In `create_entity()` function — after `db.flush()` (entity has an id), add:

```python
    # Embed entity for semantic search
    embed_text = f"{entity.name} {entity.category or ''} {entity.description or ''}"
    if entity.properties:
        import json
        props_str = json.dumps(entity.properties) if isinstance(entity.properties, dict) else str(entity.properties)
        embed_text += f" {props_str}"
    embedding_service.embed_and_store(
        db, str(entity.tenant_id), "entity", str(entity.id), embed_text
    )
```

**Step 2: Replace ILIKE search with vector similarity**

In `search_entities()` function, replace the ILIKE query with:

```python
def search_entities(db: Session, tenant_id, name_query: str = None, entity_type: str = None,
                    category: str = None, skip: int = 0, limit: int = 50):
    """Search entities using vector similarity when query provided, fallback to filters."""
    if name_query and settings.GOOGLE_API_KEY:
        # Semantic search via embeddings
        results = embedding_service.search_similar(
            db, str(tenant_id), ["entity"], name_query, limit=limit
        )
        if results:
            entity_ids = [r["content_id"] for r in results]
            entities = db.query(KnowledgeEntity).filter(
                KnowledgeEntity.id.in_(entity_ids),
                KnowledgeEntity.tenant_id == tenant_id,
            ).all()
            # Preserve similarity ranking
            id_order = {eid: i for i, eid in enumerate(entity_ids)}
            entities.sort(key=lambda e: id_order.get(str(e.id), 999))
            return entities

    # Fallback to existing filter logic
    query = db.query(KnowledgeEntity).filter(KnowledgeEntity.tenant_id == tenant_id)
    if name_query:
        query = query.filter(KnowledgeEntity.name.ilike(f"%{name_query}%"))
    if entity_type:
        query = query.filter(KnowledgeEntity.entity_type == entity_type)
    if category:
        query = query.filter(KnowledgeEntity.category == category)
    return query.offset(skip).limit(limit).all()
```

**Step 3: Add embedding on entity update**

In `update_entity()` function — after `db.flush()`, add same embedding logic as create.

**Step 4: Delete embedding on entity delete**

In `delete_entity()` function — before `db.delete(entity)`:

```python
    embedding_service.delete_embedding(db, "entity", str(entity.id))
```

**Step 5: Commit**

```bash
git add apps/api/app/services/knowledge.py
git commit -m "feat: wire vector embeddings into knowledge entity CRUD and search"
```

---

### Task 6: Wire Embeddings into Memory Activities

**Files:**
- Modify: `apps/api/app/services/memory_activity.py`

**Step 1: Embed on activity log**

In `apps/api/app/services/memory_activity.py`, import embedding service:

```python
from app.services import embedding_service
```

In `log_activity()` — after `db.flush()`, add:

```python
    # Embed activity for semantic memory recall
    embed_text = f"{event_type}: {description}"
    if event_metadata:
        import json
        meta_str = json.dumps(event_metadata) if isinstance(event_metadata, dict) else str(event_metadata)
        embed_text += f" {meta_str[:500]}"  # Cap metadata to avoid token limits
    embedding_service.embed_and_store(
        db, str(tenant_id), "memory_activity", str(activity.id), embed_text
    )
```

**Step 2: Add semantic search endpoint for memory**

In `apps/api/app/services/memory_activity.py`, add:

```python
def search_memory(db: Session, tenant_id, query: str, content_types: list = None, limit: int = 20):
    """Semantic search across memory — skills, entities, activities, chat."""
    types_to_search = content_types or None  # None = all types
    return embedding_service.search_similar(db, str(tenant_id), types_to_search, query, limit)
```

**Step 3: Add search API route**

In `apps/api/app/api/v1/memories.py`, add endpoint:

```python
@router.get("/search")
def search_memory(
    q: str,
    types: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unified semantic search across all memory content types."""
    content_types = types.split(",") if types else None
    results = memory_activity_service.search_memory(
        db, current_user.tenant_id, q, content_types, limit
    )
    return {"results": results, "query": q}
```

**Step 4: Commit**

```bash
git add apps/api/app/services/memory_activity.py apps/api/app/api/v1/memories.py
git commit -m "feat: wire vector embeddings into memory activities with semantic search endpoint"
```

---

## Phase 3: Unified Skill System

### Task 7: Three-Tier Directory Structure + Skill Manager v2

**Files:**
- Modify: `apps/api/app/services/skill_manager.py`
- Modify: `apps/api/app/schemas/file_skill.py`

**Step 1: Update FileSkill schema with v2 fields**

Modify `apps/api/app/schemas/file_skill.py`:

```python
"""Schemas for file-based skills."""
from pydantic import BaseModel
from typing import List, Optional


class SkillInput(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False


class FileSkill(BaseModel):
    name: str
    engine: str = "python"
    script_path: str = "script.py"
    description: Optional[str] = None
    inputs: List[SkillInput] = []
    skill_dir: str = ""
    # v2 fields
    version: int = 1
    category: str = "general"
    tags: List[str] = []
    auto_trigger: Optional[str] = None
    chain_to: List[str] = []
    prompts: List[str] = []
    tier: str = "native"
    slug: str = ""
    source_repo: Optional[str] = None
```

**Step 2: Rewrite skill_manager.py for three tiers**

Replace `apps/api/app/services/skill_manager.py` with the v2 implementation. Key changes:

- `SKILLS_DIR` becomes base dir with `native/`, `community/`, and `tenant_<uuid>/` subdirs
- `scan()` scans all three tier directories
- `_parse_skill_md()` reads v2 frontmatter fields (version, category, tags, auto_trigger, chain_to, prompts)
- `list_skills(tenant_id)` returns native + tenant's custom + community
- `create_skill()` writes to `tenant_<uuid>/` dir
- `update_skill()` bumps version, appends to CHANGELOG.md
- `fork_skill()` copies from native/community to tenant dir
- `get_skill_versions()` reads CHANGELOG.md
- `rollback_skill()` restores previous version from CHANGELOG

Full rewrite of `apps/api/app/services/skill_manager.py`:

```python
"""SkillManager v2 — three-tier skill system with versioning."""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import yaml

from app.schemas.file_skill import FileSkill, SkillInput

logger = logging.getLogger(__name__)

# Bundled skills ship with the container image (read-only)
BUNDLED_SKILLS_DIR = Path(__file__).parent.parent / "skills"
# Base writable skills directory
SKILLS_BASE = Path(os.environ.get("DATA_STORAGE_PATH", str(BUNDLED_SKILLS_DIR.parent))) / "skills"

VALID_CATEGORIES = {"sales", "marketing", "data", "coding", "communication", "automation", "general"}


def _parse_skill_md(skill_dir: Path, tier: str = "native", tenant_id: str = None) -> Optional[FileSkill]:
    """Parse a skill.md file and return a FileSkill, or None if malformed."""
    skill_file = skill_dir / "skill.md"
    if not skill_file.exists():
        return None
    try:
        content = skill_file.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        metadata = yaml.safe_load(parts[1].strip())
        if not isinstance(metadata, dict):
            return None

        body = parts[2].strip()
        description = body
        if description.startswith("## Description"):
            description = description[len("## Description"):].strip()

        raw_inputs = metadata.get("inputs", []) or []
        inputs = [
            SkillInput(
                name=inp.get("name", ""),
                type=inp.get("type", "string"),
                description=inp.get("description", ""),
                required=bool(inp.get("required", False)),
            )
            for inp in raw_inputs
            if isinstance(inp, dict)
        ]

        return FileSkill(
            name=metadata["name"],
            engine=metadata.get("engine", "python"),
            script_path=metadata.get("script_path", "script.py"),
            description=description or None,
            inputs=inputs,
            skill_dir=str(skill_dir),
            version=metadata.get("version", 1),
            category=metadata.get("category", "general"),
            tags=metadata.get("tags", []),
            auto_trigger=metadata.get("auto_trigger"),
            chain_to=metadata.get("chain_to", []),
            prompts=metadata.get("prompts", []),
            tier=tier,
            slug=skill_dir.name,
            source_repo=metadata.get("source_repo"),
        )
    except Exception as exc:
        logger.error("Error loading skill from %s: %s", skill_dir, exc)
        return None


class SkillManager:
    """Singleton — manages three-tier file-based skills."""

    _instance: Optional["SkillManager"] = None

    def __init__(self) -> None:
        self._skills: List[FileSkill] = []

    @classmethod
    def get_instance(cls) -> "SkillManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _native_dir(self) -> Path:
        return SKILLS_BASE / "native"

    def _community_dir(self) -> Path:
        return SKILLS_BASE / "community"

    def _tenant_dir(self, tenant_id: str) -> Path:
        return SKILLS_BASE / f"tenant_{tenant_id}"

    def scan(self) -> None:
        """Scan all skill directories and load definitions."""
        SKILLS_BASE.mkdir(parents=True, exist_ok=True)
        native_dir = self._native_dir()
        native_dir.mkdir(parents=True, exist_ok=True)
        self._community_dir().mkdir(parents=True, exist_ok=True)

        # Seed bundled skills into native dir
        if BUNDLED_SKILLS_DIR.is_dir() and BUNDLED_SKILLS_DIR.resolve() != native_dir.resolve():
            for entry in BUNDLED_SKILLS_DIR.iterdir():
                if entry.is_dir() and not (native_dir / entry.name).exists():
                    shutil.copytree(entry, native_dir / entry.name)
                    logger.info("Seeded bundled skill: %s", entry.name)

        loaded: List[FileSkill] = []

        # Scan native
        if native_dir.is_dir():
            for entry in sorted(native_dir.iterdir()):
                if entry.is_dir():
                    skill = _parse_skill_md(entry, tier="native")
                    if skill:
                        loaded.append(skill)

        # Scan community
        community_dir = self._community_dir()
        if community_dir.is_dir():
            for entry in sorted(community_dir.iterdir()):
                if entry.is_dir():
                    skill = _parse_skill_md(entry, tier="community")
                    if skill:
                        loaded.append(skill)

        # Scan all tenant dirs
        if SKILLS_BASE.is_dir():
            for tenant_dir in sorted(SKILLS_BASE.iterdir()):
                if tenant_dir.is_dir() and tenant_dir.name.startswith("tenant_"):
                    tid = tenant_dir.name[len("tenant_"):]
                    for entry in sorted(tenant_dir.iterdir()):
                        if entry.is_dir():
                            skill = _parse_skill_md(entry, tier="custom", tenant_id=tid)
                            if skill:
                                loaded.append(skill)

        self._skills = loaded
        logger.info("SkillManager: %d skill(s) loaded", len(self._skills))

    def list_skills(self, tenant_id: str = None) -> List[FileSkill]:
        """Return skills visible to a tenant: native + community + their custom."""
        if not tenant_id:
            return [s for s in self._skills if s.tier in ("native", "community")]
        tenant_dir_name = f"tenant_{tenant_id}"
        return [
            s for s in self._skills
            if s.tier in ("native", "community")
            or (s.tier == "custom" and tenant_dir_name in s.skill_dir)
        ]

    def get_skill_by_name(self, name: str, tenant_id: str = None) -> Optional[FileSkill]:
        """Find a skill by name from visible skills."""
        for skill in self.list_skills(tenant_id):
            if skill.name.lower() == name.lower():
                return skill
        return None

    def get_skill_by_slug(self, slug: str, tenant_id: str = None) -> Optional[FileSkill]:
        """Find a skill by slug."""
        for skill in self.list_skills(tenant_id):
            if skill.slug == slug:
                return skill
        return None

    def create_skill(self, tenant_id: str, name: str, description: str, engine: str,
                     script: str, inputs: list, category: str = "general",
                     auto_trigger: str = None, chain_to: list = None, tags: list = None) -> dict:
        """Create a new custom skill for a tenant."""
        if self.get_skill_by_name(name, tenant_id):
            return {"error": f"Skill '{name}' already exists."}

        slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
        if not slug:
            return {"error": "Invalid skill name."}

        skill_dir = self._tenant_dir(tenant_id) / slug
        if skill_dir.exists():
            return {"error": f"Directory '{slug}' already exists."}

        script_filenames = {"python": "script.py", "shell": "script.sh", "markdown": "prompt.md"}
        script_file = script_filenames.get(engine, "script.py")

        try:
            skill_dir.mkdir(parents=True, exist_ok=True)

            frontmatter = {
                "name": name,
                "engine": engine,
                "script_path": script_file,
                "version": 1,
                "category": category if category in VALID_CATEGORIES else "general",
            }
            if tags:
                frontmatter["tags"] = tags
            if auto_trigger:
                frontmatter["auto_trigger"] = auto_trigger
            if chain_to:
                frontmatter["chain_to"] = chain_to
            if inputs:
                frontmatter["inputs"] = inputs

            md_content = "---\n" + yaml.dump(frontmatter, default_flow_style=False) + "---\n\n"
            md_content += f"## Description\n{description}\n"

            (skill_dir / "skill.md").write_text(md_content, encoding="utf-8")
            (skill_dir / script_file).write_text(script, encoding="utf-8")

            if engine == "shell":
                os.chmod(skill_dir / script_file, 0o755)

            self.scan()
            created = self.get_skill_by_name(name, tenant_id)
            if created:
                return {"skill": created}
            return {"error": "Skill created but failed to load — check format."}
        except Exception as e:
            logger.exception("Failed to create skill: %s", e)
            if skill_dir.exists():
                shutil.rmtree(skill_dir, ignore_errors=True)
            return {"error": f"Failed to create skill: {str(e)}"}

    def update_skill(self, tenant_id: str, slug: str, updates: dict) -> dict:
        """Update a custom skill. Bumps version, writes CHANGELOG."""
        skill = self.get_skill_by_slug(slug, tenant_id)
        if not skill:
            return {"error": f"Skill '{slug}' not found."}
        if skill.tier != "custom":
            return {"error": "Only custom skills can be edited. Fork it first."}
        if f"tenant_{tenant_id}" not in skill.skill_dir:
            return {"error": "Not authorized to edit this skill."}

        skill_dir = Path(skill.skill_dir)
        skill_file = skill_dir / "skill.md"
        content = skill_file.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        metadata = yaml.safe_load(parts[1].strip())
        old_version = metadata.get("version", 1)

        # Bump version
        new_version = old_version + 1
        metadata["version"] = new_version

        # Apply updates
        for key in ("name", "description", "category", "auto_trigger", "tags", "chain_to", "engine"):
            if key in updates and key != "description":
                metadata[key] = updates[key]

        body = parts[2].strip() if len(parts) > 2 else ""
        if "description" in updates:
            body = f"## Description\n{updates['description']}"

        md_content = "---\n" + yaml.dump(metadata, default_flow_style=False) + "---\n\n" + body + "\n"
        skill_file.write_text(md_content, encoding="utf-8")

        # Update script if provided
        if "script" in updates:
            script_path = skill_dir / metadata.get("script_path", "script.py")
            script_path.write_text(updates["script"], encoding="utf-8")

        # Append to CHANGELOG
        changelog = skill_dir / "CHANGELOG.md"
        entry = f"\n## v{new_version} — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        entry += f"- Updated: {', '.join(updates.keys())}\n"
        if changelog.exists():
            existing = changelog.read_text(encoding="utf-8")
            changelog.write_text(entry + existing, encoding="utf-8")
        else:
            changelog.write_text(f"# Changelog\n{entry}", encoding="utf-8")

        self.scan()
        return {"skill": self.get_skill_by_slug(slug, tenant_id)}

    def fork_skill(self, tenant_id: str, slug: str) -> dict:
        """Fork a native/community skill into tenant's custom skills."""
        skill = self.get_skill_by_slug(slug)
        if not skill:
            return {"error": f"Skill '{slug}' not found."}
        if skill.tier == "custom":
            return {"error": "Skill is already a custom skill."}

        target_dir = self._tenant_dir(tenant_id) / slug
        if target_dir.exists():
            return {"error": f"You already have a skill with slug '{slug}'."}

        try:
            shutil.copytree(skill.skill_dir, str(target_dir))

            # Update the frontmatter to reflect fork
            skill_file = target_dir / "skill.md"
            content = skill_file.read_text(encoding="utf-8")
            parts = content.split("---", 2)
            metadata = yaml.safe_load(parts[1].strip())
            metadata["version"] = 1  # Reset version
            body = parts[2].strip() if len(parts) > 2 else ""
            md_content = "---\n" + yaml.dump(metadata, default_flow_style=False) + "---\n\n" + body + "\n"
            skill_file.write_text(md_content, encoding="utf-8")

            # Add CHANGELOG
            changelog = target_dir / "CHANGELOG.md"
            changelog.write_text(
                f"# Changelog\n\n## v1 — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"- Forked from {skill.tier} skill: {skill.name}\n",
                encoding="utf-8",
            )

            self.scan()
            forked = self.get_skill_by_slug(slug, tenant_id)
            if forked:
                return {"skill": forked}
            return {"error": "Fork created but failed to load."}
        except Exception as e:
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            return {"error": f"Fork failed: {str(e)}"}

    def delete_skill(self, tenant_id: str, slug: str) -> dict:
        """Delete a custom skill."""
        skill = self.get_skill_by_slug(slug, tenant_id)
        if not skill:
            return {"error": "Skill not found."}
        if skill.tier != "custom":
            return {"error": "Only custom skills can be deleted."}
        if f"tenant_{tenant_id}" not in skill.skill_dir:
            return {"error": "Not authorized."}

        shutil.rmtree(skill.skill_dir, ignore_errors=True)
        self.scan()
        return {"success": True}

    def get_skill_versions(self, slug: str, tenant_id: str = None) -> list:
        """Read CHANGELOG.md for a skill."""
        skill = self.get_skill_by_slug(slug, tenant_id)
        if not skill:
            return []
        changelog = Path(skill.skill_dir) / "CHANGELOG.md"
        if not changelog.exists():
            return [{"version": skill.version, "note": "Initial version"}]
        return [{"raw": changelog.read_text(encoding="utf-8")}]

    def execute_skill(self, name: str, inputs: dict, tenant_id: str = None) -> dict:
        """Execute a file-based skill by name with given inputs."""
        skill = self.get_skill_by_name(name, tenant_id)
        if not skill:
            available = [s.name for s in self.list_skills(tenant_id)]
            return {"error": f"Skill '{name}' not found. Available: {available}"}

        script_path = os.path.join(skill.skill_dir, skill.script_path)
        if not os.path.exists(script_path):
            return {"error": f"Script not found: {script_path}"}

        try:
            if skill.engine == "python":
                return self._execute_python(skill.name, script_path, inputs)
            elif skill.engine == "shell":
                return self._execute_shell(skill.name, script_path, inputs)
            elif skill.engine == "markdown":
                return self._execute_markdown(skill, inputs)
            else:
                return {"error": f"Unsupported engine: {skill.engine}"}
        except Exception as e:
            logger.exception("Skill execution failed: %s", e)
            return {"error": f"Skill execution failed: {str(e)}"}

    def _execute_python(self, name: str, script_path: str, inputs: dict) -> dict:
        import importlib.util
        spec = importlib.util.spec_from_file_location("skill_script", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "execute"):
            return {"error": "Skill script has no 'execute' function."}
        result = module.execute(inputs)
        return {"success": True, "skill": name, "result": result}

    def _execute_shell(self, name: str, script_path: str, inputs: dict) -> dict:
        env = os.environ.copy()
        for k, v in inputs.items():
            env[f"SKILL_INPUT_{k.upper()}"] = str(v)
        proc = subprocess.run(
            ["bash", script_path], capture_output=True, text=True, timeout=60, env=env,
        )
        if proc.returncode != 0:
            return {"error": f"Shell script exited with code {proc.returncode}", "stderr": proc.stderr[:2000]}
        try:
            result = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            result = {"output": proc.stdout.strip()}
        return {"success": True, "skill": name, "result": result}

    def _execute_markdown(self, skill: FileSkill, inputs: dict) -> dict:
        """Execute markdown skill — assemble main prompt + sub-prompts."""
        skill_dir = Path(skill.skill_dir)
        content = (skill_dir / skill.script_path).read_text(encoding="utf-8")

        # Append sub-prompts in order
        for prompt_file in skill.prompts:
            prompt_path = skill_dir / "prompts" / prompt_file
            if prompt_path.exists():
                content += "\n\n---\n\n" + prompt_path.read_text(encoding="utf-8")

        # Substitute placeholders
        for k, v in inputs.items():
            content = content.replace(f"{{{{{k}}}}}", str(v))

        return {"success": True, "skill": skill.name, "result": {"prompt": content}}

    def execute_chain(self, name: str, inputs: dict, tenant_id: str = None, depth: int = 0) -> dict:
        """Execute a skill and its chain_to skills sequentially."""
        if depth >= 3:
            return {"error": "Max chain depth (3) reached."}

        result = self.execute_skill(name, inputs, tenant_id)
        if "error" in result:
            return result

        skill = self.get_skill_by_name(name, tenant_id)
        if not skill or not skill.chain_to:
            return result

        chain_results = [result]
        current_inputs = result.get("result", {})
        if not isinstance(current_inputs, dict):
            current_inputs = {"previous_result": current_inputs}

        for next_slug in skill.chain_to:
            next_skill = self.get_skill_by_slug(next_slug, tenant_id)
            if not next_skill:
                next_skill = self.get_skill_by_name(next_slug, tenant_id)
            if not next_skill:
                continue
            chain_result = self.execute_chain(next_skill.name, current_inputs, tenant_id, depth + 1)
            chain_results.append(chain_result)
            if "error" in chain_result:
                break
            current_inputs = chain_result.get("result", {})
            if not isinstance(current_inputs, dict):
                current_inputs = {"previous_result": current_inputs}

        return {
            "success": True,
            "skill": name,
            "result": chain_results[-1].get("result"),
            "chain": [r.get("skill") for r in chain_results],
        }

    # --- GitHub Import (existing, updated for tiers) ---

    def import_from_github(self, repo_url: str, github_token: Optional[str] = None) -> dict:
        """Import skill(s) from a GitHub repo into community tier."""
        owner, repo, branch, path = self._parse_github_url(repo_url)
        if not owner or not repo:
            return {"error": f"Could not parse GitHub URL: {repo_url}"}

        headers = {"Accept": "application/vnd.github+json"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

        try:
            with httpx.Client(timeout=30.0) as client:
                if not branch:
                    repo_resp = client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
                    if repo_resp.status_code != 200:
                        return {"error": f"Failed to access repo: HTTP {repo_resp.status_code}"}
                    branch = repo_resp.json().get("default_branch", "main")

                api_path = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
                resp = client.get(api_path, headers=headers, params={"ref": branch})
                if resp.status_code != 200:
                    return {"error": f"Failed to read repo contents: HTTP {resp.status_code}"}

                contents = resp.json()
                if isinstance(contents, list):
                    file_names = [f["name"] for f in contents if f["type"] == "file"]
                    if "skill.md" in file_names:
                        return self._import_single_skill(client, headers, owner, repo, branch, path, contents)

                    imported, errors = [], []
                    for subdir in [f for f in contents if f["type"] == "dir"]:
                        sub_resp = client.get(
                            f"https://api.github.com/repos/{owner}/{repo}/contents/{subdir['path']}",
                            headers=headers, params={"ref": branch},
                        )
                        if sub_resp.status_code != 200:
                            continue
                        sub_contents = sub_resp.json()
                        if "skill.md" in [f["name"] for f in sub_contents if f["type"] == "file"]:
                            result = self._import_single_skill(client, headers, owner, repo, branch, subdir["path"], sub_contents)
                            if "error" in result:
                                errors.append(result["error"])
                            elif "skill" in result:
                                imported.append(result["skill"].name)

                    if not imported and not errors:
                        return {"error": "No skills found in repository."}
                    return {"imported": imported, "errors": errors, "source": f"{owner}/{repo}"}
                else:
                    return {"error": "Expected a directory, got a file."}
        except httpx.TimeoutException:
            return {"error": "GitHub API request timed out."}
        except Exception as e:
            logger.exception("GitHub import failed: %s", e)
            return {"error": f"Import failed: {str(e)}"}

    def _import_single_skill(self, client, headers, owner, repo, branch, path, contents) -> dict:
        """Download skill files into community directory."""
        files: Dict[str, str] = {}
        for f in contents:
            if f["type"] != "file":
                continue
            raw_resp = client.get(f["download_url"])
            if raw_resp.status_code == 200:
                files[f["name"]] = raw_resp.text

        if "skill.md" not in files:
            return {"error": f"No skill.md in {path}"}

        content = files["skill.md"]
        if not content.startswith("---"):
            return {"error": f"skill.md in {path} has no YAML frontmatter"}
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {"error": f"Malformed skill.md in {path}"}

        metadata = yaml.safe_load(parts[1].strip())
        skill_name = metadata.get("name", "")
        if not skill_name:
            return {"error": f"No name in {path}"}

        slug = re.sub(r'[^a-z0-9]+', '_', skill_name.lower()).strip('_')
        skill_dir = self._community_dir() / slug
        if skill_dir.exists():
            return {"error": f"Community skill '{slug}' already exists."}

        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            for filename, file_content in files.items():
                (skill_dir / filename).write_text(file_content, encoding="utf-8")

            # Inject source_repo into frontmatter
            metadata["source_repo"] = f"https://github.com/{owner}/{repo}"
            body = parts[2].strip() if len(parts) > 2 else ""
            md_content = "---\n" + yaml.dump(metadata, default_flow_style=False) + "---\n\n" + body + "\n"
            (skill_dir / "skill.md").write_text(md_content, encoding="utf-8")

            if metadata.get("engine") == "shell":
                script_path = metadata.get("script_path", "script.sh")
                script_file = skill_dir / script_path
                if script_file.exists():
                    os.chmod(script_file, 0o755)

            self.scan()
            created = self.get_skill_by_slug(slug)
            if created:
                return {"skill": created}
            return {"error": "Files downloaded but skill failed to load."}
        except Exception as e:
            if skill_dir.exists():
                shutil.rmtree(skill_dir, ignore_errors=True)
            return {"error": f"Failed to write skill files: {str(e)}"}

    @staticmethod
    def _parse_github_url(url: str):
        url = url.strip().rstrip("/")
        m = re.match(r'https?://github\.com/([^/]+)/([^/]+)(?:/tree/([^/]+)(?:/(.*))?)?', url)
        if m:
            return m.group(1), m.group(2), m.group(3), m.group(4) or ""
        parts = url.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1], None, "/".join(parts[2:]) if len(parts) > 2 else ""
        return None, None, None, ""


# Module-level singleton
skill_manager = SkillManager.get_instance()
```

**Step 3: Commit**

```bash
git add apps/api/app/services/skill_manager.py apps/api/app/schemas/file_skill.py
git commit -m "feat: rewrite skill_manager for three-tier system with versioning, forking, chaining"
```

---

### Task 8: Sync Skill Registry to DB + Embeddings

**Files:**
- Create: `apps/api/app/services/skill_registry_service.py`

**Step 1: Create registry sync service**

This service syncs disk skills → DB `skill_registry` table and generates embeddings.

Create `apps/api/app/services/skill_registry_service.py`:

```python
"""Skill registry sync — keeps skill_registry table and embeddings in sync with disk."""
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.skill_registry import SkillRegistry
from app.schemas.file_skill import FileSkill
from app.services import embedding_service
from app.services.skill_manager import skill_manager

logger = logging.getLogger(__name__)


def sync_skills_to_db(db: Session) -> int:
    """Scan disk skills and sync to skill_registry + embeddings. Returns count synced."""
    skill_manager.scan()
    all_skills = skill_manager._skills  # All skills across all tiers
    synced = 0

    existing_slugs = {r.slug: r for r in db.query(SkillRegistry).all()}

    for skill in all_skills:
        tenant_id = None
        if skill.tier == "custom" and "tenant_" in skill.skill_dir:
            import re
            m = re.search(r'tenant_([a-f0-9\-]+)', skill.skill_dir)
            if m:
                tenant_id = m.group(1)

        if skill.slug in existing_slugs:
            # Update existing
            reg = existing_slugs[skill.slug]
            reg.name = skill.name
            reg.version = skill.version
            reg.tier = skill.tier
            reg.category = skill.category
            reg.tags = skill.tags
            reg.auto_trigger_description = skill.auto_trigger
            reg.chain_to = skill.chain_to
            reg.engine = skill.engine
            reg.source_repo = skill.source_repo
            del existing_slugs[skill.slug]
        else:
            # Create new
            reg = SkillRegistry(
                tenant_id=tenant_id,
                slug=skill.slug,
                name=skill.name,
                version=skill.version,
                tier=skill.tier,
                category=skill.category,
                tags=skill.tags or [],
                auto_trigger_description=skill.auto_trigger,
                chain_to=skill.chain_to or [],
                engine=skill.engine,
                source_repo=skill.source_repo,
            )
            db.add(reg)

        # Embed skill for auto-trigger
        embed_text = ""
        if skill.auto_trigger:
            embed_text += skill.auto_trigger + " "
        if skill.description:
            embed_text += skill.description
        if embed_text.strip():
            embedding_service.embed_and_store(
                db, tenant_id, "skill", skill.slug, embed_text.strip()
            )
        synced += 1

    # Remove orphaned registry entries (skill deleted from disk)
    for slug, orphan in existing_slugs.items():
        embedding_service.delete_embedding(db, "skill", slug)
        db.delete(orphan)

    db.commit()
    logger.info("Skill registry sync: %d skills synced", synced)
    return synced


def match_skills(db: Session, tenant_id: str, query: str, limit: int = 3) -> List[dict]:
    """Find skills that match a user query via embedding similarity."""
    return embedding_service.search_similar(
        db, tenant_id, ["skill"], query, limit=limit
    )
```

**Step 2: Wire sync into API startup**

Modify `apps/api/app/main.py` — in the startup event, after `skill_manager.scan()`, add:

```python
from app.services.skill_registry_service import sync_skills_to_db
# ... inside startup event, after skill_manager.scan():
try:
    from app.db.session import SessionLocal
    db = SessionLocal()
    sync_skills_to_db(db)
    db.close()
except Exception as e:
    logger.warning("Skill registry sync failed (pgvector may not be ready): %s", e)
```

**Step 3: Commit**

```bash
git add apps/api/app/services/skill_registry_service.py apps/api/app/main.py
git commit -m "feat: add skill registry sync service — syncs disk skills to DB + embeddings on startup"
```

---

## Phase 4: API Layer

### Task 9: Update Skills API Endpoints

**Files:**
- Modify: `apps/api/app/api/v1/skills_new.py`

**Step 1: Rewrite skills API with tier support**

Replace `apps/api/app/api/v1/skills_new.py` with updated endpoints. Key changes:

- `GET /library` — accepts `tier`, `category`, `search` query params
- `PUT /library/{slug}` — update custom skill
- `POST /library/{slug}/fork` — fork native/community to custom
- `DELETE /library/{slug}` — delete custom skill
- `GET /library/{slug}/versions` — version history
- `GET /library/match` — auto-trigger match endpoint (for ADK)
- All mutating endpoints call `skill_registry_service.sync_skills_to_db()` after changes

```python
"""API routes for skills marketplace v2."""
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Dict, List, Optional

from app.api.deps import get_db, get_current_user
from app.core.config import settings
from app.models.user import User
from app.schemas.file_skill import FileSkill
from app.services.skill_manager import skill_manager
from app.services.skill_registry_service import sync_skills_to_db, match_skills
from app.services.memory_activity import log_activity

router = APIRouter()


def _verify_internal_key(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    if x_internal_key not in (getattr(settings, 'API_INTERNAL_KEY', ''), getattr(settings, 'MCP_API_KEY', '')):
        raise HTTPException(status_code=401, detail="Invalid internal key")


# --- Library endpoints (file-based skills) ---

@router.get("/library", response_model=List[FileSkill])
def list_file_skills(
    tier: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List skills visible to current tenant, with optional filters."""
    skills = skill_manager.list_skills(str(current_user.tenant_id))

    if tier:
        skills = [s for s in skills if s.tier == tier]
    if category:
        skills = [s for s in skills if s.category == category]

    if search:
        # Try vector search first
        results = match_skills(db, str(current_user.tenant_id), search, limit=50)
        if results:
            matched_slugs = {r["content_id"] for r in results}
            skills = [s for s in skills if s.slug in matched_slugs]
        else:
            # Fallback to text search
            q = search.lower()
            skills = [s for s in skills if q in s.name.lower() or q in (s.description or "").lower()
                      or any(q in t.lower() for t in s.tags)]

    return skills


@router.get("/library/internal", response_model=List[FileSkill])
def list_file_skills_internal(
    _auth: None = Depends(_verify_internal_key),
):
    """List file-based skills (internal — for ADK server)."""
    return skill_manager.list_skills()


@router.get("/library/match")
def match_skill_to_query(
    q: str,
    limit: int = 3,
    tenant_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_internal_key),
):
    """Find skills matching a query via semantic similarity (internal — for ADK)."""
    results = match_skills(db, tenant_id, q, limit=limit)
    # Enrich with full skill data
    enriched = []
    for r in results:
        skill = skill_manager.get_skill_by_slug(r["content_id"], tenant_id)
        if skill:
            enriched.append({
                "skill": skill.dict(),
                "similarity": r["similarity"],
            })
    return {"matches": enriched}


class FileSkillCreateInput(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False


class FileSkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    engine: str = "python"
    script: str = 'def execute(inputs):\n    return {"result": "done"}'
    inputs: List[FileSkillCreateInput] = []
    category: str = "general"
    auto_trigger: Optional[str] = None
    chain_to: List[str] = []
    tags: List[str] = []


@router.post("/library/create", response_model=FileSkill, status_code=201)
def create_file_skill(
    payload: FileSkillCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new custom skill."""
    result = skill_manager.create_skill(
        tenant_id=str(current_user.tenant_id),
        name=payload.name,
        description=payload.description,
        engine=payload.engine,
        script=payload.script,
        inputs=[inp.dict() for inp in payload.inputs],
        category=payload.category,
        auto_trigger=payload.auto_trigger,
        chain_to=payload.chain_to,
        tags=payload.tags,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    sync_skills_to_db(db)

    log_activity(
        db, tenant_id=current_user.tenant_id,
        event_type="skill_created",
        description=f"Skill created: {payload.name} ({payload.engine})",
        source="skills",
        event_metadata={"skill_name": payload.name, "engine": payload.engine, "category": payload.category},
    )
    return result["skill"]


class FileSkillUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    engine: Optional[str] = None
    script: Optional[str] = None
    category: Optional[str] = None
    auto_trigger: Optional[str] = None
    chain_to: Optional[List[str]] = None
    tags: Optional[List[str]] = None


@router.put("/library/{slug}", response_model=FileSkill)
def update_file_skill(
    slug: str,
    payload: FileSkillUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a custom skill. Bumps version automatically."""
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    result = skill_manager.update_skill(str(current_user.tenant_id), slug, updates)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    sync_skills_to_db(db)
    return result["skill"]


@router.post("/library/{slug}/fork", response_model=FileSkill, status_code=201)
def fork_skill(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fork a native/community skill into My Skills."""
    result = skill_manager.fork_skill(str(current_user.tenant_id), slug)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    sync_skills_to_db(db)

    log_activity(
        db, tenant_id=current_user.tenant_id,
        event_type="skill_forked",
        description=f"Skill forked: {result['skill'].name}",
        source="skills",
        event_metadata={"skill_slug": slug},
    )
    return result["skill"]


@router.delete("/library/{slug}", status_code=204)
def delete_file_skill(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a custom skill."""
    result = skill_manager.delete_skill(str(current_user.tenant_id), slug)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    sync_skills_to_db(db)


@router.get("/library/{slug}/versions")
def get_skill_versions(
    slug: str,
    current_user: User = Depends(get_current_user),
):
    """Get version history for a skill."""
    versions = skill_manager.get_skill_versions(slug, str(current_user.tenant_id))
    return {"versions": versions}


@router.post("/library/internal/execute")
def execute_file_skill_internal(
    skill_name: str = Body(...),
    inputs: Dict = Body(default={}),
    tenant_id: Optional[str] = Body(default=None),
    _auth: None = Depends(_verify_internal_key),
):
    """Execute a file-based skill by name (internal — for ADK server)."""
    result = skill_manager.execute_skill(skill_name, inputs, tenant_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/library/execute")
def execute_file_skill(
    skill_name: str = Body(...),
    inputs: Dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute a file-based skill by name (user-facing)."""
    result = skill_manager.execute_skill(skill_name, inputs, str(current_user.tenant_id))

    if "error" in result:
        log_activity(
            db, tenant_id=current_user.tenant_id,
            event_type="skill_failed",
            description=f"Skill execution failed: {skill_name}",
            source="skills",
            event_metadata={"skill_name": skill_name, "inputs": inputs, "error": result["error"]},
        )
        raise HTTPException(status_code=400, detail=result["error"])

    log_activity(
        db, tenant_id=current_user.tenant_id,
        event_type="skill_executed",
        description=f"Skill executed: {skill_name}",
        source="skills",
        event_metadata={"skill_name": skill_name, "inputs": inputs},
    )
    return result


class GitHubImportRequest(BaseModel):
    repo_url: str


@router.post("/library/import-github")
def import_from_github(
    payload: GitHubImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import skill(s) from a GitHub repository into community tier."""
    from app.models.integration_config import IntegrationConfig
    from app.services.orchestration.credential_vault import retrieve_credentials_for_skill

    github_token = None
    try:
        config = db.query(IntegrationConfig).filter(
            IntegrationConfig.tenant_id == current_user.tenant_id,
            IntegrationConfig.integration_name == "github",
        ).first()
        if config:
            creds = retrieve_credentials_for_skill(db, config.id, current_user.tenant_id)
            github_token = creds.get("access_token")
    except Exception:
        pass

    result = skill_manager.import_from_github(payload.repo_url, github_token=github_token)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    sync_skills_to_db(db)

    imported = result.get("imported", [])
    skill_obj = result.get("skill")
    if skill_obj:
        imported = [skill_obj.name]

    log_activity(
        db, tenant_id=current_user.tenant_id,
        event_type="skill_imported",
        description=f"Skills imported from GitHub: {', '.join(imported)}",
        source="skills",
        event_metadata={"repo_url": payload.repo_url, "imported": imported},
    )
    return result


# --- DB-backed skills (existing, kept for scoring rubrics) ---

import uuid
from app.schemas.skill import SkillInDB, SkillCreate, SkillUpdate
from app.schemas.skill_execution import SkillExecutionInDB, SkillExecuteRequest
from app.services import skills as service


@router.get("/", response_model=List[SkillInDB])
def list_skills(
    skill_type: Optional[str] = None, skip: int = 0, limit: int = 100,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    return service.get_skills(db, current_user.tenant_id, skill_type, skip, limit)


@router.post("/", response_model=SkillInDB, status_code=201)
def create_skill(
    skill_in: SkillCreate, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.create_skill(db, skill_in, current_user.tenant_id)


@router.get("/{skill_id}", response_model=SkillInDB)
def get_skill(
    skill_id: uuid.UUID, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    skill = service.get_skill(db, skill_id, current_user.tenant_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.put("/{skill_id}", response_model=SkillInDB)
def update_skill(
    skill_id: uuid.UUID, skill_in: SkillUpdate, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    skill = service.update_skill(db, skill_id, current_user.tenant_id, skill_in)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.delete("/{skill_id}", status_code=204)
def delete_skill(
    skill_id: uuid.UUID, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not service.delete_skill(db, skill_id, current_user.tenant_id):
        raise HTTPException(status_code=400, detail="Cannot delete")


@router.post("/{skill_id}/execute")
def execute_skill(
    skill_id: uuid.UUID, request: SkillExecuteRequest,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    result = service.execute_skill(db, skill_id, current_user.tenant_id, request.entity_id, request.params)
    if not result:
        raise HTTPException(status_code=404, detail="Skill not found or disabled")
    return result


@router.get("/{skill_id}/executions", response_model=List[SkillExecutionInDB])
def list_skill_executions(
    skill_id: uuid.UUID, skip: int = 0, limit: int = 50,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    return service.get_skill_executions(db, skill_id, current_user.tenant_id, skip, limit)


@router.post("/{skill_id}/clone", response_model=SkillInDB, status_code=201)
def clone_skill(
    skill_id: uuid.UUID, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    skill = service.clone_skill(db, skill_id, current_user.tenant_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill
```

**Step 2: Commit**

```bash
git add apps/api/app/api/v1/skills_new.py
git commit -m "feat: rewrite skills API with tier filters, update, fork, delete, match, versions"
```

---

## Phase 5: ADK Integration

### Task 10: Replace Vertex AI with Gemini Embedding in ADK

**Files:**
- Modify: `apps/adk-server/memory/vertex_vector.py`
- Modify: `apps/adk-server/config/settings.py`
- Modify: `apps/adk-server/requirements.txt`

**Step 1: Update settings**

In `apps/adk-server/config/settings.py`, add:

```python
google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
```

**Step 2: Replace embedding service**

Rewrite `apps/adk-server/memory/vertex_vector.py` to use `google-genai` SDK with `gemini-embedding-2-preview` instead of Vertex AI `text-embedding-005`. Keep the same interface (`get_embedding_service()` singleton, `get_embedding()`, `get_embeddings_batch()`).

```python
"""Embedding service using Gemini Embedding 2."""
import logging
from typing import List, Optional

from config.settings import settings

logger = logging.getLogger(__name__)

_client = None
EMBEDDING_MODEL = "gemini-embedding-2-preview"
EMBEDDING_DIMS = 768


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=settings.google_api_key)
    return _client


class EmbeddingService:
    """Generate embeddings via Gemini Embedding 2."""

    def get_embedding(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[List[float]]:
        if not settings.google_api_key:
            return None
        try:
            from google.genai import types
            client = _get_client()
            result = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text[:8000],
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=EMBEDDING_DIMS,
                ),
            )
            return result.embeddings[0].values
        except Exception as e:
            logger.error("Embedding failed: %s", e)
            return None

    def get_embeddings_batch(self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[Optional[List[float]]]:
        return [self.get_embedding(t, task_type) for t in texts]


_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
```

**Step 3: Add google-genai to ADK requirements**

In `apps/adk-server/requirements.txt`, add:

```
google-genai>=1.0.0
```

**Step 4: Commit**

```bash
git add apps/adk-server/memory/vertex_vector.py apps/adk-server/config/settings.py apps/adk-server/requirements.txt
git commit -m "feat: replace Vertex AI embeddings with Gemini Embedding 2 in ADK"
```

---

### Task 11: Semantic Context Assembly for Luna

**Files:**
- Modify: `apps/adk-server/tools/skill_tools.py`
- Modify: `apps/adk-server/agents/personal_assistant.py` (or wherever Luna's system prompt is built)

**Step 1: Add skill match tool**

In `apps/adk-server/tools/skill_tools.py`, add a new function that calls the match endpoint:

```python
async def match_skills_to_context(user_message: str, tenant_id: str = None) -> dict:
    """Find skills that match a user's message via semantic similarity.
    Called automatically before each Luna response to inject relevant skill instructions.
    """
    try:
        api_base = settings.api_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{api_base}/api/v1/skills/library/match",
                params={"q": user_message, "limit": 3, "tenant_id": tenant_id or ""},
                headers={"X-Internal-Key": settings.mcp_api_key},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning("Skill match failed: %s", e)
    return {"matches": []}
```

**Step 2: Add semantic recall tool**

In `apps/adk-server/tools/skill_tools.py`, add:

```python
async def recall_memory(query: str, tenant_id: str = None, types: str = None, limit: int = 10) -> dict:
    """Semantic search across all memory — entities, activities, past conversations.
    Use this to recall relevant context before responding.
    """
    try:
        api_base = settings.api_base_url.rstrip("/")
        params = {"q": query, "limit": limit}
        if types:
            params["types"] = types
        # Use internal endpoint (needs to be added to memories.py with internal key auth)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{api_base}/api/v1/memories/search/internal",
                params=params,
                headers={"X-Internal-Key": settings.mcp_api_key},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning("Memory recall failed: %s", e)
    return {"results": []}
```

**Step 3: Add internal search endpoint to memories API**

In `apps/api/app/api/v1/memories.py`, add:

```python
@router.get("/search/internal")
def search_memory_internal(
    q: str,
    types: Optional[str] = None,
    limit: int = 20,
    tenant_id: Optional[str] = None,
    _auth: None = Depends(_verify_internal_key),
):
    """Unified semantic search (internal — for ADK server)."""
    content_types = types.split(",") if types else None
    results = memory_activity_service.search_memory(db_session, tenant_id, q, content_types, limit)
    return {"results": results}
```

Note: This endpoint needs the internal key verification dependency. Import it from skills_new or extract to a shared deps module.

**Step 4: Wire into Luna's agent definition**

In Luna's personal_assistant.py, add the `match_skills_to_context` and `recall_memory` functions to the tool list so they appear in Luna's available tools. Luna's system prompt should include instructions like:

```
Before responding, use recall_memory to check for relevant knowledge and context.
When you detect a skill that matches the user's request, use run_skill to execute it.
```

**Step 5: Commit**

```bash
git add apps/adk-server/tools/skill_tools.py apps/adk-server/agents/personal_assistant.py apps/api/app/api/v1/memories.py
git commit -m "feat: add semantic context assembly — skill matching and memory recall for Luna"
```

---

## Phase 6: Frontend

### Task 12: Update Skills Service Layer

**Files:**
- Modify: `apps/web/src/services/skills.js`

**Step 1: Add marketplace API calls**

Add to `apps/web/src/services/skills.js`:

```javascript
// --- File-based skills marketplace ---
export const getFileSkills = (params = {}) => {
  const query = new URLSearchParams();
  if (params.tier) query.append('tier', params.tier);
  if (params.category) query.append('category', params.category);
  if (params.search) query.append('search', params.search);
  return api.get(`/skills/library?${query.toString()}`);
};

export const createFileSkill = (data) =>
  api.post('/skills/library/create', data);

export const updateFileSkill = (slug, data) =>
  api.put(`/skills/library/${slug}`, data);

export const forkFileSkill = (slug) =>
  api.post(`/skills/library/${slug}/fork`);

export const deleteFileSkill = (slug) =>
  api.delete(`/skills/library/${slug}`);

export const executeFileSkill = (skillName, inputs = {}) =>
  api.post('/skills/library/execute', { skill_name: skillName, inputs });

export const getSkillVersions = (slug) =>
  api.get(`/skills/library/${slug}/versions`);

export const importFromGithub = (repoUrl) =>
  api.post('/skills/library/import-github', { repo_url: repoUrl });
```

**Step 2: Commit**

```bash
git add apps/web/src/services/skills.js
git commit -m "feat: add marketplace API calls to skills service"
```

---

### Task 13: Update i18n Files

**Files:**
- Modify: `apps/web/src/i18n/locales/en/skills.json`
- Modify: `apps/web/src/i18n/locales/es/skills.json`

**Step 1: Update English translations**

```json
{
  "title": "Skills Marketplace",
  "subtitle": "Discover, create, and run reusable skills that agents can use",
  "loading": "Loading skills...",
  "noSkills": "No skills yet",
  "noSkillsDesc": "Create your first skill or ask Luna to build one for you.",
  "engine": "Engine",
  "inputs": "Inputs",
  "required": "required",
  "optional": "optional",
  "run": "Run",
  "running": "Running...",
  "createSkill": "Create Skill",
  "totalSkills": "skills available",
  "tryIt": "Try it",
  "result": "Result",
  "close": "Close",
  "cancel": "Cancel",
  "create": "Create",
  "creating": "Creating...",
  "viewSource": "View Source",
  "skillCreated": "Skill created successfully!",
  "tabs": {
    "mySkills": "My Skills",
    "native": "Native",
    "community": "Community"
  },
  "categories": {
    "all": "All",
    "sales": "Sales",
    "marketing": "Marketing",
    "data": "Data",
    "coding": "Coding",
    "communication": "Communication",
    "automation": "Automation",
    "general": "General"
  },
  "actions": {
    "fork": "Fork to My Skills",
    "edit": "Edit",
    "delete": "Delete",
    "versions": "Version History",
    "viewGithub": "View on GitHub",
    "import": "Import from GitHub"
  },
  "search": {
    "placeholder": "Search skills..."
  },
  "version": "v{{version}}",
  "forked": "Skill forked successfully!",
  "deleted": "Skill deleted.",
  "updated": "Skill updated!",
  "form": {
    "name": "Skill Name",
    "namePlaceholder": "e.g. scrape_pricing_page",
    "engine": "Engine",
    "description": "Description",
    "descriptionPlaceholder": "What does this skill do?",
    "scriptContent": "Script",
    "scriptPlaceholder": "def execute(inputs):\n    # Your skill logic here\n    return {\"result\": \"done\"}",
    "category": "Category",
    "autoTrigger": "Auto-Trigger Description",
    "autoTriggerPlaceholder": "When should Luna use this skill automatically?",
    "chainTo": "Chain To",
    "chainToPlaceholder": "Skills to run after this one",
    "tags": "Tags",
    "tagsPlaceholder": "Comma-separated tags",
    "inputName": "Input Name",
    "inputType": "Type",
    "inputDescription": "Description",
    "inputRequired": "Required",
    "addInput": "Add Input",
    "removeInput": "Remove",
    "inputsSection": "Skill Inputs"
  },
  "execute": {
    "title": "Run Skill",
    "inputValue": "Value",
    "submit": "Execute",
    "success": "Skill executed successfully",
    "error": "Execution failed"
  },
  "errors": {
    "load": "Failed to load skills. Please try again.",
    "execute": "Failed to execute skill.",
    "create": "Failed to create skill.",
    "fork": "Failed to fork skill.",
    "delete": "Failed to delete skill.",
    "update": "Failed to update skill.",
    "import": "Failed to import from GitHub."
  }
}
```

**Step 2: Update Spanish translations** (same structure, translated)

**Step 3: Commit**

```bash
git add apps/web/src/i18n/locales/en/skills.json apps/web/src/i18n/locales/es/skills.json
git commit -m "feat: update i18n with marketplace v2 strings"
```

---

### Task 14: Rewrite SkillsPage.js as Marketplace

**Files:**
- Modify: `apps/web/src/pages/SkillsPage.js`

**Step 1: Full rewrite**

Replace `apps/web/src/pages/SkillsPage.js` with the three-tab marketplace layout:

- **State**: `skills`, `loading`, `activeTab` ('native'|'my'|'community'), `activeCategory`, `searchQuery`, `showCreate`, `showImport`, `executeSkill`, `editSkill`
- **Tabs**: Native (default, shown first for new users), My Skills, Community
- **Category chips**: All, Sales, Marketing, Data, Coding, Communication, Automation, General
- **Search bar**: Debounced text input, calls `getFileSkills({search: query})`
- **Skill cards**: Show name, category badge, engine badge, version, tier indicator
  - Click → expand inline: description, inputs, sub-prompts, chain info
  - `[Run]` button → execute modal (existing pattern)
  - `[···]` dropdown menu with tier-specific actions
- **Create modal**: Name, engine picker (3 options with default templates), category dropdown, description, auto-trigger, tags, chain-to multi-select, script editor, inputs builder
- **Import GitHub modal**: URL input, import button
- **Fork confirmation**: Simple confirm dialog
- **Responsive grid**: `repeat(auto-fill, minmax(350px, 1fr))`

The component should follow existing patterns from the codebase:
- Use React Bootstrap (Card, Modal, Form, Badge, Nav, Button, Row, Col, Spinner)
- Use react-icons (FaCode, FaTerminal, FaMarkdown, FaGithub, FaPlay, FaPlus, FaCodeBranch, FaEdit, FaTrash, FaSearch, FaHistory)
- Use useTranslation from react-i18next
- Use toast notifications for success/error (existing pattern)
- Use glassmorphic card styling (existing CSS patterns)

Due to the size of this component (~600 lines), implement it following the existing SkillsPage.js structure but with the three-tab layout, category filters, and expanded card actions. Reference `IntegrationsPage.js` for the tab pattern and `AgentsPage.js` for the card grid pattern.

**Step 2: Commit**

```bash
git add apps/web/src/pages/SkillsPage.js
git commit -m "feat: rewrite SkillsPage as three-tab marketplace with categories, search, fork"
```

---

## Phase 7: Infrastructure

### Task 15: Helm + Secrets Updates

**Files:**
- Modify: `helm/values/servicetsunami-api.yaml`
- Modify: `helm/values/servicetsunami-adk.yaml`
- Modify: `helm/values/servicetsunami-worker.yaml`

**Step 1: Add GOOGLE_API_KEY secret reference**

In each Helm values file, add GOOGLE_API_KEY to the secrets/env section (follows the same pattern as ANTHROPIC_API_KEY):

```yaml
# In externalSecrets or env section:
- name: GOOGLE_API_KEY
  valueFrom:
    secretKeyRef:
      name: servicetsunami-secrets
      key: servicetsunami-google-api-key
```

**Step 2: Create GCP Secret**

```bash
echo -n "YOUR_GOOGLE_API_KEY" | gcloud secrets create servicetsunami-google-api-key --data-file=-
```

**Step 3: Enable pgvector on Cloud SQL**

```bash
gcloud sql instances patch <INSTANCE_NAME> --database-flags=cloudsql.enable_pgvector=on
```

Note: This requires a brief database restart.

**Step 4: Run migrations on prod**

After deploying the API with new code:

```bash
kubectl exec -it deployment/servicetsunami-api -n prod -- psql $DATABASE_URL -f /app/migrations/042_add_pgvector_and_embeddings.sql
kubectl exec -it deployment/servicetsunami-api -n prod -- psql $DATABASE_URL -f /app/migrations/043_add_skill_registry.sql
```

**Step 5: Commit**

```bash
git add helm/values/servicetsunami-api.yaml helm/values/servicetsunami-adk.yaml helm/values/servicetsunami-worker.yaml
git commit -m "feat: add GOOGLE_API_KEY to Helm values for API, ADK, and worker"
```

---

### Task 16: Backfill Existing Entities with Embeddings

**Files:**
- Create: `apps/api/migrations/044_backfill_embeddings.py`

**Step 1: Create backfill script**

This is a one-time Python script (not SQL) that iterates all existing knowledge entities and memory activities, generates embeddings, and stores them.

Create `apps/api/migrations/044_backfill_embeddings.py`:

```python
"""One-time backfill: generate embeddings for all existing knowledge entities and memory activities."""
import os
import sys

# Add app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import SessionLocal
from app.models.knowledge_entity import KnowledgeEntity
from app.models.memory_activity import MemoryActivity
from app.services import embedding_service

def backfill():
    db = SessionLocal()
    try:
        # Backfill knowledge entities
        entities = db.query(KnowledgeEntity).all()
        print(f"Backfilling {len(entities)} knowledge entities...")
        for i, entity in enumerate(entities):
            text = f"{entity.name} {entity.category or ''} {entity.description or ''}"
            embedding_service.embed_and_store(
                db, str(entity.tenant_id), "entity", str(entity.id), text
            )
            if (i + 1) % 50 == 0:
                db.commit()
                print(f"  ...{i + 1}/{len(entities)}")
        db.commit()
        print(f"Done: {len(entities)} entities embedded.")

        # Backfill memory activities
        activities = db.query(MemoryActivity).all()
        print(f"Backfilling {len(activities)} memory activities...")
        for i, activity in enumerate(activities):
            text = f"{activity.event_type}: {activity.description or ''}"
            embedding_service.embed_and_store(
                db, str(activity.tenant_id), "memory_activity", str(activity.id), text
            )
            if (i + 1) % 50 == 0:
                db.commit()
                print(f"  ...{i + 1}/{len(activities)}")
        db.commit()
        print(f"Done: {len(activities)} activities embedded.")
    finally:
        db.close()

if __name__ == "__main__":
    backfill()
```

**Step 2: Run on prod after deploy**

```bash
kubectl exec -it deployment/servicetsunami-api -n prod -- python migrations/044_backfill_embeddings.py
```

**Step 3: Commit**

```bash
git add apps/api/migrations/044_backfill_embeddings.py
git commit -m "feat: add embedding backfill script for existing entities and activities"
```

---

## Implementation Order Summary

| Phase | Task | Description | Dependencies |
|-------|------|-------------|-------------|
| 1 | 1 | pgvector + embeddings migration | None |
| 1 | 2 | skill_registry migration | None |
| 1 | 3 | SQLAlchemy models + requirements | Tasks 1-2 |
| 2 | 4 | Gemini embedding service | Task 3 |
| 2 | 5 | Wire embeddings → knowledge entities | Task 4 |
| 2 | 6 | Wire embeddings → memory activities | Task 4 |
| 3 | 7 | Three-tier skill manager v2 | None |
| 3 | 8 | Skill registry sync + embed on boot | Tasks 4, 7 |
| 4 | 9 | Skills API endpoints v2 | Tasks 7, 8 |
| 5 | 10 | ADK: Gemini embeddings | None |
| 5 | 11 | ADK: semantic context assembly | Tasks 9, 10 |
| 6 | 12 | Frontend: skills service layer | Task 9 |
| 6 | 13 | Frontend: i18n | None |
| 6 | 14 | Frontend: SkillsPage marketplace | Tasks 12, 13 |
| 7 | 15 | Helm + secrets | None |
| 7 | 16 | Backfill embeddings | Tasks 4, 15 |

**Parallelizable**: Tasks 1+2 (both migrations), Tasks 5+6 (both embedding wiring), Tasks 10+12+13+15 (independent), Task 7 (no deps on embedding work).

---

## Verification Checklist

1. [ ] `CREATE EXTENSION vector` succeeds on local DB
2. [ ] Embedding service generates 768-dim vectors from Gemini API
3. [ ] Creating a knowledge entity also creates an embedding row
4. [ ] `GET /memories/search?q=pricing` returns semantically relevant results
5. [ ] `skill_manager.scan()` loads skills from all three tier directories
6. [ ] `GET /skills/library?tier=native` returns only native skills
7. [ ] `POST /skills/library/create` creates skill in tenant dir, registers in DB, embeds
8. [ ] `POST /skills/library/{slug}/fork` copies native skill to custom tier
9. [ ] `PUT /skills/library/{slug}` bumps version, updates CHANGELOG
10. [ ] `GET /skills/library/match?q=score+this+lead` returns lead_scorer skill
11. [ ] Frontend: three tabs show correct skills per tier
12. [ ] Frontend: category chips filter skills
13. [ ] Frontend: search bar finds skills by semantic match
14. [ ] Frontend: create modal creates a custom skill
15. [ ] Frontend: fork button on native skill creates copy in My Skills
16. [ ] Luna auto-triggers matching skill when user asks relevant question
17. [ ] Skill chaining executes: skill A → skill B → result
18. [ ] Backfill script embeds all existing entities and activities
