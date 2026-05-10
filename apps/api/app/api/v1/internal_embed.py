"""Internal embedding endpoint for in-cluster service-to-service use.

POST /api/v1/internal/embed
  Headers: X-Internal-Key: <API_INTERNAL_KEY or MCP_API_KEY>
  Body: { "text": str, "task_type": "document" | "query" }
  Response 200: { "embedding": [<768 floats>] | null }

Why this endpoint exists: ``apps/mcp-server`` previously embedded text in
process via ``sentence-transformers`` (pulls torch ~1.5GB). This route
delegates back to ``apps.services.embedding_service.embed_text`` which
already routes to the Rust gRPC ``embedding-service`` (fast path) and
falls back to the local sentence-transformers install in the API pod.
The MCP server can then drop the heavy ML dependency entirely.

Authentication mirrors the other ``/internal/*`` endpoints — accepts
either ``API_INTERNAL_KEY`` or ``MCP_API_KEY`` via the ``X-Internal-Key``
header (see ``internal_agent_tokens.py`` for the canonical pattern).

Failure semantics: never raise to the caller for embedding failures.
``embed_text`` returns ``None`` when both the gRPC and Python fallback
paths fail; we surface that as ``{"embedding": null}`` so the caller
can decide whether to skip indexing — matches the existing best-effort
behaviour of the MCP helper this replaces.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.embedding_service import embed_text

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_internal_key(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
) -> None:
    if x_internal_key not in (settings.API_INTERNAL_KEY, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")


class EmbedRequest(BaseModel):
    text: str = Field(..., description="Text to embed (truncated upstream).")
    task_type: Literal["document", "query"] = Field(
        "document",
        description=(
            "Embedding task type. ``document`` uses the search_document "
            "prefix; ``query`` uses search_query."
        ),
    )


class EmbedResponse(BaseModel):
    embedding: Optional[list[float]] = Field(
        None,
        description=(
            "768-dim float vector, or null if both Rust gRPC and Python "
            "fallback paths failed (caller should treat as best-effort)."
        ),
    )


# Map the MCP-side task_type values onto the API's internal naming.
_TASK_TYPE_MAP = {
    "document": "RETRIEVAL_DOCUMENT",
    "query": "RETRIEVAL_QUERY",
}


@router.post("/embed", response_model=EmbedResponse)
def embed_endpoint(
    body: EmbedRequest,
    _auth: None = Depends(_verify_internal_key),
) -> EmbedResponse:
    """Embed a single string and return the 768-dim vector.

    Returns ``{"embedding": null}`` (HTTP 200) on graceful failure so
    callers don't have to translate exceptions into None themselves.
    """
    api_task_type = _TASK_TYPE_MAP[body.task_type]
    try:
        vector = embed_text(body.text, task_type=api_task_type)
    except Exception:  # pragma: no cover — embed_text already swallows
        logger.exception("internal /embed: embed_text raised unexpectedly")
        return EmbedResponse(embedding=None)
    return EmbedResponse(embedding=vector)
