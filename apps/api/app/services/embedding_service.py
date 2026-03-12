"""Embedding service — generate, store, and search vector embeddings.

Uses Google Gemini Embedding 2 (768-dim) via the google-genai SDK.
All functions are module-level, matching the service pattern used elsewhere.
"""
import logging
import uuid
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.embedding import Embedding

logger = logging.getLogger(__name__)

# Lazy-initialized Google GenAI client
_client = None

_MODEL = "gemini-embedding-2-preview"
_DIMENSIONS = 768
_MAX_INPUT_CHARS = 8000  # stay under 8192-token limit


def _get_client():
    """Lazy-init the Google GenAI client."""
    global _client
    if _client is not None:
        return _client
    if not settings.GOOGLE_API_KEY:
        return None
    from google import genai  # lazy import
    _client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    return _client


# ------------------------------------------------------------------
# Core: embed text
# ------------------------------------------------------------------

def embed_text(
    text_content: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> Optional[List[float]]:
    """Generate a 768-dim embedding for *text_content*.

    Returns None when no API key is configured or on upstream error.
    """
    client = _get_client()
    if client is None:
        logger.debug("embed_text skipped — GOOGLE_API_KEY not set")
        return None

    try:
        truncated = text_content[:_MAX_INPUT_CHARS]
        response = client.models.embed_content(
            model=_MODEL,
            contents=truncated,
            config={
                "task_type": task_type,
                "output_dimensionality": _DIMENSIONS,
            },
        )
        return list(response.embeddings[0].values)
    except Exception:
        logger.exception("embed_text failed")
        return None


# ------------------------------------------------------------------
# Store / delete
# ------------------------------------------------------------------

def embed_and_store(
    db: Session,
    tenant_id: uuid.UUID,
    content_type: str,
    content_id: str,
    text_content: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> Optional[Embedding]:
    """Embed *text_content* and upsert the row in the embeddings table."""
    vector = embed_text(text_content, task_type=task_type)
    if vector is None:
        return None

    # Remove previous embedding for the same content
    db.query(Embedding).filter(
        Embedding.content_type == content_type,
        Embedding.content_id == content_id,
    ).delete(synchronize_session="fetch")

    row = Embedding(
        tenant_id=tenant_id,
        content_type=content_type,
        content_id=content_id,
        embedding=vector,
        text_content=text_content[:_MAX_INPUT_CHARS],
        task_type=task_type,
        model=_MODEL,
    )
    db.add(row)
    db.flush()
    return row


def delete_embedding(db: Session, content_type: str, content_id: str) -> None:
    """Delete embedding(s) matching *content_type* + *content_id*."""
    db.query(Embedding).filter(
        Embedding.content_type == content_type,
        Embedding.content_id == content_id,
    ).delete(synchronize_session="fetch")
    db.flush()


# ------------------------------------------------------------------
# Search / recall
# ------------------------------------------------------------------

def search_similar(
    db: Session,
    tenant_id: uuid.UUID,
    content_types: Optional[List[str]],
    query_text: str,
    limit: int = 10,
) -> List[Dict]:
    """Return the *limit* most similar embeddings to *query_text*.

    Uses pgvector cosine distance operator (<=>).
    Filters by tenant_id (includes NULL for global content) and optional
    content_types.
    """
    vector = embed_text(query_text, task_type="RETRIEVAL_QUERY")
    if vector is None:
        return []

    vector_literal = "[" + ",".join(str(v) for v in vector) + "]"

    # Build optional content_type filter
    type_clause = ""
    params: dict = {
        "vector": vector_literal,
        "tenant_id": str(tenant_id),
        "lim": limit,
    }
    if content_types:
        type_clause = "AND content_type = ANY(:ctypes)"
        params["ctypes"] = content_types

    sql = text(f"""
        SELECT
            id,
            tenant_id,
            content_type,
            content_id,
            text_content,
            1 - (embedding <=> :vector::vector) AS similarity
        FROM embeddings
        WHERE (tenant_id = :tenant_id::uuid OR tenant_id IS NULL)
          {type_clause}
        ORDER BY embedding <=> :vector::vector
        LIMIT :lim
    """)

    rows = db.execute(sql, params).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "tenant_id": str(r["tenant_id"]) if r["tenant_id"] else None,
            "content_type": r["content_type"],
            "content_id": r["content_id"],
            "text_content": r["text_content"],
            "similarity": float(r["similarity"]),
        }
        for r in rows
    ]


def recall(
    db: Session,
    tenant_id: uuid.UUID,
    query: str,
    limit: int = 20,
) -> List[Dict]:
    """Broad recall across all content types — convenience wrapper."""
    return search_similar(db, tenant_id, content_types=None, query_text=query, limit=limit)
